import csv
import argparse
import json
import os

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import PercentFormatter


ROOT = os.path.dirname(os.path.abspath(__file__))
RESULT_DIR = os.path.join(ROOT, "experiment_results")
OUT_DIR = os.path.join(RESULT_DIR, "paper_figures")
FONT_PATH = r"C:\Windows\Fonts\NotoSansSC-VF.ttf"


def configure_paths(result_dir=None):
    global RESULT_DIR, OUT_DIR
    if result_dir:
        RESULT_DIR = os.path.abspath(result_dir)
        OUT_DIR = os.path.join(RESULT_DIR, "paper_figures")


def ensure_style():
    os.makedirs(OUT_DIR, exist_ok=True)
    font_manager.fontManager.addfont(FONT_PATH)
    prop = font_manager.FontProperties(fname=FONT_PATH)
    plt.rcParams.update(
        {
            "font.family": prop.get_name(),
            "axes.unicode_minus": False,
            "figure.dpi": 150,
            "savefig.dpi": 300,
            "axes.linewidth": 0.8,
            "axes.edgecolor": "#333333",
            "axes.labelsize": 10,
            "axes.titlesize": 12,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.fontsize": 9,
        }
    )


def read_csv(name):
    path = os.path.join(RESULT_DIR, name)
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        for k, v in list(row.items()):
            try:
                row[k] = float(v)
            except (TypeError, ValueError):
                pass
    return rows


def save(fig, name):
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, f"{name}.png"), bbox_inches="tight")
    fig.savefig(os.path.join(OUT_DIR, f"{name}.svg"), bbox_inches="tight")
    plt.close(fig)


def style_axes(ax):
    ax.grid(True, axis="y", color="#d9d9d9", linewidth=0.7, alpha=0.75)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def fig_cost_composition():
    with open(os.path.join(RESULT_DIR, "base_solution_summary.json"), "r", encoding="utf-8") as f:
        base = json.load(f)
    labels = ["建设固定成本", "eVTOL配置成本", "最坏情景惩罚成本"]
    values = [base["fixed_cost"], base["fleet_cost"], base["worst_penalty_cost"]]
    colors = ["#4E79A7", "#F28E2B", "#59A14F"]

    fig, ax = plt.subplots(figsize=(5.8, 4.2))
    bars = ax.bar(labels, values, color=colors, width=0.58)
    total = sum(values)
    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + total * 0.015,
            f"{value:.0f}\n({value / total:.1%})",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    ax.set_ylabel("成本（万元）")
    ax.set_title("基准方案系统成本构成")
    ax.set_ylim(0, max(values) * 1.22)
    style_axes(ax)
    save(fig, "图4_系统成本构成")


def fig_gamma_sensitivity():
    rows = sorted(read_csv("gamma_sensitivity.csv"), key=lambda r: r["gamma"])
    x = [r["gamma"] for r in rows]
    fig, ax1 = plt.subplots(figsize=(6.4, 4.4))
    ax1.plot(x, [r["objective"] for r in rows], marker="o", color="#4E79A7", linewidth=2.0, label="系统总成本")
    ax1.plot(x, [r["fixed_cost"] + r["fleet_cost"] for r in rows], marker="s", color="#F28E2B", linewidth=2.0, label="第一阶段投入")
    ax1.set_xlabel("保守度参数 Gamma")
    ax1.set_ylabel("成本（万元）")
    style_axes(ax1)
    ax2 = ax1.twinx()
    ax2.plot(x, [r["min_coverage"] for r in rows], marker="^", color="#59A14F", linewidth=2.0, label="最坏情景覆盖率")
    ax2.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax2.set_ylabel("覆盖率")
    ax2.spines["top"].set_visible(False)
    lines = ax1.get_lines() + ax2.get_lines()
    ax1.legend(lines, [l.get_label() for l in lines], loc="center right", frameon=False)
    ax1.set_title("保守度参数 Gamma 对模型结果的影响")
    save(fig, "图5_Gamma灵敏度分析")


def fig_range_sensitivity():
    rows = sorted(read_csv("range_sensitivity.csv"), key=lambda r: r["base_range"])
    x = [r["base_range"] for r in rows]
    fig, ax1 = plt.subplots(figsize=(6.4, 4.4))
    ax1.plot(x, [r["objective"] for r in rows], marker="o", color="#4E79A7", linewidth=2.0, label="系统总成本")
    ax1.plot(x, [r["worst_penalty_cost"] for r in rows], marker="s", color="#E15759", linewidth=2.0, label="最坏情景惩罚成本")
    ax1.set_xlabel("eVTOL基准航程（km）")
    ax1.set_ylabel("成本（万元）")
    style_axes(ax1)
    ax2 = ax1.twinx()
    ax2.plot(x, [r["min_coverage"] for r in rows], marker="^", color="#59A14F", linewidth=2.0, label="最坏情景覆盖率")
    ax2.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax2.set_ylabel("覆盖率")
    ax2.spines["top"].set_visible(False)
    lines = ax1.get_lines() + ax2.get_lines()
    ax1.legend(lines, [l.get_label() for l in lines], loc="center right", frameon=False)
    ax1.set_title("航程参数对鲁棒覆盖效果的影响")
    save(fig, "图6_航程灵敏度分析")


