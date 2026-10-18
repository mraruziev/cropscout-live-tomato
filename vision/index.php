<?php
declare(strict_types=1);

require_once __DIR__ . '/secure.php';
require_secure_vision_request();
header('Permissions-Policy: camera=(self)');
$styleHash = @hash_file('sha256', __DIR__ . '/styles.css');
$scriptHash = @hash_file('sha256', __DIR__ . '/app.js');
$styleVersion = is_string($styleHash) ? substr($styleHash, 0, 12) : '25';
$scriptVersion = is_string($scriptHash) ? substr($scriptHash, 0, 12) : '25';
header('Cache-Control: no-cache, no-store, max-age=0, must-revalidate');
?><!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <meta name="description" content="CropSCOUT Vision: the camera AI subsystem of the CropSCOUT field robot. Live tomato leaf disease screening runs in the browser, on the device, with no upload.">
    <meta name="referrer" content="same-origin">
    <meta name="theme-color" content="#0b0e0c">
    <title>CropSCOUT Vision — camera AI subsystem</title>
    <link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
    <link rel="icon" href="assets/favicon-32.png" sizes="32x32" type="image/png">
    <link rel="apple-touch-icon" href="assets/apple-touch-icon.png">
    <link rel="stylesheet" href="styles.css?v=<?= rawurlencode($styleVersion) ?>">
    <script src="app.js?v=<?= rawurlencode($scriptVersion) ?>" type="module"></script>
</head>
<body class="vision-page">
<header class="app-header">
    <a class="brand-lockup" href="/" aria-label="CropSCOUT home">
        <img class="brand-mark" src="assets/logo-mark.svg" alt="" width="44" height="44">
        <span class="brand-text">
            <span class="brand-name">Crop<span>SCOUT</span></span>
            <span class="brand-mode">Vision · camera AI</span>
        </span>
    </a>

    <div class="header-actions">
        <dl class="sys-readout" aria-label="Subsystem telemetry">
            <div><dt>Module</dt><dd>VIS-CAM 01</dd></div>
            <div><dt>Runtime</dt><dd>ORT-web · WASM · 1T</dd></div>
            <div><dt>Crop</dt><dd id="hud-crop">TOMATO</dd></div>
            <div><dt>Mode</dt><dd id="hud-mode">SQUARE</dd></div>
            <div><dt>Frames</dt><dd id="hud-frames">0</dd></div>
            <div><dt>Infer</dt><dd id="hud-ms">— ms</dd></div>
        </dl>
        <div class="model-state" id="model-state" aria-live="polite">
            <span class="state-dot" aria-hidden="true"></span>
            <span id="model-state-text">model check pending</span>
        </div>
        <a class="site-home-link" href="/">Robot home <span aria-hidden="true">↗</span></a>
    </div>
</header>

