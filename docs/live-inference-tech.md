## Live tomato-disease detection in a mobile web page: research findings (Oct 16, 2026)

**Starting point:** `vision/app.js` uses onnxruntime-web **1.29.0**, the plain wasm build (`vendor/ort.wasm.bundle.min.mjs` with `ort-wasm-simd-threaded.wasm`). It sets `numThreads = 1` and `proxy = false`, and runs on the main thread. Each photo goes through two 224px classifiers (crop-view and disease, about 6 MB each, yolo26n-cls sized), plus 22 MB lemon and cucumber specialists. The page already calls `getUserMedia`. The latest ORT release is v1.31.0 (2026-10-09).

### 1. WebGPU execution provider status
- **How to enable:** import `onnxruntime-web/webgpu` (or load `ort.webgpu.min.js`) and pass `executionProviders: ['webgpu']`, keeping `'wasm'` as the fallback. Useful extras:
  - `enableGraphCapture`, which needs static shapes and every kernel running on WebGPU.
  - `preferredOutputLocation: 'gpu-buffer'` and `Tensor.fromGpuBuffer` to keep data on the GPU.
  - `env.webgpu.profiling` for timing.
- **Android Chrome:** on by default since Chrome 121 on Android 12+ with ARM, Qualcomm or Intel GPUs. Imagination GPUs on Android 16+ are supported since Chrome 139. Samsung Xclipse and other GPUs are still TBD, so a wasm fallback is required.
- **iOS Safari:** WebGPU is on by default in iOS/iPadOS 26. **For onnxruntime-web on iOS it is risky right now.** I'm basing this on bug reports; I did not test on an iPhone.
  - #27584: yolo26n on WebGPU with ORT 1.24.3 crashes iOS 26.3 Safari after about 500 inferences in a camera loop. The bot closed it as stale with no fix.
  - #26827: the JSEP/asyncify builds (which WebGPU needs) peg CPU at 400%+ and grow memory to 1–14 GB on WebKit 26.2+, and iOS kills the page. A Sep 2026 comment says the native WebGPU asyncify build also fails on iPadOS 26 with 1.29.0. The plain wasm build was reported stable on 1.29.0. Again stale-closed with no fix.
  - #26480: WebGPU init failed on Safari 26.0 (`adapterInfo` undefined). A polyfill fixed it in late 2025.
  - The official README compatibility table still lists WebGPU as unsupported on Safari. It looks outdated.
