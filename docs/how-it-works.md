# How CropSCOUT Live works

Everything runs in the browser. Camera frames are analysed in memory and never leave the phone.

## Pipeline

```
camera (getUserMedia, back camera, 1080p)
  │  requestVideoFrameCallback → a fresh frame each cycle
  ▼
centre square ──► halved 2:1 by the browser (1080 → 540 px) ──► 224 px (antialiased bilinear, same as photo mode)
  ▼
crop/type model (YOLO26n classifier, 9 classes)
  │  smoothed over frames; needs ≥ 60 % confidence and ≥ 10 % margin, and not "Other"
  ▼
condition model for that crop and plant part
  │  tomato leaf → tomato-leaf specialist (YOLO26n, trained on field leaves too)
  │  tomato fruit, apple, cucumber fruit, lemon fruit → general model (YOLO26n, 46 classes)
  │  cucumber leaf → specialist · lemon leaf → guarded hybrid
  │  only the classes of that crop and plant part are compared
  │  smoothed over frames; 4 safeguards (confidence, margin, family support, healthy separation)
  ▼
vote: show a verdict when 3 of the last 4 frames agree · hold it while 2 of 4 still do
  ▼
live label on the camera view · "Freeze" → full photo report with the AI evidence map
```

With the optional **leaf finder** (`/vision/?detector=1`), a YOLO26n detector first looks for tomato leaves and fruit in the square. When several smaller leaves are found, each one is cut out and runs through the same steps as its own track, with its own smoothing and votes. When one leaf fills the square, or nothing is found, the square is analysed as above. Details: [leaf-finder.md](leaf-finder.md).

## Models

| Model | Architecture | Input | Output | Size |
|---|---|---|---|---|
| Crop / type | YOLO26n classifier | 1×3×224×224, RGB, 0–1 | 9 class scores (softmax inside the model) | 6 MB |
| General condition | YOLO26n classifier | same | 46 class scores | 6 MB |
| Tomato-leaf specialist | YOLO26n classifier | same | the same 46 class scores; only the tomato-leaf ones are compared | 6 MB |
| Cucumber-leaf specialist | YOLO26s classifier | same | 54 class scores | 22 MB |
| Lemon-leaf specialist | YOLO26s classifier | same | 20 class scores | 22 MB |
| Leaf finder (optional) | YOLO26n detector | 1×3×320×320, RGB, 0–1 | 1×300×6 boxes: x1, y1, x2, y2, score, class (no NMS step) | 10 MB |

- The models were trained with Ultralytics and exported to ONNX.
- They run with onnxruntime-web (WebAssembly, 1 thread), so the same code works on iPhone and Android.
- Before a model is used, the page checks its SHA-256 against `vision/private/model-metadata.json`.

## Safety rules

- **The crop comes first.** If the crop/type model is not sure, or says "Other", no disease is shown.
- **Raw scores only.** Condition scores are compared only within the detected crop and plant part, and they are never renormalised.
- **Four safeguards** must all pass: confidence ≥ 55 %, a lead of ≥ 10 % over the next condition, ≥ 35 % total support for that crop and plant part, and ≥ 8 % separation between healthy and disease.
- **Smoothing never lowers a threshold.** Scores are averaged over frames (62 % new frame, 38 % history), and the same safeguards are then applied to the averaged scores.
- **Voting only decides what is shown.**
  - A verdict appears after 3 of the last 4 frames pass every safeguard with the same answer.
  - It is withdrawn once fewer than 2 do.
  - It is cleared at once if the crop is lost or changes.
- **With the leaf finder, all of this runs per leaf.** Each leaf has its own smoothing and votes. A frame where the finder misses a leaf counts as a failed frame for that leaf (it can withdraw a verdict, never confirm one), and the finder never changes a score or a threshold.
- **Field notes never change a result**, and nothing retrains automatically.

## Why halving

- The live frame must look like the photo-mode input, or the scores drift.
- One large browser downscale is not equivalent: going straight from 1080 to 448 px moved crop scores by more than 10 points on test images, and once pushed a leaf past the 60% crop gate.
- An exact 2:1 step averages 2×2 pixels. 1080 → 540 → 224 stays within about 1–3 points of photo mode, and costs less than half as much as resizing from full size.

## Live loop timing

- Each cycle analyses one frame, then rests for at least as long as it worked.
- The minimum cycle is 350 ms. Model work therefore never takes more than half the main thread, and the page stays responsive on slow phones.
- The rest is capped at 1 s, so one slow frame cannot freeze the loop.
- It then waits for the camera's next new frame, so the same frame is never analysed twice.
- The tomato-leaf specialist (6 MB) loads with the base models, because tomato leaves are the main use.
- The cucumber and lemon specialists (22 MB each) download in the background the first time that crop is seen. Until they are ready, the label says it is loading the condition model; the camera and the crop check keep running.
- If the page goes to the background, the camera stops.

## Files

| Path | What |
|---|---|
| `vision/index.php` | Page markup, camera panel, result card |
| `vision/app.js` | Everything in the browser: models, preprocessing, safeguards, live loop, field notes |
| `vision/styles.css` | Styles |
| `vision/model.php` | Serves the models and metadata from `vision/private/` |
| `vision/feedback.php`, `vision/lib/feedback.php` | Saves field notes (SQLite) |
| `vision/private/model-metadata.json` | Class lists, thresholds, model hashes, advice text |
| `vision/private/dataset-provenance.json` | Datasets and licences behind each model |
| `tools/detector/` | Build the leaf finder's box dataset, train it and export it ([leaf-finder.md](leaf-finder.md)) |
| `tools/classifier/` | Build the field leaf set, fine-tune the tomato-leaf and crop/type models, export them, score them on real photos ([field-classifier.md](field-classifier.md)) |
| `vision/vendor/` | onnxruntime-web (WebAssembly build) |
| `tools/build_static.py`, `tools/serve_static.py` | The PHP-free copy of the page in `dist/static/` (models as plain files, no field notes) and a local server for it |
| `scripts/` | Fetch the models from the repo's `models` branch, link or install them, run the PHP server or build and serve the static copy (macOS/Linux and Windows) |
| `.github/workflows/pages.yml` | Builds the static copy on every push to `main` and publishes it to GitHub Pages |

## Test hook

`window.CropScoutVision.liveStats()` returns the live loop's state:
- frames analysed
- average milliseconds per frame
- the label currently shown
- the verdict being held
- with the leaf finder: `mode` (`square` or `leaves`), average detector milliseconds, and each leaf's box, state and shown verdict

The end-to-end tests in `tests/` use it, and it also works for checks on a real phone.