<main class="page-main">
<section class="hero" aria-labelledby="page-title">
    <div class="hero-copy">
        <p class="hero-eyebrow"><span class="rec-dot" aria-hidden="true"></span>Camera AI subsystem · live screening</p>
        <h1 id="page-title">Scout every leaf. <span class="hero-accent">Catch disease early.</span></h1>
        <p class="hero-lede">This is the vision stage of the CropSCOUT rover. The camera feed is read a few times a second, each frame goes through the crop gate, the condition model and four safeguards, and a label is shown only when several frames agree.</p>
        <div class="hero-actions">
            <button class="hero-camera-button" id="hero-camera-button" type="button">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7.5h3l1.4-2h7.2l1.4 2h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>
                Open live feed
            </button>
            <button class="hero-photo-button" id="hero-photo-button" type="button">
                <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="16" height="14" rx="2"/><path d="m4 16 4.5-4.5 3.5 3.5 2.5-2.5L20 18"/><circle cx="15.5" cy="9.5" r="1.4"/></svg>
                Analyse a still
            </button>
        </div>
        <div class="hero-coverage">
            <p class="hero-scope" id="hero-scope">Tomato focus: the gate decides leaf, fruit or neither, and the crop is taken as tomato. Switch the crop focus to ALL to let the gate also tell apple, cucumber and lemon apart.</p>
            <p class="chips-label" id="chips-label">Tomato leaf conditions</p>
            <ul class="condition-chips" aria-labelledby="chips-label">
                <li class="is-healthy">Healthy</li>
                <li>Early blight</li>
                <li>Late blight</li>
                <li>Septoria</li>
                <li>Bacterial spot</li>
                <li>Black spot</li>
                <li>Target spot</li>
                <li>Leaf mold</li>
                <li>Mosaic virus</li>
                <li>Yellow leaf curl virus</li>
                <li>Spider mite</li>
            </ul>
            <div class="hero-flags" role="group" aria-label="Pipeline options">
                <a class="hero-flag" id="crop-focus-toggle" href="?crop=all" title="Switch the crop focus">
                    <span class="flag-label">Crop focus</span>
                    <span class="flag-value" id="crop-focus-state">TOMATO</span>
                </a>
                <a class="hero-flag" id="leaf-finder-toggle" href="?detector=1" title="Turn the leaf finder on or off">
                    <span class="flag-label">Leaf finder</span>
                    <span class="flag-value" id="leaf-finder-state">OFF</span>
                </a>
            </div>
        </div>
        <p class="hero-note">Screening support, not a laboratory diagnosis or a spray recommendation. Confirm uncertain or severe symptoms with an agronomist before treating.</p>
    </div>
    <aside class="pipeline-card" aria-labelledby="pipeline-title">
        <h2 id="pipeline-title">Inference pipeline</h2>
        <ol class="pipeline">
            <li><span>01</span><strong>Sensor feed</strong><small>centre square · 224 px · two-step downscale</small></li>
            <li><span>02</span><strong>Crop / type gate</strong><small id="pipeline-gate">YOLO26n-cls · tomato focus: leaf, fruit or other</small></li>
            <li><span>03</span><strong>Condition model</strong><small>tomato-leaf specialist · 46 classes · field-trained</small></li>
            <li><span>04</span><strong>Safeguards</strong><small>confidence · margin · family mass · healthy separation</small></li>
            <li><span>05</span><strong>Frame vote</strong><small>3 of last 4 agree to show · withdrawn under 2</small></li>
        </ol>
        <dl class="pipeline-stats">
            <div><dt>Input</dt><dd>224 px</dd></div>
            <div><dt>Vote</dt><dd>3 of 4</dd></div>
            <div><dt>Frames sent</dt><dd>0</dd></div>
        </dl>
        <p class="pipeline-foot">Frames are processed in browser memory and never leave the device.</p>
    </aside>
</section>

