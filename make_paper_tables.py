import argparse
import csv
import os


ROOT = os.path.dirname(os.path.abspath(__file__))
RESULT_DIR = os.path.join(ROOT, "experiment_results")
OUT_DIR = os.path.join(RESULT_DIR, "paper_tables")


def configure_paths(result_dir=None):
    global RESULT_DIR, OUT_DIR
    if result_dir:
        RESULT_DIR = os.path.abspath(result_dir)
        OUT_DIR = os.path.join(RESULT_DIR, "paper_tables")


def read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def to_float(x):
    try:
        return float(x)
    except Exception:
        return None


def fmt_money(x):
    return f"{x:.2f}"


def fmt_pct(x):
    return f"{100.0 * x:.2f}%"


def make_range_table():
    rows = read_csv(os.path.join(RESULT_DIR, "range_sensitivity.csv"))
    parsed = []
    for r in rows:
        parsed.append(
            {
                "base_range_km": to_float(r["base_range"]),
                "objective_10k_cny": to_float(r["objective"]),
                "fixed_cost_10k_cny": to_float(r["fixed_cost"]),
                "fleet_cost_10k_cny": to_float(r["fleet_cost"]),
                "worst_penalty_10k_cny": to_float(r["worst_penalty_cost"]),
                "avg_coverage": to_float(r["avg_coverage"]),
                "min_coverage": to_float(r["min_coverage"]),
                "worst_scenario": r.get("worst_scenario", ""),
                "status": r.get("status", ""),
            }
        )
    parsed.sort(key=lambda r: (r["base_range_km"] if r["base_range_km"] is not None else 1e9))

    out_rows = []
    for r in parsed:
        out_rows.append(
            {
                "航程（km）": int(round(r["base_range_km"])) if r["base_range_km"] is not None else "",
                "系统总成本（万元）": fmt_money(r["objective_10k_cny"]),
                "建设固定成本（万元）": fmt_money(r["fixed_cost_10k_cny"]),
                "机队配置成本（万元）": fmt_money(r["fleet_cost_10k_cny"]),
                "最坏情景惩罚成本（万元）": fmt_money(r["worst_penalty_10k_cny"]),
                "平均覆盖率": fmt_pct(r["avg_coverage"]),
                "最坏覆盖率": fmt_pct(r["min_coverage"]),
                "最坏情景": r["worst_scenario"],
                "求解状态": r["status"],
            }
        )

    fields = list(out_rows[0].keys()) if out_rows else []
    write_csv(os.path.join(OUT_DIR, "表6_航程参数灵敏度分析.csv"), out_rows, fields)

    md_path = os.path.join(OUT_DIR, "表6_航程参数灵敏度分析.md")
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("表6 航程参数灵敏度分析结果\n\n")
        f.write("|" + "|".join(fields) + "|\n")
        f.write("|" + "|".join(["---"] * len(fields)) + "|\n")
        for r in out_rows:
            f.write("|" + "|".join(str(r[k]) for k in fields) + "|\n")


def make_base_summary_table():
    import json

    with open(os.path.join(RESULT_DIR, "base_solution_summary.json"), "r", encoding="utf-8") as f:
        base = json.load(f)
    rows = [
        {"指标": "目标函数值", "数值": f"{base['objective']:.2f}", "单位": "万元"},
        {"指标": "建设固定成本", "数值": f"{base['fixed_cost']:.2f}", "单位": "万元"},
        {"指标": "eVTOL配置成本", "数值": f"{base['fleet_cost']:.2f}", "单位": "万元"},
        {"指标": "最坏情景惩罚成本", "数值": f"{base['worst_penalty_cost']:.2f}", "单位": "万元"},
        {"指标": "选定起降场数量", "数值": f"{base['selected_sites']}", "单位": "个"},
        {"指标": "配置eVTOL数量", "数值": f"{base['fleet_total']}", "单位": "架"},
        {"指标": "平均覆盖率", "数值": f"{base['avg_coverage'] * 100:.2f}", "单位": "%"},
        {"指标": "最坏情景覆盖率", "数值": f"{base['min_coverage'] * 100:.2f}", "单位": "%"},
        {"指标": "最坏情景", "数值": base["worst_scenario"], "单位": "-"},
    ]
    fields = ["指标", "数值", "单位"]
    write_csv(os.path.join(OUT_DIR, "表1_基准方案结果汇总.csv"), rows, fields)
    with open(os.path.join(OUT_DIR, "表1_基准方案结果汇总.md"), "w", encoding="utf-8") as f:
        f.write("表1 基准方案结果汇总\n\n")
        f.write("|指标|数值|单位|\n|---|---:|---|\n")
        for r in rows:
            f.write(f"|{r['指标']}|{r['数值']}|{r['单位']}|\n")


