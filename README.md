# CropSCOUT Live

**Point your phone at a tomato leaf and see the disease screen live, with no photo upload, no app install and no server.**

Farmers shouldn't need to take a photo, upload it and wait. CropSCOUT Live runs small AI models in the web browser. It reads the camera a few times a second and shows what it sees on the camera view, such as *Tomato leaf · Early blight*. It shows a result only when it is sure.

## Demo

```bash
scripts/link-models.sh /path/to/onnx/models   # puts the model files into vision/private/
scripts/serve.sh                               # http://localhost:8080/vision/
```

On Windows (needs PHP 8 on PATH, e.g. `winget install PHP.PHP.8.4`, with `pdo_sqlite`, `sqlite3`, `gd`, `mbstring` and `zip` enabled in `php.ini`):

```bat
scripts\install-models.cmd C:\path\to\onnx\models   REM copies the models and checks their SHA-256 against the metadata
scripts\serve.cmd                                   REM http://localhost:8080/vision/
```

1. Open `http://localhost:8080/vision/` in Chrome or Safari.
2. Press **Live camera** and hold a tomato leaf inside the square.
3. A confirmed label appears in about 1–2 seconds.
4. Press the shutter to **freeze** the frame and get the full report, with the red AI evidence map.
5. To try the **leaf finder** on a whole plant, open `http://localhost:8080/vision/?detector=1`. Each tomato leaf or fruit it finds gets its own box and its own result.

On a phone the camera needs HTTPS, so open the deployed site or tunnel your local server.

### Without PHP (static build)

The screening itself never touches the server, so the page can also run as plain files. `tools/build_static.py` writes `dist/static/` with `index.html`, the app, the ONNX runtime and the models under `models/`; the page then reads the models from there instead of `model.php`, and the field-notes panel (which needs the PHP backend) is hidden. The models behave identically.

```bash
scripts/build-static.sh --serve        # macOS/Linux: build, then serve http://localhost:8081/
scripts\build-static.cmd               # Windows: build (add --models C:\path\to\onnx if they are not in vision\private)
scripts\serve-static.cmd               # Windows: serve http://localhost:8081/
```

Any static host works for the result (the camera still needs HTTPS or localhost). Field notes and the team review page exist only in the PHP deployment.

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

Details: [docs/how-it-works.md](docs/how-it-works.md) · [docs/leaf-finder.md](docs/leaf-finder.md) · [docs/field-classifier.md](docs/field-classifier.md)

## Tech stack

| Part | What we used |
|---|---|
| Models | Ultralytics YOLO26 image classifiers (n and s sizes), a tomato-leaf specialist trained on field leaves, and a YOLO26n leaf/fruit detector, exported to ONNX |
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
| Leaf finder on, busy plant, 3 leaves checked | ~170 ms per frame | ~0.5–0.9 s per frame |

On 22 test images shown to Chrome as a fake camera, the live label matched the photo-mode result on **22 of 22** and never flickered on a steady image (finder off, with the current models; the finder-on run with them is still to do). On six held-out whole-plant photos the page now names the right disease on three or four and never a wrong one; before the field leaf classifier it named a wrong one on two or three.

Details and model-by-model numbers: [docs/benchmark.md](docs/benchmark.md)

## What it can recognise

- **Tomato leaf:** healthy, early blight, late blight, septoria leaf spot, bacterial spot, black spot, target spot, leaf mold, mosaic virus, yellow leaf curl virus and two-spotted spider mite.
- **Tomato fruit:** healthy only, for now.
- **Also:** apple, cucumber and lemon/citrus leaves and fruit.

The models were trained on public datasets: PlantVillage, PlantDoc, Fruits-360 and others, and the tomato-leaf model also on photos of leaves on the plant from CCMT (Ghana), SLIF-Tomato (Sri Lanka), a Sichuan greenhouse set and a Taiwan set, cut out by the leaf finder. All of them are listed with licences in `vision/private/dataset-provenance.json`; how the field set was built and what it changed is in [docs/field-classifier.md](docs/field-classifier.md).

## Field datasets

We looked for public tomato datasets taken **in the field**, because a live camera sees real plants, not leaves on a white table. Every claim was checked twice. The leaf finder is trained on SLIF-Tomato, the Sichuan greenhouse set, PlantDoc and TFDD (tomato fruit), all CC BY 4.0; Tomato-Village is not used.

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
- [x] Find each leaf first: a YOLO26n leaf/fruit detector at 320 px, then classify each leaf crop with the same safeguards (behind `?detector=1`; [results](docs/leaf-finder.md#results))
- [x] Retrain the condition model on field leaf crops cut out by the leaf finder (CCMT, SLIF, Sichuan, Taiwan), with the whole-plant scenes as a gate: confident wrong names on the six scenes went from 3 to 0 ([results](docs/field-classifier.md#results))
- [ ] Turn the finder on by default for tomato once it has been timed on real phones
- [ ] Test on real phones (iPhone Safari, Android Chrome) and real field videos; use our own farm videos to raise the finder's recall on big leaves
- [ ] Freeze report for the leaf being shown, not the whole square
- [ ] Tomato fruit diseases (anthracnose, blossom-end rot, cracking, late blight)
- [ ] WebGPU on Android Chrome, keeping WebAssembly as the fallback

## Repo map

| Path | What |
|---|---|
| `vision/` | The web app (camera, models, safeguards, results, field notes) |
| `docs/` | How it works, speed, dataset research, browser AI notes |
| `tests/` | Fake-camera end-to-end tests, and a real video played as the camera |
| `tools/benchmark/` | Model speed scripts |
| `tools/detector/` | Leaf finder: fetch the box datasets, build, train, export, evaluate |
| `tools/classifier/` | Field leaf classifier: fetch the field sets, cut leaves with the finder, fine-tune, export, score on real photos |
| `scripts/` | Link the models and run a local server |

*Screening support only. Confirm uncertain or severe symptoms with a local agronomist before treatment.*
