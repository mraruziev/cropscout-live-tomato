# Speed and accuracy checks

All numbers below were measured on an Apple M2 Mac (16 GB). Phone numbers are estimates until they are measured on real devices.

## End-to-end: live camera vs photo mode

`tests/live-e2e.mjs` shows each test image to Chrome as a fake 1080p camera for 25 s, then uploads the same image in photo mode. The test set has 22 images: real phone photos, one PlantVillage example per tomato class, and two images with no crop.

| | Fixed-wait loop (850 ms between frames) | Adaptive loop (current) |
|---|---|---|
| Live result agrees with photo mode | 22 / 22 | **22 / 22** |
| Frames analysed in 25 s | 27 | **67** |
| Time to first confirmed verdict | 1.3 s | **1.0 s** |
| Label changes on a steady image (flicker) | 0 | **0** |

"Agrees" means the same condition name is shown, or both modes decline to give a result.

## One live frame (headless Chrome, M2)

| Step | Time |
|---|---|
| Centre square → halved to 540 px (browser) → 224 px (JavaScript antialiased resize) | ~20 ms |
| Crop / type + condition model + safeguards (tomato) | ~50 ms |
| **Whole tomato frame** | **~74 ms** |
| Whole lemon-leaf frame (base + specialist model) | ~115 ms |

### Why 540 px and not 448 px

We measured the crop/type score for the same image fed through each live shrink size and through photo mode:

| Image | Photo mode | Full 1080 px | 1024 px | **540 px (2:1)** | 448 px |
|---|---|---|---|---|---|
| Early blight leaf | no reliable crop | Other 51.7 % | Other 54.8 % | **Other 53.0 %** | Tomato leaf 65.1 % ❌ |
| Late blight leaf | 54 % | 54.1 % | 51.3 % | **52.0 %** | 62.5 % ❌ |
| Healthy leaf | 91 % | 90.6 % | 87.7 % | **88.3 %** | 87.4 % |
| Septoria leaf (phone photo) | 100 % | 100 % | 100 % | **100 %** | 100 % |
| Shrink time | — | ~42 ms | ~41 ms | **~19 ms** | ~12 ms |

At 448 px, two leaves crossed the 60 % crop gate that photo mode keeps them under, and one of them then showed a disease that photo mode withholds. Exact 2:1 halving keeps live mode within about 1–3 points of photo mode, at less than half the cost of resizing from full size.

## Models

Each number is the median of 50 runs after 5 warm-up runs, one 224×224 image at a time.

| Model | Params | CPU, 1 thread (onnxruntime) | CPU, 4 threads | WebAssembly, 1 thread (onnxruntime-web 1.29) |
|---|---|---|---|---|
| Crop / type (YOLO26n) | 1.54 M | 6.4 ms | 2.3 ms | 13.7 ms |
| General condition (YOLO26n) | 1.58 M | 6.3 ms | 2.4 ms | 14.6 ms |
| Cucumber-leaf specialist (YOLO26s) | 5.50 M | 20.1 ms | 7.3 ms | 46.0 ms |
| Lemon-leaf specialist (YOLO26s) | 5.46 M | 20.4 ms | 7.4 ms | 46.3 ms |

- The page runs WebAssembly with 1 thread.
- Browsers allow more threads only with cross-origin isolation headers, and threaded WebAssembly is unreliable on iPhone.

## Phone estimate

A mid-range phone runs WebAssembly roughly 3–5× slower than the M2.

| | Work per frame | Cycle (≥ 350 ms, work ≤ half) | Live updates per second |
|---|---|---|---|
| Tomato | 220–370 ms | 440–740 ms | ~1.3–2.2 |
| Lemon leaf | 350–580 ms | 700–1160 ms | ~0.9–1.4 |

A verdict needs 3 agreeing frames, so the first confirmed tomato label should appear about 1.5–2.5 s after a leaf fills the square.

## Rerun

```bash
cd tests && PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install && node live-e2e.mjs
```

```bash
python3 -m venv .venv && .venv/bin/pip install onnxruntime onnx numpy
.venv/bin/python tools/benchmark/bench.py vision/private
```

```bash
npm install onnxruntime-web@1.29.0
node tools/benchmark/bench-web.mjs ./node_modules/onnxruntime-web/dist/ort.wasm.bundle.min.mjs vision/private 1
```
