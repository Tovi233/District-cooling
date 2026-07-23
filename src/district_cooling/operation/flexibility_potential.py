"""Cold-station-only flexibility-potential estimation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class StationFlexibilityConfig:
    """Assumptions for first-stage station-side flexibility estimation."""

    rt_to_kwh: float = 3.517
    target_response_duration_h: float = 2.0
    ice_reserve_fraction: float = 0.1
    usable_ice_fraction: float = 0.85
    mechanical_cooling_cop: float = 5.8
    ice_making_cop: float = 4.11
    restore_duration_h: float = 4.0
    max_ice_discharge_power_kw: float | None = None
    max_ice_discharge_quantile: float = 0.95
    min_reducible_power_kw_for_available: float = 1000.0
    min_duration_h_for_available: float = 1.0
    min_reducible_power_kw_for_cautious: float = 300.0
    min_duration_h_for_cautious: float = 0.5
    note: str = ""

    def validate(self) -> None:
        if self.rt_to_kwh <= 0:
            raise ValueError("rt_to_kwh must be positive")
        if self.target_response_duration_h <= 0:
            raise ValueError("target_response_duration_h must be positive")
        if not 0 <= self.ice_reserve_fraction < 1:
            raise ValueError("ice_reserve_fraction must be in [0, 1)")
        if not 0 < self.usable_ice_fraction <= 1:
            raise ValueError("usable_ice_fraction must be in (0, 1]")
        if self.mechanical_cooling_cop <= 0 or self.ice_making_cop <= 0:
            raise ValueError("COP assumptions must be positive")
        if self.restore_duration_h <= 0:
            raise ValueError("restore_duration_h must be positive")
        if not 0 < self.max_ice_discharge_quantile <= 1:
            raise ValueError("max_ice_discharge_quantile must be in (0, 1]")


def load_flexibility_config(path: str | Path) -> StationFlexibilityConfig:
    """Load station flexibility assumptions from JSON."""
    values = json.loads(Path(path).read_text(encoding="utf-8"))
    allowed = set(StationFlexibilityConfig.__dataclass_fields__)
    config = StationFlexibilityConfig(**{key: value for key, value in values.items() if key in allowed})
    config.validate()
    return config


def estimate_station_flexibility(
    operation_modes: pd.DataFrame,
    config: StationFlexibilityConfig,
) -> pd.DataFrame:
    """Estimate flexibility potential from station-side time-series data.

    This first-stage method intentionally uses only cold-station measurements:
    load, total power, operation mode, and ice inventory. It estimates two
    response mechanisms: stopping/reducing ice-making load, and using available
    stored ice to replace part of mechanical cooling.
    """
    data = operation_modes.copy()
    data["collect_time_iso"] = pd.to_datetime(data["collect_time_iso"])
    data = data.sort_values("collect_time_iso").reset_index(drop=True)

    step_h = _median_timestep_hours(data)
    data["gap_aware_ice_delta_rt"] = _gap_aware_delta(data["collect_time_iso"], data["ice_inventory"], step_h)
    data["ice_discharge_power_kw"] = (-data["gap_aware_ice_delta_rt"] * config.rt_to_kwh / step_h).clip(lower=0)
    data["ice_charge_power_kw"] = (data["gap_aware_ice_delta_rt"] * config.rt_to_kwh / step_h).clip(lower=0)
    data["ice_remaining_kwh"] = pd.to_numeric(data["ice_inventory"], errors="coerce") * config.rt_to_kwh

    max_ice_remaining_kwh = float(data["ice_remaining_kwh"].max(skipna=True))
    reserve_kwh = max_ice_remaining_kwh * config.ice_reserve_fraction
    data["usable_ice_energy_kwh"] = (
        (data["ice_remaining_kwh"] - reserve_kwh).clip(lower=0) * config.usable_ice_fraction
    )

    observed_discharge = data["ice_discharge_power_kw"][data["ice_discharge_power_kw"] > 0]
    if config.max_ice_discharge_power_kw is not None:
        max_discharge_kw = float(config.max_ice_discharge_power_kw)
    elif observed_discharge.empty:
        max_discharge_kw = 0.0
    else:
        max_discharge_kw = float(observed_discharge.quantile(config.max_ice_discharge_quantile))

    data["max_available_ice_discharge_kw"] = data["usable_ice_energy_kwh"].div(
        config.target_response_duration_h
    ).clip(upper=max_discharge_kw)

    records = [_estimate_one(row, config, reserve_kwh, max_discharge_kw) for _, row in data.iterrows()]
    return pd.concat([data, pd.DataFrame(records)], axis=1)


def summarize_flexibility(flexibility: pd.DataFrame) -> pd.DataFrame:
    """Summarize flexibility potential by operation mode and response level."""
    grouped = (
        flexibility.groupby(["operation_mode", "response_level"], dropna=False)
        .agg(
            time_points=("collect_time_iso", "count"),
            mean_cooling_load_kw=("cooling_load_kw", "mean"),
            mean_current_power_kw=("power_kw", "mean"),
            mean_reducible_power_kw=("reducible_power_kw", "mean"),
            max_reducible_power_kw=("reducible_power_kw", "max"),
            mean_response_duration_h=("response_duration_h", "mean"),
            mean_transferable_cooling_energy_kwh=("transferable_cooling_energy_kwh", "mean"),
            mean_rebound_power_kw=("rebound_power_kw", "mean"),
        )
        .reset_index()
        .sort_values(["operation_mode", "response_level"])
    )
    grouped["duration_h"] = grouped["time_points"] * _median_timestep_hours(flexibility)
    return grouped


def _estimate_one(
    row: pd.Series,
    config: StationFlexibilityConfig,
    reserve_kwh: float,
    max_discharge_kw: float,
) -> dict[str, Any]:
    mode = str(row.get("operation_mode", ""))
    cooling_load_kw = _to_float(row.get("cooling_load_kw"))
    current_power_kw = _to_float(row.get("power_kw"))
    usable_ice_energy_kwh = _to_float(row.get("usable_ice_energy_kwh"))
    available_ice_discharge_kw = _to_float(row.get("max_available_ice_discharge_kw"))
    current_ice_discharge_kw = _to_float(row.get("ice_discharge_power_kw"))
    current_ice_charge_kw = _to_float(row.get("ice_charge_power_kw"))

    stop_ice_making_cooling_kw = 0.0
    stop_ice_making_power_kw = 0.0
    load_shift_cooling_kw = 0.0
    load_shift_power_kw = 0.0
    reason_parts: list[str] = []

    if mode == "制冰":
        stop_ice_making_cooling_kw = current_ice_charge_kw
        stop_ice_making_power_kw = stop_ice_making_cooling_kw / config.ice_making_cop
        reason_parts.append("制冰工况: 估算停止或降低制冰带来的电功率削减")
    elif mode in {"基载", "基载+双工况"}:
        load_shift_cooling_kw = min(cooling_load_kw, available_ice_discharge_kw)
        load_shift_power_kw = load_shift_cooling_kw / config.mechanical_cooling_cop
        reason_parts.append("机械制冷工况: 估算可由蓄冰替代的冷机供冷")
    elif mode in {"释冰+基载", "释冰+基载+双工况"}:
        additional_ice_kw = max(available_ice_discharge_kw - current_ice_discharge_kw, 0.0)
        load_shift_cooling_kw = min(cooling_load_kw, additional_ice_kw)
        load_shift_power_kw = load_shift_cooling_kw / config.mechanical_cooling_cop
        reason_parts.append("正在释冰: 估算蓄冰槽剩余可增加释冷功率")
    elif mode == "释冰":
        reason_parts.append("纯释冰工况: 主冷机未运行, 站侧可削减空间较小")
    else:
        reason_parts.append("异常或未定义工况: 不建议参与响应")

    reducible_power_kw = max(stop_ice_making_power_kw + load_shift_power_kw, 0.0)
    reducible_power_kw = min(reducible_power_kw, max(current_power_kw, 0.0))

    transferable_cooling_energy_kwh = 0.0
    response_duration_h = 0.0
    rebound_energy_kwh = 0.0
    if load_shift_cooling_kw > 0:
        response_duration_h = min(config.target_response_duration_h, usable_ice_energy_kwh / load_shift_cooling_kw)
        transferable_cooling_energy_kwh = load_shift_cooling_kw * response_duration_h
        rebound_energy_kwh += transferable_cooling_energy_kwh
    if stop_ice_making_cooling_kw > 0:
        response_duration_h = max(response_duration_h, config.target_response_duration_h)
        lost_ice_making_energy_kwh = stop_ice_making_cooling_kw * config.target_response_duration_h
        rebound_energy_kwh += lost_ice_making_energy_kwh
        transferable_cooling_energy_kwh += lost_ice_making_energy_kwh

    rebound_power_kw = rebound_energy_kwh / config.ice_making_cop / config.restore_duration_h
    response_level = _response_level(reducible_power_kw, response_duration_h, config)
    if usable_ice_energy_kwh <= 0 and mode != "制冰":
        reason_parts.append(f"可用冰量低于预留阈值, 预留冰量={reserve_kwh:.0f} kWh")
    if max_discharge_kw > 0:
        reason_parts.append(
            f"最大释冰功率按历史{config.max_ice_discharge_quantile:.0%}分位估计为{max_discharge_kw:.0f} kW"
        )

    return {
        "stop_ice_making_cooling_kw": stop_ice_making_cooling_kw,
        "stop_ice_making_power_kw": stop_ice_making_power_kw,
        "load_shift_cooling_kw": load_shift_cooling_kw,
        "load_shift_power_kw": load_shift_power_kw,
        "reducible_power_kw": reducible_power_kw,
        "response_duration_h": response_duration_h,
        "transferable_cooling_energy_kwh": transferable_cooling_energy_kwh,
        "rebound_power_kw": rebound_power_kw,
        "response_level": response_level,
        "flexibility_reason": "; ".join(reason_parts),
    }


def _response_level(
    reducible_power_kw: float,
    response_duration_h: float,
    config: StationFlexibilityConfig,
) -> str:
    if (
        reducible_power_kw >= config.min_reducible_power_kw_for_available
        and response_duration_h >= config.min_duration_h_for_available
    ):
        return "可响应"
    if (
        reducible_power_kw >= config.min_reducible_power_kw_for_cautious
        and response_duration_h >= config.min_duration_h_for_cautious
    ):
        return "谨慎响应"
    return "不建议响应"


def _gap_aware_delta(time: pd.Series, values: pd.Series, step_h: float) -> pd.Series:
    value = pd.to_numeric(values, errors="coerce")
    delta = value.diff()
    time_delta_h = pd.to_datetime(time).diff().dt.total_seconds() / 3600
    return delta.where(time_delta_h.le(step_h * 1.5))


def _median_timestep_hours(data: pd.DataFrame) -> float:
    time_delta = pd.to_datetime(data["collect_time_iso"]).sort_values().diff().dropna()
    if time_delta.empty:
        return 0.25
    return float(time_delta.median().total_seconds() / 3600)


def _to_float(value: Any, default: float = 0.0) -> float:
    if pd.isna(value):
        return default
    return float(value)
