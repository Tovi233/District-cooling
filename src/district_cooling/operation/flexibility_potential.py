"""Cold-station-only flexibility-potential estimation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


DUAL_ICE_MAKING_CAPACITY_KW = 4220.0
DUAL_AIR_CONDITION_CAPACITY_KW = 5415.0
DUAL_ICE_MAKING_RATED_OUT_TEMP_C = -5.6
DUAL_AIR_CONDITION_OUT_TEMP_C = 6.0
BASE_AIR_CONDITION_CAPACITY_KW = 3868.0
BASE_AIR_CONDITION_COP = 5.73
DUAL_AIR_CONDITION_COP = 5.83
WATER_HEAT_KW_PER_M3H_C = 1.163
BASE_CHILLER_FLOW_M3H = 788.0
DUAL_CHILLER_FLOW_M3H = 1200.0

MODE_ALIASES = {
    "制冰": "制冰",
    "基载": "基载",
    "基载+双工况": "基载+双工况",
    "释冰": "释冰",
    "释冰+基载": "释冰+基载",
    "释冰+基载+双工况": "释冰+基载+双工况",
    "异常": "异常",
    "异常/未定义": "异常/未定义",
    "�Ʊ�": "制冰",
    "����": "基载",
    "����+˫����": "基载+双工况",
    "�ͱ�": "释冰",
    "�ͱ�+����": "释冰+基载",
    "�ͱ�+����+˫����": "释冰+基载+双工况",
    "�쳣": "异常",
    "�쳣/δ����": "异常/未定义",
}


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
    max_ice_inventory_kwh: float | None = None
    max_ice_discharge_power_kw: float | None = None
    max_ice_discharge_quantile: float = 0.95
    min_reducible_power_kw_for_available: float = 1000.0
    min_duration_h_for_available: float = 1.0
    min_reducible_power_kw_for_limited: float = 300.0
    min_duration_h_for_limited: float = 0.5
    contract_supply_temp_c: float = 4.0
    water_heat_kw_per_m3h_c: float = WATER_HEAT_KW_PER_M3H_C
    base_chiller_flow_m3h: float = BASE_CHILLER_FLOW_M3H
    dual_chiller_flow_m3h: float = DUAL_CHILLER_FLOW_M3H
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
        if self.max_ice_inventory_kwh is not None and self.max_ice_inventory_kwh <= 0:
            raise ValueError("max_ice_inventory_kwh must be positive when provided")
        if not 0 < self.max_ice_discharge_quantile <= 1:
            raise ValueError("max_ice_discharge_quantile must be in (0, 1]")
        if self.water_heat_kw_per_m3h_c <= 0:
            raise ValueError("water_heat_kw_per_m3h_c must be positive")
        if self.base_chiller_flow_m3h < 0 or self.dual_chiller_flow_m3h < 0:
            raise ValueError("rated chiller flow values must be non-negative")


def load_flexibility_config(path: str | Path) -> StationFlexibilityConfig:
    """Load station flexibility assumptions from JSON."""
    values = json.loads(Path(path).read_text(encoding="utf-8"))
    if "min_reducible_power_kw_for_cautious" in values and "min_reducible_power_kw_for_limited" not in values:
        values["min_reducible_power_kw_for_limited"] = values["min_reducible_power_kw_for_cautious"]
    if "min_duration_h_for_cautious" in values and "min_duration_h_for_limited" not in values:
        values["min_duration_h_for_limited"] = values["min_duration_h_for_cautious"]
    allowed = set(StationFlexibilityConfig.__dataclass_fields__)
    config = StationFlexibilityConfig(**{key: value for key, value in values.items() if key in allowed})
    config.validate()
    return config


def estimate_station_flexibility(
    operation_modes: pd.DataFrame,
    config: StationFlexibilityConfig,
) -> pd.DataFrame:
    """Estimate station-side flexibility from load, power, mode, and ice inventory."""
    data = operation_modes.copy()
    data["collect_time_iso"] = pd.to_datetime(data["collect_time_iso"])
    data = data.sort_values("collect_time_iso").reset_index(drop=True)
    data["operation_mode"] = data["operation_mode"].map(normalize_operation_mode)

    step_h = _median_timestep_hours(data)
    data["gap_aware_ice_delta_rt"] = _gap_aware_delta(data["collect_time_iso"], data["ice_inventory"], step_h)
    data["ice_discharge_on"] = data.apply(_ice_discharge_on, axis=1)
    data["effective_ice_delta_rt"] = data.apply(
        lambda row: estimate_effective_ice_delta_rt(
            dual_chiller_on_count=int(_to_float(row.get("dual_chiller_on_count"))),
            dual_min_chw_out_temp_c=_to_float(row.get("dual_min_chw_out_temp_c"), 99.0),
            dual_chiller_power_kw=_to_float(row.get("dual_chiller_power_kw")),
            measured_ice_delta_per_step_rt=_to_float(row.get("gap_aware_ice_delta_rt")),
            ice_discharge_on=bool(row.get("ice_discharge_on")),
            step_h=step_h,
            rt_to_kwh=config.rt_to_kwh,
            ice_making_cop=config.ice_making_cop,
        ),
        axis=1,
    )
    data["gap_aware_ice_delta_kwh"] = data["gap_aware_ice_delta_rt"] * config.rt_to_kwh
    data["effective_ice_delta_kwh"] = data["effective_ice_delta_rt"] * config.rt_to_kwh
    data["ice_discharge_power_kw"] = (-data["effective_ice_delta_rt"] * config.rt_to_kwh / step_h).clip(lower=0)
    data["ice_charge_power_kw"] = (data["effective_ice_delta_rt"] * config.rt_to_kwh / step_h).clip(lower=0)
    data["ice_remaining_kwh"] = pd.to_numeric(data["ice_inventory"], errors="coerce") * config.rt_to_kwh
    data["station_cop"] = pd.to_numeric(data["cooling_load_kw"], errors="coerce") / pd.to_numeric(
        data["power_kw"], errors="coerce"
    ).replace(0, pd.NA)

    if config.max_ice_inventory_kwh is not None:
        max_ice_remaining_kwh = float(config.max_ice_inventory_kwh)
    else:
        max_ice_remaining_kwh = float(data["ice_remaining_kwh"].max(skipna=True))
    data["max_ice_inventory_kwh"] = max_ice_remaining_kwh
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


def estimate_effective_ice_delta_rt(
    dual_chiller_on_count: int,
    dual_min_chw_out_temp_c: float,
    dual_chiller_power_kw: float,
    measured_ice_delta_per_step_rt: float,
    ice_discharge_on: bool,
    step_h: float,
    rt_to_kwh: float,
    ice_making_cop: float = 4.11,
) -> float:
    """Use dual-mode low outlet temperature to estimate ice-making ice increment."""
    if dual_chiller_on_count >= 1 and dual_min_chw_out_temp_c < 0.0:
        if dual_chiller_power_kw > 0.0:
            return dual_chiller_power_kw * ice_making_cop * step_h / rt_to_kwh
        return estimate_dual_ice_making_capacity_kw(dual_min_chw_out_temp_c, dual_chiller_on_count) * step_h / rt_to_kwh
    if not ice_discharge_on:
        return 0.0
    return measured_ice_delta_per_step_rt


def estimate_dual_ice_making_capacity_kw(outlet_temp_c: float, dual_chiller_on_count: int) -> float:
    """Estimate ice-making cooling power from dual-mode outlet temperature."""
    temp = min(max(outlet_temp_c, DUAL_ICE_MAKING_RATED_OUT_TEMP_C), 0.0)
    slope = (DUAL_AIR_CONDITION_CAPACITY_KW - DUAL_ICE_MAKING_CAPACITY_KW) / (
        DUAL_AIR_CONDITION_OUT_TEMP_C - DUAL_ICE_MAKING_RATED_OUT_TEMP_C
    )
    single_capacity_kw = DUAL_ICE_MAKING_CAPACITY_KW + slope * (temp - DUAL_ICE_MAKING_RATED_OUT_TEMP_C)
    return max(dual_chiller_on_count, 0) * single_capacity_kw


def estimate_ice_replacement_power_kw(
    available_ice_cooling_kw: float,
    cooling_load_kw: float,
    base_chiller_on_count: int,
    dual_chiller_on_count: int,
) -> tuple[float, float, str]:
    """Convert available ice cooling to reducible electric power.

    The ice cooling is first compared with the cooling capacity of currently
    running chillers. It replaces dual-mode chiller cooling first, then base
    chiller cooling. Electric reduction is capped by the replaced chiller power.
    """
    return estimate_chiller_reduction_power_kw(
        available_ice_cooling_kw,
        cooling_load_kw,
        base_chiller_on_count,
        dual_chiller_on_count,
        cooling_source_name="释冰",
    )


def estimate_chiller_reduction_power_kw(
    reducible_cooling_kw: float,
    cooling_load_kw: float,
    base_chiller_on_count: int,
    dual_chiller_on_count: int,
    cooling_source_name: str = "可削减冷量",
) -> tuple[float, float, str]:
    """Convert reducible cooling load into reducible chiller electric power."""
    base_capacity = max(base_chiller_on_count, 0) * BASE_AIR_CONDITION_CAPACITY_KW
    dual_capacity = max(dual_chiller_on_count, 0) * DUAL_AIR_CONDITION_CAPACITY_KW
    remaining = min(max(reducible_cooling_kw, 0.0), max(cooling_load_kw, 0.0), base_capacity + dual_capacity)
    replaced_cooling_kw = remaining

    dual_replace_kw = min(remaining, dual_capacity)
    remaining -= dual_replace_kw
    base_replace_kw = min(remaining, base_capacity)

    reducible_power_kw = dual_replace_kw / DUAL_AIR_CONDITION_COP + base_replace_kw / BASE_AIR_CONDITION_COP
    description = (
        f"{cooling_source_name}替代双工况冷量={dual_replace_kw:.1f} kW, "
        f"替代基载冷量={base_replace_kw:.1f} kW"
    )
    return reducible_power_kw, replaced_cooling_kw, description


def estimate_supply_temperature_reduction(
    effective_chiller_flow_m3h: float,
    total_supply_temp_c: float,
    cooling_load_kw: float,
    base_chiller_on_count: int,
    dual_chiller_on_count: int,
    config: StationFlexibilityConfig,
) -> tuple[float, float, float, str]:
    """Estimate power reduction from relaxing over-low supply temperature."""
    if pd.isna(total_supply_temp_c):
        return 0.0, 0.0, 0.0, "缺少总供水温度, 无法计算供水温度上调潜力"
    overcooling_delta_c = max(config.contract_supply_temp_c - float(total_supply_temp_c), 0.0)
    overcooling_cooling_kw = max(effective_chiller_flow_m3h, 0.0) * config.water_heat_kw_per_m3h_c * overcooling_delta_c
    power_kw, cooling_kw, detail = estimate_chiller_reduction_power_kw(
        overcooling_cooling_kw,
        cooling_load_kw,
        base_chiller_on_count,
        dual_chiller_on_count,
        cooling_source_name="供水温度上调",
    )
    return power_kw, cooling_kw, overcooling_delta_c, detail


def estimate_effective_chiller_flow_m3h(
    base_chiller_on_count: int,
    dual_chiller_on_count: int,
    config: StationFlexibilityConfig,
) -> float:
    """Estimate active chilled-water flow from currently running chiller counts."""
    return (
        max(base_chiller_on_count, 0) * config.base_chiller_flow_m3h
        + max(dual_chiller_on_count, 0) * config.dual_chiller_flow_m3h
    )


def normalize_operation_mode(mode: object) -> str:
    text = "" if pd.isna(mode) else str(mode)
    return MODE_ALIASES.get(text, text)


def _ice_discharge_on(row: pd.Series) -> bool:
    if "ice_discharge_on" in row and not pd.isna(row.get("ice_discharge_on")):
        value = row.get("ice_discharge_on")
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "是", "释冰", "on"}
        return bool(value)
    return _to_float(row.get("gap_aware_ice_delta_rt")) < -50.0


def _estimate_one(
    row: pd.Series,
    config: StationFlexibilityConfig,
    reserve_kwh: float,
    max_discharge_kw: float,
) -> dict[str, Any]:
    mode = normalize_operation_mode(row.get("operation_mode", ""))
    cooling_load_kw = _to_float(row.get("cooling_load_kw"))
    current_power_kw = _to_float(row.get("power_kw"))
    usable_ice_energy_kwh = _to_float(row.get("usable_ice_energy_kwh"))
    available_ice_discharge_kw = _to_float(row.get("max_available_ice_discharge_kw"))
    current_ice_discharge_kw = _to_float(row.get("ice_discharge_power_kw"))
    current_ice_charge_kw = _to_float(row.get("ice_charge_power_kw"))
    base_on = int(_to_float(row.get("base_chiller_on_count")))
    dual_on = int(_to_float(row.get("dual_chiller_on_count")))
    dual_power_kw = _to_float(row.get("dual_chiller_power_kw"))
    measured_flow_m3h = _to_float(row.get("flow_m3h"))
    effective_chiller_flow_m3h = _to_float(
        row.get("effective_chiller_flow_m3h"),
        estimate_effective_chiller_flow_m3h(base_on, dual_on, config),
    )
    total_supply_temp_c = _to_float(row.get("total_supply_temp_c"), float("nan"))

    stop_ice_making_cooling_kw = 0.0
    stop_ice_making_power_kw = 0.0
    load_shift_cooling_kw = 0.0
    load_shift_power_kw = 0.0
    supply_temp_reduction_cooling_kw = 0.0
    supply_temp_reduction_power_kw = 0.0
    overcooling_delta_temp_c = 0.0
    reason_parts: list[str] = []

    if mode == "制冰":
        stop_ice_making_cooling_kw = current_ice_charge_kw
        stop_ice_making_power_kw = dual_power_kw if dual_power_kw > 0 else stop_ice_making_cooling_kw / config.ice_making_cop
        reason_parts.append("制冰工况: 用双工况冷水机组电功率估算停止制冰负荷")
    elif mode in {"基载", "基载+双工况"}:
        load_shift_power_kw, load_shift_cooling_kw, detail = estimate_ice_replacement_power_kw(
            available_ice_discharge_kw, cooling_load_kw, base_on, dual_on
        )
        reason_parts.append(f"机械制冷工况: {detail}")
    elif mode in {"释冰+基载", "释冰+基载+双工况"}:
        additional_ice_kw = max(available_ice_discharge_kw - current_ice_discharge_kw, 0.0)
        load_shift_power_kw, load_shift_cooling_kw, detail = estimate_ice_replacement_power_kw(
            additional_ice_kw, cooling_load_kw, base_on, dual_on
        )
        reason_parts.append(f"正在释冰: 剩余释冰空间继续替代机械制冷; {detail}")
    elif mode == "释冰":
        reason_parts.append("纯释冰工况: 主冷机未运行, 站侧可削减空间较小")
    else:
        reason_parts.append("异常或未定义工况: 不建议参与响应")

    supply_flow_m3h = effective_chiller_flow_m3h
    supply_base_on = base_on
    supply_dual_on = dual_on
    if mode == "制冰":
        supply_flow_m3h = estimate_effective_chiller_flow_m3h(base_on, 0, config)
        supply_dual_on = 0
    (
        supply_temp_reduction_power_kw,
        supply_temp_reduction_cooling_kw,
        overcooling_delta_temp_c,
        supply_detail,
    ) = estimate_supply_temperature_reduction(
        supply_flow_m3h,
        total_supply_temp_c,
        cooling_load_kw,
        supply_base_on,
        supply_dual_on,
        config,
    )
    if supply_temp_reduction_cooling_kw > 0:
        reason_parts.append(
            f"总供水温度{total_supply_temp_c:.2f} degC低于合同{config.contract_supply_temp_c:.2f} degC; "
            f"{supply_detail}"
        )

    reducible_power_kw = min(
        max(stop_ice_making_power_kw + load_shift_power_kw + supply_temp_reduction_power_kw, 0.0),
        max(current_power_kw, 0.0),
    )

    transferable_cooling_energy_kwh = 0.0
    response_duration_h = 0.0
    ice_supported_duration_h = (
        usable_ice_energy_kwh / available_ice_discharge_kw if available_ice_discharge_kw > 0 else 0.0
    )
    rebound_energy_kwh = 0.0
    if load_shift_cooling_kw > 0:
        response_duration_h = min(config.target_response_duration_h, usable_ice_energy_kwh / load_shift_cooling_kw)
        transferable_cooling_energy_kwh = load_shift_cooling_kw * response_duration_h
        rebound_energy_kwh += transferable_cooling_energy_kwh
    if supply_temp_reduction_power_kw > 0:
        response_duration_h = max(response_duration_h, config.target_response_duration_h)
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
        reason_parts.append(f"最大释冰功率按历史{config.max_ice_discharge_quantile:.0%}分位估计为{max_discharge_kw:.0f} kW")

    return {
        "stop_ice_making_cooling_kw": stop_ice_making_cooling_kw,
        "stop_ice_making_power_kw": stop_ice_making_power_kw,
        "load_shift_cooling_kw": load_shift_cooling_kw,
        "load_shift_power_kw": load_shift_power_kw,
        "supply_temp_reduction_cooling_kw": supply_temp_reduction_cooling_kw,
        "supply_temp_reduction_power_kw": supply_temp_reduction_power_kw,
        "overcooling_delta_temp_c": overcooling_delta_temp_c,
        "contract_supply_temp_c": config.contract_supply_temp_c,
        "measured_flow_m3h": measured_flow_m3h,
        "effective_chiller_flow_m3h": effective_chiller_flow_m3h,
        "reducible_power_kw": reducible_power_kw,
        "response_duration_h": response_duration_h,
        "ice_supported_duration_h": ice_supported_duration_h,
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
        reducible_power_kw >= config.min_reducible_power_kw_for_limited
        and response_duration_h >= config.min_duration_h_for_limited
    ):
        return "有限响应"
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
