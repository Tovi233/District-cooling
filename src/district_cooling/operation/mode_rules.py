"""Rule-based operation-mode indicators for cold-station measured data."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

import pandas as pd


@dataclass(frozen=True)
class ModeRuleConfig:
    """Thresholds and equipment roles used by the station-mode classifier."""

    design_cooling_capacity_kw: float = 20113.0
    standby_cooling_load_kw: float = 500.0
    standby_flow_m3h: float = 300.0
    ice_delta_threshold_per_step: float = 50.0
    chiller_status_on_threshold: float = 0.5
    chiller_power_on_threshold_kw: float = 20.0
    tower_power_on_threshold_kw: float = 1.0
    pump_power_on_threshold_kw: float = 1.0
    ice_making_supply_temp_threshold_c: float = 0.0
    base_chiller_ids: tuple[str, ...] = field(default_factory=lambda: ("CH_01", "CH_04"))
    dual_mode_chiller_ids: tuple[str, ...] = field(default_factory=lambda: ("CH_02",))
    ignored_chiller_ids: tuple[str, ...] = field(default_factory=lambda: ("CH_03",))
    chiller_flow_m3h: dict[str, float] = field(
        default_factory=lambda: {
            "CH_01": 788.0,
            "CH_02": 1200.0,
            "CH_04": 1200.0,
        }
    )


def classify_operation_modes(data: pd.DataFrame, config: ModeRuleConfig | None = None) -> pd.DataFrame:
    """Return station-level operating indicators and rule-based mode labels."""
    cfg = config or ModeRuleConfig()
    features = data[["source_sheet", "collect_time_iso"]].copy()

    features["cooling_load_kw"] = _numeric(data, "SYS_TOTAL__cooling_load")
    features["flow_m3h"] = _numeric(data, "SYS_TOTAL__flow_m3h")
    features["power_kw"] = _numeric(data, "SYS_TOTAL__power_kw")
    features["ice_inventory"] = _numeric(data, "ICE_01__inventory_rt")
    features["total_supply_temp_c"] = _total_supply_temperature(data)
    features["ice_delta_per_step"] = features["ice_inventory"].diff()
    features["load_ratio"] = features["cooling_load_kw"] / cfg.design_cooling_capacity_kw
    features["kw_per_cooling_kw"] = features["power_kw"] / features["cooling_load_kw"].replace(0, pd.NA)

    ch_status_cols = [c for c in data.columns if c.startswith("CH_") and c.endswith("__status")]
    ct_power_cols = [c for c in data.columns if c.startswith("CT_") and c.endswith("__power_kw")]
    pump_power_cols = [c for c in data.columns if c.startswith("PUMP_") and c.endswith("__power_kw")]
    setpoint_cols = [c for c in data.columns if c.startswith("CH_") and c.endswith("__setpoint_temp")]

    features["chiller_on_count"] = data[ch_status_cols].fillna(0).gt(cfg.chiller_status_on_threshold).sum(axis=1)
    features["base_chiller_on_count"] = _count_running_chillers(data, cfg.base_chiller_ids, cfg)
    features["dual_chiller_on_count"] = _count_running_chillers(data, cfg.dual_mode_chiller_ids, cfg)
    features["ignored_chiller_on_count"] = _count_running_chillers(data, cfg.ignored_chiller_ids, cfg)
    features["base_chiller_power_kw"] = _sum_chiller_parameter(data, cfg.base_chiller_ids, "power_kw")
    features["dual_chiller_power_kw"] = _sum_chiller_parameter(data, cfg.dual_mode_chiller_ids, "power_kw")
    features["effective_chiller_flow_m3h"] = _sum_running_chiller_flow(data, cfg)
    features["cooling_tower_on_count"] = data[ct_power_cols].fillna(0).gt(cfg.tower_power_on_threshold_kw).sum(axis=1)
    features["pump_on_count"] = data[pump_power_cols].fillna(0).gt(cfg.pump_power_on_threshold_kw).sum(axis=1)
    features["min_chiller_setpoint_c"] = data[setpoint_cols].min(axis=1, skipna=True) if setpoint_cols else pd.NA
    features["dual_min_chw_out_temp_c"] = _min_chiller_parameter(data, cfg.dual_mode_chiller_ids, "chw_out_temp")
    features["ice_action"] = features["ice_delta_per_step"].apply(lambda value: _ice_action(value, cfg))

    mode_rows = features.apply(lambda row: _classify_one(row, cfg), axis=1, result_type="expand")
    features["operation_mode"] = mode_rows[0]
    features["mode_reason"] = mode_rows[1]
    return features


def summarize_modes(features: pd.DataFrame) -> pd.DataFrame:
    """Summarize operating-mode duration and parameter ranges."""
    grouped = (
        features.groupby("operation_mode", dropna=False)
        .agg(
            time_points=("collect_time_iso", "count"),
            start_time=("collect_time_iso", "min"),
            end_time=("collect_time_iso", "max"),
            mean_cooling_load_kw=("cooling_load_kw", "mean"),
            max_cooling_load_kw=("cooling_load_kw", "max"),
            mean_load_ratio=("load_ratio", "mean"),
            mean_power_kw=("power_kw", "mean"),
            mean_flow_m3h=("flow_m3h", "mean"),
            mean_base_chiller_on_count=("base_chiller_on_count", "mean"),
            mean_dual_chiller_on_count=("dual_chiller_on_count", "mean"),
            mean_ice_delta_per_step=("ice_delta_per_step", "mean"),
        )
        .reset_index()
        .sort_values("time_points", ascending=False)
    )
    grouped["duration_h"] = grouped["time_points"] * _median_timestep_hours(features)
    return grouped


def daily_mode_summary(features: pd.DataFrame) -> pd.DataFrame:
    """Return one daily table with operating-mode time counts."""
    out = features.copy()
    out["date"] = out["collect_time_iso"].dt.date.astype(str)
    pivot = out.pivot_table(
        index="date",
        columns="operation_mode",
        values="collect_time_iso",
        aggfunc="count",
        fill_value=0,
    )
    pivot = pivot.reset_index()
    return pivot


def _numeric(data: pd.DataFrame, column: str) -> pd.Series:
    if column not in data:
        return pd.Series(pd.NA, index=data.index, dtype="Float64")
    return pd.to_numeric(data[column], errors="coerce")


def _classify_one(row: pd.Series, cfg: ModeRuleConfig) -> tuple[str, str]:
    cooling_load = _value(row, "cooling_load_kw")
    flow = _value(row, "flow_m3h")
    ice_delta = _value(row, "ice_delta_per_step")
    base_on = int(_value(row, "base_chiller_on_count", 0))
    dual_on = int(_value(row, "dual_chiller_on_count", 0))
    dual_out_temp = _value(row, "dual_min_chw_out_temp_c", 99.0)

    is_standby = (
        cooling_load < cfg.standby_cooling_load_kw and base_on == 0 and dual_on == 0
    ) or flow < cfg.standby_flow_m3h
    if is_standby:
        return "异常", f"冷负荷<{cfg.standby_cooling_load_kw:g} kW且主设备未运行，或流量<{cfg.standby_flow_m3h:g} m3/h"

    is_discharge = ice_delta < -cfg.ice_delta_threshold_per_step
    is_ice_making_temp = dual_out_temp < cfg.ice_making_supply_temp_threshold_c
    is_ice_making = dual_on > 0 and is_ice_making_temp

    if is_ice_making:
        return "制冰", (
            f"双工况冷机运行台数={dual_on}，"
            f"双工况出水温度<{cfg.ice_making_supply_temp_threshold_c:g} degC；"
            f"蓄冰量变化={ice_delta:g}/步"
        )
    if dual_on > 0 and is_discharge and base_on > 0:
        return "释冰+基载+双工况", (
            f"双工况冷机运行台数={dual_on}，机载冷机运行台数={base_on}，"
            f"蓄冰量减少>{cfg.ice_delta_threshold_per_step:g}/步"
        )
    if base_on > 0 and is_discharge:
        return "释冰+基载", (
            f"机载冷机运行台数={base_on}，蓄冰量减少>{cfg.ice_delta_threshold_per_step:g}/步"
        )
    if is_discharge and base_on == 0 and dual_on == 0:
        return "释冰", f"无主冷机运行，蓄冰量减少>{cfg.ice_delta_threshold_per_step:g}/步"
    if dual_on > 0 and is_discharge:
        return "异常", (
            f"双工况冷机运行台数={dual_on}，蓄冰量减少>{cfg.ice_delta_threshold_per_step:g}/步，"
            "但当前工况体系未定义该释冰设备组合"
        )
    if base_on > 0 and dual_on > 0:
        return "基载+双工况", f"机载/基载冷机运行台数={base_on}，双工况冷机运行台数={dual_on}"
    if base_on > 0:
        return "基载", f"机载/基载冷机运行台数={base_on}"
    if dual_on > 0:
        return "异常", (
            f"双工况冷机运行台数={dual_on}，但出水温度未达到制冰阈值，"
            "且当前工况体系未定义该机械制冷设备组合"
        )

    return "异常", "主冷机未运行，且未满足释冰或制冰工况"


def _count_running_chillers(data: pd.DataFrame, chiller_ids: tuple[str, ...], cfg: ModeRuleConfig) -> pd.Series:
    if not chiller_ids:
        return pd.Series(0, index=data.index, dtype="int64")

    flags: list[pd.Series] = []
    for chiller_id in chiller_ids:
        status_col = f"{chiller_id}__status"
        power_col = f"{chiller_id}__power_kw"
        if status_col in data:
            flags.append(pd.to_numeric(data[status_col], errors="coerce").fillna(0).gt(cfg.chiller_status_on_threshold))
        elif power_col in data:
            flags.append(pd.to_numeric(data[power_col], errors="coerce").fillna(0).gt(cfg.chiller_power_on_threshold_kw))
    if not flags:
        return pd.Series(0, index=data.index, dtype="int64")
    return pd.concat(flags, axis=1).sum(axis=1)


def _min_chiller_parameter(data: pd.DataFrame, chiller_ids: tuple[str, ...], parameter: str) -> pd.Series:
    columns = [f"{chiller_id}__{parameter}" for chiller_id in chiller_ids if f"{chiller_id}__{parameter}" in data]
    if not columns:
        return pd.Series(pd.NA, index=data.index, dtype="Float64")
    return data[columns].min(axis=1, skipna=True)


def _sum_chiller_parameter(data: pd.DataFrame, chiller_ids: tuple[str, ...], parameter: str) -> pd.Series:
    columns = [f"{chiller_id}__{parameter}" for chiller_id in chiller_ids if f"{chiller_id}__{parameter}" in data]
    if not columns:
        return pd.Series(0.0, index=data.index, dtype="float64")
    return data[columns].apply(pd.to_numeric, errors="coerce").fillna(0.0).sum(axis=1)


def _sum_running_chiller_flow(data: pd.DataFrame, cfg: ModeRuleConfig) -> pd.Series:
    total = pd.Series(0.0, index=data.index, dtype="float64")
    for chiller_id, flow_m3h in cfg.chiller_flow_m3h.items():
        status_col = f"{chiller_id}__status"
        power_col = f"{chiller_id}__power_kw"
        if status_col in data:
            running = pd.to_numeric(data[status_col], errors="coerce").fillna(0).gt(cfg.chiller_status_on_threshold)
        elif power_col in data:
            running = pd.to_numeric(data[power_col], errors="coerce").fillna(0).gt(cfg.chiller_power_on_threshold_kw)
        else:
            continue
        total = total + running.astype(float) * flow_m3h
    return total


def _total_supply_temperature(data: pd.DataFrame) -> pd.Series:
    """Estimate user-side total chilled-water supply temperature.

    The processed station table has no explicit total supply temperature column.
    Heat exchanger outlet temperatures are the closest user-side supply proxy.
    If these columns are unavailable, fall back to the plant ice-side outlet.
    """
    preferred_columns = [
        column
        for column in ("HE_01__chw_out_temp", "HE_02__chw_out_temp", "HE_03__chw_out_temp")
        if column in data
    ]
    if preferred_columns:
        return data[preferred_columns].apply(pd.to_numeric, errors="coerce").mean(axis=1, skipna=True)
    fallback_columns = [column for column in ("ICE_01__chw_out_temp",) if column in data]
    if fallback_columns:
        return data[fallback_columns].apply(pd.to_numeric, errors="coerce").mean(axis=1, skipna=True)
    return pd.Series(pd.NA, index=data.index, dtype="Float64")


def _ice_action(value: float, cfg: ModeRuleConfig) -> str:
    if pd.isna(value):
        return "未知"
    if value > cfg.ice_delta_threshold_per_step:
        return "蓄冰"
    if value < -cfg.ice_delta_threshold_per_step:
        return "释冰"
    return "基本不变"


def _value(row: pd.Series, column: str, default: float = 0.0) -> float:
    value = row.get(column, default)
    if pd.isna(value):
        return default
    return float(value)


def _median_timestep_hours(features: pd.DataFrame) -> float:
    time_delta = features["collect_time_iso"].sort_values().diff().dropna()
    if time_delta.empty:
        return 0.25
    return float(time_delta.median().total_seconds() / 3600.0)
