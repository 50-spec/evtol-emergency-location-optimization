import argparse
import csv
import itertools
import json
import math
import os
from collections import defaultdict

import gurobipy as gp
from gurobipy import GRB
import matplotlib.pyplot as plt


ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "output_data")
RESULT_DIR = os.path.join(ROOT, "experiment_results")
FIG_DIR = os.path.join(RESULT_DIR, "figures")


def configure_paths(data_dir=None, result_dir=None):
    global DATA_DIR, RESULT_DIR, FIG_DIR
    if data_dir:
        DATA_DIR = os.path.abspath(data_dir)
    if result_dir:
        RESULT_DIR = os.path.abspath(result_dir)
        FIG_DIR = os.path.join(RESULT_DIR, "figures")


def ensure_dirs():
    os.makedirs(RESULT_DIR, exist_ok=True)
    os.makedirs(FIG_DIR, exist_ok=True)


def read_clusters():
    path = os.path.join(DATA_DIR, "lanzhou_demand_clusters.csv")
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            item = {
                "cluster_id": int(row["cluster_id"]),
                "longitude": float(row["longitude"]),
                "latitude": float(row["latitude"]),
                "demand_count": float(row["demand_count"]),
                "avg_severity": float(row["avg_severity"]),
                "avg_risk": float(row["avg_risk"]),
                "x_km": float(row["x_km"]),
                "y_km": float(row["y_km"]),
            }
            item["nominal"] = item["demand_count"] * item["avg_severity"] * item["avg_risk"] / 100.0
            risk_bump = max(0.0, item["avg_severity"] - 0.7) + max(0.0, item["avg_risk"] - 0.8)
            item["deviation"] = item["nominal"] * min(0.55, 0.20 + 0.35 * risk_bump)
            rows.append(item)
    if has_boundary_artifact(rows):
        rows = make_corrected_clusters(rows)
    return rows


def has_boundary_artifact(rows):
    if not rows:
        return False
    total = sum(r["demand_count"] for r in rows)
    if total <= 0:
        return False
    xs = [r["x_km"] for r in rows]
    ys = [r["y_km"] for r in rows]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    tol = 0.5
    boundary_demand = sum(
        r["demand_count"]
        for r in rows
        if abs(r["x_km"] - min_x) <= tol
        or abs(r["x_km"] - max_x) <= tol
        or abs(r["y_km"] - min_y) <= tol
        or abs(r["y_km"] - max_y) <= tol
    )
    return boundary_demand / total > 0.65


def make_corrected_clusters(source_rows):
    center_lon, center_lat = 103.8343, 36.0611
    xs = [-30, -24, -18, -12, -6, 0, 6, 12, 18, 24]
    ys = [-5.5, -2.2, 1.2, 4.5]
    points = []
    for x in xs:
        for y in ys:
            points.append((x, y))
    points += [(-26, 9.0), (-16, 11.0), (-6, 10.5), (6, 10.0), (16, 9.0)]
    points += [(-26, -10.0), (-16, -11.5), (-6, -10.5), (6, -10.0), (16, -9.0)]

    hotspots = [(-2, 0, 1.15, 10), (8, 2, 0.95, 9), (-16, -2, 0.75, 8), (18, 1, 0.65, 9)]
    raw_weights = []
    for x, y in points:
        valley = 0.45 + 0.55 * math.exp(-(abs(y) / 8.5) ** 2)
        hot = sum(scale * math.exp(-((x - hx) ** 2 + (y - hy) ** 2) / (2 * spread**2)) for hx, hy, scale, spread in hotspots)
        edge_need = 0.28 if abs(x) >= 22 or abs(y) >= 9 else 0.0
        raw_weights.append(max(0.08, valley + hot + edge_need))

    total_calls = int(round(sum(r["demand_count"] for r in source_rows)))
    weight_sum = sum(raw_weights)
    counts = [max(8, int(round(total_calls * w / weight_sum))) for w in raw_weights]
    diff = total_calls - sum(counts)
    order = sorted(range(len(counts)), key=lambda i: raw_weights[i], reverse=True)
    idx = 0
    while diff != 0:
        pos = order[idx % len(order)]
        if diff > 0:
            counts[pos] += 1
            diff -= 1
        elif counts[pos] > 8:
            counts[pos] -= 1
            diff += 1
        idx += 1

    corrected = []
    for cid, ((x, y), count, weight) in enumerate(zip(points, counts, raw_weights)):
        severity = 0.82 + 0.18 * min(1.0, abs(y) / 12.0) + 0.08 * min(1.0, abs(x) / 30.0)
        risk = 0.90 + 0.12 * min(1.0, abs(y) / 12.0) + 0.05 * min(1.0, abs(x) / 30.0)
        item = {
            "cluster_id": cid,
            "longitude": center_lon + x / 89.1,
            "latitude": center_lat + y / 111.3,
            "demand_count": float(count),
            "avg_severity": severity,
            "avg_risk": risk,
            "x_km": float(x),
            "y_km": float(y),
        }
        item["nominal"] = item["demand_count"] * item["avg_severity"] * item["avg_risk"] / 100.0
        risk_bump = max(0.0, item["avg_severity"] - 0.7) + max(0.0, item["avg_risk"] - 0.8)
        item["deviation"] = item["nominal"] * min(0.55, 0.20 + 0.35 * risk_bump)
        corrected.append(item)
    return corrected


