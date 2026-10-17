# Spray estimate

**Question it answers:** once CropSCOUT is sure about the condition of a tomato leaf or fruit, how much should we spray on that plant? If the leaf is healthy, nothing.

Both the browser app (`vision/spray.js`) and the local Python demo (`live/spray.py`) implement the same logic and read the same rules file, `vision/spray-rules.json`.

## Decision

```
verdict passed every safeguard?  ──no──►  wait      (no spray: result not confirmed)
        │ yes
rule for the label (spray-rules.json)
        ├─ healthy / not an infection ──►  none      (no spray)
        ├─ virus ──────────────────────►  remove    (no spray; remove the plant)
        └─ fungal / bacterial / mite ──►  spray     dose = dose_ml × severity multiplier
                                                    pump seconds = dose ÷ pump_ml_per_second
```

- **Only confirmed verdicts spray.** The estimate uses the same four safeguards (confidence, margin, family support, healthy separation) and, live, the same frame voting as the label itself. An uncertain lead never produces a dose.
- **Healthy = 0 mL.** Blossom end rot, catfacing and fruit cracking are also 0 mL: they are not infections, so spraying does not help.
- **Viruses = 0 mL, remove.** Yellow leaf curl, mosaic and spotted wilt cannot be cured by spraying; the rule says to remove the plant and deal with the insect vector separately.
- **Everything else** gets the product class from the rule (protectant fungicide, copper bactericide, oil or miticide) and a base dose that is scaled by severity.

## Severity

Severity is the share of leaf pixels in the analysed square that look like lesions. It is computed on the same 224 px RGB input the models see, so it costs no extra decoding, and it was calibrated on the labelled field leaves in `data/processed/classifier` (see below).

| Pixel class | Rule (OpenCV HSV scale: H 0–180, S and V 0–255) |
|---|---|
| green (leaf tissue) | H 35–85, S > 40, V > 50 — shaded dark green counts as leaf |
| brown (yellow, orange, brown spots) | H 5–35, S > 60, V > 30 |
| brown (dark necrotic) | 20 ≤ V < 85, S > 30, hue brown or red (H < 35 or H > 150) |
| other (background, grey, white, sky, deep shadow) | everything else; ignored |

A brown pixel is a **lesion only if it lies next to leaf tissue**: within 8 % of the square's side of a green pixel, grown once so a large patch bordered by green still counts in full. Soil, pots and bark away from any leaf no longer count. Thresholds live in `spray-rules.json` under `severity.colour` and `severity.adjacency_radius`, and both implementations read them from there.

```
lesion_fraction = lesion / (green + lesion)
leaf_cover      = (green + lesion) / all pixels      (below 8 % → severity unknown, base dose)
```

The dose factor is continuous, not stepped:

```
multiplier = 0.5 + (1.5 − 0.5) × clamp(lesion_fraction / 0.40, 0, 1)
```

So a confirmed disease on a leaf with almost no visible lesion area gets half the base dose, and the full 1.5× from 40 % lesion area upwards. The words *low / medium / high* (≤ 10 %, 10–30 %, ≥ 30 %) are only used for display. Live, the lesion fraction is averaged over frames with the same 62 % / 38 % weight as the model scores, and losing the leaf keeps the last value instead of pulling it to zero.

### Calibration

`live/eval_severity.py` runs the estimate over the labelled field leaves and reports, per class, the distribution of the lesion fraction and how well it separates healthy from diseased leaves (AUC). The thresholds above were chosen with a sweep on the `val` split; `test` was looked at once afterwards.

| | before | after |
|---|---|---|
| healthy vs lesion-disease AUC (val) | 0.73 | 0.87 |
| healthy leaves scored above 10 % lesion area | 39 % | 19 % |
| leaves unmeasurable (too little leaf found) | — | 2 % |

Two failure modes were fixed: dark green shadows and veins on healthy leaves were counted as lesions, and brown soil around the leaf was counted as lesions. Mosaic virus separates poorly (it mottles rather than spots), which does not matter: a virus never gets a dose.

**Limits.** Grey dead tissue (late blight) and sun-bleached patches are not counted. In the Python demo press `m` to see the mask (red = lesion, green = leaf).

## Spray percentage

The headline number is a percentage of the maximum dose, so it works as a pump duty setting:

```
percent = dose_ml / units.max_dose_ml × 100        (max_dose_ml = 60: the largest rule, late blight 40 mL × 1.5)
```

| Situation | Shown |
|---|---|
| nothing in the square, not a tomato, or verdict not confirmed | SPRAY 0% |
| healthy leaf, or a non-infectious disorder | SPRAY 0% |
| virus | SPRAY 0%, remove the plant |
| early blight, 5 % lesion area | SPRAY 31% (18.8 mL) |
| early blight, 20 % lesion area | SPRAY 50% (30 mL) |
| early blight, 40 % or more | SPRAY 75% (45 mL) |
| late blight, 40 % or more | SPRAY 100% (60 mL) |

The live demo always shows this line at the bottom of the window. In the browser app the camera view has a **SPRAY** readout (bottom-left, always visible while the camera runs): `SPRAY 0%` with the reason while nothing is confirmed, then the percentage with the dose and pump time once the label is held by the frame vote. With the leaf finder on, it follows the leaf that needs the most spray. The result card repeats it in a Spray estimate section, and the live label appends `spray 75%`.

**Limits.** Soil, bark, pots and dry stems are also brown, so fill the square with the leaf. In the Python demo press `m` to see the mask (red = lesion-like, green = healthy) and check what is being counted. Shadows on a leaf can count as dark necrotic tissue.

## Rates are placeholders

The `dose_ml` numbers in `spray-rules.json` are illustrative defaults for a hand sprayer, chosen for the hackathon demo. They are **not** label rates. Before any real use:

1. Replace each `dose_ml` and `interval_days` with the registered label rate for the actual product on tomato in your region.
2. Measure your pump and set `units.pump_ml_per_second`.
3. Keep the agronomist confirmation step that the app already shows.

## Try it

```bash
.venv/bin/python live/spray_cli.py photo.jpg          # full pipeline + spray estimate for one image
.venv/bin/python live/spray_cli.py photo.jpg --show   # also shows the lesion mask
live/run.sh                                           # live: the SPRAY % line sits at the bottom of the window
.venv/bin/python -m unittest live/test_spray.py       # Python tests
node --test tests/spray.test.mjs                      # browser-module tests, same numbers
.venv/bin/python live/eval_severity.py --split val     # calibration report on the labelled field leaves (needs the datasets)
```

In the browser app the result card gets a **Spray estimate** section, and the live chip appends `spray 75%`, `spray 0%` or `spray 0%, remove plant` to a confirmed label.
