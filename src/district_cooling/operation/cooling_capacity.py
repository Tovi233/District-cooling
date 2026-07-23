"""Hybrid cooling-capacity calculations for measured station data."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class WaterSideCapacityConfig:
    """Configuration for chiller water-side cooling-capacity calculation."""

    water_density_kg_m3: float
    water_specific_heat_kj_kg_k: float
    rated_frequency_hz: float
    max_flow_ratio: float
    use_frequency_to_scale_flow: bool
    ignore_chiller_power_for_capacity: bool
    chiller_mappings: tuple[dict[str, Any], ...]
    pump_inventory: dict[str, Any]
    reference_capacity_limits: dict[str, Any]


def load_capacity_config(path: str | Path) -> WaterSideCapacityConfig:
    """Load water-side capacity calculation config from JSON."""
    values = json.loads(Path(path).read_text(encoding="utf-8"))
    return WaterSideCapacityConfig(
        water_density_kg_m3=float(values["water_density_kg_m3"]),
        water_specific_heat_kj_kg_k=float(values["water_specific_heat_kj_kg_k"]),
        rated_frequency_hz=float(values["rated_frequency_hz"]),
        max_flow_ratio=float(values["max_flow_ratio"]),
        use_frequency_to_scale_flow=bool(values["use_frequency_to_scale_flow"]),
        ignore_chiller_power_for_capacity=bool(values["ignore_chiller_power_for_capacity"]),
        chiller_mappings=tuple(values["chiller_mappings"]),
        pump_inventory=dict(values.get("pump_inventory", {})),
        reference_capacity_limits=dict(values.get("reference_capacity_limits", {})),
    )


def calculate_water_side_capacity(data: pd.DataFrame, config: WaterSideCapacityConfig) -> pd.DataFrame:
    """Calculate cooling capacity with the configured method for each chiller.

    Supported methods:
    - water_side: Q = rho * cp * flow / 3600 * (T_chw_in - T_chw_out)
    - power_cop: Q = motor_power * COP
    """
    out = data[["source_sheet", "collect_time_iso"]].copy()
    total = pd.Series(0.0, index=data.index)

    for mapping in config.chiller_mappings:
        if not mapping.get("use", True):
            continue
        chiller_id = str(mapping["chiller_id"])
        pump_id = str(mapping["pump_id"])
        rated_flow = float(mapping["rated_flow_m3h"])
        prefix = f"{chiller_id}"
        method = str(mapping.get("capacity_method", "water_side"))

        tin = _numeric(data, f"{chiller_id}__chw_in_temp")
        tout = _numeric(data, f"{chiller_id}__chw_out_temp")
        status = _numeric(data, f"{chiller_id}__status").fillna(0.0)
        delta_t = (tin - tout).clip(lower=0)
        flow_m3h = pd.Series(pd.NA, index=data.index, dtype="Float64")
        cop = pd.Series(pd.NA, index=data.index, dtype="Float64")

        if method == "water_side":
            pump_freq = _numeric(data, f"{pump_id}__freq_hz")
            pump_power = _numeric(data, f"{pump_id}__power_kw").fillna(0.0)
            flow_ratio = _flow_ratio_from_pump(pump_freq, pump_power, status, config)
            flow_m3h = rated_flow * flow_ratio
            capacity_kw = (
                config.water_density_kg_m3
                * config.water_specific_heat_kj_kg_k
                * flow_m3h
                / 3600.0
                * delta_t
            )
        elif method == "power_cop":
            motor_power = _numeric(data, f"{chiller_id}__power_kw").fillna(0.0)
            cop = _cop_for_mapping(mapping, tout)
            capacity_kw = motor_power * cop
        else:
            capacity_kw = pd.Series(0.0, index=data.index)

        capacity_kw = capacity_kw.where(status.gt(0.5), 0.0)
        reference = config.reference_capacity_limits.get(chiller_id, {})
        air_conditioning_limit = reference.get("air_conditioning_capacity_kw")
        if air_conditioning_limit is not None:
            out[f"{prefix}_capacity_over_reference_ratio"] = capacity_kw / float(air_conditioning_limit)

        out[f"{prefix}_capacity_method"] = method
        out[f"{prefix}_mapped_pump"] = pump_id
        out[f"{prefix}_estimated_flow_m3h"] = flow_m3h
        out[f"{prefix}_chw_delta_t_c"] = delta_t
        out[f"{prefix}_capacity_cop"] = cop
        out[f"{prefix}_water_side_capacity_kw"] = capacity_kw
        total = total.add(capacity_kw.fillna(0.0), fill_value=0.0)

    out["calculated_total_chiller_capacity_kw"] = total
    if "SYS_TOTAL__cooling_load" in data:
        out["measured_system_cooling_load_kw"] = _numeric(data, "SYS_TOTAL__cooling_load")
        out["capacity_minus_system_load_kw"] = out["calculated_total_chiller_capacity_kw"] - out[
            "measured_system_cooling_load_kw"
        ]
        out["capacity_to_system_load_ratio"] = out["calculated_total_chiller_capacity_kw"] / out[
            "measured_system_cooling_load_kw"
        ].replace(0, pd.NA)
    return out


def summarize_water_side_capacity(capacity: pd.DataFrame) -> pd.DataFrame:
    """Summarize calculated capacity by chiller and total."""
    records: list[dict[str, Any]] = []
    for column in capacity.columns:
        if column.endswith("_water_side_capacity_kw") or column == "calculated_total_chiller_capacity_kw":
            series = pd.to_numeric(capacity[column], errors="coerce")
            records.append(
                {
                    "item": column.replace("_water_side_capacity_kw", ""),
                    "mean_kw": series.mean(),
                    "min_kw": series.min(),
                    "max_kw": series.max(),
                    "p05_kw": series.quantile(0.05),
                    "p95_kw": series.quantile(0.95),
                    "nonzero_points": int(series.gt(1).sum()),
                }
            )
        if column.endswith("_capacity_over_reference_ratio"):
            series = pd.to_numeric(capacity[column], errors="coerce")
            records.append(
                {
                    "item": column.replace("_capacity_over_reference_ratio", "_over_reference_ratio"),
                    "mean_kw": series.mean(),
                    "min_kw": series.min(),
                    "max_kw": series.max(),
                    "p05_kw": series.quantile(0.05),
                    "p95_kw": series.quantile(0.95),
                    "nonzero_points": int(series.gt(1.0).sum()),
                }
            )
    if "capacity_to_system_load_ratio" in capacity:
        ratio = pd.to_numeric(capacity["capacity_to_system_load_ratio"], errors="coerce")
        records.append(
            {
                "item": "capacity_to_system_load_ratio",
                "mean_kw": ratio.mean(),
                "min_kw": ratio.min(),
                "max_kw": ratio.max(),
                "p05_kw": ratio.quantile(0.05),
                "p95_kw": ratio.quantile(0.95),
                "nonzero_points": int(ratio.dropna().count()),
            }
        )
    return pd.DataFrame(records)


def _flow_ratio_from_pump(
    pump_freq: pd.Series,
    pump_power: pd.Series,
    chiller_status: pd.Series,
    config: WaterSideCapacityConfig,
) -> pd.Series:
    if config.use_frequency_to_scale_flow and pump_freq.notna().any():
        ratio = pump_freq / config.rated_frequency_hz
        ratio = ratio.clip(lower=0, upper=config.max_flow_ratio)
        if pump_power.notna().any():
            ratio = ratio.where(pump_power.gt(1.0) | chiller_status.gt(0.5), 0.0)
        return ratio.fillna(0.0)
    return chiller_status.gt(0.5).astype(float)


def _cop_for_mapping(mapping: dict[str, Any], chw_out_temp: pd.Series) -> pd.Series:
    air_cop = float(mapping.get("cop_air_conditioning", mapping.get("cop", 1.0)))
    ice_cop = mapping.get("cop_ice_making")
    cop = pd.Series(air_cop, index=chw_out_temp.index, dtype="float64")
    if ice_cop is not None:
        threshold = float(mapping.get("ice_making_chw_out_threshold_c", 0.0))
        cop = cop.where(chw_out_temp.ge(threshold), float(ice_cop))
    return cop


def _numeric(data: pd.DataFrame, column: str) -> pd.Series:
    if column not in data:
        return pd.Series(pd.NA, index=data.index, dtype="Float64")
    return pd.to_numeric(data[column], errors="coerce")
