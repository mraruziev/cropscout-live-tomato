# CropSCOUT Live

**Point your phone at a tomato leaf and see the disease screen live, with no photo upload, no app install and no server.**

Farmers shouldn't need to take a photo, upload it and wait. CropSCOUT Live runs small AI models in the web browser. It reads the camera a few times a second and shows what it sees on the camera view, such as *Tomato leaf · Early blight*. It shows a result only when it is sure.

## Demo

```bash
scripts/link-models.sh /path/to/onnx/models   # puts the model files into vision/private/
scripts/serve.sh                               # http://localhost:8080/vision/
```

1. Open `http://localhost:8080/vision/` in Chrome or Safari.
2. Press **Live camera** and hold a tomato leaf inside the square.
3. A confirmed label appears in about 1–2 seconds.
4. Press the shutter to **freeze** the frame and get the full report, with the red AI evidence map.
5. To try the **leaf finder** on a whole plant, open `http://localhost:8080/vision/?detector=1`. Each tomato leaf or fruit it finds gets its own box and its own result.

On a phone the camera needs HTTPS, so open the deployed site or tunnel your local server.

## How it works

```
camera ─► centre square ─► 224 px ─► crop/type model ─► condition model ─► 4 safeguards ─► vote over frames ─► live label
```

1. **Crop first.** A YOLO26n classifier decides whether the square shows a tomato leaf, a tomato fruit, another supported crop, or something else. If it isn't sure, no disease is shown.
2. **Then the condition.** The condition model compares only the classes for that crop and plant part.
3. **Four safeguards** must pass: confidence, a lead over the next condition, total support for the crop, and healthy-vs-disease separation.
4. **Steady label.**
   - Scores are averaged over frames.
   - A verdict appears only when 3 of the last 4 frames agree, and it is withdrawn once fewer than 2 still do.
   - It is cleared at once if the crop is lost.
5. **Private.** Frames are analysed in browser memory and never leave the phone.
6. **Leaf finder (optional, `?detector=1`).** A small YOLO26n detector finds each tomato leaf and fruit in a busy frame. Each one is cut out and goes through steps 1–4 on its own, with its own smoothing and votes. When one leaf fills the square, the square is analysed exactly as above.

Details: [docs/how-it-works.md](docs/how-it-works.md) · [docs/leaf-finder.md](docs/leaf-finder.md)

## Tech stack

| Part | What we used |
|---|---|
| Models | Ultralytics YOLO26 image classifiers (n and s sizes) and a YOLO26n leaf/fruit detector, exported to ONNX |
| In-browser AI | onnxruntime-web 1.29, WebAssembly, 1 thread (works on iPhone and Android) |
| Camera | `getUserMedia`, `requestVideoFrameCallback`, a centre-square crop |
| Web | Plain JavaScript (ES modules), HTML/CSS, a small PHP backend that serves the models and stores field notes (SQLite) |
| Tests | Playwright + Chrome with a fake camera made from real photos |

## Speed and accuracy

| | Apple M2, Chrome | Mid-range phone (estimate) |
|---|---|---|
| One live tomato frame | ~74 ms | ~220–370 ms |
| Live updates | ~2.7 per second | ~1.3–2.2 per second |
| First confirmed label | 1.0 s | ~1.5–2.5 s |

On 22 test images shown to Chrome as a fake camera, the live label matched the photo-mode result on **22 of 22**, and it never flickered on a steady image.

Details and model-by-model numbers: [docs/benchmark.md](docs/benchmark.md)

## What it can recognise

- **Tomato leaf:** healthy, early blight, late blight, septoria leaf spot, bacterial spot, black spot, target spot, leaf mold, mosaic virus, yellow leaf curl virus and two-spotted spider mite.
- **Tomato fruit:** healthy only, for now.
- **Also:** apple, cucumber and lemon/citrus leaves and fruit.

The models were trained on public datasets: PlantVillage, PlantDoc, the Tomato Leaf Dataset (Bangladesh), Fruits-360 and others. All of them are listed with licences in `vision/private/dataset-provenance.json`.

## Datasets for the next step

We looked for public tomato datasets taken **in the field**, because a live camera sees real plants, not leaves on a white table. Every claim was checked twice.

| Dataset | What it has | Photos | Commercial use | Fit for live camera |
|---|---|---|---|---|
| [SLIF-Tomato](https://www.kaggle.com/datasets/romiyalgeorge/slif-tomato-dataset) (Sri Lanka) | Boxes + labels, phone photos in fields | ~613 scenes | Yes (CC BY 4.0) | Good |
| [Sichuan greenhouse](https://data.mendeley.com/datasets/c2x8rynybg/1) | Boxes on leaf, fruit and stem, 0.2–2 m away | 1,026 | Yes (CC BY 4.0) | Good |
| [CCMT Ghana](https://data.mendeley.com/datasets/bwh3zbpkpv/1) (tomato part) | Labels, leaves on the plant | ~5,350 | Yes (CC BY 4.0) | Good for the classifier |
| [Tomato-Village](https://github.com/mamta-joshi-gehlot/Tomato-Village) (India) | Boxes, field | 1,796 | **No license** | Blocked |
| [PlantDoc](https://github.com/pratikkayal/PlantDoc-Object-Detection-Dataset) | Boxes, web photos | 746 | Unclear | Already used |
| [Atma Jaya (Roboflow)](https://universe.roboflow.com/universitas-atma-jaya/tomato-leaf-disease-rxcft) | Boxes, mixed sources (includes potato) | ≤8,439 | Unclear | Poor |

**Takeaway:** no big public dataset of field tomato photos with boxes exists; all of them together add up to about 3,000–4,000 unique photos. The most valuable data will be our own short videos from real farms. Full notes are in [docs/datasets.md](docs/datasets.md).

## Roadmap

- [x] Live camera screening in the browser, with safeguards and frame voting
- [x] Fake-camera end-to-end tests
- [ ] Test on real phones (iPhone Safari, Android Chrome) and real field videos
- [ ] Find each leaf first: a small YOLO26n leaf/fruit detector at 320 px, then classify each leaf crop with the same safeguards
- [ ] Tomato fruit diseases (anthracnose, blossom-end rot, cracking, late blight)
- [ ] WebGPU on Android Chrome, keeping WebAssembly as the fallback

## Repo map

| Path | What |
|---|---|
| `vision/` | The web app (camera, models, safeguards, results, field notes) |
| `docs/` | How it works, speed, dataset research, browser AI notes |
| `tests/` | Fake-camera end-to-end tests |
| `tools/benchmark/` | Model speed scripts |
| `tools/detector/` | Leaf finder: fetch the box datasets, build, train, export, evaluate |
| `scripts/` | Link the models and run a local server |

*Screening support only. Confirm uncertain or severe symptoms with a local agronomist before treatment.*