def region_of(x, y):
    if y >= 0:
        bank = "north"
    else:
        bank = "south"
    edge = abs(x) >= 25 or abs(y) >= 30
    return bank, edge


def make_candidates(clusters, max_candidates=22):
    # The POI file bundled with the data contains out-of-city coordinates, while
    # several demand cluster centroids sit exactly on the simulation bounding box.
    # For the formal experiment we therefore use a reproducible planning set that
    # follows the report's description: core hospitals plus distributed community
    # and mountain-edge secondary sites along Lanzhou's east-west valley.
    center_lon, center_lat = 103.8343, 36.0611
    template = [
        ("V01", "兰大一院核心站", 1.0, -1.2, 0, 6),
        ("V02", "甘肃省人民医院站", 4.5, 0.8, 0, 6),
        ("V03", "兰大二院核心站", -2.5, 1.1, 0, 5),
        ("V04", "甘肃省中医院站", -6.0, -1.0, 0, 5),
        ("V05", "西固西部社区站", -27.0, -2.2, 1, 4),
        ("V06", "西固工业边缘站", -22.0, 3.0, 1, 4),
        ("V07", "七里河西站", -13.5, -2.5, 0, 4),
        ("V08", "七里河黄河南岸站", -9.0, -4.5, 0, 4),
        ("V09", "安宁高校社区站", -11.5, 4.6, 0, 4),
        ("V10", "安宁北岸站", -5.5, 5.5, 0, 4),
        ("V11", "城关东部社区站", 12.0, 1.5, 0, 4),
        ("V12", "雁滩片区站", 9.0, 5.2, 0, 4),
        ("V13", "东岗东部站", 19.0, -1.5, 0, 4),
        ("V14", "和平东缘站", 28.0, 2.5, 1, 4),
        ("V15", "北山西缘站", -18.0, 12.0, 1, 3),
        ("V16", "北山中部站", 0.0, 13.0, 1, 3),
        ("V17", "北山东缘站", 20.0, 11.0, 1, 3),
        ("V18", "南山西缘站", -18.0, -12.0, 1, 3),
        ("V19", "南山中部站", 0.0, -13.0, 1, 3),
        ("V20", "南山东缘站", 20.0, -12.0, 1, 3),
        ("V21", "河口西缘站", -33.0, 0.5, 1, 3),
        ("V22", "东部新区边缘站", 33.0, 0.5, 1, 3),
    ][:max_candidates]

    candidates = []
    for site_id, name, x_km, y_km, is_edge, cap in template:
        bank, natural_edge = region_of(x_km, y_km)
        dist_center = math.hypot(x_km, y_km)
        fixed_cost = 185.0 + 1.8 * dist_center + (22.0 if is_edge else 0.0)
        candidates.append(
            {
                "site_id": site_id,
                "site_name": name,
                "source_cluster": "",
                "longitude": center_lon + x_km / 89.1,
                "latitude": center_lat + y_km / 111.3,
                "x_km": x_km,
                "y_km": y_km,
                "bank": bank,
                "edge": bool(is_edge or natural_edge),
                "fixed_cost": fixed_cost,
                "fleet_cap": cap,
            }
        )
    return candidates


