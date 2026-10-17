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

Severity is the share of leaf pixels in the analysed square that look like lesions. It is computed on the same 224 px RGB input the models see, so it costs no extra decoding.

| Pixel class | Rule (OpenCV HSV scale: H 0–180, S and V 0–255) |
|---|---|
| green (healthy tissue) | H 35–85, S > 60, V > 50 |
| lesion (yellow, orange, brown spots) | H 5–35, S > 60, V > 40 |
| lesion (dark necrotic) | V < 60, S > 30 |
| other (background, grey, white) | everything else; ignored |

```
lesion_fraction = lesion / (green + lesion)
leaf_cover      = (green + lesion) / all pixels
```

| Band | lesion_fraction | multiplier |
|---|---|---|
| low | ≤ 10 % | 0.6 |
| medium | 10–30 % | 1.0 |
| high | ≥ 30 % | 1.4 |
| unknown | leaf_cover < 15 % | 1.0 |

Example: early blight, base 30 mL, high severity → 42 mL, which at 10 mL/s is 4.2 s of pump time.

## Spray percentage

The headline number is a percentage of the maximum dose, so it works as a pump duty setting:

```
percent = dose_ml / units.max_dose_ml × 100        (max_dose_ml = 56: the largest rule, late blight 40 mL × 1.4)
```

| Situation | Shown |
|---|---|
| nothing in the square, not a tomato, or verdict not confirmed | SPRAY 0% |
| healthy leaf, or a non-infectious disorder | SPRAY 0% |
| virus | SPRAY 0%, remove the plant |
| early blight, low severity | SPRAY 32% (18 mL) |
| early blight, high severity | SPRAY 75% (42 mL) |
| late blight, high severity | SPRAY 100% (56 mL) |

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
```

In the browser app the result card gets a **Spray estimate** section, and the live chip appends `spray 75%`, `spray 0%` or `spray 0%, remove plant` to a confirmed label.
