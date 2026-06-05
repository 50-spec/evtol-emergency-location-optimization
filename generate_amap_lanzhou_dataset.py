import argparse
import csv
import json
import math
import os
import random
import time
import urllib.parse
import urllib.request
from collections import Counter

import numpy as np
import pandas as pd


CENTER_LON = 103.8343
CENTER_LAT = 36.0611
BOUNDS = {
    "lon_min": 103.35,
    "lon_max": 104.25,
    "lat_min": 35.85,
    "lat_max": 36.25,
}


SEARCH_PLAN = {
    "hospital": ["医院", "综合医院", "急救中心", "卫生院"],
    "residential": ["小区", "住宅区", "社区", "家园"],
    "school": ["学校", "大学", "中学", "小学"],
    "commercial": ["商场", "购物中心", "市场", "广场"],
    "transport": ["公交站", "地铁站", "火车站", "汽车站"],
    "park": ["公园", "景区", "体育场"],
}

LAYER_BASE_WEIGHT = {
    "residential": 1.00,
    "hospital": 0.70,
    "school": 0.38,
    "commercial": 0.55,
    "transport": 0.45,
    "park": 0.22,
}


def lonlat_to_xy(lon, lat):
    x = (lon - CENTER_LON) * 111.32 * math.cos(math.radians(CENTER_LAT))
    y = (lat - CENTER_LAT) * 110.57
    return x, y


def xy_to_lonlat(x, y):
    lon = CENTER_LON + x / (111.32 * math.cos(math.radians(CENTER_LAT)))
    lat = CENTER_LAT + y / 110.57
    return lon, lat


def in_bounds(lon, lat):
    return (
        BOUNDS["lon_min"] <= lon <= BOUNDS["lon_max"]
        and BOUNDS["lat_min"] <= lat <= BOUNDS["lat_max"]
    )


def amap_request(key, keyword, page, offset):
    params = {
        "key": key,
        "keywords": keyword,
        "city": "兰州市",
        "citylimit": "true",
        "offset": str(offset),
        "page": str(page),
        "extensions": "base",
        "output": "json",
    }
    url = "https://restapi.amap.com/v3/place/text?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_location(value):
    if not value or "," not in value:
        return None
    lon_text, lat_text = value.split(",", 1)
    lon = float(lon_text)
    lat = float(lat_text)
    if not in_bounds(lon, lat):
        return None
    return lon, lat


def fetch_amap_pois(key, max_pages=20, offset=25):
    records = {}
    errors = []
    for layer, keywords in SEARCH_PLAN.items():
        for keyword in keywords:
            for page in range(1, max_pages + 1):
                payload = None
                for attempt in range(5):
                    try:
                        payload = amap_request(key, keyword, page, offset)
                    except Exception as exc:
                        errors.append({"keyword": keyword, "page": page, "error": str(exc)})
                        time.sleep(0.8 + attempt * 0.8)
                        continue
                    if payload.get("status") == "1":
                        break
                    info = payload.get("info", "unknown")
                    if "QPS" in info or "LIMIT" in info:
                        time.sleep(1.2 + attempt * 1.2)
                        continue
                    break
                if payload is None:
                    break
                if payload.get("status") != "1":
                    errors.append({"keyword": keyword, "page": page, "error": payload.get("info", "unknown")})
                    break
                pois = payload.get("pois", [])
                if not pois:
                    break
                for poi in pois:
                    loc = parse_location(poi.get("location", ""))
                    if not loc:
                        continue
                    lon, lat = loc
                    poi_id = poi.get("id") or f"{poi.get('name','')}_{lon:.6f}_{lat:.6f}"
                    key_tuple = (poi_id, layer)
                    if key_tuple in records:
                        continue
                    x, y = lonlat_to_xy(lon, lat)
                    records[key_tuple] = {
                        "poi_id": poi_id,
                        "name": poi.get("name", ""),
                        "type": poi.get("type", ""),
                        "address": poi.get("address", ""),
                        "longitude": lon,
                        "latitude": lat,
                        "keyword": keyword,
                        "layer": layer,
                        "source": "amap_api",
                        "x_km": x,
                        "y_km": y,
                    }
                time.sleep(0.35)
    return list(records.values()), errors


