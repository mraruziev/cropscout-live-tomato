# Live-camera end-to-end tests

`live-e2e.mjs` checks the live-camera mode of CropSCOUT Live against the photo-upload path, using a fake camera.

For each fixture it:

1. builds a still fake-camera clip with `make_fake_camera.py`. The image is centre-cropped to a square and pasted in the middle of a grey 1920x1080 frame, written as Y4M. The exact square is also saved as `<id>.square.png`.
2. starts (or reuses) `php -S` for `--root` and launches the installed Google Chrome (headless) with the clip as its camera.
3. opens `/vision/` and waits for `#model-state.ready`.
4. clicks **Live camera** and watches the live overlay for 25 s. It records the time to the first condition verdict, the final live text, frames analysed, average frame time, and every change to the overlay (flicker).
5. closes the camera, uploads `<id>.square.png` and reads the upload result.
6. prints one JSON line per fixture, then a markdown table: fixture | expected | live verdict | upload verdict | agree? | time-to-verdict | frames | avg ms | flicker count.

A live verdict **agrees** with the upload verdict when both show the same condition name, or when both abstain ("uncertain" / "no reliable match").

Frame counts and frame times come from `window.CropScoutVision.liveStats()` when the page has that hook. Without the hook, the harness estimates them from page instrumentation and marks them with `*`. Each `drawImage(video)` call counts as one frame, and frame time runs from that call to the last overlay update before the next frame.

The harness only reads from the served root. It allows only GET/HEAD requests to its own server and blocks the field-note endpoint. Generated files go to `tests/.out/`.

## Install

```sh
cd tests
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install   # uses the installed Google Chrome, no browser download
```

You also need:

- `php` on PATH
- Google Chrome installed
- a Python with `numpy` and `opencv-python`. Pass it with `--python <exe>` or `CROPSCOUT_PYTHON=<exe>`; it defaults to the repo's `.venv`, or `python3`.

## Fixtures

`fixtures.example.json` shows the format, with placeholder paths. Copy it to `fixtures.local.json` (gitignored) and put real absolute paths in it. The harness reads `fixtures.local.json` first and falls back to the example file.

Each fixture has exactly one source:

- `"path"`: one image
- `"dir"`: a folder; the first image by sorted file name is used
- `"synthetic"`: `"noise"` or `"grey"`, a frame with no crop in it

Add `"scene": "plant"` to a fixture that shows a busy scene with several leaves (a whole plant or a canopy). Photo mode is not the reference for those, because one leaf no longer fills the square, so they are left out of the agreement count and reported in the **Leaf finder** table instead: how often the frame was split into leaves, how many were found, and what each one showed.

## Run

```sh
cd tests
node live-e2e.mjs                                   # all fixtures, against this repo's vision/
node live-e2e.mjs --only tomato-leaf-septoria       # one fixture (substring of the id; comma-separate several)
node live-e2e.mjs --only user-,no-crop              # a group
node live-e2e.mjs --root <dir> --report .out/reference.md   # reference run against another copy of the site
node live-e2e.mjs --query detector=1                # with the leaf finder on (/vision/?detector=1)
node live-e2e.mjs --list                            # show resolved fixtures
node live-e2e.mjs --help                            # all options
```

`--root <dir>` serves a different site root (it must contain `vision/`). Each root gets its own port, derived from its path, so runs against two roots never share a server. Every run writes `tests/.out/last-run.md` and `tests/.out/last-run.jsonl`.

A full run of 22 fixtures takes about 11 minutes. Most of that is the fixed 25 s live window per fixture. For a quicker check, use `--live-seconds 10` or `--stop-when-stable 5000`.

Other useful options:

- `--headed`: watch the browser
- `--keep-y4m`: keep the clips, which are about 93 MB each and deleted by default
- `--keep-server`: leave `php -S` running so the next run reuses it

## Real video as the camera

`live-video.mjs` plays a real video to the live page and records what it shows over time, for a check on moving, handheld footage rather than a still fixture:

```sh
python -I make_video_camera.py farm.webm farm.y4m --side 480 --fps 10 --start 20 --seconds 60   # centre square of each frame
node live-video.mjs --clip farm.y4m --seconds 60 --url http://localhost:8080 --query detector=1 --out .out/farm
```

It writes `timeline.jsonl` (the live label, mode and every leaf's state, every `--poll-ms`) and `frames/NNNNN.png` (the camera view with its overlay, every `--shot-ms`). The page must already be served (`scripts/serve.sh`). Chrome loops the clip, so keep `--seconds` within the clip.

## Fake camera colour

Chrome reads Y4M as limited-range BT.601 4:2:0, whatever the header says. The generator encodes that way by default. `node live-e2e.mjs --calibrate` measures this with a colour-patch clip, and every fixture also reports the camera-vs-PNG colour error in the Diagnostics table. Expect well under 1 level of error per channel, apart from chroma blur at sharp colour edges.
