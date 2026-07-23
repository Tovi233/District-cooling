"""Office layout geometry estimators used by building RC inputs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OfficeModule:
    """Typical single-office dimensions."""

    width_m: float
    depth_m: float

    @property
    def area_m2(self) -> float:
        return self.width_m * self.depth_m

    def validate(self) -> None:
        if self.width_m <= 0:
            raise ValueError("office width_m must be positive")
        if self.depth_m <= 0:
            raise ValueError("office depth_m must be positive")


@dataclass(frozen=True)
class InteriorWallEstimate:
    """Estimated interior wall quantities for one floor or a whole building."""

    office_count_per_floor: float
    plan_width_m: float
    plan_depth_m: float
    interior_wall_length_per_floor_m: float
    interior_wall_area_per_floor_m2: float
    interior_wall_volume_per_floor_m3: float
    total_interior_wall_area_m2: float
    total_interior_wall_volume_m3: float


def estimate_office_interior_walls(
    floor_area_per_floor_m2: float,
    floor_count: float,
    floor_height_m: float,
    wall_thickness_m: float,
    office_module: OfficeModule,
    plan_aspect_ratio: float = 1.0,
    layout_complexity_factor: float = 1.0,
) -> InteriorWallEstimate:
    """Estimate interior partition volume from single-floor area.

    The estimator assumes repeated office modules arranged in a near-rectangular
    grid. Shared walls are counted once, and the exterior perimeter is excluded:

        L_inner = A / width + A / depth - (plan_width + plan_depth)

    The optional layout_complexity_factor can represent corridors, service
    rooms, and non-ideal partitions when survey data becomes available.
    """
    office_module.validate()
    if floor_area_per_floor_m2 <= 0:
        raise ValueError("floor_area_per_floor_m2 must be positive")
    if floor_count <= 0:
        raise ValueError("floor_count must be positive")
    if floor_height_m <= 0:
        raise ValueError("floor_height_m must be positive")
    if wall_thickness_m <= 0:
        raise ValueError("wall_thickness_m must be positive")
    if plan_aspect_ratio <= 0:
        raise ValueError("plan_aspect_ratio must be positive")
    if layout_complexity_factor <= 0:
        raise ValueError("layout_complexity_factor must be positive")

    plan_width_m = (floor_area_per_floor_m2 * plan_aspect_ratio) ** 0.5
    plan_depth_m = (floor_area_per_floor_m2 / plan_aspect_ratio) ** 0.5
    office_count_per_floor = floor_area_per_floor_m2 / office_module.area_m2
    ideal_length = (
        floor_area_per_floor_m2 / office_module.width_m
        + floor_area_per_floor_m2 / office_module.depth_m
        - plan_width_m
        - plan_depth_m
    )
    interior_wall_length_per_floor_m = max(ideal_length, 0.0) * layout_complexity_factor
    interior_wall_area_per_floor_m2 = interior_wall_length_per_floor_m * floor_height_m
    interior_wall_volume_per_floor_m3 = (
        interior_wall_area_per_floor_m2 * wall_thickness_m
    )

    return InteriorWallEstimate(
        office_count_per_floor=office_count_per_floor,
        plan_width_m=plan_width_m,
        plan_depth_m=plan_depth_m,
        interior_wall_length_per_floor_m=interior_wall_length_per_floor_m,
        interior_wall_area_per_floor_m2=interior_wall_area_per_floor_m2,
        interior_wall_volume_per_floor_m3=interior_wall_volume_per_floor_m3,
        total_interior_wall_area_m2=interior_wall_area_per_floor_m2 * floor_count,
        total_interior_wall_volume_m3=interior_wall_volume_per_floor_m3 * floor_count,
    )
