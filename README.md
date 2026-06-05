# evtol-emergency-location-optimization

兰州市 eVTOL 急救起降点选址实验代码。

## scripts

- `generate_amap_lanzhou_dataset.py`
- `run_evtol_experiments.py`
- `make_paper_figures.py`
- `make_paper_tables.py`
- `collect_gurobi_diagnostics.py`

## install

```powershell
pip install -r requirements.txt
```

## run

```powershell
$env:AMAP_KEY="your-amap-key"

python generate_amap_lanzhou_dataset.py --out-dir output_data_amap_realistic --calls 12000 --clusters 50

python run_evtol_experiments.py --data-dir output_data_amap_realistic --result-dir experiment_results_amap

python make_paper_figures.py --result-dir experiment_results_amap
python make_paper_tables.py --result-dir experiment_results_amap

python collect_gurobi_diagnostics.py --data-dir output_data_amap_realistic --result-dir experiment_results_amap
```

## output

- `output_data_amap_realistic/`
- `experiment_results_amap/`
