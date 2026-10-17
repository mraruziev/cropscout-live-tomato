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
  │  tomato → general model (YOLO26n, 46 classes, only tomato classes are compared)
  │  cucumber leaf → specialist · lemon leaf → guarded hybrid
  │  smoothed over frames; 4 safeguards (confidence, margin, family support, healthy separation)
  ▼
vote: show a verdict when 3 of the last 4 frames agree · hold it while 2 of 4 still do
  ▼
live label on the camera view · "Freeze" → full photo report with the AI evidence map
```

## Models

| Model | Architecture | Input | Output | Size |
|---|---|---|---|---|
| Crop / type | YOLO26n classifier | 1×3×224×224, RGB, 0–1 | 9 class scores (softmax inside the model) | 6 MB |
| General condition | YOLO26n classifier | same | 46 class scores | 6 MB |
| Cucumber-leaf specialist | YOLO26s classifier | same | 54 class scores | 22 MB |
| Lemon-leaf specialist | YOLO26s classifier | same | 20 class scores | 22 MB |

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
| `vision/vendor/` | onnxruntime-web (WebAssembly build) |

## Test hook

`window.CropScoutVision.liveStats()` returns the live loop's state:
- frames analysed
- average milliseconds per frame
- the label currently shown
- the verdict being held

The end-to-end tests in `tests/` use it, and it also works for checks on a real phone.