def add_terrain_layers(pois):
    terrain = []
    for idx, x in enumerate(np.linspace(-34, 34, 23)):
        lon, lat = xy_to_lonlat(float(x), 0.0)
        terrain.append(
            {
                "poi_id": f"T_RIVER_{idx:03d}",
                "name": "黄河河谷控制点",
                "type": "terrain;river",
                "address": "兰州市黄河沿线",
                "longitude": lon,
                "latitude": lat,
                "keyword": "黄河",
                "layer": "river",
                "source": "terrain_rule",
                "x_km": float(x),
                "y_km": 0.0,
            }
        )
    for side, y in [("N", 12.0), ("S", -12.0)]:
        for idx, x in enumerate(np.linspace(-32, 32, 17)):
            lon, lat = xy_to_lonlat(float(x), y)
            terrain.append(
                {
                    "poi_id": f"T_MOUNTAIN_{side}_{idx:03d}",
                    "name": "南北山边缘控制点" if side == "S" else "北山边缘控制点",
                    "type": "terrain;mountain",
                    "address": "兰州市南北山边缘",
                    "longitude": lon,
                    "latitude": lat,
                    "keyword": "山地",
                    "layer": "mountain",
                    "source": "terrain_rule",
                    "x_km": float(x),
                    "y_km": y,
                }
            )
    return pois + terrain


def fallback_hospitals():
    hospitals = [
        ("H_LDYY", "兰州大学第一医院", 1.0, -1.2),
        ("H_GSSRM", "甘肃省人民医院", 4.5, 0.8),
        ("H_LDEY", "兰州大学第二医院", -2.5, 1.1),
        ("H_GSSZYY", "甘肃省中医院", -6.0, -1.0),
        ("H_XG", "西固区人民医院", -24.0, -1.0),
        ("H_AN", "安宁区人民医院", -8.5, 4.6),
    ]
    rows = []
    for poi_id, name, x, y in hospitals:
        lon, lat = xy_to_lonlat(x, y)
        rows.append(
            {
                "poi_id": poi_id,
                "name": name,
                "type": "医疗保健服务;综合医院",
                "address": "兰州市",
                "longitude": lon,
                "latitude": lat,
                "keyword": "医院",
                "layer": "hospital",
                "source": "manual_anchor",
                "x_km": x,
                "y_km": y,
            }
        )
    return rows


def build_sampling_frame(pois):
    df = pd.DataFrame(pois)
    service_layers = ["residential", "hospital", "school", "commercial", "transport", "park"]
    frame = df[df["layer"].isin(service_layers)].copy()
    if frame[frame["layer"] == "hospital"].shape[0] < 4:
        frame = pd.concat([frame, pd.DataFrame(fallback_hospitals())], ignore_index=True)
    if frame.empty:
        raise RuntimeError("No usable Lanzhou POIs were fetched from Amap.")
    frame["terrain_risk"] = (
        0.18 * (frame["y_km"].abs() / 12.0).clip(0, 1)
        + 0.12 * (frame["x_km"].abs() / 32.0).clip(0, 1)
        + 0.10 * ((frame["y_km"].abs() > 8) | (frame["x_km"].abs() > 24)).astype(float)
    )
    hotspots = [(-2, 0, 1.0, 9), (8, 3, 0.85, 8), (-11, 4, 0.65, 7), (-22, -1, 0.55, 7)]
    hot = np.zeros(len(frame))
    for hx, hy, scale, spread in hotspots:
        hot += scale * np.exp(-((frame["x_km"] - hx) ** 2 + (frame["y_km"] - hy) ** 2) / (2 * spread**2))
    edge_boost = ((frame["x_km"].abs() > 18) | (frame["y_km"].abs() > 6)).astype(float)
    frame["demand_weight"] = frame["layer"].map(LAYER_BASE_WEIGHT).fillna(0.2) * (
        0.45 + hot + frame["terrain_risk"]
    ) * (1.0 + 1.6 * frame["terrain_risk"] + 0.45 * edge_boost)
    frame["demand_weight"] = frame["demand_weight"].clip(lower=0.03)
    return frame.reset_index(drop=True)


def hour_probabilities():
    counts = np.array(
        [234, 167, 128, 153, 167, 237, 356, 559, 666, 607, 607, 571,
         558, 606, 634, 684, 752, 824, 821, 791, 725, 488, 356, 309],
        dtype=float,
    )
    return counts / counts.sum()