<div class="screening-grid">
    <section class="panel capture-panel" aria-labelledby="capture-title">
        <div class="panel-head">
            <p class="section-number">01 / input feed</p>
            <span class="panel-tag">camera · still</span>
        </div>
        <div class="panel-intro">
            <h2 id="capture-title">Feed the subsystem</h2>
            <p>Use the live camera, or load one still of a single fruit or leaf in daylight.</p>
        </div>
        <p class="experimental-notice"><strong>Experimental model release.</strong> Confirm the crop and leaf/fruit type before acting. Fruit on the plant, yellowing cucumber leaves, whole tomato seedlings and tomato-fruit rots are still misidentified or not covered. This is not a diagnosis or a pesticide recommendation.</p>

        <input
            class="visually-hidden"
            id="image-input"
            name="image"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            tabindex="-1"
            aria-hidden="true"
        >
        <input
            class="visually-hidden"
            id="native-camera-input"
            name="camera-image"
            type="file"
            accept="image/*"
            capture="environment"
            tabindex="-1"
            aria-hidden="true"
        >

        <div class="drop-zone" id="drop-zone">
            <div class="upload-prompt" id="upload-prompt">
                <span class="upload-icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24"><path d="M4 7.5h3l1.4-2h7.2l1.4 2h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>
                </span>
                <strong>No frame loaded</strong>
                <span>Open the live feed or drop one clear crop photo here</span>
                <div class="capture-actions">
                    <button class="camera-button" id="open-camera-button" type="button">
                        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7.5h3l1.4-2h7.2l1.4 2h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>
                        Live feed
                    </button>
                    <button class="native-camera-button" id="native-camera-button" type="button">
                        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7.5h3l1.4-2h7.2l1.4 2h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>
                        Capture still
                    </button>
                    <button class="choose-button" id="upload-photo-button" type="button">
                        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v5h14v-5"/></svg>
                        Load file
                    </button>
                </div>
                <small id="camera-availability-note">On-device inference · frames never uploaded · live feed on phones needs HTTPS · JPEG, PNG or WebP up to 15 MB</small>
            </div>

            <figure class="preview-shell" id="preview-shell" tabindex="-1" hidden>
                <div class="preview-media" id="preview-media">
                    <img id="image-preview" alt="Selected crop photo">
                    <canvas id="disease-overlay" class="disease-overlay" hidden aria-hidden="true"></canvas>
                    <div class="scan-overlay" id="scan-overlay" hidden aria-hidden="true">
                        <span class="scan-beam"></span>
                        <span class="scan-corners"></span>
                    </div>
                    <p class="evidence-legend" id="evidence-legend" hidden>
                        <span aria-hidden="true"></span>
                        <strong>AI evidence</strong> — red areas affected the model score most; they are not exact lesion boundaries.
                    </p>
                </div>
                <figcaption>
                    <span><strong>Analysis crop · 224 px</strong><small id="file-name"></small></span>
                    <div class="preview-actions">
                        <button id="reopen-camera-button" type="button">live feed</button>
                        <button id="replace-photo-button" type="button">replace</button>
                    </div>
                </figcaption>
            </figure>
        </div>

        <details class="crop-correction" id="crop-correction">
            <summary>
                <span>Crop or photo type wrong?</span>
                <strong>Override</strong>
            </summary>
            <fieldset class="crop-confirmation">
                <legend class="visually-hidden">Crop confirmation</legend>
                <div class="confirmation-grid">
                    <label for="crop-override">
                        Crop
                        <select id="crop-override">
                            <option value="">Auto identify</option>
                            <option value="Apple">Apple</option>
                            <option value="Tomato">Tomato</option>
                            <option value="Cucumber">Cucumber</option>
                            <option value="Lemon">Lemon / citrus</option>
                        </select>
                    </label>
                    <label for="organ-override">
                        Photo type
                        <select id="organ-override">
                            <option value="">Auto identify</option>
                            <option value="leaf">Leaf</option>
                            <option value="fruit">Fruit</option>
                        </select>
                    </label>
                </div>
                <p>If either automatic result is wrong, select both the known crop and Leaf or Fruit, then run the analysis again.</p>
            </fieldset>
        </details>

        <div class="capture-note">
            <span aria-hidden="true">◎</span>
            <p><strong>For condition screening:</strong> one close, sharp fruit or leaf filling the square. Covered fruit conditions are screened directly; leaf diseases need a sharp leaf frame.</p>
        </div>

        <button class="analyze-button" id="analyze-button" type="button" disabled>
            <span>Run inference</span>
            <span aria-hidden="true">→</span>
        </button>
    </section>

    <section class="panel result-panel" aria-labelledby="result-heading">
        <div class="panel-head">
            <p class="section-number">02 / inference output</p>
            <span class="panel-tag">on-device</span>
        </div>

        <div class="result-empty" id="result-empty">
            <span class="scan-glyph" aria-hidden="true"><img src="assets/logo-mark.svg" alt="" width="64" height="64"></span>
            <p class="eyebrow">awaiting frame</p>
            <h2 id="result-heading">Output will appear here</h2>
            <p class="result-empty-lede">Load a tomato, cucumber, apple or lemon frame. Inference runs in this browser; the image is not sent to the server.</p>
            <ol class="empty-steps">
                <li><span>1</span><strong>Frame one leaf</strong><small>fill the square · daylight · sharp focus</small></li>
                <li><span>2</span><strong>Hold steady</strong><small>3 of the last 4 frames must agree</small></li>
                <li><span>3</span><strong>Read the result</strong><small>condition · confidence · spray estimate</small></li>
            </ol>
        </div>

        <div class="result-busy" id="result-busy" hidden aria-live="polite">
            <span class="spinner" aria-hidden="true"></span>
            <p class="eyebrow">inference running</p>
            <h2>Scanning frame…</h2>
            <p id="busy-stage">Loading the AI models in this browser.</p>
        </div>

        <div class="result-error" id="result-error" hidden role="alert">
            <p class="eyebrow">inference unavailable</p>
            <h2 id="error-title">We could not analyse this frame</h2>
            <p id="error-message">Try a brighter, sharper image with one crop filling the frame.</p>
        </div>

        <article class="result-card" id="result-card" hidden aria-live="polite">
            <div class="result-meta">
                <span class="match-badge" id="match-badge">screening result</span>
                <span class="field-badge">local browser AI</span>
            </div>

            <p class="crop-label" id="result-crop">screening summary</p>
            <h2 id="result-title">Result</h2>
            <p class="result-lede" id="result-lede"></p>

            <dl class="result-facts" aria-label="Screening result details">
                <div>
                    <dt>Crop</dt>
                    <dd id="result-fact-crop">Not established</dd>
                </div>
                <div>
                    <dt>Photo type</dt>
                    <dd id="result-fact-organ">Not established</dd>
                </div>
                <div>
                    <dt>Condition screen</dt>
                    <dd id="result-fact-condition">Not run</dd>
                </div>
                <div>
                    <dt>Status</dt>
                    <dd id="result-fact-status">Waiting</dd>
                </div>
            </dl>

            <button class="result-correction-button" id="result-correction-button" type="button">
                <span>Crop or photo type wrong?</span>
                <strong>Override →</strong>
            </button>

            <div class="score-grid">
                <div class="confidence-card" id="identity-score-card">
                    <div>
                        <span id="identity-score-label">Crop and photo-type match</span>
                        <strong id="identity-score-value">0%</strong>
                    </div>
                    <div class="confidence-track" aria-hidden="true">
                        <span id="identity-score-bar"></span>
                    </div>
                </div>
                <div class="confidence-card" id="condition-score-card" hidden>
                    <div>
                        <span id="condition-score-label">Closest condition model score</span>
                        <strong id="condition-score-value">0%</strong>
                    </div>
                    <div class="confidence-track" aria-hidden="true">
                        <span id="condition-score-bar"></span>
                    </div>
                </div>
            </div>

            <aside class="closest-match" id="closest-match" hidden>
                <p>Closest covered match — not a diagnosis</p>
                <div>
                    <strong id="closest-match-name"></strong>
                    <span id="closest-match-score"></span>
                </div>
                <p id="closest-match-reason"></p>
            </aside>

            <aside class="evidence-note" id="evidence-note" hidden>
                <span aria-hidden="true"></span>
                <p><strong>Red AI evidence is shown on the frame.</strong> It marks image regions that changed this model result most, not exact disease or lesion boundaries.</p>
            </aside>

            <section class="result-section" id="summary-section">
                <h3 id="summary-heading">Condition details</h3>
                <p id="result-summary"></p>
            </section>

            <section class="result-section spray-section" id="spray-section" hidden>
                <h3>Spray estimate</h3>
                <p class="spray-summary" id="result-spray"></p>
                <p class="spray-detail" id="result-spray-detail"></p>
            </section>

            <section class="result-section" id="next-section">
                <h3>What to do next</h3>
                <ol id="result-next"></ol>
            </section>

            <details class="alternatives" id="alternatives-wrap">
                <summary id="alternatives-summary">Other covered model matches</summary>
                <ol id="alternatives-list"></ol>
            </details>

            <p class="screening-disclaimer" id="result-disclaimer">Screening support only — confirm uncertain or severe symptoms with a local agronomist or plant diagnostic lab before treatment.</p>

            <section class="field-note" id="field-note" hidden>
                <h3>Was this right?</h3>
                <p class="field-note-lede">Tell CropSCOUT what you actually see. Your answer is saved as a <strong>field note</strong> for the team to review before any retraining. It never changes this result and is not recorded as a confirmed diagnosis.</p>

                <div class="field-note-known" id="field-note-known" hidden>
                    <strong>You already noted this photo</strong>
                    <p id="field-note-known-text"></p>
                </div>

                <div class="field-note-choice" id="field-note-choice">
                    <button type="button" class="field-note-button" id="field-note-yes">Yes — matches what I see</button>
                    <button type="button" class="field-note-button" id="field-note-no">No — it is actually…</button>
                    <button type="button" class="field-note-button ghost" id="field-note-unsure">Not sure</button>
                </div>

                <form class="field-note-form" id="field-note-form" hidden>
                    <label class="field-note-field" id="field-note-label-field" hidden>
                        <span>What do you actually see?</span>
                        <select id="field-note-label"></select>
                    </label>
                    <div class="field-note-grid">
                        <label class="field-note-field">
                            <span>Growth stage</span>
                            <select id="field-note-stage"></select>
                        </label>
                        <label class="field-note-field">
                            <span>How far along is it?</span>
                            <select id="field-note-severity"></select>
                        </label>
                    </div>
                    <label class="field-note-field">
                        <span>Anything else worth knowing? (optional)</span>
                        <textarea id="field-note-text" maxlength="600" rows="2" placeholder="Where on the plant, how many plants, what you sprayed"></textarea>
                    </label>
                    <label class="field-note-contribute">
                        <input type="checkbox" id="field-note-contribute">
                        <span><strong>Send this photo with my note.</strong> The photo is uploaded to crop-scout.com and reviewed by the team, so CropSCOUT can learn this pattern. Leave it unticked and only the note is saved, on this device.</span>
                    </label>
                    <button type="submit" class="field-note-submit" id="field-note-submit">Save field note</button>
                </form>

                <p class="field-note-status" id="field-note-status" hidden></p>
            </section>
        </article>
    </section>
