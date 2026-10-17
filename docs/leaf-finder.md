# Leaf finder

The classifiers expect **one leaf or fruit filling the square**. A phone held up to a whole plant shows many small leaves, which the classifiers never saw in training. The leaf finder is a small detector that finds each tomato leaf and fruit in the square, so each one can be cut out and checked on its own.

It is behind a feature flag: open the page as `/vision/?detector=1`. Without the flag the page behaves exactly as before.

```
camera ─► centre square ─► 540 px ─► 320 px ─► leaf finder (YOLO26n detector)
                              │                     │ boxes: tomato_leaf, tomato_fruit
                              │                     ▼
                              │       a box's longer side ≥ 60 % of the square, or no box?
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
- **Crop lost, verdict cleared.** As before, a leaf whose crop gate fails loses its verdict at once. Switching between "whole square" and "separate leaves" starts every track from scratch. Splitting into leaves takes one frame; going back to the whole square takes two in a row, so one empty detector frame does not wipe the leaves.
- **Close-ups match photo mode.** When one box fills most of the square, or nothing is found, the whole square is analysed exactly as without the finder.
- **Same preprocessing.** Each leaf is cut from a full-resolution copy of the square taken in the same instant as the detector's input (not from the 540 px copy, and not from a later video frame), halved 2:1 by the browser while it stays at least 448 px (the crop side is rounded so every step is exact), then resized with the same antialiased resize as photo mode. The classifier ONNX files are fixed at batch 1, so each leaf runs on its own.
- **Fails safe.** If the finder model is missing, fails its SHA-256 check, has a malformed metadata entry or returns an unexpected output, it is switched off and live mode analyses the whole square.

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

In `app.js`: a leaf keeps its track while its box overlaps last frame's box by IoU ≥ 0.5 (strict, so a neighbouring leaf does not inherit a verdict), and a box that overlaps a better box by IoU > 0.7 (the same object boxed as leaf and as fruit) is dropped.

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

## Training

YOLO26n from the COCO checkpoint, 320 px, 50 epochs, batch 32, on an Apple M2 (MPS) in 1.8 hours. The best epoch is exported to ONNX (opset 17, static 1×3×320×320, 9.7 MB) with the NMS-free one-to-one head, so the page needs no NMS code. `export.py` checks that onnxruntime and Ultralytics return the same boxes (max difference 0.000 px on the sample).

Ultralytics validates with the one-to-many head plus NMS unless `nms=False` is passed, so the numbers printed during training are not those of the exported head. `evaluate.py` scores the exported head.

## Results

### Detector, held-out test split (339 images, exported NMS-free head)

| | mAP50 | mAP50-95 |
|---|---|---|
| All | 0.47 | 0.24 |
| tomato_leaf | 0.15 | — |
| tomato_fruit | 0.79 | — |
| PlantDoc (48 images) | 0.62 | 0.34 |
| Sichuan, capture day 0617 (22) | 0.48 | 0.28 |
| SLIF (204) | 0.13 | 0.05 |
| TFDD (65) | 0.84 | 0.43 |

The leaf number is low mainly because SLIF has about 24 small, partly boxed leaflets per photo. What matters for the page is the boxes it actually uses: on the centre square, score ≥ 0.35 and longer side ≥ 15 % of the square.

| At the page's settings | Boxes used | Correct (IoU ≥ 0.5 with a labelled box) | Large labelled boxes found |
|---|---|---|---|
| All | 541 | 71 % | 24 % |
| Sichuan | 31 | 84 % | 34 % |
| TFDD | 59 | 97 % | 84 % |
| PlantDoc | 141 | 69 % | 56 % |
| SLIF | 310 | 66 % | 16 % |

"Correct" is a lower bound: on SLIF and Sichuan photos many real leaves have no box, so a box on one of them counts as wrong. Looking at SLIF test photos, the misses are mostly sub-leaf boxes (a lesion patch on a big leaf) and the odd pot rim. A box that is not a tomato leaf still has to pass the crop/type gate before anything is shown.

### Live, fake camera (`tests/live-e2e.mjs`)

**Finder off, after the field leaf classifier work: 22 of 22 close-ups match photo mode**, no flicker, first verdict in 1.0–1.4 s, 65–68 frames in 25 s, 46–111 ms per frame. The six whole-plant scenes in the same run: three right disease names (dense greenhouse plant, potted plant, stem) and three abstentions, no wrong name.

**Finder on:** before the classifier work, the close-ups also matched photo mode on 22 of 22, with about the same time to a verdict (1.0–1.4 s); on 21 of the 22 the finder sees one leaf filling the square (or nothing) and the square is analysed as before. The one exception is a cluster of four tomatoes on white: it was split into three fruits, one was confirmed healthy-like, and the label matches photo mode. With the new models this mode has so far been checked offline only (`tools/classifier/evaluate.py`: photo mode = live square on all close-ups, the scene results below); the browser run is `cd tests && node live-e2e.mjs --query detector=1`.

| Apple M2, headless Chrome, WebAssembly 1 thread | Finder off | Finder on, one leaf fills the square | Finder on, 3 leaves |
|---|---|---|---|
| Leaf finder | — | 53–61 ms (40 ms model + resize) | 58–60 ms |
| Whole frame (tomato) | 53–72 ms | 101–122 ms | 160–172 ms |
| Live cycle | ~370–380 ms | ~370–380 ms | ~380 ms |
| First confirmed label | 1.0 s | 1.0–1.2 s | 1.3–1.4 s |

The cycle barely changes on the M2 because the loop already rests at least 350 ms per cycle. A lemon leaf adds its 22 MB specialist (about 155 ms per frame). On a mid-range phone (3–5× slower WebAssembly) a three-leaf frame is about 0.5–0.9 s of work; the loop then rests as long as it worked, so a per-leaf verdict (3 agreeing frames) needs about 4–6 s.

### Whole-plant scenes

Six held-out photos (test split, never trained on) shown as the fake camera. Ground truth comes from each source's own label. **Before** is the condition model and crop/type model the page shipped with; **now** is after the [field leaf classifier](field-classifier.md) work: a tomato-leaf condition specialist and a crop/type model that both learned from field leaf crops cut out by this finder.

| Scene | Truth | Before, finder off | Before, finder on | Now, finder off | Now, finder on |
|---|---|---|---|---|---|
| Greenhouse plant (Sichuan) | viral mottling | abstain (read as cucumber leaf) | 1 leaf · abstain | abstain (cucumber leaf) | 1 leaf · **mosaic virus 99 %** ✓ |
| Greenhouse, dense (Sichuan) | viral mottling | abstain (read as citrus fruit) | 3 leaves · **late blight 72 %** ✗ | **mosaic virus 99 %** ✓ | 3 leaves · **mosaic virus 99–100 %** ✓ |
| Greenhouse fruit (Sichuan) | gray mold (not a covered class) | abstain | 1 fruit · abstain | abstain | 1 leaf · abstain |
| Field, potted plant (SLIF) | early blight | abstain (cucumber leaf) | not split · abstain | **early blight 100 %** ✓ | not split · **early blight 100 %** ✓ |
| Field, stem (SLIF) | early blight | **cucumber bacterial wilt 76 %** ✗ | 1 leaf · **leaf mold 100 %** ✗ | **early blight 100 %** ✓ | 1 leaf · **early blight 71 %** ✓ |
| Canopy (PlantDoc) | leaf mold | **citrus greening 98 %** ✗ | not split · **citrus greening 98 %** ✗ | abstain (tomato leaf, 46 %) | not split · abstain |

Confident wrong disease names: before 2 (off) and 3 (on); now **0 and 0**. Right names: before 0; now 3 (off) and 4 (on). What this shows:

- **The finder does its job where it fires.** Its crops are clean single leaflets, and with a condition model that has seen field leaves they get the right name: the first scene, which abstained on the whole square, is named only through its leaf crop.
- **Two of the three old failures were the crop gate, not the condition model.** The stem scene (read as cucumber) and the canopy (read as citrus fruit) were fixed by giving the crop/type model field tomato leaves.
- **Recall on big, obvious leaves is still limited.** The canopy and the potted plant are not split, so the whole square decides; the potted plant is now right that way, the canopy abstains.

The finder is still **off by default** (`?detector=1`). With these results it is ready to be turned on for tomato; the remaining reasons to wait are speed on slow phones (about 50 ms more per frame) and the fruit classes, which are not covered either way.

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
.venv/bin/python -I tools/detector/evaluate.py runs/detect/runs/detector/yolo26n-320/weights/best.pt data/processed/detector test
```

`export.py` writes `vision/private/cropscout-leaf-detector.onnx` (gitignored) and its SHA-256 into the metadata.
