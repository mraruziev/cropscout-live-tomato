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
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="description" content="Experimental crop and visible-symptom screening for apple, tomato, cucumber and lemon. Analyze photos or a live camera locally in your browser, without an account.">
    <meta name="referrer" content="same-origin">
    <title>CropSCOUT Vision — crop screening</title>
    <link rel="canonical" href="https://crop-scout.com/vision/">
    <link rel="stylesheet" href="styles.css?v=<?= rawurlencode($styleVersion) ?>">
    <script src="app.js?v=<?= rawurlencode($scriptVersion) ?>" type="module"></script>
</head>
<body class="vision-page">
<header class="app-header">
    <div class="brand-lockup" aria-label="CropSCOUT Vision">
        <span class="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 40 40" role="img">
                <path d="M20 30V16m0 4c-5.5 0-9.5-3.5-9.5-8.5 5.5 0 9.5 3.5 9.5 8.5Zm0-4c5.5 0 9.5-3.5 9.5-8.5-5.5 0-9.5 3.5-9.5 8.5Z"/>
            </svg>
        </span>
        <span class="brand-name">Crop<span>SCOUT</span></span>
        <span class="brand-mode">vision / public beta</span>
    </div>

    <div class="header-actions">
        <div class="model-state" id="model-state" aria-live="polite">
            <span class="state-dot" aria-hidden="true"></span>
            <span id="model-state-text">model check pending</span>
        </div>
        <a class="site-home-link" href="/">CropSCOUT home <span aria-hidden="true">↗</span></a>
    </div>
</header>

<main class="screening-grid">
    <section class="panel capture-panel" aria-labelledby="capture-title">
        <p class="section-number">01 / capture</p>
        <div class="panel-intro">
            <h1 id="capture-title">Show us the crop</h1>
            <p>Photograph one fruit or one leaf in daylight. Keep it sharp and let it fill most of the frame.</p>
        </div>
        <p class="experimental-notice"><strong>Experimental screening.</strong> Confirm the crop and leaf/fruit type before acting. Fruit photographed on the plant, yellowing cucumber leaves, whole tomato seedlings and tomato-fruit rots are still misidentified or not covered. This is not a diagnosis or a pesticide recommendation.</p>

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
                <span class="upload-icon" aria-hidden="true">↥</span>
                <strong>Add one clear crop photo</strong>
                <span>Fill the frame with one fruit or leaf</span>
                <div class="capture-actions">
                    <button class="camera-button" id="open-camera-button" type="button">
                        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7.5h3l1.4-2h7.2l1.4 2h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>
                        Live camera
                    </button>
                    <button class="native-camera-button" id="native-camera-button" type="button">
                        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7.5h3l1.4-2h7.2l1.4 2h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>
                        Take photo
                    </button>
                    <button class="choose-button" id="upload-photo-button" type="button">
                        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v5h14v-5"/></svg>
                        Upload photo
                    </button>
                </div>
                <small id="camera-availability-note">No account needed. Photos stay on this device. Live camera on phones needs HTTPS · JPEG, PNG or WebP · up to 15 MB.</small>
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
                    <span><strong>Square analysis crop</strong><small id="file-name"></small></span>
                    <div class="preview-actions">
                        <button id="reopen-camera-button" type="button">Live camera</button>
                        <button id="replace-photo-button" type="button">Replace</button>
                    </div>
                </figcaption>
            </figure>
        </div>

        <details class="crop-correction" id="crop-correction">
            <summary>
                <span>Crop or photo type wrong?</span>
                <strong>Correct it</strong>
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
                <p>If either automatic result is wrong, select both the known crop and Leaf or Fruit, then analyze again.</p>
            </fieldset>
        </details>

        <div class="capture-note">
            <span aria-hidden="true">◎</span>
            <p><strong>For condition screening:</strong> use one close, clear fruit or leaf. Covered fruit conditions can be screened directly; leaf diseases still need a sharp leaf photo.</p>
        </div>

        <button class="analyze-button" id="analyze-button" type="button" disabled>
            <span>Analyze photo</span>
            <span aria-hidden="true">→</span>
        </button>
    </section>

    <section class="panel result-panel" aria-labelledby="result-heading">
        <p class="section-number">02 / result</p>

        <div class="result-empty" id="result-empty">
            <span class="scan-glyph" aria-hidden="true"></span>
            <p class="eyebrow">browser-local field screening</p>
            <h2 id="result-heading">Your result will appear here</h2>
            <p>Choose a tomato, cucumber, apple, lemon, or leaf photo. Analysis runs in this browser; the image is not sent to the website server.</p>
        </div>

        <div class="result-busy" id="result-busy" hidden aria-live="polite">
            <span class="spinner" aria-hidden="true"></span>
            <p class="eyebrow">analyzing locally</p>
            <h2>Scanning crop image…</h2>
            <p id="busy-stage">Loading the AI models in this browser.</p>
        </div>

        <div class="result-error" id="result-error" hidden role="alert">
            <p class="eyebrow">analysis unavailable</p>
            <h2 id="error-title">We could not analyze this photo</h2>
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
                <strong>Correct it →</strong>
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
                <p><strong>Red AI evidence is shown on the photo.</strong> It marks image regions that changed this model result most, not exact disease or lesion boundaries.</p>
            </aside>

            <section class="result-section" id="summary-section">
                <h3 id="summary-heading">Condition details</h3>
                <p id="result-summary"></p>
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
</main>

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
                <p>Live square capture</p>
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
                    <small>Live local AI</small>
                    <strong id="live-crop-result">Starting recognition…</strong>
                    <span id="live-condition-result">Keep one fruit or leaf inside the square</span>
                </span>
            </aside>
            <span class="visually-hidden" id="live-recognition-announcement" aria-live="polite" aria-atomic="true"></span>
            <div class="camera-guide">
                <span id="camera-guide-copy">Everything inside this square will be analyzed</span>
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
    <div class="noscript-warning">CropSCOUT Vision needs JavaScript to analyze images locally in your browser.</div>
</noscript>
</body>
</html>
