# Field leaf classifier

The condition model learned tomato leaves mostly from pictures of one leaf on a plain background. A phone pointed at a plant sees leaves against soil, stems and other leaves, and the [leaf finder](leaf-finder.md) cuts single leaflets out of such scenes. On those crops the old model gave confident wrong names. This page describes the field-leaf set built to fix that, the two retrained models, and what they do on real photos.

## What was wrong

Two things, found by running the page's own pipeline offline (`tools/classifier/pipeline.py`) on held-out field photos:

1. **The tomato condition classes were learned from mislabelled crops.** Five tomato classes (early blight, late blight, leaf mold, bacterial spot, target spot) and part of healthy came only from box crops of the Bangladesh tomato leaf set, whose class IDs are not named in the data and had been inferred. Looked at by eye, its "late blight" crops are whole healthy-looking field leaves and its "healthy" crops are lesion close-ups. So a clean field leaflet read as *late blight* and a lesion as *healthy*. These crops are left out of the retrained model, except black spot, which they were right about.
2. **The crop/type gate did not know field tomato leaves.** Its tomato leaves came from plain backgrounds, while its cucumber and lemon leaves included field photos, so a tomato leaf with soil behind it was read as *cucumber leaf* or *citrus*. Two of the three confident wrong names on the whole-plant scenes came from this gate, not from the condition model.

## Field leaf set

Built by `tools/classifier/build_dataset.py` from four public sets that allow commercial use (all CC BY 4.0). Every photo gives its centre square (what photo mode and a whole-square live frame see) and every leaf the leaf finder cuts out of it at the page's settings (score ≥ 0.35, longer side ≥ 15 % of the square, padding 1.15). Photos are first shown at the camera's 1080 px, so each crop has the resolution the page would give it.

