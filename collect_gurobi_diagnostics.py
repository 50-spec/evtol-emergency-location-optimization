import argparse
import csv
import ctypes
import json
import os
import platform
import time
import winreg

import gurobipy as gp
from gurobipy import GRB
import matplotlib.pyplot as plt

import run_evtol_experiments as exp


def get_cpu_name():
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        )
        value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
        return value.strip()
    except Exception:
        return platform.processor() or platform.machine()


def get_total_memory_gb():
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
        return stat.ullTotalPhys / (1024**3)
    return None


def write_csv(path, rows, fields):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def solve_with_diagnostics(clusters, candidates, result_dir, gamma=6):
    weather_factors = {"clear": 1.00, "rain": 0.85, "wind": 0.70}
    scenarios = exp.build_scenarios(clusters, gamma, weather_factors)
    hospital_anchors = sorted(candidates, key=lambda s: s["fixed_cost"])[:3]

    feasible = {}
    for s_idx, sc in enumerate(scenarios):
        for i, site in enumerate(candidates):
            for j, demand in enumerate(clusters):
                hospital = exp.nearest_hospital_like_anchor(demand, hospital_anchors)
                d_ij = exp.dist(site, demand)
                os1 = 2.0 * d_ij
                os2 = d_ij + exp.dist(demand, hospital) + exp.dist(hospital, site)
                route = 0.35 * os1 + 0.65 * os2
                if route <= 250.0 * sc["alpha"]:
                    feasible[(s_idx, i, j)] = True

    m = gp.Model("evtOL_base_diagnostics")
    log_path = os.path.join(result_dir, "base_gurobi.log")
    m.Params.OutputFlag = 1
    m.Params.LogToConsole = 0
    m.Params.LogFile = log_path
    m.Params.TimeLimit = 120
    m.Params.MIPGap = 0.001
    m.Params.Seed = 1

    x = m.addVars(len(candidates), vtype=GRB.BINARY, name="x")
    y = m.addVars(len(candidates), vtype=GRB.INTEGER, lb=0, name="fleet")
    eta = m.addVar(lb=0, name="eta")
    u = m.addVars(len(scenarios), len(clusters), lb=0, name="unmet")
    z_keys = list(feasible.keys())
    z = m.addVars(z_keys, lb=0, name="serve")

    for i, site in enumerate(candidates):
        m.addConstr(y[i] <= site["fleet_cap"] * x[i], name=f"cap_{i}")
        m.addConstr(y[i] >= x[i], name=f"activate_{i}")

    m.addConstr(gp.quicksum(x[i] for i in range(len(candidates))) <= 10, name="max_sites")
    m.addConstr(gp.quicksum(x[i] for i in range(len(candidates))) >= 10, name="min_sites")
    m.addConstr(gp.quicksum(y[i] for i in range(len(candidates))) <= 24, name="fleet_budget")
    m.addConstr(gp.quicksum(x[i] for i, s in enumerate(candidates) if s["bank"] == "north") >= 2, name="north_min")
    m.addConstr(gp.quicksum(x[i] for i, s in enumerate(candidates) if s["bank"] == "south") >= 2, name="south_min")
    m.addConstr(gp.quicksum(x[i] for i, s in enumerate(candidates) if s["edge"]) >= 3, name="edge_min")

    for s_idx, sc in enumerate(scenarios):
        for i in range(len(candidates)):
            arcs = [z[s_idx, i, j] for j in range(len(clusters)) if (s_idx, i, j) in feasible]
            m.addConstr(gp.quicksum(arcs) <= 5.0 * y[i], name=f"sorties_{s_idx}_{i}")
        for j, d in enumerate(clusters):
            demand_value = d["nominal"] + (d["deviation"] if d["cluster_id"] in sc["boosted"] else 0.0)
            incoming = [z[s_idx, i, j] for i in range(len(candidates)) if (s_idx, i, j) in feasible]
            m.addConstr(gp.quicksum(incoming) + u[s_idx, j] == demand_value, name=f"demand_{s_idx}_{j}")
        m.addConstr(eta >= 135.0 * gp.quicksum(u[s_idx, j] for j in range(len(clusters))), name=f"eta_{s_idx}")

    fixed = gp.quicksum(candidates[i]["fixed_cost"] * x[i] for i in range(len(candidates)))
    fleet_cost = gp.quicksum(205.0 * y[i] for i in range(len(candidates)))
    m.setObjective(fixed + fleet_cost + eta, GRB.MINIMIZE)
    m.update()

    progress = []
    last_record = {"t": -1.0, "best": None, "bound": None}

    def cb(model, where):
        if where == GRB.Callback.MIP:
            runtime = model.cbGet(GRB.Callback.RUNTIME)
            best = model.cbGet(GRB.Callback.MIP_OBJBST)
            bound = model.cbGet(GRB.Callback.MIP_OBJBND)
            nodes = model.cbGet(GRB.Callback.MIP_NODCNT)
            iters = model.cbGet(GRB.Callback.MIP_ITRCNT)
            if best >= GRB.INFINITY:
                best = None
            if bound <= -GRB.INFINITY or bound >= GRB.INFINITY:
                bound = None
            should_record = (
                runtime - last_record["t"] >= 0.05
                or best != last_record["best"]
                or bound != last_record["bound"]
            )
            if should_record:
                progress.append(
                    {
                        "time_sec": runtime,
                        "best_objective": best,
                        "best_bound": bound,
                        "nodes": nodes,
                        "simplex_iterations": iters,
                    }
                )
                last_record.update({"t": runtime, "best": best, "bound": bound})

    start = time.perf_counter()
    m.optimize(cb)
    wall_clock = time.perf_counter() - start

    if m.Status not in (GRB.OPTIMAL, GRB.TIME_LIMIT):
        raise RuntimeError(f"Gurobi status {m.Status}")

    if not progress or progress[-1].get("best_objective") != m.ObjVal:
        progress.append(
            {
                "time_sec": m.Runtime,
                "best_objective": m.ObjVal,
                "best_bound": m.ObjBound,
                "nodes": m.NodeCount,
                "simplex_iterations": m.IterCount,
            }
        )

    diag = {
        "status_code": m.Status,
        "status": "OPTIMAL" if m.Status == GRB.OPTIMAL else "TIME_LIMIT",
        "objective": m.ObjVal,
        "best_bound": m.ObjBound,
        "mip_gap": m.MIPGap,
        "runtime_sec": m.Runtime,
        "wall_clock_sec": wall_clock,
        "node_count": m.NodeCount,
        "simplex_iterations": m.IterCount,
        "solution_count": m.SolCount,
        "num_variables": m.NumVars,
        "num_binary_variables": m.NumBinVars,
        "num_integer_variables": m.NumIntVars,
        "num_constraints": m.NumConstrs,
        "num_nonzeros": m.NumNZs,
        "scenario_count": len(scenarios),
        "demand_cluster_count": len(clusters),
        "candidate_count": len(candidates),
        "feasible_arc_count": len(feasible),
        "parameters": {
            "gamma": gamma,
            "base_range_km": 250.0,
            "penalty": 135.0,
            "aircraft_cost": 205.0,
            "max_total_fleet": 24,
            "site_count": 10,
            "sortie_capacity": 5.0,
            "time_limit_sec": 120,
            "mip_gap_target": 0.001,
            "seed": 1,
        },
        "environment": {
            "os": platform.platform(),
            "cpu": get_cpu_name(),
            "logical_processors": os.cpu_count(),
            "memory_gb": get_total_memory_gb(),
            "python": platform.python_version(),
            "gurobi_version": ".".join(map(str, gp.gurobi.version())),
        },
    }
    return diag, progress, log_path


