# eVTOL Emergency Location Optimization

本仓库包含毕业设计中用于 eVTOL 急救起降点选址优化实验的 Python 脚本，主要覆盖兰州市模拟急救需求数据生成、Gurobi 求解、敏感性分析、论文图表生成和求解诊断。

## 文件说明

- `generate_amap_lanzhou_dataset.py`：基于高德地图 POI 和模拟规则生成兰州市急救需求数据。
- `run_evtol_experiments.py`：构建并求解 eVTOL 急救起降点选址优化模型，输出实验结果。
- `make_paper_figures.py`：根据实验结果生成论文图件。
- `make_paper_tables.py`：根据实验结果生成论文表格。
- `collect_gurobi_diagnostics.py`：收集 Gurobi 基准场景求解日志、收敛曲线和诊断信息。

## 环境依赖

建议使用 Python 3.10 或更高版本。

```powershell
pip install -r requirements.txt
```

其中 `gurobipy` 需要本机已经配置可用的 Gurobi 许可证。

## 运行流程

1. 配置高德地图 API key。代码只从环境变量读取 key，不需要也不应该把 key 写进源码。

```powershell
$env:AMAP_KEY="your-amap-key"
```

2. 生成兰州市模拟急救需求数据。

```powershell
python generate_amap_lanzhou_dataset.py --out-dir output_data_amap_realistic --calls 12000 --clusters 50
```

3. 运行优化实验。

```powershell
python run_evtol_experiments.py --data-dir output_data_amap_realistic --result-dir experiment_results_amap
```

4. 生成论文图表。

```powershell
python make_paper_figures.py --result-dir experiment_results_amap
python make_paper_tables.py --result-dir experiment_results_amap
```

5. 可选：收集 Gurobi 求解诊断。

```powershell
python collect_gurobi_diagnostics.py --data-dir output_data_amap_realistic --result-dir experiment_results_amap
```

## 隐私说明

仓库不包含明文 API key、Gurobi 许可证、个人手机号、邮箱、身份证号或本机绝对路径。运行生成的数据、日志、图件和实验结果目录已加入 `.gitignore`，避免把本地结果文件误提交。