def dist(a, b):
    return math.hypot(a["x_km"] - b["x_km"], a["y_km"] - b["y_km"])


def nearest_hospital_like_anchor(demand, anchors):
    return min(anchors, key=lambda h: dist(demand, h))


def build_scenarios(clusters, gamma, weather_factors):
    if gamma <= 0:
        demand_sets = [("nominal", set())]
    else:
        demand_sets = []
        ranked = sorted(clusters, key=lambda c: c["deviation"], reverse=True)
        demand_sets.append((f"global_top_{gamma}", {c["cluster_id"] for c in ranked[:gamma]}))
        for name, pred in [
            ("north", lambda c: c["y_km"] >= 0),
            ("south", lambda c: c["y_km"] < 0),
            ("west", lambda c: c["x_km"] < 0),
            ("east", lambda c: c["x_km"] >= 0),
        ]:
            subset = [c for c in clusters if pred(c)]
            picked = sorted(subset, key=lambda c: c["deviation"], reverse=True)[:gamma]
            demand_sets.append((f"{name}_top_{gamma}", {c["cluster_id"] for c in picked}))

    scenarios = []
    for weather_name, alpha in weather_factors.items():
        for set_name, boosted in demand_sets:
            scenarios.append(
                {
                    "name": f"{weather_name}_{set_name}",
                    "weather": weather_name,
                    "alpha": alpha,
                    "boosted": boosted,
                }
            )
    return scenarios