- **Typical speedup for small CNNs on phones:** small. The only real phone measurement I found is yolo11n-pose at 320px on an unnamed phone: WebGPU 59 ms median (16.6 fps) against wasm 65 ms (14.8 fps). WebGPU model load was 814 ms against 238 ms for wasm.
  - Larger gains show up on bigger inputs and models. A Pixel 8 Pro running an embedding model got about 4.7x (193 ms against 902 ms).
  - A desktop "30 vs 8 fps" figure for yolov8n is anecdotal.
  - Expect 1–5 s of shader compilation on the first run (#25882).

**Recommendation:** keep the plain wasm build on iOS. Load the WebGPU bundle only on Chromium after `navigator.gpu.requestAdapter()` succeeds, and fall back to wasm otherwise.

### 2. Realistic frame rates
I found no published phone benchmarks for these exact models. The numbers below are my **estimates (unverified)**, scaled by FLOPs from the pose data point above and from Ultralytics CPU tables (yolo11n-cls at 224 = 5.0 ms CPU ONNX; yolo11n at 640 = 56.1 ms; yolo26n at 640 = 38.9 ms).

| Model | wasm, 1 thread, mid-range phone | WebGPU (Android) |
|---|---|---|
| yolo11n-cls / yolo26n-cls at 224 (about 0.4–0.5 GFLOPs) | about 20–60 ms per model | small gain |
| Your two-model pipeline at 224 | about 5–15 fps of inference | — |
| yolo11n / yolo26n detect at 320 (about 1.4–1.6 GFLOPs) | about 60–150 ms (5–15 fps), consistent with the 65 ms data point | about 1.1–2x faster |
| Detect at 640 (5.5–6.5 GFLOPs) | about 250–600 ms (2–4 fps), not usable live | perhaps 30–100 ms on a good GPU (unverified) |

You need to measure on two or three real target phones before committing.

### 3. Frame loop best practices
- **Loop driver:** use `video.requestVideoFrameCallback` (Safari/iOS 15.4+, Chrome 83+, Firefox 132+) and fall back to `requestAnimationFrame`. Re-register inside each callback.
- **Throttling:** allow one inference in flight at a time and drop frames while busy (skip-if-busy). Cap at about 4–8 Hz and adapt the interval to the measured latency.
- **Worker:** run ORT in your own Web Worker. Note that `env.wasm.proxy` does not work with WebGPU.
  - Either transfer `createImageBitmap(video)` to the worker and resize there with `OffscreenCanvas` (2D in workers from Safari 16.4 per my recollection; not checked in this research),
  - or draw a 224px crop on the main thread and transfer the pixel `ArrayBuffer`.
  - Whether WebGPU works inside workers on Safari is unverified.
- **Preprocessing must match training:** shorter-edge resize, antialiased bilinear. Canvas downscaling from 720p straight to 224 can alias, so downscale in two steps. Check live-frame results against your 16 real photos, not just validation scores.
- **Camera settings:**
  - Request `{facingMode:{ideal:'environment'}, width:{ideal:1280}, height:{ideal:720}, frameRate:{max:30}}` with no audio.
  - The `<video>` element needs `playsinline muted autoplay`. Missing `playsinline` is the classic cause of a black box on iOS.
  - Avoid `history.pushState` while streaming: WebKit bug 272704 (iOS 17.4.1) mutes the track.
  - Stop the tracks on `visibilitychange` / `pagehide`.
- **Torch:** check `track.getCapabilities().torch`, then call `applyConstraints({advanced:[{torch:true}]})`. WebKit added torch in late 2023. On iOS 18, `getSettings()` reported a stale torch value; it was fixed upstream in Dec 2024.
- **Focus:** iOS Safari apparently exposes no `focusMode` (third-party claim, unverified). Pro iPhones switch lenses on their own at close range (for example to macro), and the web cannot lock the lens (Apple forum thread, no fix). Tell users to hold the phone about 20–30 cm from the leaf.
- **Battery and heat:** iOS has no thermal API. Compute Pressure (Chrome 125+) is confirmed for CPU on desktop; Android and thermal support are unverified. So limit the work yourself:
  - Use a modest resolution and 30 fps.
  - Run inference at only a few Hz.
  - Pause when the frame is blurry, unchanged or shows no leaf.
  - Stop automatically after a period of inactivity.
- **UX that works:** run the two 224px classifiers live on a centre crop and smooth the probabilities over about 5–10 frames. Show a label only once it is stable and the frame passes sharpness and exposure checks. Then auto-capture the best frame and run the full pipeline, including the specialists, on it.
- **Threads:** COOP/COEP headers enable multi-threaded wasm. Microsoft measured MobileNetV2 3.4x faster with 2 threads plus SIMD, on a desktop. This is worth it on Android. On iOS, threaded wasm historically broke or hung ORT (#11567, #11679, both stale-closed), so keep `numThreads = 1` there unless device tests prove otherwise. COEP `require-corp` also restricts any third-party resources on the page.

### 4. Alternatives
- **LiteRT.js (`@litertjs/core`, launched July 9, 2026):** runs `.tflite` files with XNNPACK on wasm and ML Drift on WebGPU. Ultralytics can export LiteRT directly. Google claims up to 3x faster than other web runtimes, but that was measured on an M4 MacBook. It is the only option worth an A/B test on phones; iOS behaviour is unverified and the library is very new.
- **MediaPipe Tasks:** has a very fast camera pipeline (pose lite ran at 56 fps against YOLO's 16.6 fps on the same phone). Custom models need TFLite plus metadata and fit its fixed task heads, so it is only worth it if you re-target your models to it.
- **TensorFlow.js:** no advantage. It needs a PyTorch → ONNX → TF → TF.js conversion, and Google now points to LiteRT.js. I found no official maintenance-mode announcement.
- **Transformers.js:** wraps onnxruntime-web, so it adds nothing for Ultralytics models.
- **WebNN:** experimental and Chrome-only; skip it.

### 5. Ultralytics export settings for the web
- **Shapes:** use `imgsz=224` for the classifiers and 320 (or 384/416) for a live detector, with the same size at train or validation time. Set `dynamic=False` and `batch=1`. Static shapes are needed for graph capture; with dynamic shapes, use `freeDimensionOverrides`.
- **Graph:** keep `simplify=True` (onnxslim). Pin the opset (for example 17) rather than taking the latest default. One community README says opset 12 is required for WebGPU; that is unverified and probably outdated.
- **Precision:** current docs replace `half` / `int8` with `quantize=16` / `quantize=8`, which needs calibration data. Check that your installed Ultralytics version has this.
  - **wasm:** use fp32 or uint8 int8. The ORT docs say to avoid fp16 on wasm because it is slow on CPU.
  - **WebGPU:** fp16 can help where the adapter supports `shader-f16` (Chrome 121+; Safari not confirmed). Avoid int8 on WebGPU, because ConvInteger/MatMulInteger fall back to the CPU and it gets slower.
  - That means two model files per platform. A CPU fp16 export keeps fp32 inputs and outputs.
- **YOLO26 detector:** `nms=False` gives an NMS-free 1×300×6 output, so there is no NMS to write in JavaScript. COCO mAP drops slightly, from 40.9 to 40.1.
- **Re-check accuracy:** after any quantization, test accuracy again on real field photos.

**Sources:**
- ONNX Runtime docs: [WebGPU EP](https://onnxruntime.ai/docs/tutorials/web/ep-webgpu.html), [Env flags and session options](https://onnxruntime.ai/docs/tutorials/web/env-flags-and-session-options.html), [Performance diagnosis](https://onnxruntime.ai/docs/tutorials/web/performance-diagnosis.html), [README 1.30.0](https://cdn.jsdelivr.net/npm/onnxruntime-web@1.30.0/README.md)
- ONNX Runtime issues: [#27584](https://github.com/microsoft/onnxruntime/issues/27584), [#26827](https://github.com/microsoft/onnxruntime/issues/26827), [#26480](https://github.com/microsoft/onnxruntime/issues/26480), [#25882](https://github.com/microsoft/onnxruntime/issues/25882), [#11567](https://github.com/microsoft/onnxruntime/issues/11567), [#11679](https://github.com/microsoft/onnxruntime/issues/11679)
- WebGPU support: [gpuweb Implementation Status](https://github.com/gpuweb/gpuweb/wiki/Implementation-Status), [Chrome 121 WebGPU on Android](https://developer.chrome.com/blog/new-in-webgpu-121), [WebGPU in iOS 26](https://appdevelopermagazine.com/webgpu-in-ios-26/)
- Phone and benchmark data: [Rise PR #2 (phone YOLO measurement)](https://github.com/rexbel/Rise/pull/2), [Pixel 8 Pro WebGPU benchmark](https://huggingface.co/spaces/Xenova/webgpu-embedding-benchmark/discussions/31), [Dev.to WebGPU/WASM article](https://dev.to/nughes/running-ai-models-in-the-browser-practical-webgpuwasm-inference-for-production-web-apps-3gl8), [nomi30701 yolo-onnxruntime-web](https://github.com/nomi30701/yolo-object-detection-onnxruntime-web), [MS ORT Web blog (2021)](https://opensource.microsoft.com/blog/2021/09/02/onnx-runtime-web-running-your-machine-learning-model-in-browser/)
- Ultralytics: [YOLO26](https://docs.ultralytics.com/models/yolo26/), [YOLO11](https://docs.ultralytics.com/models/yolo11), [ONNX integration](https://docs.ultralytics.com/integrations/onnx/), [Export mode](https://docs.ultralytics.com/modes/export/)
- Camera and frame loop: [rVFC on web.dev](https://web.dev/articles/requestvideoframecallback-rvfc), [caniuse rVFC](https://caniuse.com/wf-request-video-frame-callback), [WebKit torch bug 280970](https://bugs.webkit.org/show_bug.cgi?id=280970), [WebKit 243075](https://bugs.webkit.org/show_bug.cgi?id=243075), [WebKit 272704](https://bugs.webkit.org/show_bug.cgi?id=272704), [iOS black-box fix](https://flaviocopes.com/webrtc-ios-black-box.md), [Apple forum lens switching](https://developer.apple.com/forums/thread/776460), [Dynamsoft focus guide](https://www.dynamsoft.com/codepool/camera-focus-control-on-web.html), [Compute Pressure](https://developer.chrome.com/docs/web-platform/compute-pressure)
- Alternatives: [LiteRT.js announcement](https://developers.googleblog.com/en/litertjs-googles-high-performance-web-ai-inference/), [LiteRT for Web docs](https://developers.google.com/edge/litert/web), [caniuse relaxed SIMD](https://caniuse.com/wf-wasm-simd-relaxed)
