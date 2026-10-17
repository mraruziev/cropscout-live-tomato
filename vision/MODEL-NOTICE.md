# CropSCOUT Live — model and safety notice

CropSCOUT Live is a visible-symptom screening prototype. It is not a laboratory
diagnosis and must not be used as an automatic pesticide trigger.

## What it does

- A crop/type model compares the image with Apple, Tomato, Cucumber,
  Lemon/Citrus and `Other`, and tells leaf from fruit.
- A condition model runs only after a supported crop and plant part are
  established. It compares raw scores only with the covered conditions for that
  crop and plant part. Scores are never renormalised.
- Cucumber leaves use a cucumber-leaf specialist. Lemon leaves use a guarded
  hybrid: a healthy result from the general model is kept, the specialist never
  adds a new healthy claim, and a disease lead from the specialist must also pass
  a 70% confidence floor or the result abstains.
- When a condition fails a confidence, margin, family-support or
  healthy-separation safeguard, the page names the closest covered match but
  labels it **not a diagnosis** and explains why it was withheld.

## Live camera

- The camera starts only after the user selects **Live camera**, and it stops
  when the panel closes or the page goes to the background.
- Frames are analysed in browser memory and never leave the device.
- The centre square of each frame is analysed a few times a second, using the
  same 224 px preprocessing as photo mode.
- Scores are smoothed across frames, and every safeguard is applied to the
  smoothed scores. A condition is shown only after 3 of the last 4 frames pass
  every safeguard with the same answer. It is withdrawn once fewer than 2 still
  do, or at once when the crop is no longer recognised.
- **Freeze** captures the square and runs the full photo report, including the
  red AI evidence map. That report checks one frame, so it can differ slightly
  from the live label.
- On a phone, the live camera needs HTTPS. `localhost` works for development.

## AI evidence map

For a confident disease result, the red map marks the image areas whose
occlusion most changed the model score. It is a coarse 4 × 4 explanation, not a
lesion outline. Healthy, uncertain and crop-only results do not show it.

## Field notes

- Under every result, the user can say whether it matched what they saw.
- **A note never changes a screening result.**
- **Nothing retrains automatically.** Notes queue for a person on the team to
  review.
- The photo is uploaded only if the user ticks **Send this photo with my note**.
  It is then re-encoded so that camera and GPS metadata are removed.

## Coverage and known limits

- Tomato leaf covers healthy, bacterial spot, black spot, early blight, late
  blight, leaf mold, septoria leaf spot, target spot, mosaic virus,
  yellow leaf curl virus and two-spotted spider mite.
- Tomato fruit has only a healthy class, so the tool cannot name a tomato-fruit
  disease yet.
- Several tomato leaf classes were learned mostly from photos of single leaves
  on a plain background. Close-ups of one leaf work best; whole plants,
  seedlings and fruit on the vine are often not recognised.
- Validation photos come from the same public collections as the training
  photos. They are not independent farms, seasons or cameras, so judge the tool
  by real field photos.

The public datasets behind each model, and their licences, are listed in
`private/dataset-provenance.json`.