def nearest_hospital_metrics(x, y, hospitals):
    dx = hospitals["x_km"].to_numpy() - x
    dy = hospitals["y_km"].to_numpy() - y
    distances = np.sqrt(dx * dx + dy * dy)
    idx = int(np.argmin(distances))
    return float(distances[idx]), float(hospitals.iloc[idx]["x_km"]), float(hospitals.iloc[idx]["y_km"])


def simulate_calls(pois, call_count, seed):
    rng = np.random.default_rng(seed)
    random.seed(seed)
    frame = build_sampling_frame(pois)
    hospitals = pd.DataFrame(fallback_hospitals())
    weights = frame["demand_weight"].to_numpy()
    weights = weights / weights.sum()
    center_indices = rng.choice(len(frame), size=call_count, replace=True, p=weights)
    hours = rng.choice(np.arange(24), size=call_count, p=hour_probabilities())

    rows = []
    sigma_by_layer = {
        "residential": 0.65,
        "hospital": 0.45,
        "school": 0.55,
        "commercial": 0.75,
        "transport": 0.70,
        "park": 0.85,
    }
    for call_idx, center_idx in enumerate(center_indices, 1):
        center = frame.iloc[int(center_idx)]
        sigma = sigma_by_layer.get(center["layer"], 0.7)
        x = float(center["x_km"] + rng.normal(0, sigma))
        y = float(center["y_km"] + rng.normal(0, sigma * 0.8))
        x = float(np.clip(x, -36.0, 36.0))
        y = float(np.clip(y, -14.0, 14.0))
        lon, lat = xy_to_lonlat(x, y)
        hour = int(hours[call_idx - 1])
        rush = 1.0 if hour in {7, 8, 17, 18, 19, 20} else 0.0
        night = 1.0 if hour <= 5 else 0.0
        terrain = 0.16 * min(abs(y) / 12.0, 1.0) + 0.10 * min(abs(x) / 32.0, 1.0)
        layer_risk = {
            "residential": 0.04,
            "hospital": 0.02,
            "school": -0.02,
            "commercial": 0.03,
            "transport": 0.05,
            "park": -0.01,
        }.get(center["layer"], 0.0)
        risk = 0.90 + terrain + layer_risk + 0.05 * rush + rng.normal(0, 0.075)
        risk = float(np.clip(risk, 0.55, 1.45))
        severity = 0.86 + 0.28 * rng.beta(2.0, 5.5) + 0.10 * night + 0.10 * terrain + 0.18 * (risk - 1.0)
        severity += rng.normal(0, 0.13)
        severity = float(np.clip(severity, 0.35, 1.60))
        nearest_dist, hospital_x, hospital_y = nearest_hospital_metrics(x, y, hospitals)
        cross_river = 1.0 if y * hospital_y < -0.2 else 0.0
        road_factor = 1.65 + 0.35 * rush + 0.35 * cross_river + 0.65 * (abs(y) > 8) + 0.18 * (abs(x) > 20)
        ambulance_time = 9.0 + nearest_dist * road_factor / 21.0 * 60.0 + rng.normal(0, 2.2)
        ambulance_time += 5.0 * cross_river + 4.5 * (abs(y) > 8) + 2.5 * (abs(x) > 24)
        ambulance_time = float(np.clip(ambulance_time, 8.0, 85.0))
        evtol_route = nearest_dist * 1.12
        evtol_time = 5.0 + evtol_route / 150.0 * 60.0 + rng.normal(0, 0.6)
        evtol_time = float(np.clip(evtol_time, 5.5, 26.0))
        savings = max(0.0, (ambulance_time - evtol_time) / ambulance_time * 100.0)
        if ambulance_time > 35:
            htr_type = "response_failure"
        elif savings > 60 and ambulance_time > 28:
            htr_type = "time_saving"
        elif (abs(y) > 8 or abs(x) > 24) and ambulance_time > 30:
            htr_type = "terrain_barrier"
        else:
            htr_type = ""
        rows.append(
            {
                "Call_ID": f"EMR_{call_idx:06d}",
                "longitude": round(lon, 6),
                "latitude": round(lat, 6),
                "source_layer": center["layer"],
                "risk_index": round(risk, 6),
                "event_hour": hour,
                "X_Coordinate_km": round(x, 4),
                "Y_Coordinate_km": round(y, 4),
                "severity_score": round(severity, 6),
                "ambulance_time_min": round(ambulance_time, 2),
                "evtol_time_min": round(evtol_time, 2),
                "time_savings_ratio": round(savings, 2),
                "htr_type": htr_type,
            }
        )
    return pd.DataFrame(rows)