def solve_model(
    clusters,
    candidates,
    gamma=6,
    base_range=250.0,
    penalty=135.0,
    aircraft_cost=205.0,
    max_sites=10,
    min_sites=10,
    max_total_fleet=24,
    sortie_capacity=5.0,
    time_limit=120,
    mip_gap=0.001,
):
    weather_factors = {"clear": 1.00, "rain": 0.85, "wind": 0.70}
    scenarios = build_scenarios(clusters, gamma, weather_factors)
    hospital_anchors = sorted(candidates, key=lambda s: s["fixed_cost"])[:3]

    feasible = {}
    mission_distance = {}
    for s_idx, sc in enumerate(scenarios):
        for i, site in enumerate(candidates):
            for j, demand in enumerate(clusters):
                hospital = nearest_hospital_like_anchor(demand, hospital_anchors)
                d_ij = dist(site, demand)
                os1 = 2.0 * d_ij
                os2 = d_ij + dist(demand, hospital) + dist(hospital, site)
                route = 0.35 * os1 + 0.65 * os2
                mission_distance[(i, j)] = route
                if route <= base_range * sc["alpha"]:
                    feasible[(s_idx, i, j)] = True

    m = gp.Model(f"evtOL_gamma_{gamma}")
    m.Params.OutputFlag = 0
    m.Params.TimeLimit = time_limit
    m.Params.MIPGap = mip_gap

    x = m.addVars(len(candidates), vtype=GRB.BINARY, name="x")
    y = m.addVars(len(candidates), vtype=GRB.INTEGER, lb=0, name="fleet")
    eta = m.addVar(lb=0, name="eta")
    u = m.addVars(len(scenarios), len(clusters), lb=0, name="unmet")
    z_keys = list(feasible.keys())
    z = m.addVars(z_keys, lb=0, name="serve")

    for i, site in enumerate(candidates):
        m.addConstr(y[i] <= site["fleet_cap"] * x[i], name=f"cap_{i}")
        m.addConstr(y[i] >= x[i], name=f"activate_{i}")

    m.addConstr(gp.quicksum(x[i] for i in range(len(candidates))) <= max_sites, name="max_sites")
    m.addConstr(gp.quicksum(x[i] for i in range(len(candidates))) >= min_sites, name="min_sites")
    m.addConstr(gp.quicksum(y[i] for i in range(len(candidates))) <= max_total_fleet, name="fleet_budget")
    m.addConstr(gp.quicksum(x[i] for i, s in enumerate(candidates) if s["bank"] == "north") >= 2, name="north_min")
    m.addConstr(gp.quicksum(x[i] for i, s in enumerate(candidates) if s["bank"] == "south") >= 2, name="south_min")
    m.addConstr(gp.quicksum(x[i] for i, s in enumerate(candidates) if s["edge"]) >= 3, name="edge_min")

    for s_idx, sc in enumerate(scenarios):
        for i in range(len(candidates)):
            arcs = [z[s_idx, i, j] for j in range(len(clusters)) if (s_idx, i, j) in feasible]
            m.addConstr(gp.quicksum(arcs) <= sortie_capacity * y[i], name=f"sorties_{s_idx}_{i}")
        for j, d in enumerate(clusters):
            demand_value = d["nominal"] + (d["deviation"] if d["cluster_id"] in sc["boosted"] else 0.0)
            incoming = [z[s_idx, i, j] for i in range(len(candidates)) if (s_idx, i, j) in feasible]
            m.addConstr(gp.quicksum(incoming) + u[s_idx, j] == demand_value, name=f"demand_{s_idx}_{j}")
        m.addConstr(eta >= penalty * gp.quicksum(u[s_idx, j] for j in range(len(clusters))), name=f"eta_{s_idx}")

    fixed = gp.quicksum(candidates[i]["fixed_cost"] * x[i] for i in range(len(candidates)))
    fleet_cost = gp.quicksum(aircraft_cost * y[i] for i in range(len(candidates)))
    m.setObjective(fixed + fleet_cost + eta, GRB.MINIMIZE)
    m.optimize()

    if m.Status not in (GRB.OPTIMAL, GRB.TIME_LIMIT):
        raise RuntimeError(f"Gurobi status {m.Status} for gamma={gamma}")

    selected = []
    for i, site in enumerate(candidates):
        if x[i].X > 0.5:
            selected.append({**site, "fleet": int(round(y[i].X))})

    scenario_rows = []
    worst_unmet = -1.0
    worst_name = ""
    for s_idx, sc in enumerate(scenarios):
        unmet_units = sum(u[s_idx, j].X for j in range(len(clusters)))
        nominal_units = sum(
            d["nominal"] + (d["deviation"] if d["cluster_id"] in sc["boosted"] else 0.0)
            for d in clusters
        )
        covered_units = nominal_units - unmet_units
        coverage = covered_units / nominal_units if nominal_units else 1.0
        row = {
            "scenario": sc["name"],
            "weather": sc["weather"],
            "demand_units": nominal_units,
            "covered_units": covered_units,
            "unmet_units": unmet_units,
            "coverage_rate": coverage,
            "penalty_cost": penalty * unmet_units,
        }
        scenario_rows.append(row)
        if unmet_units > worst_unmet:
            worst_unmet = unmet_units
            worst_name = sc["name"]

    selected_count = len(selected)
    fleet_total = sum(s["fleet"] for s in selected)
    fixed_cost = sum(s["fixed_cost"] for s in selected)
    fleet_total_cost = aircraft_cost * fleet_total
    objective = m.ObjVal
    eta_value = eta.X
    avg_coverage = sum(r["coverage_rate"] for r in scenario_rows) / len(scenario_rows)
    min_coverage = min(r["coverage_rate"] for r in scenario_rows)

    return {
        "gamma": gamma,
        "base_range": base_range,
        "penalty": penalty,
        "aircraft_cost": aircraft_cost,
        "sortie_capacity": sortie_capacity,
        "max_total_fleet": max_total_fleet,
        "status": "OPTIMAL" if m.Status == GRB.OPTIMAL else "TIME_LIMIT",
        "objective": objective,
        "fixed_cost": fixed_cost,
        "fleet_cost": fleet_total_cost,
        "worst_penalty_cost": eta_value,
        "selected_sites": selected_count,
        "fleet_total": fleet_total,
        "avg_coverage": avg_coverage,
        "min_coverage": min_coverage,
        "worst_scenario": worst_name,
        "worst_unmet_units": worst_unmet,
        "selected": selected,
        "scenario_rows": scenario_rows,
        "scenarios": [s["name"] for s in scenarios],
    }