def make_selected_site_table():
    rows = read_csv(os.path.join(RESULT_DIR, "selected_vertiports_base.csv"))
    out_rows = []
    for r in rows:
        out_rows.append(
            {
                "站点编号": r["site_id"],
                "站点名称": r.get("site_name", ""),
                "东西向坐标（km）": f"{float(r['x_km']):.2f}",
                "南北向坐标（km）": f"{float(r['y_km']):.2f}",
                "空间分区": "北岸" if r.get("bank") == "north" else "南岸",
                "是否边缘站点": "是" if str(r.get("edge")).lower() == "true" else "否",
                "配置eVTOL（架）": int(float(r["fleet"])),
            }
        )
    fields = list(out_rows[0].keys()) if out_rows else []
    write_csv(os.path.join(OUT_DIR, "表2_基准起降场选址与机队配置.csv"), out_rows, fields)
    with open(os.path.join(OUT_DIR, "表2_基准起降场选址与机队配置.md"), "w", encoding="utf-8") as f:
        f.write("表2 基准起降场选址与机队配置\n\n")
        f.write("|" + "|".join(fields) + "|\n")
        f.write("|" + "|".join(["---"] * len(fields)) + "|\n")
        for r in out_rows:
            f.write("|" + "|".join(str(r[k]) for k in fields) + "|\n")


def make_gamma_table():
    rows = sorted(read_csv(os.path.join(RESULT_DIR, "gamma_sensitivity.csv")), key=lambda r: float(r["gamma"]))
    out_rows = []
    for r in rows:
        out_rows.append(
            {
                "Gamma": int(float(r["gamma"])),
                "系统总成本（万元）": f"{float(r['objective']):.2f}",
                "最坏惩罚成本（万元）": f"{float(r['worst_penalty_cost']):.2f}",
                "平均覆盖率": f"{float(r['avg_coverage']) * 100:.2f}%",
                "最坏覆盖率": f"{float(r['min_coverage']) * 100:.2f}%",
                "最坏情景": r["worst_scenario"],
            }
        )
    fields = list(out_rows[0].keys()) if out_rows else []
    write_csv(os.path.join(OUT_DIR, "表3_Gamma灵敏度分析.csv"), out_rows, fields)
    with open(os.path.join(OUT_DIR, "表3_Gamma灵敏度分析.md"), "w", encoding="utf-8") as f:
        f.write("表3 Gamma灵敏度分析结果\n\n")
        f.write("|" + "|".join(fields) + "|\n")
        f.write("|" + "|".join(["---"] * len(fields)) + "|\n")
        for r in out_rows:
            f.write("|" + "|".join(str(r[k]) for k in fields) + "|\n")


def make_penalty_table():
    rows = sorted(read_csv(os.path.join(RESULT_DIR, "penalty_sensitivity.csv")), key=lambda r: float(r["penalty"]))
    out_rows = []
    for r in rows:
        out_rows.append(
            {
                "惩罚成本（万元）": f"{float(r['penalty']):.0f}",
                "系统总成本（万元）": f"{float(r['objective']):.2f}",
                "机队规模（架）": int(float(r["fleet_total"])),
                "最坏惩罚成本（万元）": f"{float(r['worst_penalty_cost']):.2f}",
                "平均覆盖率": f"{float(r['avg_coverage']) * 100:.2f}%",
                "最坏覆盖率": f"{float(r['min_coverage']) * 100:.2f}%",
            }
        )
    fields = list(out_rows[0].keys()) if out_rows else []
    write_csv(os.path.join(OUT_DIR, "表5_惩罚成本灵敏度分析.csv"), out_rows, fields)
    with open(os.path.join(OUT_DIR, "表5_惩罚成本灵敏度分析.md"), "w", encoding="utf-8") as f:
        f.write("表5 惩罚成本灵敏度分析结果\n\n")
        f.write("|" + "|".join(fields) + "|\n")
        f.write("|" + "|".join(["---"] * len(fields)) + "|\n")
        for r in out_rows:
            f.write("|" + "|".join(str(r[k]) for k in fields) + "|\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-dir", default=RESULT_DIR)
    args = parser.parse_args()
    configure_paths(args.result_dir)
    make_base_summary_table()
    make_selected_site_table()
    make_gamma_table()
    make_penalty_table()
    make_range_table()
    print(f"paper tables written to: {OUT_DIR}")


if __name__ == "__main__":
    main()