def weighted_kmeans(points, weights, k, seed, max_iter=80):
    rng = np.random.default_rng(seed)
    n = len(points)
    centers = np.empty((k, 2), dtype=float)
    first = rng.choice(n, p=weights / weights.sum())
    centers[0] = points[first]
    min_dist_sq = np.sum((points - centers[0]) ** 2, axis=1)
    for center_idx in range(1, k):
        probs = min_dist_sq * weights
        probs = probs / probs.sum()
        selected = rng.choice(n, p=probs)
        centers[center_idx] = points[selected]
        min_dist_sq = np.minimum(min_dist_sq, np.sum((points - centers[center_idx]) ** 2, axis=1))
    labels = np.zeros(n, dtype=int)
    for _ in range(max_iter):
        dist_sq = ((points[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        new_labels = dist_sq.argmin(axis=1)
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for center_idx in range(k):
            mask = labels == center_idx
            if not mask.any():
                centers[center_idx] = points[rng.integers(0, n)]
                continue
            w = weights[mask]
            centers[center_idx] = np.average(points[mask], axis=0, weights=w)
    return labels, centers


def build_clusters(calls, k, seed):
    points = calls[["X_Coordinate_km", "Y_Coordinate_km"]].to_numpy(dtype=float)
    weights = (calls["severity_score"] * calls["risk_index"]).to_numpy(dtype=float)
    labels, centers = weighted_kmeans(points, weights, k, seed)
    calls = calls.copy()
    calls["cluster_id"] = labels
    rows = []
    for cluster_id in range(k):
        subset = calls[calls["cluster_id"] == cluster_id]
        if subset.empty:
            continue
        demand_count = int(len(subset))
        weighted_x = float(np.average(subset["X_Coordinate_km"], weights=subset["severity_score"]))
        weighted_y = float(np.average(subset["Y_Coordinate_km"], weights=subset["severity_score"]))
        lon, lat = xy_to_lonlat(weighted_x, weighted_y)
        rows.append(
            {
                "cluster_id": cluster_id,
                "longitude": round(lon, 6),
                "latitude": round(lat, 6),
                "demand_count": demand_count,
                "avg_severity": round(float(subset["severity_score"].mean()), 4),
                "avg_risk": round(float(subset["risk_index"].mean()), 4),
                "x_km": round(weighted_x, 4),
                "y_km": round(weighted_y, 4),
            }
        )
    cluster_df = pd.DataFrame(rows).sort_values("demand_count", ascending=False).reset_index(drop=True)
    id_map = {int(old): int(new) for new, old in enumerate(cluster_df["cluster_id"].tolist())}
    cluster_df["cluster_id"] = range(len(cluster_df))
    calls["cluster_id"] = calls["cluster_id"].map(id_map).astype(int)
    return calls, cluster_df


def write_outputs(out_dir, pois, calls, clusters, errors):
    os.makedirs(out_dir, exist_ok=True)
    poi_df = pd.DataFrame(pois)
    poi_columns = [
        "poi_id", "name", "type", "address", "longitude", "latitude", "keyword", "layer", "source", "x_km", "y_km"
    ]
    poi_df[poi_columns].to_csv(os.path.join(out_dir, "lanzhou_poi_layers.csv"), index=False, encoding="utf-8-sig")
    final_columns = [
        "Call_ID", "longitude", "latitude", "source_layer", "risk_index", "event_hour",
        "X_Coordinate_km", "Y_Coordinate_km", "severity_score", "cluster_id",
    ]
    calls[final_columns].to_csv(os.path.join(out_dir, "lanzhou_final_ems_dataset.csv"), index=False, encoding="utf-8-sig")
    clusters.to_csv(os.path.join(out_dir, "lanzhou_demand_clusters.csv"), index=False, encoding="utf-8-sig")
    htr = calls[calls["htr_type"] != ""].copy()
    htr_columns = final_columns + ["ambulance_time_min", "evtol_time_min", "time_savings_ratio", "htr_type"]
    htr[htr_columns].to_csv(os.path.join(out_dir, "lanzhou_hard_to_reach_areas.csv"), index=False, encoding="utf-8-sig")
    summary = {
        "city": "Lanzhou",
        "source_mode": "amap_api_plus_simulation",
        "poi_count": int(len(poi_df)),
        "api_poi_count": int((poi_df["source"] == "amap_api").sum()),
        "call_count": int(len(calls)),
        "cluster_count": int(len(clusters)),
        "htr_count": int(len(htr)),
        "htr_ratio": round(float(len(htr) / len(calls) * 100.0), 2),
        "center": {"lon": CENTER_LON, "lat": CENTER_LAT},
        "layer_counts": {k: int(v) for k, v in calls["source_layer"].value_counts().to_dict().items()},
        "poi_layer_counts": {k: int(v) for k, v in poi_df["layer"].value_counts().to_dict().items()},
        "hour_counts": {str(k): int(v) for k, v in calls["event_hour"].value_counts().sort_index().to_dict().items()},
        "severity_stats": {k: float(v) for k, v in calls["severity_score"].describe()[["mean", "std", "min", "max"]].to_dict().items()},
        "api_error_count": len(errors),
        "api_errors_sample": errors[:10],
    }
    with open(os.path.join(out_dir, "lanzhou_dataset_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    validation = build_validation_text(poi_df, calls, clusters, htr, summary)
    with open(os.path.join(out_dir, "dataset_validation_report.md"), "w", encoding="utf-8") as f:
        f.write(validation)


def build_validation_text(poi_df, calls, clusters, htr, summary):
    coord_counts = calls.groupby(["longitude", "latitude"]).size().sort_values(ascending=False)
    top2_share = float(coord_counts.head(2).sum() / len(calls) * 100.0)
    top5_cluster_share = float(clusters.sort_values("demand_count", ascending=False).head(5)["demand_count"].sum() / clusters["demand_count"].sum() * 100.0)
    corr = float(calls["risk_index"].corr(calls["severity_score"]))
    lines = [
        "# 兰州 eVTOL 医疗救援模拟数据质量检查",
        "",
        "## 核心结论",
        "",
        "数据以高德地图兰州市 POI 为空间锚点，并叠加河谷城市、跨河通行和山缘难到达等规则生成模拟急救呼叫。",
        "",
        "## 关键指标",
        "",
        f"- POI 总数：{summary['poi_count']}，其中高德 API 获取 {summary['api_poi_count']} 个。",
        f"- 急救呼叫数：{summary['call_count']}。",
        f"- 需求聚类数：{summary['cluster_count']}。",
        f"- 难到达需求数：{summary['htr_count']}，占比 {summary['htr_ratio']}%。",
        f"- 前两个重复坐标占比：{top2_share:.2f}%。",
        f"- 前五个聚类需求占比：{top5_cluster_share:.2f}%。",
        f"- 风险指数与严重度相关系数：{corr:.3f}。",
        "",
        "## 判断",
        "",
        "本轮数据去除了边界点堆积和 POI 城市错位问题，难到达需求比例也控制在实验设定范围内。数据类型为模拟急救需求，不代表真实 120 出车记录。",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="output_data_amap_realistic")
    parser.add_argument("--calls", type=int, default=12000)
    parser.add_argument("--clusters", type=int, default=50)
    parser.add_argument("--seed", type=int, default=20260511)
    args = parser.parse_args()
    api_key = os.environ.get("AMAP_KEY")
    if not api_key:
        raise SystemExit("AMAP_KEY environment variable is required.")
    pois, errors = fetch_amap_pois(api_key)
    pois = add_terrain_layers(pois)
    calls = simulate_calls(pois, args.calls, args.seed)
    calls, clusters = build_clusters(calls, args.clusters, args.seed)
    write_outputs(args.out_dir, pois, calls, clusters, errors)
    print(json.dumps({
        "out_dir": args.out_dir,
        "poi_count": len(pois),
        "api_poi_count": sum(1 for p in pois if p["source"] == "amap_api"),
        "call_count": len(calls),
        "cluster_count": len(clusters),
        "htr_count": int((calls["htr_type"] != "").sum()),
        "htr_ratio": round(float((calls["htr_type"] != "").mean() * 100.0), 2),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