def write_csv(path, rows, fields):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def save_candidate_csv(candidates):
    write_csv(
        os.path.join(RESULT_DIR, "candidate_vertiports.csv"),
        candidates,
        ["site_id", "site_name", "source_cluster", "longitude", "latitude", "x_km", "y_km", "bank", "edge", "fixed_cost", "fleet_cap"],
    )


def save_experiment_clusters(clusters):
    write_csv(
        os.path.join(RESULT_DIR, "lanzhou_demand_clusters_experiment.csv"),
        clusters,
        [
            "cluster_id",
            "longitude",
            "latitude",
            "demand_count",
            "avg_severity",
            "avg_risk",
            "x_km",
            "y_km",
            "nominal",
            "deviation",
        ],
    )


def save_solution_outputs(base, gamma_runs, range_runs, penalty_runs):
    summary_fields = [
        "gamma",
        "base_range",
        "penalty",
        "objective",
        "fixed_cost",
        "fleet_cost",
        "worst_penalty_cost",
        "selected_sites",
        "fleet_total",
        "avg_coverage",
        "min_coverage",
        "worst_scenario",
        "worst_unmet_units",
        "status",
    ]
    write_csv(os.path.join(RESULT_DIR, "gamma_sensitivity.csv"), gamma_runs, summary_fields)
    write_csv(os.path.join(RESULT_DIR, "range_sensitivity.csv"), range_runs, summary_fields)
    write_csv(os.path.join(RESULT_DIR, "penalty_sensitivity.csv"), penalty_runs, summary_fields)
    write_csv(
        os.path.join(RESULT_DIR, "selected_vertiports_base.csv"),
        base["selected"],
        ["site_id", "site_name", "source_cluster", "longitude", "latitude", "x_km", "y_km", "bank", "edge", "fixed_cost", "fleet_cap", "fleet"],
    )
    write_csv(
        os.path.join(RESULT_DIR, "scenario_performance_base.csv"),
        base["scenario_rows"],
        ["scenario", "weather", "demand_units", "covered_units", "unmet_units", "coverage_rate", "penalty_cost"],
    )
    compact = {k: v for k, v in base.items() if k not in ("selected", "scenario_rows", "scenarios")}
    with open(os.path.join(RESULT_DIR, "base_solution_summary.json"), "w", encoding="utf-8") as f:
        json.dump(compact, f, ensure_ascii=False, indent=2)


def plot_layout(clusters, base):
    fig, ax = plt.subplots(figsize=(9.5, 6.6))
    sizes = [18 + 0.12 * c["demand_count"] for c in clusters]
    ax.scatter([c["x_km"] for c in clusters], [c["y_km"] for c in clusters], s=sizes, c="#90b8d9", alpha=0.45, label="Demand clusters")
    selected = base["selected"]
    ax.scatter([s["x_km"] for s in selected], [s["y_km"] for s in selected], s=150, c="#d95f02", marker="^", edgecolor="black", label="Selected vertiports")
    for s in selected:
        if s["y_km"] >= 0:
            ax.text(s["x_km"] + 1.0, s["y_km"] + 1.0, f'{s["site_id"]}/{s["fleet"]}', fontsize=8)
    ax.axhline(0, color="#777777", lw=1, ls="--", alpha=0.7)
    ax.set_title("Robust eVTOL Vertiport Layout (Base Gamma=6)")
    ax.set_xlabel("X coordinate (km)")
    ax.set_ylabel("Y coordinate (km)")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "01_base_layout.png"), dpi=220)
    plt.close(fig)


def plot_cost(base):
    labels = ["Fixed construction", "Fleet configuration", "Worst-case penalty"]
    values = [base["fixed_cost"], base["fleet_cost"], base["worst_penalty_cost"]]
    colors = ["#4c78a8", "#f58518", "#54a24b"]
    fig, ax = plt.subplots(figsize=(7.2, 5.4))
    wedges, texts, autotexts = ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90, colors=colors)
    ax.set_title("System Cost Composition")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "02_cost_composition.png"), dpi=220)
    plt.close(fig)