</div>
</main>

<footer class="site-footer">
    <div class="footer-inner">
        <div class="footer-brand">
            <p class="footer-wordmark"><img src="assets/logo-mark.svg" alt="" width="44" height="44">Crop<span>SCOUT</span> <small>Vision</small></p>
            <p>Camera AI subsystem of the CropSCOUT field robot. Field robotics, built around the farmer.</p>
        </div>
        <div class="footer-columns">
            <div>
                <h2>Privacy</h2>
                <p>Camera frames and photos are analysed in this browser and never leave the device.</p>
            </div>
            <div>
                <h2>Screening</h2>
                <p>Screening support, not a laboratory diagnosis or a spray recommendation.</p>
            </div>
            <div>
                <h2>Stack</h2>
                <p>YOLO26 classifiers + leaf finder · ONNX · onnxruntime-web 1.29</p>
            </div>
        </div>
    </div>
</footer>

<section
    class="camera-panel"
    id="camera-panel"
    hidden
    role="dialog"
    aria-modal="true"
    aria-labelledby="camera-title"
    aria-describedby="camera-status camera-guide-copy"
    tabindex="-1"
>
    <div class="camera-dialog">
        <header class="camera-heading">
            <div>
                <p><span class="rec-dot" aria-hidden="true"></span>VIS-CAM 01 · live feed</p>
                <h2 id="camera-title">Frame one fruit or leaf</h2>
            </div>
            <button class="camera-close" id="close-camera-button" type="button" aria-label="Close camera">×</button>
        </header>

        <div class="camera-view" id="camera-view">
            <video id="camera-video" autoplay muted playsinline></video>
            <div class="live-leaf-boxes" id="live-leaf-boxes" hidden aria-hidden="true"></div>
            <aside class="live-recognition is-loading" id="live-recognition">
                <span class="live-recognition-dot" aria-hidden="true"></span>
                <span>
                    <small>Live on-device AI</small>
                    <strong id="live-crop-result">Starting recognition…</strong>
                    <span id="live-condition-result">Keep one fruit or leaf inside the square</span>
                </span>
            </aside>
            <span class="visually-hidden" id="live-recognition-announcement" aria-live="polite" aria-atomic="true"></span>
            <aside class="live-spray is-idle" id="live-spray" hidden>
                <small>Spray estimate</small>
                <strong id="live-spray-percent">SPRAY 0%</strong>
                <span id="live-spray-detail">Point the square at a tomato leaf</span>
            </aside>
            <div class="camera-guide">
                <span id="camera-guide-copy">Everything inside this square is analysed</span>
            </div>
            <div class="camera-hud" aria-hidden="true">
                <span>224 px</span>
                <span id="hud-cam-frames">0 fr</span>
                <span id="hud-cam-ms">— ms</span>
            </div>
        </div>

        <p class="camera-status" id="camera-status" aria-live="polite">Camera is off.</p>
        <div class="camera-controls" role="group" aria-label="Camera controls">
            <button class="camera-tool" id="switch-camera-button" type="button" disabled>
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 8h11m0 0-3-3m3 3-3 3M20 16H9m0 0 3 3m-3-3 3-3"/></svg>
                Flip
            </button>
            <button class="camera-capture" id="capture-camera-button" type="button" disabled aria-label="Freeze this square for a full result">
                <span aria-hidden="true"></span>
            </button>
            <button class="camera-tool" id="cancel-camera-button" type="button">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>
                Cancel
            </button>
        </div>
        <p class="camera-hint">Recognition updates a few times a second and shows a condition only after several frames agree. Use the shutter to freeze this frame for the full report and red AI evidence; that report checks one frame, so it can differ slightly from the live label.</p>

        <div class="camera-fallback" id="camera-fallback" hidden>
            <p>Live preview is unavailable, but you can still use your phone’s camera.</p>
            <button id="camera-fallback-button" type="button">Take a phone photo</button>
        </div>
    </div>