def fig_penalty_sensitivity():
    rows = sorted(read_csv("penalty_sensitivity.csv"), key=lambda r: r["penalty"])
    x = [r["penalty"] for r in rows]
    fig, ax1 = plt.subplots(figsize=(6.4, 4.4))
    ax1.plot(x, [r["fleet_total"] for r in rows], marker="o", color="#4E79A7", linewidth=2.0, label="机队规模")
    ax1.set_xlabel("单位未满足需求惩罚成本（万元）")
    ax1.set_ylabel("eVTOL配置数量（架）")
    ax1.set_ylim(0, max(r["fleet_total"] for r in rows) + 4)
    style_axes(ax1)
    ax2 = ax1.twinx()
    ax2.plot(x, [r["min_coverage"] for r in rows], marker="^", color="#59A14F", linewidth=2.0, label="最坏情景覆盖率")
    ax2.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax2.set_ylabel("覆盖率")
    ax2.spines["top"].set_visible(False)
    lines = ax1.get_lines() + ax2.get_lines()
    ax1.legend(lines, [l.get_label() for l in lines], loc="lower right", frameon=False)
    ax1.set_title("惩罚成本对机队配置与覆盖率的影响")
    save(fig, "图7_惩罚成本灵敏度分析")


def fig_weather_robustness():
    rows = read_csv("scenario_performance_base.csv")
    order = ["clear", "rain", "wind"]
    label_map = {"clear": "晴好", "rain": "降雨", "wind": "大风"}
    vals = []
    for key in order:
        subset = [r["coverage_rate"] for r in rows if r["weather"] == key]
        vals.append(min(subset))

    fig, ax = plt.subplots(figsize=(5.4, 4.0))
    bars = ax.bar([label_map[k] for k in order], vals, color=["#4E79A7", "#F28E2B", "#E15759"], width=0.55)
    for bar, val in zip(bars, vals):
        ax.text(bar.get_x() + bar.get_width() / 2, val + 0.006, f"{val:.1%}", ha="center", fontsize=9)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_ylim(max(0, min(vals) - 0.08), 1.01)
    ax.set_ylabel("最坏情景覆盖率")
    ax.set_title("不同天气情景下的鲁棒覆盖率")
    style_axes(ax)
    save(fig, "图8_天气情景鲁棒性")


def fig_layout():
    experiment_path = os.path.join(RESULT_DIR, "lanzhou_demand_clusters_experiment.csv")
    corrected_path = os.path.join(RESULT_DIR, "lanzhou_demand_clusters_corrected.csv")
    source_path = experiment_path if os.path.exists(experiment_path) else corrected_path
    if not os.path.exists(source_path):
        source_path = os.path.join(ROOT, "output_data", "lanzhou_demand_clusters.csv")
    with open(source_path, "r", encoding="utf-8-sig", newline="") as f:
        demand = list(csv.DictReader(f))
    for row in demand:
        for key in ("x_km", "y_km", "demand_count"):
            row[key] = float(row[key])
    selected = read_csv("selected_vertiports_base.csv")
    candidates = read_csv("candidate_vertiports.csv")

    fig, ax = plt.subplots(figsize=(7.4, 4.8))
    sizes = [14 + 0.09 * r["demand_count"] for r in demand]
    ax.scatter([r["x_km"] for r in demand], [r["y_km"] for r in demand], s=sizes, color="#A6CEE3", edgecolor="#5B8DB8", alpha=0.45, label="需求聚类点")
    ax.scatter([r["x_km"] for r in candidates], [r["y_km"] for r in candidates], s=34, color="white", edgecolor="#777777", linewidth=0.9, label="候选起降场")
    ax.scatter([r["x_km"] for r in selected], [r["y_km"] for r in selected], s=95, color="#E66101", marker="^", edgecolor="black", linewidth=0.8, label="选定起降场")
    ax.axhline(0, color="#666666", linewidth=0.9, linestyle="--", alpha=0.75)
    ax.set_xlabel("东西向坐标（km）")
    ax.set_ylabel("南北向坐标（km）")
    ax.set_title("基准鲁棒优化方案的起降场空间布局")
    ax.legend(loc="lower left", frameon=False)
    ax.grid(True, color="#d9d9d9", linewidth=0.7, alpha=0.75)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    save(fig, "图3_基准起降场布局")


def fig_combined_sensitivity():
    gamma = sorted(read_csv("gamma_sensitivity.csv"), key=lambda r: r["gamma"])
    range_rows = sorted(read_csv("range_sensitivity.csv"), key=lambda r: r["base_range"])
    penalty = sorted(read_csv("penalty_sensitivity.csv"), key=lambda r: r["penalty"])

    fig, axes = plt.subplots(1, 3, figsize=(12.8, 3.8))
    panels = [
        (axes[0], gamma, "gamma", "Gamma", "（a）保守度参数"),
        (axes[1], range_rows, "base_range", "航程（km）", "（b）航程参数"),
        (axes[2], penalty, "penalty", "惩罚成本（万元）", "（c）惩罚成本"),
    ]
    for ax, rows, x_key, xlabel, title in panels:
        ax.plot([r[x_key] for r in rows], [r["min_coverage"] for r in rows], marker="o", color="#59A14F", linewidth=2.0)
        ax.yaxis.set_major_formatter(PercentFormatter(1.0))
        ax.set_xlabel(xlabel)
        ax.set_title(title)
        style_axes(ax)
    axes[0].set_ylabel("最坏情景覆盖率")
    save(fig, "图9_灵敏度分析组合图")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-dir", default=RESULT_DIR)
    args = parser.parse_args()
    configure_paths(args.result_dir)
    ensure_style()
    fig_layout()
    fig_cost_composition()
    fig_gamma_sensitivity()
    fig_penalty_sensitivity()
    fig_weather_robustness()
    print(f"paper figures written to: {OUT_DIR}")


if __name__ == "__main__":
    main()
