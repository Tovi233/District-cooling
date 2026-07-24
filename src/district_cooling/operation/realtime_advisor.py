"""Realtime operation advice for station-side flexibility control."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .flexibility_potential import (
    StationFlexibilityConfig,
    estimate_effective_chiller_flow_m3h,
    estimate_effective_ice_delta_rt,
    estimate_supply_temperature_reduction,
    estimate_ice_replacement_power_kw,
)


ResponseLevel = Literal["可响应", "有限响应", "不建议响应"]
DEFAULT_STEP_H = 0.25


@dataclass(frozen=True)
class RealtimeStationState:
    """Current station operation data used by the realtime advisor."""

    operation_mode: str
    cooling_load_kw: float
    power_kw: float
    ice_inventory_rt: float
    ice_delta_per_step_rt: float
    base_chiller_on_count: int
    dual_chiller_on_count: int
    dual_min_chw_out_temp_c: float
    dual_chiller_power_kw: float
    max_ice_discharge_power_kw: float
    max_ice_inventory_rt: float
    flow_m3h: float = 0.0
    total_supply_temp_c: float | None = None
    ice_discharge_on: bool | None = None
    min_chiller_setpoint_c: float | None = None
    base_chiller_avg_freq_hz: float | None = None
    dual_chiller_avg_freq_hz: float | None = None


@dataclass(frozen=True)
class RealtimeAdvice:
    """Calculated flexibility and direct operation recommendations."""

    response_level: ResponseLevel
    reducible_power_kw: float
    response_duration_h: float
    transferable_cooling_energy_kwh: float
    rebound_power_kw: float
    usable_ice_energy_kwh: float
    ice_discharge_power_kw: float
    ice_charge_power_kw: float
    stop_ice_making_power_kw: float
    load_shift_power_kw: float
    supply_temp_reduction_power_kw: float
    supply_temp_reduction_cooling_kw: float
    overcooling_delta_temp_c: float
    operation_summary: str
    recommended_actions: tuple[str, ...]
    warnings: tuple[str, ...]


def infer_station_mode(
    base_chiller_on_count: int,
    dual_chiller_on_count: int,
    dual_min_chw_out_temp_c: float,
    measured_ice_delta_per_step_rt: float,
    ice_discharge_on: bool | None = None,
) -> str:
    """Infer operation mode using the established priority rules."""
    base_on = base_chiller_on_count > 0
    dual_on = dual_chiller_on_count > 0
    ice_discharging = measured_ice_delta_per_step_rt < -50.0 if ice_discharge_on is None else ice_discharge_on
    ice_making = dual_on and dual_min_chw_out_temp_c < 0.0

    if ice_making:
        return "制冰"
    if ice_discharging and base_on and dual_on:
        return "释冰+基载+双工况"
    if ice_discharging and base_on:
        return "释冰+基载"
    if ice_discharging and not base_on and not dual_on:
        return "释冰"
    if base_on and dual_on:
        return "基载+双工况"
    if base_on:
        return "基载"
    return "异常/未定义"


def advise_realtime_operation(
    state: RealtimeStationState,
    config: StationFlexibilityConfig | None = None,
) -> RealtimeAdvice:
    """Return station-side flexibility and direct control advice."""
    cfg = config or StationFlexibilityConfig()
    effective_ice_delta_rt = estimate_effective_ice_delta_rt(
        state.dual_chiller_on_count,
        state.dual_min_chw_out_temp_c,
        state.dual_chiller_power_kw,
        state.ice_delta_per_step_rt,
        state.ice_discharge_on if state.ice_discharge_on is not None else state.ice_delta_per_step_rt < -50.0,
        DEFAULT_STEP_H,
        cfg.rt_to_kwh,
        cfg.ice_making_cop,
    )
    ice_discharge_kw = max(-effective_ice_delta_rt * cfg.rt_to_kwh / DEFAULT_STEP_H, 0.0)
    ice_charge_kw = max(effective_ice_delta_rt * cfg.rt_to_kwh / DEFAULT_STEP_H, 0.0)
    ice_remaining_kwh = state.ice_inventory_rt * cfg.rt_to_kwh
    reserve_kwh = state.max_ice_inventory_rt * cfg.rt_to_kwh * cfg.ice_reserve_fraction
    usable_ice_kwh = max(ice_remaining_kwh - reserve_kwh, 0.0) * cfg.usable_ice_fraction
    available_ice_kw = min(usable_ice_kwh / cfg.target_response_duration_h, state.max_ice_discharge_power_kw)

    mode = state.operation_mode or infer_station_mode(
        state.base_chiller_on_count,
        state.dual_chiller_on_count,
        state.dual_min_chw_out_temp_c,
        state.ice_delta_per_step_rt,
        state.ice_discharge_on,
    )

    stop_ice_power_kw = 0.0
    load_shift_power_kw = 0.0
    load_shift_cooling_kw = 0.0
    supply_temp_reduction_power_kw = 0.0
    supply_temp_reduction_cooling_kw = 0.0
    overcooling_delta_temp_c = 0.0
    transferable_cooling_kwh = 0.0
    response_duration_h = 0.0
    actions: list[str] = []
    warnings: list[str] = []

    if mode == "制冰":
        stop_ice_power_kw = ice_charge_kw / cfg.ice_making_cop
        response_duration_h = cfg.target_response_duration_h if stop_ice_power_kw > 0 else 0.0
        transferable_cooling_kwh = ice_charge_kw * response_duration_h
        actions.append("停止或降低制冰负荷，可直接减少双工况机组制冰电功率。")
    elif mode in {"基载", "基载+双工况"}:
        load_shift_power_kw, load_shift_cooling_kw, detail = estimate_ice_replacement_power_kw(
            available_ice_kw,
            state.cooling_load_kw,
            state.base_chiller_on_count,
            state.dual_chiller_on_count,
        )
        actions.append(f"增加释冰供冷替代机械制冷。{detail}。")
    elif mode in {"释冰+基载", "释冰+基载+双工况"}:
        additional_ice_kw = max(available_ice_kw - ice_discharge_kw, 0.0)
        load_shift_power_kw, load_shift_cooling_kw, detail = estimate_ice_replacement_power_kw(
            additional_ice_kw,
            state.cooling_load_kw,
            state.base_chiller_on_count,
            state.dual_chiller_on_count,
        )
        actions.append(f"提高释冰功率进一步替代机械制冷。{detail}。")
    else:
        actions.append("当前工况不适合作为自动需求响应时段，建议先核查设备状态和测点。")

    if state.total_supply_temp_c is not None:
        supply_base_on = state.base_chiller_on_count
        supply_dual_on = 0 if mode == "制冰" else state.dual_chiller_on_count
        (
            supply_temp_reduction_power_kw,
            supply_temp_reduction_cooling_kw,
            overcooling_delta_temp_c,
            detail,
        ) = estimate_supply_temperature_reduction(
            estimate_effective_chiller_flow_m3h(
                supply_base_on,
                supply_dual_on,
                cfg,
            ),
            state.total_supply_temp_c,
            state.cooling_load_kw,
            supply_base_on,
            supply_dual_on,
            cfg,
        )
        if supply_temp_reduction_power_kw > 0:
            actions.append(
                f"总供水温度低于合同值{cfg.contract_supply_temp_c:.1f}℃，可上调供水温度减少过冷冷量。{detail}。"
            )

    if load_shift_cooling_kw > 0:
        response_duration_h = min(cfg.target_response_duration_h, usable_ice_kwh / load_shift_cooling_kw)
        transferable_cooling_kwh = load_shift_cooling_kw * response_duration_h
    if supply_temp_reduction_power_kw > 0:
        response_duration_h = max(response_duration_h, cfg.target_response_duration_h)

    reducible_power_kw = min(
        max(stop_ice_power_kw + load_shift_power_kw + supply_temp_reduction_power_kw, 0.0),
        max(state.power_kw, 0.0),
    )
    rebound_power_kw = transferable_cooling_kwh / cfg.ice_making_cop / cfg.restore_duration_h
    level = _response_level(reducible_power_kw, response_duration_h, cfg)

    if not _has_frequency(state.base_chiller_avg_freq_hz) and not _has_frequency(state.dual_chiller_avg_freq_hz):
        warnings.append("当前数据没有有效冷机频率测点，变频建议需接入冷机频率或压缩机负荷率后校核。")
    if level == "不建议响应":
        warnings.append("可削减功率或可响应时长不足，当前不建议参与削峰响应。")

    summary = (
        f"当前工况为{mode}，可削减功率约{reducible_power_kw:.1f} kW，"
        f"可响应时长约{response_duration_h:.2f} h，响应等级为{level}。"
    )
    return RealtimeAdvice(
        response_level=level,
        reducible_power_kw=reducible_power_kw,
        response_duration_h=response_duration_h,
        transferable_cooling_energy_kwh=transferable_cooling_kwh,
        rebound_power_kw=rebound_power_kw,
        usable_ice_energy_kwh=usable_ice_kwh,
        ice_discharge_power_kw=ice_discharge_kw,
        ice_charge_power_kw=ice_charge_kw,
        stop_ice_making_power_kw=stop_ice_power_kw,
        load_shift_power_kw=load_shift_power_kw,
        supply_temp_reduction_power_kw=supply_temp_reduction_power_kw,
        supply_temp_reduction_cooling_kw=supply_temp_reduction_cooling_kw,
        overcooling_delta_temp_c=overcooling_delta_temp_c,
        operation_summary=summary,
        recommended_actions=tuple(dict.fromkeys(actions)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _response_level(
    reducible_power_kw: float,
    response_duration_h: float,
    config: StationFlexibilityConfig,
) -> ResponseLevel:
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


def _has_frequency(value: float | None) -> bool:
    return value is not None and value > 0.0