</section>

<noscript>
    <div class="noscript-warning">CropSCOUT Vision needs JavaScript to analyse images locally in your browser.</div>
</noscript>

<script type="module">
// HUD telemetry: read the engine's read-only live snapshot a few times a second.
// Display only; nothing here influences a result.
const hud = {
    mode: document.getElementById('hud-mode'),
    frames: document.getElementById('hud-frames'),
    ms: document.getElementById('hud-ms'),
    camFrames: document.getElementById('hud-cam-frames'),
    camMs: document.getElementById('hud-cam-ms'),
};
const params = new URLSearchParams(window.location.search);
const detectorRequested = params.get('detector') === '1';
const cropFocusAll = params.get('crop') === 'all';
// Both flags live in the URL, so the toggles and the readouts are set here, not on the
// server: the same page works as PHP and as a static build. Each toggle keeps the other flag.
function flagUrl(changes) {
    const next = new URLSearchParams(params);
    Object.entries(changes).forEach(([key, value]) => (value === null ? next.delete(key) : next.set(key, value)));
    const query = next.toString();
    return query ? `?${query}` : window.location.pathname;
}
const finderToggle = document.getElementById('leaf-finder-toggle');
if (finderToggle) {
    finderToggle.href = flagUrl({ detector: detectorRequested ? null : '1' });
    finderToggle.dataset.on = String(detectorRequested);
    document.getElementById('leaf-finder-state').textContent = detectorRequested ? 'ON' : 'OFF';
}
const cropToggle = document.getElementById('crop-focus-toggle');
if (cropToggle) {
    cropToggle.href = flagUrl({ crop: cropFocusAll ? null : 'all' });
    cropToggle.dataset.on = String(cropFocusAll);
    document.getElementById('crop-focus-state').textContent = cropFocusAll ? 'ALL' : 'TOMATO';
}
const hudCrop = document.getElementById('hud-crop');
if (hudCrop) hudCrop.textContent = cropFocusAll ? 'ALL' : 'TOMATO';
if (cropFocusAll) {
    const gate = document.getElementById('pipeline-gate');
    if (gate) gate.textContent = 'YOLO26n-cls · apple, tomato, cucumber, lemon · leaf or fruit · other';
    const scope = document.getElementById('hero-scope');
    if (scope) scope.textContent = 'All crops: the gate tells apple, tomato, cucumber and lemon apart, leaf or fruit, before the condition model runs. Switch the crop focus to TOMATO to treat every leaf as a tomato leaf.';
}
if (hud.mode && detectorRequested) hud.mode.textContent = 'LEAF FINDER';
function tick() {
    const api = window.CropScoutVision;
    if (api && typeof api.liveStats === 'function') {
        const s = api.liveStats();
        const ms = s.avgFrameMs ? `${Math.round(s.avgFrameMs)} ms` : '— ms';
        const modeText = s.running
            ? (s.mode === 'leaves' ? 'LEAF FINDER' : 'SQUARE')
            : (detectorRequested ? 'LEAF FINDER' : 'SQUARE');
        if (hud.mode) hud.mode.textContent = modeText;
        if (hud.frames) hud.frames.textContent = String(s.frames || 0);
        if (hud.ms) hud.ms.textContent = ms;
        if (hud.camFrames) hud.camFrames.textContent = `${s.frames || 0} fr`;
        if (hud.camMs) hud.camMs.textContent = ms;
    }
    window.setTimeout(tick, 400);
}
tick();
</script>
</body>
</html>