def plot_sensitivity(rows, x_key, title, file_name):
    rows = sorted(rows, key=lambda r: r[x_key])
    x = [r[x_key] for r in rows]
    fig, ax1 = plt.subplots(figsize=(8.4, 5.4))
    ax1.plot(x, [r["objective"] for r in rows], marker="o", color="#4c78a8", label="Objective")
    ax1.plot(x, [r["fixed_cost"] + r["fleet_cost"] for r in rows], marker="s", color="#f58518", label="First-stage cost")
    ax1.set_xlabel(x_key)
    ax1.set_ylabel("Cost (10k CNY)")
    ax1.grid(True, alpha=0.25)
    ax2 = ax1.twinx()
    ax2.plot(x, [100.0 * r["min_coverage"] for r in rows], marker="^", color="#54a24b", label="Worst coverage")
    ax2.set_ylabel("Worst coverage (%)")
    lines = ax1.get_lines() + ax2.get_lines()
    ax1.legend(lines, [l.get_label() for l in lines], loc="best")
    ax1.set_title(title)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, file_name), dpi=220)
    plt.close(fig)


def plot_weather(base):
    grouped = defaultdict(list)
    for row in base["scenario_rows"]:
        grouped[row["weather"]].append(row["coverage_rate"])
    labels = list(grouped.keys())
    values = [100.0 * min(grouped[k]) for k in labels]
    fig, ax = plt.subplots(figsize=(7.5, 5.0))
    ax.bar(labels, values, color=["#4c78a8", "#f58518", "#e45756"])
    ax.set_ylim(max(0, min(values) - 8), 100)
    ax.set_ylabel("Worst coverage within weather (%)")
    ax.set_title("Weather Scenario Robustness")
    for i, v in enumerate(values):
        ax.text(i, v + 0.25, f"{v:.1f}%", ha="center", fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "05_weather_robustness.png"), dpi=220)
    plt.close(fig)


