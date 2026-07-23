"""Small dependency-free optimizer for conservative RC calibration."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Callable

from scipy.optimize import differential_evolution, minimize

from .parameter_space import CalibrationParameter


@dataclass(frozen=True)
class OptimizationResult:
    """Result returned by the coordinate-search optimizer."""

    best_values: dict[str, float]
    best_loss: float
    evaluations: int
    hit_bounds: list[str]


def _clip(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def coordinate_search(
    parameters: list[CalibrationParameter],
    objective: Callable[[dict[str, float]], float],
    max_iterations: int = 8,
    initial_log_step: float = 0.35,
    step_shrink: float = 0.5,
    initial_values: dict[str, float] | None = None,
) -> OptimizationResult:
    """Minimize an objective over positive bounded multipliers in log space."""
    values = initial_values or {parameter.name: parameter.initial for parameter in parameters}
    best_loss = objective(values)
    evaluations = 1
    log_step = initial_log_step

    for _ in range(max_iterations):
        improved = False
        for parameter in parameters:
            current = values[parameter.name]
            candidates = (
                _clip(current * math.exp(-log_step), parameter.lower, parameter.upper),
                _clip(current * math.exp(log_step), parameter.lower, parameter.upper),
            )
            for candidate in candidates:
                if candidate == current:
                    continue
                trial = dict(values)
                trial[parameter.name] = candidate
                loss = objective(trial)
                evaluations += 1
                if loss < best_loss:
                    values = trial
                    best_loss = loss
                    improved = True
        if not improved:
            log_step *= step_shrink
            if log_step < 0.02:
                break

    hit_bounds = [
        parameter.name
        for parameter in parameters
        if (
            abs(values[parameter.name] - parameter.lower) / parameter.lower < 0.01
            or abs(values[parameter.name] - parameter.upper) / parameter.upper < 0.01
        )
    ]
    return OptimizationResult(
        best_values=values,
        best_loss=best_loss,
        evaluations=evaluations,
        hit_bounds=hit_bounds,
    )


def random_log_search(
    parameters: list[CalibrationParameter],
    objective: Callable[[dict[str, float]], float],
    samples: int,
    seed: int = 42,
) -> OptimizationResult:
    """Randomly sample bounded positive parameters uniformly in log space."""
    generator = random.Random(seed)
    best_values = {parameter.name: parameter.initial for parameter in parameters}
    best_loss = objective(best_values)
    evaluations = 1

    for _ in range(samples):
        values = {}
        for parameter in parameters:
            lower_log = math.log(parameter.lower)
            upper_log = math.log(parameter.upper)
            values[parameter.name] = math.exp(
                generator.uniform(lower_log, upper_log)
            )
        loss = objective(values)
        evaluations += 1
        if loss < best_loss:
            best_values = values
            best_loss = loss

    hit_bounds = [
        parameter.name
        for parameter in parameters
        if (
            abs(best_values[parameter.name] - parameter.lower) / parameter.lower < 0.01
            or abs(best_values[parameter.name] - parameter.upper) / parameter.upper < 0.01
        )
    ]
    return OptimizationResult(
        best_values=best_values,
        best_loss=best_loss,
        evaluations=evaluations,
        hit_bounds=hit_bounds,
    )


def scipy_differential_evolution_l_bfgs_b(
    parameters: list[CalibrationParameter],
    objective: Callable[[dict[str, float]], float],
    max_iterations: int = 40,
    population_size: int = 10,
    seed: int = 42,
    polish: bool = True,
) -> OptimizationResult:
    """Run Differential Evolution globally, then L-BFGS-B locally in log space."""
    parameter_names = [parameter.name for parameter in parameters]
    bounds = [
        (math.log(parameter.lower), math.log(parameter.upper))
        for parameter in parameters
    ]
    evaluations = 0

    def values_from_vector(vector: list[float]) -> dict[str, float]:
        return {
            name: math.exp(value)
            for name, value in zip(parameter_names, vector)
        }

    def vector_objective(vector: list[float]) -> float:
        nonlocal evaluations
        evaluations += 1
        return objective(values_from_vector(vector))

    global_result = differential_evolution(
        vector_objective,
        bounds=bounds,
        maxiter=max_iterations,
        popsize=population_size,
        seed=seed,
        polish=False,
        updating="immediate",
        workers=1,
        tol=0.01,
    )
    best_vector = global_result.x
    best_loss = float(global_result.fun)

    if polish:
        local_result = minimize(
            vector_objective,
            best_vector,
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": max_iterations * 20, "ftol": 1.0e-9},
        )
        if float(local_result.fun) < best_loss:
            best_vector = local_result.x
            best_loss = float(local_result.fun)

    best_values = values_from_vector(best_vector)
    hit_bounds = [
        parameter.name
        for parameter in parameters
        if (
            abs(best_values[parameter.name] - parameter.lower) / parameter.lower < 0.01
            or abs(best_values[parameter.name] - parameter.upper) / parameter.upper < 0.01
        )
    ]
    return OptimizationResult(
        best_values=best_values,
        best_loss=best_loss,
        evaluations=evaluations,
        hit_bounds=hit_bounds,
    )
