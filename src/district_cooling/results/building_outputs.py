"""Building and pipe result exports as CSV files and PNG plots."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
import math
from typing import Any, Callable, Iterable, Sequence

from PIL import Image, ImageDraw, ImageFont

from district_cooling.load import materialize_building_model_config
from district_cooling.system import CoupledSystemSample


@dataclass(frozen=True)
class BuildingACLoadPoint:
    """One building air-conditioning load point."""

    time_s: float
    time_h: float
    q_cool_kw: float


@dataclass(frozen=True)
class ResultSeriesPoint:
    """One generic result series point."""

    time_s: float
    time_h: float
    value_kw: float


def _plot_font(size: int = 22, bold: bool = False) -> ImageFont.ImageFont:
    """Return a readable plot font with a default fallback."""
    font_names = (
        ("arialbd.ttf", "DejaVuSans-Bold.ttf", "arial.ttf", "DejaVuSans.ttf")
        if bold
        else ("arial.ttf", "DejaVuSans.ttf")
    )
    for font_name in font_names:
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _x_axis_bounds(x_values: Sequence[float]) -> tuple[float, float]:
    """Return 0 to the next 24-hour multiple."""
    x_max = max(x_values)
    return 0.0, max(24.0, math.ceil(x_max / 24.0) * 24.0)


def _nice_y_bounds(y_values: Sequence[float]) -> tuple[float, float]:
    """Return padded y-axis bounds."""
    y_min = min(y_values)
    y_max = max(y_values)
    if y_max == y_min:
        return y_min - 1.0, y_max + 1.0
    padding = (y_max - y_min) * 0.08
    return y_min - padding, y_max + padding


def _draw_time_axis_ticks(
    draw: ImageDraw.ImageDraw,
    x_coord: Callable[[float], float],
    axis_y: float,
    plot_top: float,
    x_max: float,
    font: ImageFont.ImageFont,
) -> None:
    """Draw x-axis ticks every 24 hours."""
    tick = 0.0
    while tick <= x_max + 1.0e-9:
        x = x_coord(tick)
        draw.line((x, plot_top, x, axis_y), fill="#eeeeee", width=1)
        draw.line((x, axis_y - 5, x, axis_y + 5), fill="#222222", width=2)
        draw.text((x, axis_y + 22), f"{tick:.0f}", fill="#111111", font=font, anchor="mm")
        tick += 24.0


def _draw_y_axis_ticks(
    draw: ImageDraw.ImageDraw,
    y_coord: Callable[[float], float],
    plot_left: float,
    plot_right: float,
    y_min: float,
    y_max: float,
    font: ImageFont.ImageFont,
) -> None:
    """Draw y-axis ticks and horizontal grid lines."""
    tick_count = 5
    for index in range(tick_count):
        value = y_min + (y_max - y_min) * index / (tick_count - 1)
        y = y_coord(value)
        draw.line((plot_left, y, plot_right, y), fill="#eeeeee", width=1)
        draw.line((plot_left - 5, y, plot_left + 5, y), fill="#222222", width=2)
        draw.text((plot_left - 12, y), f"{value:.1f}", fill="#111111", font=font, anchor="rm")


def _draw_vertical_label(
    image: Image.Image,
    text: str,
    center: tuple[float, float],
    font: ImageFont.ImageFont,
) -> None:
    """Draw a readable vertical axis label."""
    bbox = ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox((0, 0), text, font=font)
    label_width = bbox[2] - bbox[0] + 8
    label_height = bbox[3] - bbox[1] + 8
    label = Image.new("RGBA", (label_width, label_height), (255, 255, 255, 0))
    label_draw = ImageDraw.Draw(label)
    label_draw.text((4, 4), text, fill="#111111", font=font)
    rotated = label.rotate(90, expand=True)
    x = int(center[0] - rotated.width / 2)
    y = int(center[1] - rotated.height / 2)
    image.paste(rotated, (x, y), rotated)


def extract_building_ac_load(
    rows: Iterable[CoupledSystemSample],
) -> list[BuildingACLoadPoint]:
    """Extract building air-conditioning cooling load from coupled rows."""
    return [
        BuildingACLoadPoint(
            time_s=row.time_s,
            time_h=row.time_s / 3600,
            q_cool_kw=row.q_cool_w / 1000,
        )
        for row in rows
    ]


def extract_result_series(
    rows: Iterable[CoupledSystemSample],
    value_getter: Callable[[CoupledSystemSample], float],
) -> list[ResultSeriesPoint]:
    """Extract a kW time series from coupled simulation rows."""
    return [
        ResultSeriesPoint(
            time_s=row.time_s,
            time_h=row.time_s / 3600,
            value_kw=value_getter(row) / 1000,
        )
        for row in rows
    ]


def export_series_csv(
    path: str | Path,
    points: Iterable[ResultSeriesPoint],
    value_column_name: str,
) -> None:
    """Write a result series to CSV."""
    points = list(points)
    if not points:
        raise ValueError("points must not be empty")

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["time_s", "time_h", value_column_name])
        writer.writeheader()
        for point in points:
            writer.writerow(
                {
                    "time_s": point.time_s,
                    "time_h": point.time_h,
                    value_column_name: point.value_kw,
                }
            )


def export_building_ac_load_png(
    path: str | Path,
    points: Sequence[BuildingACLoadPoint],
    width: int = 900,
    height: int = 420,
) -> None:
    """Create a PNG line plot for building air-conditioning load."""
    generic_points = [
        ResultSeriesPoint(
            time_s=point.time_s,
            time_h=point.time_h,
            value_kw=point.q_cool_kw,
        )
        for point in points
    ]
    export_series_png(
        path=path,
        points=generic_points,
        title="Building Air-Conditioning Cooling Load",
        y_label="Qcool (kW)",
        width=width,
        height=height,
    )


def export_series_png(
    path: str | Path,
    points: Sequence[ResultSeriesPoint],
    title: str,
    y_label: str,
    width: int = 900,
    height: int = 420,
) -> None:
    """Create a PNG line plot for any result series."""
    if not points:
        raise ValueError("points must not be empty")
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")

    margin_left = 150
    margin_right = 36
    margin_top = 70
    margin_bottom = 92
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom

    x_values = [point.time_h for point in points]
    y_values = [point.value_kw for point in points]
    x_min, x_max = _x_axis_bounds(x_values)
    y_min, y_max = _nice_y_bounds(y_values)

    def x_coord(value: float) -> float:
        return margin_left + (value - x_min) / (x_max - x_min) * plot_width

    def y_coord(value: float) -> float:
        return margin_top + (y_max - value) / (y_max - y_min) * plot_height

    x_axis_y = margin_top + plot_height
    y_axis_x = margin_left
    x_label = "Time (h)"

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = _plot_font()
    title_font = _plot_font(bold=True)
    axis_title_font = _plot_font(bold=True)

    plot_center_x = margin_left + plot_width / 2
    plot_center_y = margin_top + plot_height / 2
    draw.text((plot_center_x, margin_top - 18), title, fill="#111111", font=title_font, anchor="mm")
    draw.line((y_axis_x, margin_top, y_axis_x, x_axis_y), fill="#222222", width=2)
    draw.line((margin_left, x_axis_y, width - margin_right, x_axis_y), fill="#222222", width=2)
    _draw_time_axis_ticks(draw, x_coord, x_axis_y, margin_top, x_max, font)
    _draw_y_axis_ticks(draw, y_coord, margin_left, width - margin_right, y_min, y_max, font)

    line_points = [
        (x_coord(point.time_h), y_coord(point.value_kw))
        for point in points
    ]
    if len(line_points) == 1:
        x, y = line_points[0]
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill="#0b6fa4")
    else:
        draw.line(line_points, fill="#0b6fa4", width=3, joint="curve")

    draw.text((plot_center_x, x_axis_y + 48), x_label, fill="#111111", font=axis_title_font, anchor="mm")
    _draw_vertical_label(image, y_label, (54, plot_center_y), axis_title_font)

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")


def _draw_series_panel(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    points: Sequence[ResultSeriesPoint],
    title: str,
    y_label: str,
    bounds: tuple[int, int, int, int],
    font: ImageFont.ImageFont,
) -> None:
    """Draw one result series inside a panel on an existing image."""
    if not points:
        raise ValueError("points must not be empty")

    left, top, right, bottom = bounds
    margin_left = 150
    margin_right = 18
    margin_top = 48
    margin_bottom = 64
    plot_left = left + margin_left
    plot_top = top + margin_top
    plot_right = right - margin_right
    plot_bottom = bottom - margin_bottom
    plot_width = plot_right - plot_left
    plot_height = plot_bottom - plot_top

    x_values = [point.time_h for point in points]
    y_values = [point.value_kw for point in points]
    x_min, x_max = _x_axis_bounds(x_values)
    y_min, y_max = _nice_y_bounds(y_values)

    def x_coord(value: float) -> float:
        return plot_left + (value - x_min) / (x_max - x_min) * plot_width

    def y_coord(value: float) -> float:
        return plot_top + (y_max - value) / (y_max - y_min) * plot_height

    draw.rectangle((left, top, right, bottom), outline="#dddddd", width=1)
    title_font = _plot_font(18, bold=True)
    draw.text(((plot_left + plot_right) / 2, plot_top - 18), title, fill="#111111", font=title_font, anchor="mm")
    draw.line((plot_left, plot_top, plot_left, plot_bottom), fill="#222222", width=1)
    draw.line((plot_left, plot_bottom, plot_right, plot_bottom), fill="#222222", width=1)
    _draw_time_axis_ticks(draw, x_coord, plot_bottom, plot_top, x_max, font)
    _draw_y_axis_ticks(draw, y_coord, plot_left, plot_right, y_min, y_max, font)

    line_points = [(x_coord(point.time_h), y_coord(point.value_kw)) for point in points]
    if len(line_points) == 1:
        x, y = line_points[0]
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill="#0b6fa4")
    else:
        draw.line(line_points, fill="#0b6fa4", width=2)

    axis_title_font = _plot_font(18, bold=True)
    draw.text(((plot_left + plot_right) / 2, plot_bottom + 36), "Time (h)", fill="#111111", font=axis_title_font, anchor="mm")
    axis_title_font = _plot_font(18, bold=True)
    _draw_vertical_label(image, y_label, (left + 68, plot_top + plot_height / 2), axis_title_font)


def _draw_text_lines(
    draw: ImageDraw.ImageDraw,
    lines: Sequence[str],
    bounds: tuple[int, int, int, int],
    title: str,
    font: ImageFont.ImageFont,
) -> None:
    """Draw a simple text panel."""
    left, top, right, bottom = bounds
    draw.rectangle((left, top, right, bottom), outline="#dddddd", width=1)
    draw.text(((left + right) / 2, top + 16), title, fill="#111111", font=font, anchor="mm")

    y = top + 36
    line_height = 14
    for line in lines:
        if y + line_height > bottom - 8:
            draw.text((left + 10, y), "...", fill="#111111", font=font)
            break
        draw.text((left + 10, y), line, fill="#111111", font=font)
        y += line_height


def _schedule_points_to_series(
    points: Sequence[dict[str, Any]],
    scale: float,
) -> list[ResultSeriesPoint]:
    """Convert schedule points from config to a plot series."""
    return [
        ResultSeriesPoint(
            time_s=float(point["time_h"]) * 3600.0,
            time_h=float(point["time_h"]),
            value_kw=float(point["value"]) / scale,
        )
        for point in points
    ]


def _plant_input_lines(plant_config: dict[str, Any]) -> list[str]:
    """Format plant input data as compact text lines."""
    model = plant_config["model"]
    lines = [f"Supply water temperature: {model['supply_water_temperature_c']} degC"]
    if "return_water_temperature_c" in model:
        lines.append(f"Return water temperature: {model['return_water_temperature_c']} degC")
    else:
        lines.append("Return water temperature: calculated by building and return pipe")

    for chiller in model["chillers"]:
        lines.append("")
        lines.append(
            f"{chiller['equipment_name']} | qty={chiller['quantity']} | "
            f"power={chiller['power_supply']}"
        )
        for mode in chiller["modes"]:
            lines.append(
                f"  {mode['mode_name']}: cap={mode['cooling_capacity_kw']} kW, "
                f"motor={mode['rated_motor_power_kw']} kW, COP={mode['cop']}, "
                f"chw={mode['chilled_water_temperature']}, "
                f"cw={mode['cooling_water_temperature']}"
            )
    return lines


def _pipe_input_lines(pipe_config: dict[str, Any]) -> list[str]:
    """Format pipe input data as compact text lines."""
    model = pipe_config["model"]
    initial = pipe_config["initial_state"]
    inputs = pipe_config["inputs"]
    simulation = pipe_config["simulation"]
    return [
        f"Pipe length: {model['pipe_length_m']} m",
        f"Pipe resistance per length: {model['pipe_thermal_resistance_k_m_per_w']} K*m/W",
        f"Water heat capacity: {model['water_heat_capacity_j_per_k']} J/K",
        f"Water cp: {model['water_specific_heat_j_per_kg_k']} J/(kg*K)",
        f"Initial supply temperature: {initial['supply_water_temperature_c']} degC",
        f"Initial return temperature: {initial['return_water_temperature_c']} degC",
        f"Soil temperature around buried pipe: {inputs['soil_temperature_c']} degC",
        f"Mass flow: {inputs['mass_flow_kg_per_s']} kg/s",
        f"Time step: {simulation['time_step_s']} s",
        f"Steps: {simulation['steps']}",
    ]


def _building_input_lines(building_config: dict[str, Any]) -> list[str]:
    """Format building input data as compact text lines."""
    raw_model = building_config["model"]
    model = materialize_building_model_config(building_config)
    initial = building_config["initial_state"]
    inputs = building_config["inputs"]
    outwall_r = _thermal_resistance_text(
        model,
        resistance_key="outwall_thermal_resistance_k_per_w",
        layer_key="outwall_layer",
    )
    mass_r = _thermal_resistance_text(
        model,
        resistance_key="mass_thermal_resistance_k_per_w",
        layer_key="mass_layer",
        exchange_key="mass_exchange",
    )
    lines = []
    if "geometry" in raw_model:
        geometry = raw_model["geometry"]
        derived = model["derived_geometry"]
        lines.extend(
            [
                (
                    "Geometry: "
                    f"{geometry['building_count']} building(s), "
                    f"{geometry['floors_per_building']} floors, "
                    f"{geometry['floor_area_per_floor_m2']} m2/floor, "
                    f"{geometry['floor_height_m']} m/floor"
                ),
                f"Derived height: {derived['total_building_height_m']:.3f} m",
                f"Derived total floor area: {derived['total_floor_area_m2']:.3f} m2",
                f"Derived indoor air volume: {derived['indoor_air_volume_m3']:.3f} m3",
                f"Derived exterior wall area: {derived['exterior_wall_area_m2']:.3f} m2",
            ]
        )
    lines.extend(
        [
            f"C_indoor: {model['indoor_air_heat_capacity_j_per_k']} J/K",
            f"C_m base: {model['thermal_mass_heat_capacity_j_per_k']} J/K",
            f"R_outwall: {outwall_r}",
            f"R_m: {mass_r}",
            f"Initial T_indoor: {initial['indoor_air_temperature_c']} degC",
            f"Initial T_m: {initial['thermal_mass_temperature_c']} degC",
            f"Outdoor air temperature: {inputs['outdoor_air_temperature_c']} degC",
            f"Internal heat source default: {inputs['internal_load_w']} W",
            f"Solar gain default: {inputs.get('solar_gain_w', 0.0)} W",
            f"Thermal mass heat default: {inputs.get('thermal_mass_load_w', 0.0)} W",
        ]
    )
    return lines


def _thermal_resistance_text(
    model: dict[str, Any],
    resistance_key: str,
    layer_key: str,
    exchange_key: str | None = None,
) -> str:
    """Format direct or material-derived thermal resistance for plots."""
    if exchange_key is not None and exchange_key in model:
        exchange = model[exchange_key]
        resistance = 1.0 / (
            float(exchange["heat_transfer_coefficient_w_per_m2_k"])
            * float(exchange["heat_transfer_area_m2"])
        )
        return (
            f"{resistance:.6g} K/W "
            f"(h={exchange['heat_transfer_coefficient_w_per_m2_k']} W/(m2*K), "
            f"A={exchange['heat_transfer_area_m2']} m2)"
        )
    if layer_key in model:
        layer = model[layer_key]
        resistance = (
            float(layer["thickness_m"])
            / float(layer["thermal_conductivity_w_per_m_k"])
            / float(layer["heat_transfer_area_m2"])
        )
        return (
            f"{resistance:.6g} K/W "
            f"({layer.get('material', 'layer')}, "
            f"{layer['thickness_m']} m, "
            f"lambda={layer['thermal_conductivity_w_per_m_k']} W/(m*K), "
            f"A={layer['heat_transfer_area_m2']} m2)"
        )
    return f"{model[resistance_key]} K/W"


def export_input_data_summary_png(
    path: str | Path,
    plant_config: dict[str, Any],
    pipe_config: dict[str, Any],
    building_config: dict[str, Any],
    width: int = 1600,
    height: int = 1200,
) -> None:
    """Export one PNG containing all user-provided model input data."""
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    schedule_font = _plot_font(18)
    title_font = _plot_font(bold=True)
    draw.text((width / 2, 24), "User Input Data Summary", fill="#111111", font=title_font, anchor="mm")

    gap = 20
    left = 28
    top = 52
    upper_height = 470
    plant_width = 860
    side_width = width - left * 2 - gap - plant_width

    _draw_text_lines(
        draw,
        _plant_input_lines(plant_config),
        (left, top, left + plant_width, top + upper_height),
        "Central Plant Inputs",
        font,
    )

    side_left = left + plant_width + gap
    _draw_text_lines(
        draw,
        _pipe_input_lines(pipe_config),
        (side_left, top, width - left, top + 220),
        "Pipe Network Inputs",
        font,
    )
    _draw_text_lines(
        draw,
        _building_input_lines(building_config),
        (side_left, top + 240, width - left, top + upper_height),
        "Building RC Inputs",
        font,
    )

    schedules = building_config.get("schedules", {})
    schedule_specs = [
        (
            "Internal Heat Source Schedule",
            "Qinternal (kW)",
            "internal_load_w",
            1000.0,
        ),
        (
            "Solar Gain Schedule",
            "Qsolar (kW)",
            "solar_gain_w",
            1000.0,
        ),
        (
            "Thermal Mass Heat Schedule",
            "Qm (kW)",
            "thermal_mass_load_w",
            1000.0,
        ),
        (
            "Thermal Mass Capacity Schedule",
            "Cm (1e9 J/K)",
            "thermal_mass_heat_capacity_j_per_k",
            1.0e9,
        ),
    ]
    schedule_top = top + upper_height + 28
    panel_height = height - schedule_top - 28
    panel_width = (width - left * 2 - gap * 3) // 4
    for index, (title, y_label, key, scale) in enumerate(schedule_specs):
        panel_left = left + index * (panel_width + gap)
        bounds = (panel_left, schedule_top, panel_left + panel_width, schedule_top + panel_height)
        if key in schedules:
            points = _schedule_points_to_series(schedules[key], scale)
            _draw_series_panel(image, draw, points, title, y_label, bounds, schedule_font)
        else:
            _draw_text_lines(draw, ["No schedule configured."], bounds, title, font)

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")


def export_combined_results_png(
    path: str | Path,
    series_by_name: dict[str, tuple[str, str, Sequence[ResultSeriesPoint]]],
    width: int = 2200,
    height: int = 1600,
) -> None:
    """Export a combined PNG figure for the standard result series."""
    if not series_by_name:
        raise ValueError("series_by_name must not be empty")

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = _plot_font(18)
    title_font = _plot_font(bold=True)
    draw.text((width / 2, 22), "Calculated Output Summary", fill="#111111", font=title_font, anchor="mm")

    gap = 24
    outer_left = 28
    outer_top = 48
    columns = 2
    rows = math.ceil(len(series_by_name) / columns)
    panel_width = (width - 2 * outer_left - gap * (columns - 1)) // columns
    panel_height = (height - outer_top - 28 - gap * (rows - 1)) // rows

    panel_bounds = []
    for row_index in range(rows):
        for column_index in range(columns):
            left = outer_left + column_index * (panel_width + gap)
            top = outer_top + row_index * (panel_height + gap)
            panel_bounds.append((left, top, left + panel_width, top + panel_height))

    for bounds, (_, (title, y_label, points)) in zip(panel_bounds, series_by_name.items()):
        _draw_series_panel(image, draw, points, title, y_label, bounds, font)

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")


def export_standard_results(
    figure_dir: str | Path,
    table_dir: str | Path,
    rows: Iterable[CoupledSystemSample],
) -> dict[str, dict[str, Path]]:
    """Export standard result CSV files and PNG figures for each calculation."""
    rows = list(rows)
    if not rows:
        raise ValueError("rows must not be empty")

    figure_output_dir = Path(figure_dir)
    table_output_dir = Path(table_dir)
    figure_output_dir.mkdir(parents=True, exist_ok=True)
    table_output_dir.mkdir(parents=True, exist_ok=True)

    figure_specs = {
        "internal_heat_source": (
            "Indoor Internal Heat Source",
            "Qinternal (kW)",
            "q_internal_heat_source_kw",
            lambda row: row.q_internal_load_w,
        ),
        "outwall_heat_gain": (
            "Outdoor Heat Gain Through Wall",
            "Qoutwall (kW)",
            "q_outwall_heat_gain_kw",
            lambda row: row.q_outwall_w,
        ),
        "solar_gain": (
            "Direct Solar Gain",
            "Qsolar (kW)",
            "q_solar_gain_kw",
            lambda row: row.q_solar_gain_w,
        ),
        "air_conditioning_load": (
            "Air-Conditioning Cooling Load",
            "Qcool (kW)",
            "q_air_conditioning_load_kw",
            lambda row: row.q_cool_w,
        ),
        "building_cooling_demand": (
            "Building Cooling Demand",
            "Qdemand (kW)",
            "q_building_cooling_demand_kw",
            lambda row: row.q_building_cooling_demand_w,
        ),
        "supply_pipe_loss": (
            "Supply Pipe Heat Gain/Loss",
            "Qsupply_pipe (kW)",
            "q_supply_pipe_loss_kw",
            lambda row: row.supply_pipe_heat_gain_w,
        ),
        "return_pipe_loss": (
            "Return Pipe Heat Gain/Loss",
            "Qreturn_pipe (kW)",
            "q_return_pipe_loss_kw",
            lambda row: row.return_pipe_heat_gain_w,
        ),
    }

    paths: dict[str, dict[str, Path]] = {}
    combined_series: dict[str, tuple[str, str, Sequence[ResultSeriesPoint]]] = {}
    for filename_stem, (title, y_label, column_name, getter) in figure_specs.items():
        points = extract_result_series(rows, getter)
        csv_path = table_output_dir / f"{filename_stem}.csv"
        png_path = figure_output_dir / f"{filename_stem}.png"
        export_series_csv(csv_path, points, column_name)
        export_series_png(
            path=png_path,
            points=points,
            title=title,
            y_label=y_label,
        )
        paths[filename_stem] = {"csv": csv_path, "png": png_path}
        combined_series[filename_stem] = (title, y_label, points)

    combined_png_path = figure_output_dir / "calculated_outputs_summary.png"
    export_combined_results_png(combined_png_path, combined_series)
    paths["calculated_outputs_summary"] = {"png": combined_png_path}

    return paths