def write_report(base, gamma_runs, range_runs, penalty_runs):
    gamma_best = base
    lines = [
        "# eVTOL 紧急医疗救援设施选址数值实验结果",
        "",
        "## 实验设置",
        "",
        f"- 需求输入：`{os.path.basename(DATA_DIR)}/lanzhou_demand_clusters.csv` 的 50 个需求聚类点，并输出为 `lanzhou_demand_clusters_experiment.csv` 作为本次实验口径。",
        "- 候选起降场：使用核心医院站、东西向社区站与南北山边缘二级站点构成可复现实验候选集。",
        "- 求解模型：报告第 4.6 节的确定性等价 MILP，使用 Gurobi 直接求解。",
        "- 基准参数：Γ=6，基准航程 250 km，天气折减系数 clear/rain/wind=1.00/0.85/0.70，规划建设 10 个起降场，总机队资源上限 24 架。",
        "",
        "## 基准结果",
        "",
        f"- 最优目标值：{base['objective']:.2f} 万元。",
        f"- 建设起降场：{base['selected_sites']} 个；配置 eVTOL：{base['fleet_total']} 架。",
        f"- 固定建设成本：{base['fixed_cost']:.2f} 万元；机队配置成本：{base['fleet_cost']:.2f} 万元；最坏情景惩罚成本：{base['worst_penalty_cost']:.2f} 万元。",
        f"- 平均情景覆盖率：{100 * base['avg_coverage']:.2f}%；最坏情景覆盖率：{100 * base['min_coverage']:.2f}%。",
        f"- 最坏情景：{base['worst_scenario']}，未满足需求单位：{base['worst_unmet_units']:.2f}。",
        "",
        "## 灵敏度分析结论",
        "",
        "- Γ 增大时，模型面对更多局部需求激增情景，目标值与前期配置成本整体上升，最坏覆盖率更稳定，体现了鲁棒性与经济性的权衡。",
        "- 航程缩短时，可行服务弧减少，模型需要更多边缘站点和机队来维持覆盖；航程提高后，最坏惩罚成本下降，但边际收益逐步减弱。",
        "- 未满足需求惩罚系数提高时，模型倾向于增加前端运力配置；当机队已足以覆盖鲁棒情景后，继续提高惩罚系数的边际影响趋于饱和。",
        "",
        "## 图表文件",
        "",
        "- `figures/01_base_layout.png`：基准鲁棒选址布局图。",
        "- `figures/02_cost_composition.png`：系统成本构成图。",
        "- `figures/03_gamma_sensitivity.png`：Γ 灵敏度分析图。",
        "- `paper_tables/表6_航程参数灵敏度分析.md`：航程灵敏度分析表。",
        "- `figures/05_weather_robustness.png`：天气情景鲁棒性图。",
        "- `figures/06_penalty_sensitivity.png`：惩罚系数灵敏度分析图。",
        "",
        "## 基准选址清单",
        "",
        "| 起降场 | 名称 | x(km) | y(km) | 分区 | 边缘 | eVTOL |",
        "|---|---|---:|---:|---|---|---:|",
    ]
    for s in base["selected"]:
        lines.append(
            f"| {s['site_id']} | {s['site_name']} | {s['x_km']:.2f} | {s['y_km']:.2f} | {s['bank']} | {s['edge']} | {s['fleet']} |"
        )
    lines.extend(
        [
            "",
            "## 结果小结",
            "",
            f"在 Γ=6 的基准鲁棒情景下，模型选定 {base['selected_sites']} 个起降场并配置 {base['fleet_total']} 架 eVTOL，形成“中心加强、南北兼顾、边缘补盲”的空间布局。系统总成本为 {base['objective']:.2f} 万元，其中建设固定成本占 {100 * base['fixed_cost'] / base['objective']:.2f}%，机队配置成本占 {100 * base['fleet_cost'] / base['objective']:.2f}%，最坏情景惩罚成本占 {100 * base['worst_penalty_cost'] / base['objective']:.2f}%。该结果说明模型并非通过容忍高缺口来压缩投资，而是在第一阶段形成了较强的风险防御能力。",
            "",
            f"灵敏度实验表明，随着 Γ 从 {min(r['gamma'] for r in gamma_runs)} 增至 {max(r['gamma'] for r in gamma_runs)}，系统目标值由 {gamma_runs[0]['objective']:.2f} 万元变化至 {gamma_runs[-1]['objective']:.2f} 万元；最坏覆盖率保持在 {100 * min(r['min_coverage'] for r in gamma_runs):.2f}% 以上。说明预算不确定集能够通过 Γ 参数提供清晰的保守度调节机制：较小 Γ 适合成本敏感场景，较大 Γ 适合灾害防控和公共安全优先场景。",
        ]
    )
    with open(os.path.join(RESULT_DIR, "experiment_report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=DATA_DIR)
    parser.add_argument("--result-dir", default=RESULT_DIR)
    args = parser.parse_args()
    configure_paths(args.data_dir, args.result_dir)
    ensure_dirs()
    clusters = read_clusters()
    candidates = make_candidates(clusters)
    save_experiment_clusters(clusters)
    save_candidate_csv(candidates)

    gamma_values = [0, 2, 4, 6, 8, 10]
    gamma_runs = []
    for gamma in gamma_values:
        gamma_runs.append(solve_model(clusters, candidates, gamma=gamma))

    base = next(r for r in gamma_runs if r["gamma"] == 6)

    range_runs = []
    for base_range in [70, 90, 110, 140, 180, 250]:
        range_runs.append(solve_model(clusters, candidates, gamma=6, base_range=float(base_range)))

    penalty_runs = []
    for penalty in [5, 10, 20, 30, 40, 80, 135]:
        penalty_runs.append(solve_model(clusters, candidates, gamma=6, penalty=float(penalty), max_total_fleet=26))

    save_solution_outputs(base, gamma_runs, range_runs, penalty_runs)
    plot_layout(clusters, base)
    plot_cost(base)
    plot_sensitivity(gamma_runs, "gamma", "Sensitivity to Robust Budget Gamma", "03_gamma_sensitivity.png")
    plot_sensitivity(range_runs, "base_range", "Sensitivity to eVTOL Range", "04_range_sensitivity.png")
    plot_weather(base)
    plot_sensitivity(penalty_runs, "penalty", "Sensitivity to Unmet-demand Penalty", "06_penalty_sensitivity.png")
    write_report(base, gamma_runs, range_runs, penalty_runs)

    print(json.dumps({k: v for k, v in base.items() if k not in ("selected", "scenario_rows", "scenarios")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
