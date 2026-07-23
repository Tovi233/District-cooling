"""Cluster station operation data to validate rule-based operation modes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from scipy.cluster.vq import kmeans2


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODE_DIR = PROJECT_ROOT / "data" / "processed" / "operation_mode_identification"
DEFAULT_CAPACITY_DIR = PROJECT_ROOT / "data" / "processed" / "water_side_capacity"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "processed" / "operation_mode_clustering"

FEATURE_COLUMNS = [
    "cooling_load_kw",
    "flow_m3h",
    "power_kw",
    "ice_delta_per_step",
    "load_ratio",
    "kw_per_cooling_kw",
    "base_chiller_on_count",
    "dual_chiller_on_count",
    "cooling_tower_on_count",
    "pump_on_count",
    "dual_min_chw_out_temp_c",
    "calculated_total_chiller_capacity_kw",
    "capacity_to_system_load_ratio",
]

MODE_COLORS = {
    "异常": "#8E8E93",
    "基载": "#4E79A7",
    "基载+双工况": "#EDC948",
    "制冰": "#9C6ADE",
    "释冰": "#76B7B2",
    "释冰+基载": "#59A14F",
    "释冰+基载+双工况": "#F28E2B",
}

CLUSTER_COLORS = [
    "#4E79A7",
    "#F28E2B",
    "#59A14F",
    "#E15759",
    "#76B7B2",
    "#9C6ADE",
    "#EDC948",
    "#B07AA1",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode-dir", type=Path, default=DEFAULT_MODE_DIR)
    parser.add_argument("--capacity-dir", type=Path, default=DEFAULT_CAPACITY_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--k",
        type=int,
        default=None,
        help="Cluster count. Defaults to the number of rule modes present in current data.",
    )
    parser.add_argument("--min-k", type=int, default=3, help="Only used when --auto-k is set.")
    parser.add_argument("--max-k", type=int, default=8, help="Only used when --auto-k is set.")
    parser.add_argument("--auto-k", action="store_true", help="Select k by silhouette score instead of rule-mode count.")
    parser.add_argument("--random-seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    data = _load_features(args.mode_dir, args.capacity_dir)
    feature_matrix, feature_stats = _standardize_features(data, FEATURE_COLUMNS)
    if args.auto_k:
        best_k, k_scores = _select_k(feature_matrix, args.min_k, args.max_k, args.random_seed)
    else:
        best_k = args.k or int(data["operation_mode"].nunique())
        labels_for_score, centroids_for_score = _fit_kmeans(feature_matrix, best_k, args.random_seed)
        inertia = float(np.sum(_cluster_distances(feature_matrix, labels_for_score, centroids_for_score) ** 2))
        k_scores = [{"k": best_k, "inertia": inertia, "silhouette": _sampled_silhouette(feature_matrix, labels_for_score)}]
    labels, centroids = _fit_kmeans(feature_matrix, best_k, args.random_seed)
    pca_xy, explained = _pca_2d(feature_matrix)

    clustered = data.copy()
    clustered["cluster_id"] = labels
    clustered["cluster_label"] = ["C" + str(value + 1) for value in labels]
    clustered["pca_1"] = pca_xy[:, 0]
    clustered["pca_2"] = pca_xy[:, 1]
    clustered["distance_to_cluster_center"] = _cluster_distances(feature_matrix, labels, centroids)

    cross_tab = pd.crosstab(clustered["operation_mode"], clustered["cluster_label"])
    cluster_summary = _cluster_summary(clustered)
    mode_cluster_quality = _mode_cluster_quality(clustered)
    boundary_points = _boundary_points(clustered)

    clustered.to_csv(args.output_dir / "operation_mode_clustered_timeseries.csv", index=False, encoding="utf-8-sig")
    cross_tab.to_csv(args.output_dir / "rule_mode_vs_cluster_crosstab.csv", encoding="utf-8-sig")
    cluster_summary.to_csv(args.output_dir / "cluster_summary.csv", index=False, encoding="utf-8-sig")
    mode_cluster_quality.to_csv(args.output_dir / "rule_mode_cluster_quality.csv", index=False, encoding="utf-8-sig")
    boundary_points.to_csv(args.output_dir / "cluster_boundary_points.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(k_scores).to_csv(args.output_dir / "k_selection_scores.csv", index=False, encoding="utf-8-sig")
    (args.output_dir / "feature_standardization.json").write_text(
        json.dumps(feature_stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    _draw_cluster_plot(clustered, args.output_dir / "operation_mode_cluster_pca.png", explained)
    _write_report(
        args.output_dir / "operation_mode_cluster_report.md",
        best_k,
        k_scores,
        explained,
        cross_tab,
        cluster_summary,
        mode_cluster_quality,
        boundary_points,
    )

    print(f"Selected k={best_k}")
    print(cross_tab.to_string())
    print(f"Wrote clustering outputs to {args.output_dir}")


def _load_features(mode_dir: Path, capacity_dir: Path) -> pd.DataFrame:
    modes = pd.read_csv(mode_dir / "station_operation_modes_timeseries.csv", encoding="utf-8-sig")
    capacity = pd.read_csv(capacity_dir / "water_side_chiller_capacity_timeseries.csv", encoding="utf-8-sig")
    capacity_cols = [
        "collect_time_iso",
        "calculated_total_chiller_capacity_kw",
        "capacity_to_system_load_ratio",
    ]
    data = modes.merge(capacity[capacity_cols], on="collect_time_iso", how="left")
    data["collect_time_iso"] = pd.to_datetime(data["collect_time_iso"])
    for column in FEATURE_COLUMNS:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data[FEATURE_COLUMNS] = data[FEATURE_COLUMNS].interpolate(limit_direction="both").fillna(0)
    return data


def _standardize_features(data: pd.DataFrame, columns: list[str]) -> tuple[np.ndarray, dict]:
    values = data[columns].to_numpy(dtype=float)
    mean = values.mean(axis=0)
    std = values.std(axis=0)
    std[std == 0] = 1.0
    matrix = (values - mean) / std
    stats = {
        column: {"mean": float(m), "std": float(s)}
        for column, m, s in zip(columns, mean, std, strict=True)
    }
    return matrix, stats


def _select_k(matrix: np.ndarray, min_k: int, max_k: int, seed: int) -> tuple[int, list[dict]]:
    scores = []
    for k in range(min_k, max_k + 1):
        labels, centroids = _fit_kmeans(matrix, k, seed)
        inertia = float(np.sum(_cluster_distances(matrix, labels, centroids) ** 2))
        silhouette = _sampled_silhouette(matrix, labels)
        scores.append({"k": k, "inertia": inertia, "silhouette": silhouette})
    valid = [row for row in scores if not np.isnan(row["silhouette"])]
    best = max(valid, key=lambda row: row["silhouette"]) if valid else scores[0]
    return int(best["k"]), scores


def _fit_kmeans(matrix: np.ndarray, k: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    best_labels = None
    best_centroids = None
    best_inertia = np.inf
    for attempt in range(10):
        centroids, labels = kmeans2(matrix, k, minit="points", iter=80, seed=rng)
        distances = _cluster_distances(matrix, labels, centroids)
        inertia = float(np.sum(distances**2))
        if inertia < best_inertia:
            best_inertia = inertia
            best_labels = labels
            best_centroids = centroids
    return best_labels.astype(int), best_centroids


def _cluster_distances(matrix: np.ndarray, labels: np.ndarray, centroids: np.ndarray) -> np.ndarray:
    return np.linalg.norm(matrix - centroids[labels], axis=1)


def _sampled_silhouette(matrix: np.ndarray, labels: np.ndarray, max_points: int = 700) -> float:
    if len(set(labels)) < 2:
        return float("nan")
    n = len(matrix)
    if n > max_points:
        rng = np.random.default_rng(123)
        idx = np.sort(rng.choice(n, size=max_points, replace=False))
        matrix = matrix[idx]
        labels = labels[idx]
    distances = np.linalg.norm(matrix[:, None, :] - matrix[None, :, :], axis=2)
    silhouettes = []
    for i in range(len(matrix)):
        same = labels == labels[i]
        same[i] = False
        if same.any():
            a = float(distances[i, same].mean())
        else:
            a = 0.0
        b_values = [
            float(distances[i, labels == other].mean())
            for other in sorted(set(labels))
            if other != labels[i] and (labels == other).any()
        ]
        b = min(b_values) if b_values else 0.0
        denom = max(a, b)
        silhouettes.append(0.0 if denom == 0 else (b - a) / denom)
    return float(np.mean(silhouettes))


def _pca_2d(matrix: np.ndarray) -> tuple[np.ndarray, tuple[float, float]]:
    u, s, vt = np.linalg.svd(matrix, full_matrices=False)
    xy = matrix @ vt[:2].T
    variance = s**2
    explained = variance / variance.sum()
    return xy, (float(explained[0]), float(explained[1]))


def _cluster_summary(clustered: pd.DataFrame) -> pd.DataFrame:
    return (
        clustered.groupby("cluster_label")
        .agg(
            time_points=("collect_time_iso", "count"),
            dominant_mode=("operation_mode", lambda s: s.value_counts().idxmax()),
            dominant_mode_share=("operation_mode", lambda s: s.value_counts(normalize=True).max()),
            mean_cooling_load_kw=("cooling_load_kw", "mean"),
            mean_power_kw=("power_kw", "mean"),
            mean_flow_m3h=("flow_m3h", "mean"),
            mean_ice_delta_per_step=("ice_delta_per_step", "mean"),
            mean_base_chiller_on_count=("base_chiller_on_count", "mean"),
            mean_dual_chiller_on_count=("dual_chiller_on_count", "mean"),
            mean_dual_min_chw_out_temp_c=("dual_min_chw_out_temp_c", "mean"),
            mean_calculated_capacity_kw=("calculated_total_chiller_capacity_kw", "mean"),
        )
        .reset_index()
        .sort_values("cluster_label")
    )


def _mode_cluster_quality(clustered: pd.DataFrame) -> pd.DataFrame:
    records = []
    for mode, subset in clustered.groupby("operation_mode"):
        shares = subset["cluster_label"].value_counts(normalize=True)
        records.append(
            {
                "operation_mode": mode,
                "time_points": int(len(subset)),
                "dominant_cluster": shares.idxmax(),
                "dominant_cluster_share": float(shares.max()),
                "cluster_count": int(shares.count()),
            }
        )
    return pd.DataFrame(records).sort_values("dominant_cluster_share")


def _boundary_points(clustered: pd.DataFrame) -> pd.DataFrame:
    records = []
    for cluster_label, subset in clustered.groupby("cluster_label"):
        threshold = subset["distance_to_cluster_center"].quantile(0.95)
        records.append(subset[subset["distance_to_cluster_center"] >= threshold])
    out = pd.concat(records, ignore_index=True) if records else clustered.head(0)
    columns = [
        "collect_time_iso",
        "operation_mode",
        "cluster_label",
        "distance_to_cluster_center",
        "cooling_load_kw",
        "flow_m3h",
        "power_kw",
        "ice_delta_per_step",
        "base_chiller_on_count",
        "dual_chiller_on_count",
        "dual_min_chw_out_temp_c",
        "mode_reason",
    ]
    return out[columns].sort_values("distance_to_cluster_center", ascending=False)


def _draw_cluster_plot(clustered: pd.DataFrame, path: Path, explained: tuple[float, float]) -> None:
    width, height = 1800, 900
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = _font(34, bold=True)
    font = _font(22)
    small = _font(18)
    draw.text((width // 2, 28), "规则工况与聚类结果 PCA 可视化", fill="#111111", font=title_font, anchor="ma")

    left_box = (80, 100, 860, 780)
    right_box = (940, 100, 1720, 780)
    _scatter_panel(draw, clustered, left_box, "按规则工况着色", "operation_mode", MODE_COLORS, font, small)
    cluster_colors = {
        label: CLUSTER_COLORS[idx % len(CLUSTER_COLORS)]
        for idx, label in enumerate(sorted(clustered["cluster_label"].unique()))
    }
    _scatter_panel(draw, clustered, right_box, "按聚类结果着色", "cluster_label", cluster_colors, font, small)
    label = f"PCA解释方差: PC1 {explained[0]*100:.1f}%, PC2 {explained[1]*100:.1f}%"
    draw.text((width // 2, 835), label, fill="#444444", font=font, anchor="ma")
    image.save(path)


def _scatter_panel(
    draw: ImageDraw.ImageDraw,
    data: pd.DataFrame,
    box: tuple[int, int, int, int],
    title: str,
    color_column: str,
    colors: dict[str, str],
    font: ImageFont.ImageFont,
    small: ImageFont.ImageFont,
) -> None:
    x0, y0, x1, y1 = box
    draw.text(((x0 + x1) // 2, y0 - 34), title, fill="#111111", font=font, anchor="ma")
    draw.rectangle(box, outline="#222222", width=2)
    xs = data["pca_1"].to_numpy()
    ys = data["pca_2"].to_numpy()
    px = _scale(xs, x0 + 30, x1 - 30)
    py = _scale(ys, y1 - 30, y0 + 30)
    for x, y, label in zip(px, py, data[color_column], strict=True):
        color = colors.get(str(label), "#CCCCCC")
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=color)
    legend_x, legend_y = x0 + 18, y1 + 24
    for label in sorted(data[color_column].astype(str).unique()):
        color = colors.get(label, "#CCCCCC")
        draw.rectangle((legend_x, legend_y, legend_x + 16, legend_y + 16), fill=color)
        draw.text((legend_x + 24, legend_y + 8), label, fill="#222222", font=small, anchor="lm")
        legend_x += int(draw.textlength(label, font=small)) + 80
        if legend_x > x1 - 120:
            legend_x = x0 + 18
            legend_y += 26


def _scale(values: np.ndarray, dst_min: float, dst_max: float) -> np.ndarray:
    src_min = float(np.min(values))
    src_max = float(np.max(values))
    if src_max == src_min:
        return np.full_like(values, (dst_min + dst_max) / 2)
    return dst_min + (values - src_min) / (src_max - src_min) * (dst_max - dst_min)


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
    ]
    for font_path in candidates:
        if font_path.exists():
            return ImageFont.truetype(str(font_path), size=size)
    return ImageFont.load_default()


def _write_report(
    path: Path,
    best_k: int,
    k_scores: list[dict],
    explained: tuple[float, float],
    cross_tab: pd.DataFrame,
    cluster_summary: pd.DataFrame,
    mode_cluster_quality: pd.DataFrame,
    boundary_points: pd.DataFrame,
) -> None:
    lines = [
        "# 工况聚类验证分析",
        "",
        "## 方法",
        "",
        "- 规则工况仍作为主标签。",
        "- 聚类仅用于校验工况边界、发现异常点和识别可能的子工况。",
        f"- 聚类数固定为当前规则工况数量: k = {best_k}",
        f"- PCA二维解释方差: PC1 {explained[0]*100:.1f}%, PC2 {explained[1]*100:.1f}%",
        "",
        "## K选择结果",
        "",
        _markdown_table(pd.DataFrame(k_scores)),
        "",
        "## 规则工况与聚类交叉表",
        "",
        _markdown_table(cross_tab.reset_index()),
        "",
        "## 聚类汇总",
        "",
        _markdown_table(cluster_summary),
        "",
        "## 规则工况聚类一致性",
        "",
        _markdown_table(mode_cluster_quality),
        "",
        "## 边界/异常候选点",
        "",
        _markdown_table(boundary_points.head(30)),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "无。"
    shown = df.copy()
    for column in shown.columns:
        if pd.api.types.is_float_dtype(shown[column]):
            shown[column] = shown[column].map(lambda value: "" if pd.isna(value) else f"{value:.3f}")
    headers = [str(column) for column in shown.columns]
    rows = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for _, row in shown.iterrows():
        rows.append("| " + " | ".join("" if pd.isna(row[col]) else str(row[col]) for col in shown.columns) + " |")
    return "\n".join(rows)


if __name__ == "__main__":
    main()