| Source | What we used | Photos | Squares | Leaf crops |
|---|---|---|---|---|
| [CCMT](https://data.mendeley.com/datasets/bwh3zbpkpv/1) (Ghana, leaves on the plant) | raw `healthy` and `septoria leaf spot` folders | 2,699 | 2,699 | 3,117 |
| [SLIF-Tomato](https://www.kaggle.com/datasets/romiyalgeorge/slif-tomato-dataset) (Sri Lanka, field) | the 890 full-resolution raw photos: early blight, mosaic, healthy, late blight, bacterial spot, septoria | 818 | 818 | 1,856 |
| [Sichuan greenhouse](https://data.mendeley.com/datasets/c2x8rynybg/1) | `Viral` photos → mosaic virus; a leaf crop counts only where it matches one of the set's own `Viral_Leaf` boxes | 318 | 318 | 1,174 |
| [Taiwan tomato leaves](https://data.mendeley.com/datasets/ngdgg79rzb/1) | originals: healthy, bacterial spot, late blight (227 px) | 314 | 314 | 466 |

4,149 photos, 10,762 images. What was left out, and why:

- CCMT *leaf blight* (early or late, the authors do not say), *leaf curl* (a mix of spotted, necrotic and curled leaves, not a clean yellow leaf curl virus) and *verticillium wilt*: no matching class.
- SLIF *powdery mildew* and *wilt*, Taiwan *black mold* (Pseudocercospora, not leaf mold), *gray spot* and *powdery mildew*: no matching class.
- The Netrokona set and the Daffodil set, both described as field photos: looked at, every image is a detached leaf on white card. They would have taught the plain-background shortcut again.
- The AIUB Bangladesh box crops: see above.

**Dedupe and split.** 451 byte-identical files and 60 near-duplicate photos with conflicting labels were dropped; near-duplicates (64-bit perceptual hash within 6 bits) share a group. Two SLIF photos that match a test fixture were dropped. Splits are by group, never by file: SLIF by base photo (the same split as the leaf finder's), Sichuan by capture day (0617, the day of the whole-plant fixtures, is test), CCMT and Taiwan by a hash of the group, about 80/12/8. Test: 324 photos, 762 images, never trained on.

**Close-ups.** So that the five classes which lost their box crops still have correctly labelled close-ups, 1,389 PlantVillage tomato leaves were added (one image per leaf, split by leaf ID): early blight, late blight, bacterial spot, leaf mold, target spot.

## Training

Both models are fine-tuned from the shipped checkpoints with `tools/classifier/train.py` (YOLO26n, 224 px, batch 64, AdamW with a cosine schedule, `cache=False`, Apple M2). Every epoch is saved and the one to ship is chosen on real photos with `tools/classifier/evaluate.py`, not on validation accuracy: the validation split comes from the same sources as training and cannot see a label problem.

- **Tomato-leaf specialist.** The general condition model's training set, minus the AIUB crops, plus the PlantVillage close-ups and up to 1,000 field images per tomato class (rare classes listed twice): 25,967 images. 10 epochs, lr 2·10⁻⁴, 38 minutes. Epoch 8 shipped. It has the same 46-class output as the general model and is installed as a **specialist for tomato leaves** (`condition_specialists` in `model-metadata.json`, served as `model.php?model=tomato-leaf`), so every other crop keeps the general model unchanged. It loads with the base models rather than on first use.
- **Crop/type model.** Its training set plus 800 field tomato images as `Tomato_leaf`, with the other crops' field leaves (PlantDoc, the cucumber orchard set, the lemon field sets) listed twice: a first attempt without that repetition taught "leaf on a plant, soil behind" as the tomato cue and sent a cucumber seedling and a citrus cluster to tomato. 17,295 images, 5 epochs, lr 10⁻⁴. The last epoch shipped.

```bash
.venv/bin/python -I tools/classifier/fetch_ccmt.py data/raw/ccmt          # 0.3 GB of the 8.4 GB release, by HTTP range requests
.venv/bin/python -I tools/classifier/fetch_slif_raw.py data/raw/slif      # 2.6 GB, the raw photos only
.venv/bin/python -I tools/classifier/fetch_taiwan.py data/raw/taiwan      # 48 MB (needs py7zr)
.venv/bin/python -I tools/classifier/fetch_plantvillage.py data/raw/plantvillage
.venv/bin/python -I tools/classifier/build_dataset.py data/raw data/processed/classifier
.venv/bin/python -I tools/classifier/assemble.py condition <general condition training set> data/processed/condition-ft
.venv/bin/python -I tools/classifier/assemble.py crop-view <crop/type training set> data/processed/crop-view-ft
.venv/bin/python tools/classifier/train.py <condition checkpoint> data/processed/condition-ft condition-field 10 2e-4
.venv/bin/python tools/classifier/train.py <crop/type checkpoint> data/processed/crop-view-ft crop-view-field 5 1e-4
.venv/bin/python -I tools/classifier/evaluate.py --tomato-leaf <candidate.onnx> --user-manifest <photos.json>
.venv/bin/python -I tools/classifier/export.py <best.pt> out.onnx tomato-leaf --install
.venv/bin/python -I tools/classifier/export.py <best.pt> out.onnx crop-view --install
```

`export.py` checks the class order against the metadata, that onnxruntime matches PyTorch, writes the ONNX (static 1×3×224×224, softmax inside, opset 18) into `vision/private/` and its SHA-256 into the metadata.

## Results

All numbers come from the page's own gates (crop gate, four safeguards), run offline on real photos. A result is **wrong** when a disease the photo does not have is named, **missed** when a diseased leaf is called healthy-like, and the rate is over results that were actually shown.

### Held-out field leaves (762 images from 324 photos, never trained on)

| | Shown | Right | Wrong or missed | Abstained |
|---|---|---|---|---|
| Before | 237 | 83 | 154 (**65 %**) | 525 |
| Tomato-leaf specialist, old crop gate | 544 | 450 | 94 (17 %) | 218 |
| Both new models | 725 | 681 | 44 (**6 %**) | 37 |

By class with both new models: healthy 97/99 right and 0 wrong, bacterial spot 18/20, septoria 384/418 (5 % wrong), mosaic virus 78/91 (9 %), early blight 74/94 (13 %), late blight 30/40 (17 %). The remaining mistakes are mostly SLIF leaflets: early blight read as mosaic virus or late blight, and the reverse. CCMT, Sichuan and Taiwan leaves are 0–6 % wrong.

### Whole-plant scenes (six held-out photos, as the fake camera)

See [leaf-finder.md](leaf-finder.md#whole-plant-scenes). Confident wrong disease names: before, 2 with the finder off and 3 with it on; now **0 and 0**. Four of the six scenes get the right disease with the finder on (the two others are gray mold, which is not a covered class, and a web photo of a canopy, which abstains).

### The team's own photos (24 real photos: apple, tomato, cucumber, lemon)

- No new wrong disease name. The two tomato septoria photos go from 55 % and 89 % to 100 %; the tomato leaf with field discolouration still abstains.
- Crop identity: 16 right, 7 wrong, 1 abstain (before: 17, 6, 1). The one that changed is a lemon leaf with pest damage, now read as *apple leaf* and abstaining, where before it was called *lemon leaf: nutrient deficiency*, a verdict nobody had verified. The six photos that were wrong before stay wrong: they are fruit on the plant, which the crop/type model has never seen in the field, and the unsupported-leaf photo.
- The 22 close-up fixtures: photo mode and the live square agree on all of them.

### In the browser

`tests/live-e2e.mjs`, fake camera, 25 s per fixture, Apple M2, headless Chrome, finder off: **22 of 22** close-ups match photo mode, no flicker, first verdict in 1.0–1.4 s, 46–111 ms per frame; the six scenes give three right names and three abstentions. The same run with the finder on (`--query detector=1`) has not been done yet with the new models; offline, photo mode and the live square agree on all close-ups and the scenes are as in [leaf-finder.md](leaf-finder.md#whole-plant-scenes).

### Real video

`tests/live-video.mjs` plays a real video to the page as its camera. With the old models, a four-minute public-domain news clip of a tomato farm (people, rows of plants, crates of fruit, a few close-ups) gave a verdict for 8 s of 244 s: *citrus canker* on crates of tomatoes four times, and *tomato fruit, healthy-like* on a crate. The run with the new models, and runs on a handheld-style pan over held-out field photos, are the next step (the clips are built; see the hand-over note).

## Known gaps

- Tomato **fruit** is untouched: one healthy class, and field fruit often reads as citrus. It needs fruit disease data and field fruit identity data.
- Early blight versus late blight versus mosaic on SLIF leaflets is still the weakest spot; SLIF has 13 late blight and 120 mosaic scenes in total.
- The crop/type model is a little less sure of lemon leaves (one of the team's photos moved). A field lemon-leaf set in the same mix would balance that.
- Leaf mold and target spot have no field examples at all; they rest on PlantVillage close-ups.
