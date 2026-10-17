# Data, training runs and weights

Everything under `data/raw/`, `data/processed/` and `runs/` is gitignored (about 7.5 GB) and lives in the
GitHub release **`datasets-2026-10-17`** as zip files, each under 2 GB. `scripts/fetch-datasets.sh`
downloads and unpacks all of them, or one pattern at a time:

```bash
scripts/fetch-datasets.sh                      # everything
scripts/fetch-datasets.sh 'processed-*'        # only the built training sets
scripts/fetch-datasets.sh 'training-runs-*'    # the training runs and .pt weights
```

| Asset | Unpacks to | What |
|---|---|---|
| `raw-ccmt.zip` | `data/raw/ccmt/` | CCMT raw tomato folders (Ghana), CC BY 4.0 |
| `raw-slif-detection.zip` | `data/raw/slif/Detection_Dataset/` | SLIF-Tomato boxes (the leaf finder's training set), CC BY 4.0 |
| `raw-slif-raw-Early_Blight.zip`, `raw-slif-raw-other-classes.zip` | `data/raw/slif/Raw_Dataset/` | SLIF-Tomato full-resolution field photos, CC BY 4.0 |
| `raw-sichuan-annotations.zip`, `raw-sichuan-GrayMold.zip`, `raw-sichuan-Viral.zip`, `raw-sichuan-Wilt.zip` | `data/raw/sichuan/` | Sichuan greenhouse photos and Pascal VOC boxes, CC BY 4.0 |
| `raw-taiwan.zip` | `data/raw/taiwan/` | Taiwan tomato leaves, CC BY 4.0 |
| `raw-plantdoc.zip` | `data/raw/plantdoc/` | PlantDoc tomato boxes, CC BY 4.0 (web photos) |
| `raw-plantvillage.zip` | `data/raw/plantvillage/` | PlantVillage close-ups for five tomato classes, CC BY-SA 3.0 |
| `raw-tfdd.zip` | `data/raw/tfdd/` | TFDD tomato fruit boxes, CC BY 4.0 |
| `processed-detector.zip` | `data/processed/detector/` | The leaf finder's YOLO dataset (640 px) |
| `processed-classifier.zip` | `data/processed/classifier/` | The field leaf set: squares and finder crops, split by photo |
| `processed-fixtures.zip` | `data/processed/fixtures/` | The six whole-plant test scenes |
| `training-runs-and-weights.zip` | `runs/`, `yolo26n.pt` | Every training run with per-epoch `.pt` weights, and the COCO starting checkpoint |

The fine-tuning folders (`data/processed/condition-ft`, `crop-view-ft*`) are symlink trees made by
`tools/classifier/assemble.py` from these sets plus the general models' original training sets, which
are not in this repo; `assemble.py` rebuilds them.

The six ONNX models the page uses are in git (`vision/private/cropscout-*.onnx`) and on the `models` branch.
Licences of every source are in `docs/datasets.md` and `vision/private/dataset-provenance.json`.