def plot_progress(progress, path):
    points = [row for row in progress if row.get("best_objective") is not None or row.get("best_bound") is not None]
    if not points:
        return
    times = [row["time_sec"] for row in points]
    best = [row.get("best_objective") for row in points]
    bound = [row.get("best_bound") for row in points]

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=200)
    ax.plot(times, best, marker="o", linewidth=2.0, label="Incumbent objective")
    ax.plot(times, bound, marker="s", linewidth=2.0, label="Best bound")
    ax.set_xlabel("求解时间 / 秒")
    ax.set_ylabel("目标值 / 万元")
    ax.set_title("Gurobi 基准场景目标值收敛过程")
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="output_data_amap_realistic")
    parser.add_argument("--result-dir", default="experiment_results_amap")
    args = parser.parse_args()

    exp.configure_paths(args.data_dir, args.result_dir)
    out_dir = os.path.join(os.path.abspath(args.result_dir), "gurobi_diagnostics")
    os.makedirs(out_dir, exist_ok=True)
    clusters = exp.read_clusters()
    candidates = exp.make_candidates(clusters)
    diag, progress, log_path = solve_with_diagnostics(clusters, candidates, out_dir)

    json_path = os.path.join(out_dir, "base_gurobi_diagnostics.json")
    csv_path = os.path.join(out_dir, "base_gurobi_convergence.csv")
    fig_path = os.path.join(out_dir, "图9_Gurobi目标值收敛曲线.png")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)
    write_csv(csv_path, progress, ["time_sec", "best_objective", "best_bound", "nodes", "simplex_iterations"])
    plot_progress(progress, fig_path)
    print(json.dumps({"diagnostics": json_path, "convergence": csv_path, "figure": fig_path, "log": log_path}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
