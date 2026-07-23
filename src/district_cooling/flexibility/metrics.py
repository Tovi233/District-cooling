"""General flexibility metrics based on baseline, response, and rebound power curves.

This module implements the formal quantification indicators used by the project.
Station-side, network-side, and building-side models can all feed power curves
into these functions once they can produce a baseline scenario and a response
scenario.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

import numpy as np


@dataclass(frozen=True)
class PowerResponseSeries:
    """Power curves for one demand-response event.

    Attributes:
        time_h: Time axis in hours. It can be absolute simulation time or
            relative event time, but must be monotonically increasing.
        p_base_kw: Baseline system power under normal operation.
        p_response_kw: System power during the demand-response reduction period.
        p_rebound_kw: System power during the post-response rebound period.
        response_start_h: Start time of the demand-response period.
        response_end_h: End time of the demand-response period.
        rebound_end_h: End time of the rebound period.
    """

    time_h: np.ndarray
    p_base_kw: np.ndarray
    p_response_kw: np.ndarray
    p_rebound_kw: np.ndarray
    response_start_h: float
    response_end_h: float
    rebound_end_h: float


@dataclass(frozen=True)
class FlexibilityMetrics:
    """Formal flexibility-potential indicators."""

    comprehensive_flexibility_kw: float
    max_reduction_power_kw: float
    time_to_max_reduction_h: float
    average_reduction_power_kw: float
    max_rebound_power_kw: float
    rebound_duration_h: float
    average_rebound_power_kw: float
    reduction_energy_kwh: float
    rebound_energy_kwh: float


@dataclass(frozen=True)
class CollaborationMetrics:
    """Absolute and relative collaboration-effect indicators."""

    absolute_delta: float
    relative_delta_percent: float


def calculate_flexibility_metrics(
    series: PowerResponseSeries,
    comprehensive_function: Callable[[FlexibilityMetrics], float] | None = None,
) -> FlexibilityMetrics:
    """Calculate the project-level flexibility indicators.

    The implemented formulas are:

    A = max(P_base - P_dr)
    TA = t_Amax - t_drst
    a = integral(P_base - P_dr) dt / (t_drend - t_drst)
    B = max(P_reb - P_base)
    Tb = t_rebend - t_drend
    b = integral(P_reb - P_base) dt / Tb

    F is kept configurable because the source document defines it as
    F = f(P_base, P_dr, P_reb), but does not lock a scoring function. The
    default uses a conservative net-power value:

    F = A - B
    """
    time_h, p_base, p_response, p_rebound = _validated_arrays(series)

    response_mask = _period_mask(time_h, series.response_start_h, series.response_end_h)
    rebound_mask = _period_mask(time_h, series.response_end_h, series.rebound_end_h)

    reduction_curve = (p_base - p_response).clip(min=0.0)
    rebound_curve = (p_rebound - p_base).clip(min=0.0)

    response_time = time_h[response_mask]
    response_reduction = reduction_curve[response_mask]
    rebound_time = time_h[rebound_mask]
    rebound_power = rebound_curve[rebound_mask]

    max_reduction = _max_or_zero(response_reduction)
    if response_reduction.size:
        time_to_max = float(response_time[int(np.argmax(response_reduction))] - series.response_start_h)
    else:
        time_to_max = 0.0

    response_duration = max(series.response_end_h - series.response_start_h, 0.0)
    reduction_energy = _integral_kwh(response_time, response_reduction)
    average_reduction = reduction_energy / response_duration if response_duration > 0 else 0.0

    max_rebound = _max_or_zero(rebound_power)
    rebound_duration = max(series.rebound_end_h - series.response_end_h, 0.0)
    rebound_energy = _integral_kwh(rebound_time, rebound_power)
    average_rebound = rebound_energy / rebound_duration if rebound_duration > 0 else 0.0

    draft = FlexibilityMetrics(
        comprehensive_flexibility_kw=max_reduction - max_rebound,
        max_reduction_power_kw=max_reduction,
        time_to_max_reduction_h=max(time_to_max, 0.0),
        average_reduction_power_kw=average_reduction,
        max_rebound_power_kw=max_rebound,
        rebound_duration_h=rebound_duration,
        average_rebound_power_kw=average_rebound,
        reduction_energy_kwh=reduction_energy,
        rebound_energy_kwh=rebound_energy,
    )
    if comprehensive_function is None:
        return draft
    return FlexibilityMetrics(
        comprehensive_flexibility_kw=float(comprehensive_function(draft)),
        max_reduction_power_kw=draft.max_reduction_power_kw,
        time_to_max_reduction_h=draft.time_to_max_reduction_h,
        average_reduction_power_kw=draft.average_reduction_power_kw,
        max_rebound_power_kw=draft.max_rebound_power_kw,
        rebound_duration_h=draft.rebound_duration_h,
        average_rebound_power_kw=draft.average_rebound_power_kw,
        reduction_energy_kwh=draft.reduction_energy_kwh,
        rebound_energy_kwh=draft.rebound_energy_kwh,
    )


def calculate_collaboration_effect(single_value: float, joint_value: float) -> CollaborationMetrics:
    """Calculate absolute and relative collaboration effects.

    Delta X = X_joint - X_single
    Delta X% = Delta X / X_single * 100%
    """
    absolute_delta = float(joint_value - single_value)
    if single_value == 0:
        relative_delta = 0.0
    else:
        relative_delta = absolute_delta / float(single_value) * 100.0
    return CollaborationMetrics(absolute_delta=absolute_delta, relative_delta_percent=relative_delta)


def _validated_arrays(series: PowerResponseSeries) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    arrays = (
        np.asarray(series.time_h, dtype=float),
        np.asarray(series.p_base_kw, dtype=float),
        np.asarray(series.p_response_kw, dtype=float),
        np.asarray(series.p_rebound_kw, dtype=float),
    )
    lengths = {array.size for array in arrays}
    if len(lengths) != 1:
        raise ValueError("time_h, p_base_kw, p_response_kw, and p_rebound_kw must have the same length")
    if arrays[0].size < 2:
        raise ValueError("At least two time points are required")
    if np.any(np.diff(arrays[0]) < 0):
        raise ValueError("time_h must be monotonically increasing")
    if series.response_end_h < series.response_start_h:
        raise ValueError("response_end_h must be greater than or equal to response_start_h")
    if series.rebound_end_h < series.response_end_h:
        raise ValueError("rebound_end_h must be greater than or equal to response_end_h")
    return arrays


def _period_mask(time_h: np.ndarray, start_h: float, end_h: float) -> np.ndarray:
    return (time_h >= start_h) & (time_h <= end_h)


def _integral_kwh(time_h: Iterable[float], power_kw: Iterable[float]) -> float:
    time = np.asarray(list(time_h), dtype=float)
    power = np.asarray(list(power_kw), dtype=float)
    if time.size < 2:
        return 0.0
    return float(np.trapezoid(power, time))


def _max_or_zero(values: np.ndarray) -> float:
    if values.size == 0:
        return 0.0
    return float(np.max(values))
