# Leaf finder

The classifiers expect **one leaf or fruit filling the square**. A phone held up to a whole plant shows many small leaves, which the classifiers never saw in training. The leaf finder is a small detector that finds each tomato leaf and fruit in the square, so each one can be cut out and checked on its own.

It is behind a feature flag: open the page as `/vision/?detector=1`. Without the flag the page behaves exactly as before.

```
camera ─► centre square ─► 540 px ─► 320 px ─► leaf finder (YOLO26n detector)
                              │                     │ boxes: tomato_leaf, tomato_fruit
                              │                     ▼
                              │       one box fills ≥ 60 % of the square, or no box?
                              │          yes ─► whole square ─► 224 px ─► classifiers (as without the finder)
                              │          no  ─► up to 3 boxes, each ≥ 15 % of the square
                              ▼
               each box: square cut from the full-resolution video ─► 2:1 halving ─► 224 px
                              ▼
               crop/type model ─► condition model ─► 4 safeguards ─► 3-of-4 vote   (per leaf)
```

## What stays the same

- **Every safeguard runs per leaf.** Each detected leaf is its own track with its own score smoothing and its own 3-of-4 vote, using the same thresholds as the whole square. The crop/type gate still decides whether a box is a tomato leaf or fruit; the detector's class is never used as a result.
- **Smoothing and voting never lower a threshold.** Scores are averaged per track and the same four safeguards then run on the averaged scores. A frame where the finder misses a leaf counts like a frame that failed a safeguard: an empty vote, which can withdraw a verdict but never confirm one. Two misses in a row end the track.
- **Crop lost, verdict cleared.** As before, a leaf whose crop gate fails loses its verdict at once. Switching between "whole square" and "separate leaves" starts every track from scratch.
- **Close-ups match photo mode.** When one box fills most of the square, or nothing is found, the whole square is analysed exactly as without the finder.
- **Same preprocessing.** Each leaf is cut from the full-resolution video (not from the 540 px copy), halved 2:1 by the browser while it stays at least 448 px, then resized with the same antialiased resize as photo mode. The classifier ONNX files are fixed at batch 1, so each leaf runs on its own.

## Display

- Each leaf gets a box on the camera view: green with the condition name once its vote confirms it, gold while it is being checked, dashed when it is not sure.
- The label at the top shows one leaf: a confirmed disease first, then a confirmed healthy-like leaf, then a leaf still being confirmed, then the biggest leaf. "· 3 found" says how many leaves are being checked.
- `window.CropScoutVision.liveStats()` adds `mode` (`square` or `leaves`), `avgDetectorMs`, and `leaves` (box, detector score, state and shown verdict of each leaf).

## Settings

They live in the `leaf_detector` entry of `vision/private/model-metadata.json`, next to the model's SHA-256, and are only read when the flag is on.

| Setting | Value | Meaning |
|---|---|---|
| `input_size` | 320 | detector input, 1×3×320×320, RGB, 0–1 |
| `score_threshold` | 0.35 | keep boxes at or above this score |
| `min_box_side` | 0.15 | ignore boxes whose longer side is under 15 % of the square (too small to classify) |
| `whole_square_side` | 0.6 | a box this big means one leaf fills the square: use the whole square |
| `max_leaves` | 3 | classify at most 3 boxes per frame (best scores first) |
| `crop_padding` | 1.15 | cut a square 15 % larger than the box's longer side |

## Training data

Two classes, `tomato_leaf` and `tomato_fruit`, from boxed field sets that allow commercial use (all CC BY 4.0). Tomato-Village is not used: it has no licence.

| Source | What we used | Images | Independent photos | Boxes |
|---|---|---|---|---|
| [SLIF-Tomato](https://www.kaggle.com/datasets/romiyalgeorge/slif-tomato-dataset) (Sri Lanka, field) | `Detection_Dataset` only: the only part with boxes. All 8 disease classes → `tomato_leaf` | 2,670 | 603 base photos (`tNNNN`) | leaf |
| [Sichuan greenhouse](https://data.mendeley.com/datasets/c2x8rynybg/1) (China) | `*_Leaf` → leaf, `*_Fruit` → fruit. Stem and plant-zone boxes (Top/Middle/Base) dropped; images with only zone boxes dropped (475) | 551 | 5 capture days | leaf, fruit |
| [PlantDoc](https://github.com/pratikkayal/PlantDoc-Object-Detection-Dataset) (web photos) | all tomato boxes → `tomato_leaf`; 5 files whose annotation is rotated against the image dropped | 738 | 717 files | leaf |
| [TFDD](https://data.mendeley.com/datasets/ktfnhjspjn/3) (Bangladesh, field + market) | all boxes → `tomato_fruit`, added because the three sets above have only 52 fruit boxes | 682 | 184 photo groups | fruit |

PlantDoc's licence is CC BY 4.0, but its images were scraped from the web, so rights in some pixels are unclear (see [datasets.md](datasets.md)).

**Splits are by source, never by file.** SLIF and TFDD ship only Roboflow-augmented copies (3 per photo), so all copies of one photo stay together (SLIF by base photo ID, which also joins the `_1`…`_4` siblings). Sichuan is split by capture day: 0509, 1021 and 1112 train, 0919 validation, 0617 test. Other sources are split by a hash of the group (about 80/12/8).

**Dedupe.** Every image gets a 64-bit DCT perceptual hash. Pairs within 6 bits are near-duplicates: across sources the later one is dropped; within a source the two groups are merged so they share a split. No cross-source duplicates were found; 155 within-source pairs were merged (mostly TFDD fruit photos).

**Resized copies.** Images are stored with a 640 px long side (`data/processed/detector/`, gitignored) and trained with `cache=False`.

| Split | Images | Leaf boxes | Fruit boxes |
|---|---|---|---|
| train | 3,682 | 56,098 | 622 |
| val | 620 | 8,897 | 160 |
| test | 339 | 5,122 | 95 |

**Known gaps.**
- Fruit is thin: 877 boxes in total, and TFDD often boxes the diseased patch of a fruit rather than the whole fruit, and leaves healthy fruit unboxed.
- Many leaves in SLIF and Sichuan photos are not boxed. The detector learns to be conservative, which suits this use: it only has to find a few clear leaves per frame.
- SLIF boxes are on leaflets (tomato leaves are compound), with some lesion-sized boxes.

## Rebuild

```bash
python3 -m venv .venv && .venv/bin/pip install ultralytics onnx onnxslim onnxruntime opencv-python
.venv/bin/python -I tools/detector/fetch_slif.py data/raw/slif          # 171 MB of the 6 GB archive, by HTTP range requests
.venv/bin/python -I tools/detector/fetch_sichuan.py data/raw/sichuan    # 2.8 GB, SHA-256 checked
.venv/bin/python -I tools/detector/fetch_plantdoc.py data/raw/plantdoc
.venv/bin/python -I tools/detector/fetch_tfdd.py data/raw/tfdd
.venv/bin/python -I tools/detector/build_dataset.py data/raw data/processed/detector
.venv/bin/python -I tools/detector/train.py data/processed/detector/data.yaml 50
.venv/bin/python -I tools/detector/export.py runs/detect/runs/detector/yolo26n-320/weights/best.pt data/processed/detector
```

`export.py` writes `vision/private/cropscout-leaf-detector.onnx` (gitignored) and its SHA-256 into the metadata.
