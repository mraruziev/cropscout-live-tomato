import * as ort from './vendor/ort.wasm.bundle.min.mjs';
import { decideSpray, estimateSeverityFromTensor, loadSprayRules, sprayChipText, spraySummary } from './spray.js';

// Static mode (<html data-mode="static">, produced by tools/build_static.py): no PHP.
// The models and their metadata are plain files under models/, and the field-note
// backend does not exist. Everything the models do is identical in both modes.
const STATIC_MODE = document.documentElement.dataset.mode === 'static';
const modelUrl = (alias, file) => (STATIC_MODE ? `models/${file}` : `model.php?model=${alias}`);

const MODEL_ENDPOINTS = Object.freeze({
    cropView: modelUrl('crop-view', 'cropscout-crop-view.onnx'),
    disease: modelUrl('disease', 'cropscout-disease.onnx'),
});

const METADATA_ENDPOINT = modelUrl('metadata', 'model-metadata.json');
const SPECIALIST_ENDPOINTS = Object.freeze({
    'cucumber-leaf': modelUrl('cucumber-leaf', 'cropscout-cucumber-leaf.onnx'),
    'lemon-leaf': modelUrl('lemon-leaf', 'cropscout-lemon-leaf.onnx'),
    'tomato-leaf': modelUrl('tomato-leaf', 'cropscout-tomato-leaf.onnx'),
});
const SPECIALIST_FAMILIES = Object.freeze({
    'cucumber-leaf': 'Cucumber_leaf',
    'lemon-leaf': 'Lemon_leaf',
    'tomato-leaf': 'Tomato_leaf',
});
// Loaded with the base models instead of on first use: tomato leaves are the main use.
const EAGER_SPECIALISTS = Object.freeze(['tomato-leaf']);
const LEMON_HYBRID_POLICY_ID = 'lemon_disease_only_preserve_base_healthy_v1';
const LEMON_SPECIALIST_MIN_CONFIDENCE = 0.70;
const IMAGE_SIZE = 224;
const EVIDENCE_GRID_SIZE = 4;
// Live camera sampling. The browser halves the centre square in exact 2:1
// steps (each step averages 2x2 pixels) while it stays at least twice the
// model size, then the same antialiased resize as photo mode takes it to
// 224 px. A single large browser downscale is not equivalent: going straight
// from 1080 to 448 px moved crop scores by more than 10 points in tests.
const LIVE_MIN_SAMPLE_SIDE = IMAGE_SIZE * 2;
// Live camera pacing. Each cycle rests at least as long as it worked, so model
// work never takes more than half of the main thread, but never longer than
// LIVE_MAX_REST_MS, so one slow frame cannot freeze the loop.
const LIVE_MIN_PERIOD_MS = 350;
const LIVE_MAX_REST_MS = 1000;
const LIVE_RETRY_MS = 250;
// A live verdict appears after 3 of the last 4 frames pass every safeguard
// with the same condition, and is withdrawn once fewer than 2 still do.
// Votes only decide what is displayed; they never relax a threshold.
const LIVE_VOTE_WINDOW = 4;
const LIVE_VOTES_TO_SHOW = 3;
const LIVE_VOTES_TO_HOLD = 2;
// Leaf finder (feature flag): open the page with ?detector=1. It also needs a
// leaf_detector entry in the release metadata.
const LEAF_FINDER_ENDPOINT = modelUrl('leaf-detector', 'cropscout-leaf-detector.onnx');
const LEAF_FINDER_REQUESTED = new URLSearchParams(window.location.search).get('detector') === '1';
// A detected leaf keeps its track while its box overlaps last frame's box by
// at least this much, and loses it after this many frames in a row unseen.
const LIVE_TRACK_MIN_IOU = 0.5;
const LIVE_TRACK_MAX_MISSES = 2;
const LIVE_DUPLICATE_IOU = 0.7;
const MAX_FILE_BYTES = 15 * 1024 * 1024;
const MAX_SOURCE_PIXELS = 40_000_000;
const ALLOWED_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);
const SUPPORTED_CROPS = new Map([
    ['apple', 'Apple'],
    ['tomato', 'Tomato'],
    ['cucumber', 'Cucumber'],
    ['lemon', 'Lemon'],
]);
const CROP_DISPLAY_NAMES = new Map([
    ['Lemon:fruit', 'Lemon / citrus'],
    ['Lemon:leaf', 'Lemon / citrus'],
]);
const DEFAULT_DISCLAIMER = 'Screening support only — confirm uncertain or severe symptoms with a local agronomist or plant diagnostic lab before treatment.';

ort.env.wasm.numThreads = 1;
ort.env.wasm.proxy = false;
ort.env.wasm.wasmPaths = Object.freeze({
    wasm: new URL('./vendor/ort-wasm-simd-threaded.wasm', import.meta.url).href,
});

const elements = {
    input: document.querySelector('#image-input'),
    uploadPhotoButton: document.querySelector('#upload-photo-button'),
    nativeInput: document.querySelector('#native-camera-input'),
    nativeCameraButton: document.querySelector('#native-camera-button'),
    reopenCameraButton: document.querySelector('#reopen-camera-button'),
    replacePhotoButton: document.querySelector('#replace-photo-button'),
    dropZone: document.querySelector('#drop-zone'),
    prompt: document.querySelector('#upload-prompt'),
    openCamera: document.querySelector('#open-camera-button'),
    heroCamera: document.querySelector('#hero-camera-button'),
    heroPhoto: document.querySelector('#hero-photo-button'),
    cameraAvailabilityNote: document.querySelector('#camera-availability-note'),
    cameraPanel: document.querySelector('#camera-panel'),
    cameraView: document.querySelector('#camera-view'),
    cameraVideo: document.querySelector('#camera-video'),
    liveRecognition: document.querySelector('#live-recognition'),
    liveCropResult: document.querySelector('#live-crop-result'),
    liveConditionResult: document.querySelector('#live-condition-result'),
    spraySection: document.querySelector('#spray-section'),
    spray: document.querySelector('#result-spray'),
    sprayDetail: document.querySelector('#result-spray-detail'),
    liveRecognitionAnnouncement: document.querySelector('#live-recognition-announcement'),
    liveLeafBoxes: document.querySelector('#live-leaf-boxes'),
    liveSpray: document.querySelector('#live-spray'),
    liveSprayPercent: document.querySelector('#live-spray-percent'),
    liveSprayDetail: document.querySelector('#live-spray-detail'),
    cameraGuideCopy: document.querySelector('#camera-guide-copy'),
    cameraStatus: document.querySelector('#camera-status'),
    captureCamera: document.querySelector('#capture-camera-button'),
    switchCamera: document.querySelector('#switch-camera-button'),
    closeCamera: document.querySelector('#close-camera-button'),
    cancelCamera: document.querySelector('#cancel-camera-button'),
    cameraFallback: document.querySelector('#camera-fallback'),
    cameraFallbackButton: document.querySelector('#camera-fallback-button'),
    previewShell: document.querySelector('#preview-shell'),
    previewMedia: document.querySelector('#preview-media'),
    preview: document.querySelector('#image-preview'),
    overlay: document.querySelector('#disease-overlay'),
    scanner: document.querySelector('#scan-overlay'),
    evidenceLegend: document.querySelector('#evidence-legend'),
    fileName: document.querySelector('#file-name'),
    analyze: document.querySelector('#analyze-button'),
    analyzeLabel: document.querySelector('#analyze-button span'),
    cropOverride: document.querySelector('#crop-override'),
    organOverride: document.querySelector('#organ-override'),
    cropCorrection: document.querySelector('#crop-correction'),
    resultCorrectionButton: document.querySelector('#result-correction-button'),
    appHeader: document.querySelector('.app-header'),
    pageMain: document.querySelector('main'),
    pageFooter: document.querySelector('.site-footer'),
    resultPanel: document.querySelector('.result-panel'),
    modelState: document.querySelector('#model-state'),
    modelStateText: document.querySelector('#model-state-text'),
    empty: document.querySelector('#result-empty'),
    busy: document.querySelector('#result-busy'),
    busyStage: document.querySelector('#busy-stage'),
    error: document.querySelector('#result-error'),
    errorTitle: document.querySelector('#error-title'),
    errorMessage: document.querySelector('#error-message'),
    card: document.querySelector('#result-card'),
    badge: document.querySelector('#match-badge'),
    crop: document.querySelector('#result-crop'),
    title: document.querySelector('#result-title'),
    lede: document.querySelector('#result-lede'),
    factCrop: document.querySelector('#result-fact-crop'),
    factOrgan: document.querySelector('#result-fact-organ'),
    factCondition: document.querySelector('#result-fact-condition'),
    factStatus: document.querySelector('#result-fact-status'),
    identityScoreCard: document.querySelector('#identity-score-card'),
    identityScoreLabel: document.querySelector('#identity-score-label'),
    identityScoreValue: document.querySelector('#identity-score-value'),
    identityScoreBar: document.querySelector('#identity-score-bar'),
    conditionScoreCard: document.querySelector('#condition-score-card'),
    conditionScoreLabel: document.querySelector('#condition-score-label'),
    conditionScoreValue: document.querySelector('#condition-score-value'),
    conditionScoreBar: document.querySelector('#condition-score-bar'),
    closestMatch: document.querySelector('#closest-match'),
    closestMatchName: document.querySelector('#closest-match-name'),
    closestMatchScore: document.querySelector('#closest-match-score'),
    closestMatchReason: document.querySelector('#closest-match-reason'),
    evidenceNote: document.querySelector('#evidence-note'),
    summaryHeading: document.querySelector('#summary-heading'),
    summary: document.querySelector('#result-summary'),
    next: document.querySelector('#result-next'),
    alternativesWrap: document.querySelector('#alternatives-wrap'),
    alternativesSummary: document.querySelector('#alternatives-summary'),
    alternatives: document.querySelector('#alternatives-list'),
    disclaimer: document.querySelector('#result-disclaimer'),
    fieldNote: document.querySelector('#field-note'),
    fieldNoteKnown: document.querySelector('#field-note-known'),
    fieldNoteKnownText: document.querySelector('#field-note-known-text'),
    fieldNoteChoice: document.querySelector('#field-note-choice'),
    fieldNoteYes: document.querySelector('#field-note-yes'),
    fieldNoteNo: document.querySelector('#field-note-no'),
    fieldNoteUnsure: document.querySelector('#field-note-unsure'),
    fieldNoteForm: document.querySelector('#field-note-form'),
    fieldNoteLabelField: document.querySelector('#field-note-label-field'),
    fieldNoteLabel: document.querySelector('#field-note-label'),
    fieldNoteStage: document.querySelector('#field-note-stage'),
    fieldNoteSeverity: document.querySelector('#field-note-severity'),
    fieldNoteText: document.querySelector('#field-note-text'),
    fieldNoteContribute: document.querySelector('#field-note-contribute'),
    fieldNoteSubmit: document.querySelector('#field-note-submit'),
    fieldNoteStatus: document.querySelector('#field-note-status'),
};

class VisionError extends Error {
    constructor(code, message) {
        super(message);
        this.name = 'VisionError';
        this.code = code;
    }
}

let selectedFile = null;
let previewUrl = null;
let runtimePromise = null;
let analysisSequence = 0;
let lastEvidence = null;
let cameraStream = null;
let cameraRequestGeneration = 0;
let cameraDevices = [];
let activeCameraDeviceId = '';
let preferredCameraFacing = 'environment';
// The whole centre square is one live track. With the leaf finder on, each
// detected leaf or fruit gets its own track: its own smoothing, its own votes
// and its own shown verdict.
let liveSquareTrack = createLiveTrack('square');
let liveLeafTracks = [];
let liveNextTrackId = 1;
let liveSquareStreak = 0;
let leafFinderFailed = false;
let liveLoopGeneration = 0;
let lastLiveAnnouncement = '';
const liveStats = {
    running: false,
    frames: 0,
    lastFrameMs: 0,
    avgFrameMs: 0,
    lastPreprocessMs: 0,
    mode: 'square',
    lastDetectorMs: 0,
    avgDetectorMs: 0,
    leaves: [],
    display: { state: 'loading', crop: '', condition: '' },
};
const activeLiveRecognitions = new Set();
const specialistSessions = new WeakMap();
const settledSpecialistLoads = new WeakSet();
let onnxOperationQueue = Promise.resolve();

function queueOnnxOperation(operation) {
    const pending = onnxOperationQueue.then(operation);
    onnxOperationQueue = pending.catch(() => {});
    return pending;
}

function showOnly(target) {
    [elements.empty, elements.busy, elements.error, elements.card].forEach((section) => {
        section.hidden = section !== target;
    });
}

function setScanning(active) {
    elements.scanner.hidden = !active;
    elements.previewMedia.classList.toggle('is-scanning', active);
    elements.previewMedia.setAttribute('aria-busy', active ? 'true' : 'false');
    elements.resultPanel.setAttribute('aria-busy', active ? 'true' : 'false');
}

function setBusyStage(text) {
    elements.busyStage.textContent = text;
}

function setModelState(kind, text) {
    elements.modelState.classList.remove('ready', 'error');
    if (kind === 'ready' || kind === 'error') {
        elements.modelState.classList.add(kind);
    }
    elements.modelStateText.textContent = text;
}

function setCaptureActionsDisabled(disabled) {
    [
        elements.uploadPhotoButton,
        elements.nativeCameraButton,
        elements.openCamera,
        elements.replacePhotoButton,
        elements.reopenCameraButton,
        elements.input,
        elements.nativeInput,
        elements.heroCamera,
        elements.heroPhoto,
    ].filter(Boolean).forEach((control) => {
        control.disabled = disabled;
    });
    elements.dropZone.classList.toggle('is-disabled', disabled);
    elements.dropZone.setAttribute('aria-disabled', disabled ? 'true' : 'false');
}

function renderFailure(title, message) {
    setScanning(false);
    setCaptureActionsDisabled(false);
    elements.analyze.disabled = !selectedFile;
    elements.analyzeLabel.textContent = selectedFile ? 'Try analysis again' : 'Analyze photo';
    clearEvidenceOverlay();
    elements.errorTitle.textContent = title;
    elements.errorMessage.textContent = message;
    showOnly(elements.error);
    revealResultOnPhone();
}

function revealResultOnPhone() {
    if (!window.matchMedia('(max-width: 860px)').matches) return;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.requestAnimationFrame(() => {
        elements.resultPanel.scrollIntoView({
            behavior: reducedMotion ? 'auto' : 'smooth',
            block: 'start',
        });
    });
}

function scorePercent(value) {
    const bounded = Math.max(0, Math.min(1, Number(value) || 0));
    if (bounded > 0 && bounded < 0.005) return '<1%';
    return `${Math.round(bounded * 100)}%`;
}

function renderScoreCard(card, labelElement, valueElement, barElement, score, label) {
    const visible = Number.isFinite(score);
    card.hidden = !visible;
    if (!visible) return;
    const bounded = Math.max(0, Math.min(1, Number(score) || 0));
    labelElement.textContent = label;
    valueElement.textContent = scorePercent(score);
    barElement.style.width = `${bounded * 100}%`;
}

function renderBusy() {
    clearEvidenceOverlay();
    setScanning(true);
    setCaptureActionsDisabled(true);
    elements.analyze.disabled = true;
    elements.analyzeLabel.textContent = 'Analyzing…';
    setBusyStage('Loading the AI models in this browser.');
    showOnly(elements.busy);
}

function renderResult(result) {
    setScanning(false);
    setCaptureActionsDisabled(false);
    elements.analyze.disabled = false;
    elements.analyzeLabel.textContent = 'Analyze again';
    if (!result.evidenceShown) clearEvidenceOverlay();
    const alternatives = Array.isArray(result.alternatives) ? result.alternatives : [];
    const nextSteps = Array.isArray(result.next) ? result.next : [];

    elements.badge.textContent = result.certainty || 'screening result';
    elements.crop.textContent = result.resultLabel || 'screening summary';
    elements.title.textContent = result.title || 'Uncertain result';
    elements.lede.textContent = result.lede || '';
    elements.factCrop.textContent = result.crop || 'Not established';
    elements.factOrgan.textContent = result.organ || 'Not established';
    elements.factCondition.textContent = result.condition || 'Not run';
    elements.factStatus.textContent = result.status || result.certainty || 'Screening result';
    renderScoreCard(
        elements.identityScoreCard,
        elements.identityScoreLabel,
        elements.identityScoreValue,
        elements.identityScoreBar,
        result.identityScore,
        result.identityScoreLabel || 'Crop and photo-type match'
    );
    renderScoreCard(
        elements.conditionScoreCard,
        elements.conditionScoreLabel,
        elements.conditionScoreValue,
        elements.conditionScoreBar,
        result.conditionScore,
        result.conditionScoreLabel || 'Closest condition model score'
    );
    const closestMatch = result.closestMatch;
    elements.closestMatch.hidden = !closestMatch;
    if (closestMatch) {
        elements.closestMatchName.textContent = closestMatch.label || 'No covered match';
        elements.closestMatchScore.textContent = `${scorePercent(closestMatch.confidence)} model score`;
        elements.closestMatchReason.textContent = result.gateNote || 'This match did not pass every screening safeguard.';
    }
    elements.evidenceNote.hidden = !result.evidenceShown;
    elements.summaryHeading.textContent = result.summaryHeading || 'Condition details';
    elements.summary.textContent = result.summary || 'No condition summary is available.';
    elements.next.replaceChildren(...nextSteps.map((step) => {
        const item = document.createElement('li');
        item.textContent = step;
        return item;
    }));

    const notedLabel = currentAnalysis?.knownNote?.labelText || '';
    elements.alternatives.replaceChildren(...alternatives.map((alternative) => {
        const item = document.createElement('li');
        const label = document.createElement('span');
        const score = document.createElement('span');
        label.textContent = alternative.label || 'Other match';
        score.textContent = `${scorePercent(alternative.confidence)} model score`;
        // A matching field note is flagged, never promoted into the verdict.
        if (notedLabel && alternative.label === notedLabel) {
            item.classList.add('noted');
            const tag = document.createElement('em');
            tag.textContent = 'your field note';
            label.append(' ', tag);
        }
        item.append(label, score);
        return item;
    }));
    elements.alternativesWrap.hidden = alternatives.length === 0;
    elements.alternativesWrap.open = Boolean(result.openAlternatives && alternatives.length > 0);
    elements.alternativesSummary.textContent = result.alternativesLabel || 'Other covered model matches';
    elements.disclaimer.textContent = result.disclaimer || DEFAULT_DISCLAIMER;
    renderSpray(result.spray);
    elements.cropCorrection.open = Boolean(
        result.openCorrection || elements.cropOverride.value || elements.organOverride.value
    );
    resetFieldNoteForm();
    renderFieldNotePanel();
    showOnly(elements.card);
    revealResultOnPhone();
}

function renderSpray(spray) {
    if (!elements.spraySection) return;
    elements.spraySection.hidden = !spray;
    if (!spray) return;
    elements.spraySection.dataset.action = spray.action;
    elements.spray.textContent = spraySummary(spray);
    const detail = [];
    if (spray.action === 'spray') {
        if (spray.intervalDays) detail.push(`Repeat every ${spray.intervalDays} days while symptoms persist.`);
        if (spray.reason) detail.push(spray.reason);
        detail.push('Estimate only: use the registered label rate for your product and confirm with an agronomist.');
    } else if (spray.reason) {
        detail.push(spray.reason);
    }
    elements.sprayDetail.textContent = detail.join(' ');
}

function validateFile(file) {
    if (!(file instanceof File)) {
        return 'Choose an image file first.';
    }
    if (!ALLOWED_TYPES.has(file.type)) {
        return 'Use a JPEG, PNG, or WebP image.';
    }
    if (file.size > MAX_FILE_BYTES) {
        return 'This image is larger than 15 MB. Choose a smaller copy.';
    }
    return null;
}

function selectFile(file) {
    if (elements.input.disabled) return;
    const problem = validateFile(file);
    if (problem) {
        closeCamera();
        renderFailure('Photo not accepted', problem);
        return;
    }

    const cameFromLiveCamera = !elements.cameraPanel.hidden;
    closeCamera({ restoreSurface: false });
    selectedFile = file;
    elements.cropOverride.value = '';
    elements.organOverride.value = '';
    elements.cropCorrection.open = false;
    setScanning(false);
    clearEvidenceOverlay();
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(file);
    elements.preview.src = previewUrl;
    elements.fileName.textContent = file.name || 'camera photo';
    elements.prompt.hidden = true;
    elements.previewShell.hidden = false;
    elements.analyze.disabled = false;
    elements.analyzeLabel.textContent = 'Analyze photo';
    showOnly(elements.empty);

    if (cameFromLiveCamera) {
        elements.previewShell.focus({ preventScroll: true });
    }

    document.dispatchEvent(new CustomEvent('cropscout:image-selected', { detail: { file } }));
}

function setCameraStatus(message, isError = false) {
    elements.cameraStatus.textContent = message;
    elements.cameraStatus.classList.toggle('error', isError);
    elements.cameraFallback.hidden = !isError;
}

function setLiveRecognition(state, cropText, conditionText) {
    elements.liveRecognition.classList.remove('is-loading', 'is-identified', 'is-uncertain', 'is-error');
    elements.liveRecognition.classList.add(`is-${state}`);
    liveStats.display = { state, crop: cropText, condition: conditionText };
    if (elements.liveCropResult.textContent !== cropText) {
        elements.liveCropResult.textContent = cropText;
    }
    if (elements.liveConditionResult.textContent !== conditionText) {
        elements.liveConditionResult.textContent = conditionText;
    }
}

// The live SPRAY readout. `readout` is {tone, percent, detail}; null hides it
// (no spray rules loaded). Tone: idle | wait | spray | none | remove.
function setLiveSpray(readout) {
    if (!elements.liveSpray) return;
    liveStats.spray = readout;
    elements.liveSpray.hidden = !readout;
    if (!readout) return;
    elements.liveSpray.classList.remove('is-idle', 'is-wait', 'is-spray', 'is-none', 'is-remove');
    elements.liveSpray.classList.add(`is-${readout.tone}`);
    const percentText = `SPRAY ${readout.percent}%`;
    if (elements.liveSprayPercent.textContent !== percentText) elements.liveSprayPercent.textContent = percentText;
    if (elements.liveSprayDetail.textContent !== readout.detail) elements.liveSprayDetail.textContent = readout.detail;
}

const SPRAY_IDLE = Object.freeze({ tone: 'idle', percent: 0, detail: 'Point the square at a tomato leaf' });

function sprayReadoutFor(runtime, decision, phase) {
    if (!runtime.sprayRules) return null;
    if (phase === 'abstain') return SPRAY_IDLE;
    if (phase === 'loading') return Object.freeze({ tone: 'wait', percent: 0, detail: 'Loading the condition model…' });
    if (phase === 'nocondition') return Object.freeze({ tone: 'idle', percent: 0, detail: 'No covered condition for this view' });
    if (phase === 'confirming') return Object.freeze({ tone: 'wait', percent: 0, detail: 'Condition found · confirming over frames…' });
    if (phase === 'uncertain' || !decision) return Object.freeze({ tone: 'wait', percent: 0, detail: 'Condition not confirmed · hold steady' });
    if (decision.action === 'spray') {
        return Object.freeze({
            tone: 'spray',
            percent: decision.percent,
            detail: `${decision.doseMl} mL ${decision.product} · ~${decision.spraySeconds} s pump`,
        });
    }
    if (decision.action === 'remove') return Object.freeze({ tone: 'remove', percent: 0, detail: 'Do not spray · remove this plant (virus)' });
    return Object.freeze({ tone: 'none', percent: 0, detail: decision.reason || 'Nothing to spray' });
}

function announceLiveRecognition(message) {
    if (message === lastLiveAnnouncement) return;
    lastLiveAnnouncement = message;
    elements.liveRecognitionAnnouncement.textContent = message;
}

function createLiveTrack(id, box = null) {
    return {
        id,
        box,
        score: 1,
        misses: 0,
        smoothedCrop: null,
        conditionFamily: '',
        conditionRoute: '',
        conditionSmoothingByModel: new Map(),
        votes: [],
        shown: null,
        conditionDisplayReady: false,
        status: null,
    };
}

function resetLiveConditionTracking(track, family = '', route = '') {
    track.conditionSmoothingByModel.clear();
    track.conditionFamily = family;
    track.conditionRoute = route;
    track.votes = [];
    track.shown = null;
    track.conditionDisplayReady = false;
}

// Records this frame's gated outcome for one track and returns what it may
// show. `key` is empty when the frame did not pass every safeguard.
function voteLiveVerdict(track, key, text) {
    track.votes = [...track.votes, key].slice(-LIVE_VOTE_WINDOW);
    const votesFor = (candidate) => track.votes.filter((vote) => vote === candidate).length;

    if (track.shown && votesFor(track.shown.key) >= LIVE_VOTES_TO_HOLD) {
        if (key === track.shown.key) track.shown = { key, text };
        return { shown: track.shown };
    }
    track.shown = key && votesFor(key) >= LIVE_VOTES_TO_SHOW ? { key, text } : null;
    return { shown: track.shown, pending: key ? votesFor(key) : 0 };
}

function resetLiveRecognition() {
    liveSquareTrack = createLiveTrack('square');
    liveLeafTracks = [];
    liveSquareStreak = 0;
    renderLiveLeafBoxes([]);
    Object.assign(liveStats, { mode: 'square', leaves: [] });
    lastLiveAnnouncement = '';
    elements.liveRecognitionAnnouncement.textContent = '';
    elements.cameraView.classList.remove('is-live-scanning');
    setLiveRecognition(
        'loading',
        'Starting recognition…',
        'Keep one fruit or leaf inside the square'
    );
    setLiveSpray(SPRAY_IDLE);
}

function releaseCameraStream() {
    const stream = cameraStream;
    cameraStream = null;
    if (stream) stream.getTracks().forEach((track) => track.stop());
    activeCameraDeviceId = '';
    elements.cameraVideo.pause();
    elements.cameraVideo.srcObject = null;
    elements.captureCamera.disabled = true;
    elements.switchCamera.disabled = true;
    resetLiveRecognition();
}

function restoreCaptureSurface() {
    if (selectedFile) {
        elements.prompt.hidden = true;
        elements.previewShell.hidden = false;
    } else {
        elements.prompt.hidden = false;
        elements.previewShell.hidden = true;
    }
}

function showCameraPanel() {
    elements.cameraPanel.hidden = false;
    elements.appHeader.setAttribute('inert', '');
    elements.pageMain.setAttribute('inert', '');
    elements.pageFooter?.setAttribute('inert', '');
    document.body.classList.add('camera-open');
    window.requestAnimationFrame(() => elements.cameraPanel.focus());
}

function hideCameraPanel() {
    elements.cameraPanel.hidden = true;
    elements.appHeader.removeAttribute('inert');
    elements.pageMain.removeAttribute('inert');
    elements.pageFooter?.removeAttribute('inert');
    document.body.classList.remove('camera-open');
}

function closeCamera({
    restoreSurface = true,
    returnFocus = restoreSurface,
    message = 'Camera is off.',
} = {}) {
    cameraRequestGeneration += 1;
    releaseCameraStream();
    setCameraStatus(message);
    hideCameraPanel();
    if (restoreSurface) restoreCaptureSurface();
    if (returnFocus) {
        const focusTarget = elements.previewShell.hidden
            ? elements.openCamera
            : elements.reopenCameraButton;
        focusTarget.focus({ preventScroll: true });
    }
}

function liveCameraAvailable() {
    return window.isSecureContext && Boolean(navigator.mediaDevices?.getUserMedia);
}

function configureCameraAvailability() {
    const secure = window.isSecureContext;
    const supported = Boolean(navigator.mediaDevices?.getUserMedia);
    elements.openCamera.hidden = !(secure && supported);
    if (elements.heroCamera) elements.heroCamera.hidden = !(secure && supported);
    elements.cameraAvailabilityNote.classList.toggle('warning', !(secure && supported));

    if (!secure) {
        elements.cameraAvailabilityNote.textContent = 'Live square preview needs the secure HTTPS site. Native capture may be available on supported phones; photo upload still works.';
    } else if (!supported) {
        elements.cameraAvailabilityNote.textContent = 'This browser does not support live preview. Try Take photo or Upload photo.';
    }
}

function cameraErrorMessage(error) {
    const name = error instanceof DOMException ? error.name : '';
    if (name === 'NotAllowedError' || name === 'SecurityError') {
        return 'Camera permission was blocked. Allow camera access in this browser’s site settings, or choose a saved photo.';
    }
    if (name === 'NotFoundError') {
        return 'No camera was found on this device. Connect a camera or choose a saved photo.';
    }
    if (name === 'NotReadableError' || name === 'AbortError') {
        return 'The camera is busy or disconnected. Close other camera apps and try again.';
    }
    return 'The camera could not start. Close it and try again, or choose a saved photo.';
}

async function videoDevices() {
    try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        return devices.filter((device) => device.kind === 'videoinput');
    } catch {
        return [];
    }
}

async function requestCamera({ deviceId = '', facingMode = preferredCameraFacing } = {}) {
    if (!liveCameraAvailable()) {
        configureCameraAvailability();
        elements.nativeInput.click();
        return;
    }

    const generation = ++cameraRequestGeneration;
    releaseCameraStream();
    showCameraPanel();
    setCameraStatus('Requesting camera permission…');

    const previousRecognitions = [...activeLiveRecognitions];
    if (previousRecognitions.length > 0) {
        await Promise.allSettled(previousRecognitions);
        if (generation !== cameraRequestGeneration) return;
    }

    const preferredConstraints = {
        audio: false,
        video: deviceId
            ? { deviceId: { exact: deviceId } }
            : {
                facingMode: { ideal: facingMode },
                width: { ideal: 1920 },
                height: { ideal: 1080 },
            },
    };

    let stream;
    try {
        stream = await navigator.mediaDevices.getUserMedia(preferredConstraints);
    } catch (error) {
        if (generation !== cameraRequestGeneration) return;
        if (error instanceof DOMException && error.name === 'OverconstrainedError' && !deviceId) {
            try {
                stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: true });
            } catch (fallbackError) {
                if (generation === cameraRequestGeneration) {
                    setCameraStatus(cameraErrorMessage(fallbackError), true);
                }
                return;
            }
        } else {
            if (generation === cameraRequestGeneration) {
                setCameraStatus(cameraErrorMessage(error), true);
            }
            return;
        }
    }

    if (generation !== cameraRequestGeneration) {
        stream.getTracks().forEach((track) => track.stop());
        return;
    }

    cameraStream = stream;
    const [track] = stream.getVideoTracks();
    const settings = track?.getSettings?.() || {};
    activeCameraDeviceId = settings.deviceId || deviceId;
    preferredCameraFacing = settings.facingMode || facingMode;
    if (track) {
        track.addEventListener('ended', () => {
            if (cameraStream !== stream) return;
            releaseCameraStream();
            setCameraStatus('Camera disconnected. Close this panel and try again.', true);
        }, { once: true });
    }

    elements.cameraVideo.srcObject = stream;
    try {
        await elements.cameraVideo.play();
    } catch (error) {
        if (generation === cameraRequestGeneration) {
            releaseCameraStream();
            setCameraStatus(cameraErrorMessage(error), true);
        }
        return;
    }

    if (generation !== cameraRequestGeneration) {
        // A newer camera may have opened while this older play() was pending.
        // Release only this request's stream, never the current global stream.
        stream.getTracks().forEach((track) => track.stop());
        return;
    }

    const devices = await videoDevices();
    if (generation !== cameraRequestGeneration || cameraStream !== stream) return;
    cameraDevices = devices;
    elements.captureCamera.disabled = false;
    // Some phones expose only the active lens until facingMode changes. Keep
    // Flip reachable so the facing-mode fallback below can still switch it.
    elements.switchCamera.disabled = false;
    setCameraStatus(
        cameraDevices.length > 1
            ? 'Live recognition is running. Center one leaf or fruit; switch cameras if needed.'
            : 'Live recognition is running. Center one leaf or fruit in the square.'
    );
    elements.cameraView.classList.add('is-live-scanning');
    const recognitionPromise = runLiveRecognition(generation);
    activeLiveRecognitions.add(recognitionPromise);
    recognitionPromise.finally(() => {
        activeLiveRecognitions.delete(recognitionPromise);
    }).catch(() => {});
}

// Draws a square region of the video (or of a snapshot canvas), halved 2:1 by
// the browser while it stays at least twice the model size, and returns its pixels.
function sampleSquare(source, left, top, side) {
    const steps = [side];
    while (steps.at(-1) / 2 >= LIVE_MIN_SAMPLE_SIDE) steps.push(Math.round(steps.at(-1) / 2));
    const canvas = document.createElement('canvas');
    canvas.width = steps[Math.min(1, steps.length - 1)];
    canvas.height = canvas.width;
    const context = canvas.getContext('2d', { willReadFrequently: true });
    if (!context) return null;
    context.imageSmoothingEnabled = true;
    context.imageSmoothingQuality = 'high';
    context.drawImage(
        source,
        left,
        top,
        side,
        side,
        0,
        0,
        canvas.width,
        canvas.height
    );
    // Further 2:1 steps (4K cameras) halve the canvas onto itself.
    for (let index = 2; index < steps.length; index += 1) {
        const previous = steps[index - 1];
        context.drawImage(canvas, 0, 0, previous, previous, 0, 0, steps[index], steps[index]);
    }
    const sampleSide = steps.at(-1);
    const rgba = context.getImageData(0, 0, sampleSide, sampleSide).data;
    canvas.width = 1;
    canvas.height = 1;
    return { rgba, side: sampleSide };
}

function liveSquareSample() {
    const videoWidth = elements.cameraVideo.videoWidth;
    const videoHeight = elements.cameraVideo.videoHeight;
    if (!videoWidth || !videoHeight) return null;

    const sourceSide = Math.min(videoWidth, videoHeight);
    const sourceX = (videoWidth - sourceSide) / 2;
    const sourceY = (videoHeight - sourceSide) / 2;
    const sample = sampleSquare(elements.cameraVideo, sourceX, sourceY, sourceSide);
    return sample && { ...sample, sourceX, sourceY, sourceSide };
}

// The leaf finder keeps a full-resolution copy of the centre square, taken in
// the same instant as the detector's input, so every leaf is cut from the frame
// its box was found in, however long the other leaves take.
function snapshotLiveSquare(square) {
    const canvas = document.createElement('canvas');
    canvas.width = square.sourceSide;
    canvas.height = square.sourceSide;
    const context = canvas.getContext('2d');
    if (!context) return null;
    context.drawImage(
        elements.cameraVideo,
        square.sourceX,
        square.sourceY,
        square.sourceSide,
        square.sourceSide,
        0,
        0,
        square.sourceSide,
        square.sourceSide
    );
    return canvas;
}

// Antialiased resize to the model size (same as photo mode), as an RGB CHW tensor.
async function squareTensor(rgba, sourceSide, outputSide) {
    const resizedRgb = await resizeRgbAntialiased(
        rgba,
        sourceSide,
        sourceSide,
        outputSide,
        outputSide
    );
    const planeSize = outputSide * outputSide;
    const chw = new Float32Array(planeSize * 3);
    for (let index = 0; index < planeSize; index += 1) {
        const rgbOffset = index * 3;
        chw[index] = Math.round(resizedRgb[rgbOffset]) / 255;
        chw[planeSize + index] = Math.round(resizedRgb[rgbOffset + 1]) / 255;
        chw[(planeSize * 2) + index] = Math.round(resizedRgb[rgbOffset + 2]) / 255;
    }
    return new ort.Tensor('float32', chw, [1, 3, outputSide, outputSide]);
}

async function liveVideoTensor(square = liveSquareSample()) {
    if (!square) return null;
    return squareTensor(square.rgba, square.side, IMAGE_SIZE);
}

// One detected leaf or fruit: a square around its box, cut from the
// full-resolution snapshot of the centre square, so a small leaf keeps its
// detail. It goes through the same 2:1 halving and resize as the whole square.
async function liveLeafTensor(snapshot, box, padding) {
    const squareSide = snapshot.width;
    const [x1, y1, x2, y2] = box;
    const wanted = Math.max(1, Math.min(1, Math.max(x2 - x1, y2 - y1) * padding) * squareSide);
    // Each 2:1 step must be exact, so the side is a multiple of 2 per step.
    let unit = 1;
    while (wanted / (unit * 2) >= LIVE_MIN_SAMPLE_SIDE) unit *= 2;
    const side = Math.max(unit, Math.min(Math.round(wanted / unit), Math.floor(squareSide / unit)) * unit);
    const clamp = (value) => Math.min(Math.max(Math.round(value), 0), squareSide - side);
    const left = clamp((((x1 + x2) / 2) * squareSide) - (side / 2));
    const top = clamp((((y1 + y2) / 2) * squareSide) - (side / 2));
    const sample = sampleSquare(snapshot, left, top, side);
    if (!sample) return null;
    return squareTensor(sample.rgba, sample.side, IMAGE_SIZE);
}

function smoothLiveConditionProbabilities(track, probabilities, family, route = 'base', modelId = route) {
    if (track.conditionFamily !== family || track.conditionRoute !== route) {
        resetLiveConditionTracking(track, family, route);
    }
    const previous = track.conditionSmoothingByModel.get(modelId);
    const smoothed = !previous || previous.length !== probabilities.length
        ? probabilities.slice()
        : probabilities.map((value, index) => (value * 0.62) + (previous[index] * 0.38));
    track.conditionSmoothingByModel.set(modelId, smoothed);
    return smoothed;
}

function smoothLiveCropProbabilities(track, probabilities) {
    if (!track.smoothedCrop || track.smoothedCrop.length !== probabilities.length) {
        track.smoothedCrop = probabilities.slice();
        return track.smoothedCrop;
    }
    track.smoothedCrop = probabilities.map((value, index) =>
        (value * 0.62) + (track.smoothedCrop[index] * 0.38));
    return track.smoothedCrop;
}

function waitForNextLiveFrame(delay, generation = cameraRequestGeneration) {
    return new Promise((resolve) => {
        const started = performance.now();
        const poll = () => {
            const remaining = delay - (performance.now() - started);
            if (generation !== cameraRequestGeneration || remaining <= 0) {
                resolve();
                return;
            }
            window.setTimeout(poll, Math.min(75, remaining));
        };
        window.setTimeout(poll, Math.max(0, Math.min(75, delay)));
    });
}

// Resolves when the camera presents a new frame, so the same frame is never
// analysed twice. Falls back to a short timeout where requestVideoFrameCallback
// is missing or the video has stalled.
function waitForFreshVideoFrame(timeout = LIVE_RETRY_MS) {
    const video = elements.cameraVideo;
    if (typeof video.requestVideoFrameCallback !== 'function') {
        return new Promise((resolve) => window.setTimeout(resolve, Math.min(timeout, 50)));
    }
    return new Promise((resolve) => {
        let handle = 0;
        const timer = window.setTimeout(() => {
            video.cancelVideoFrameCallback?.(handle);
            resolve();
        }, timeout);
        handle = video.requestVideoFrameCallback(() => {
            window.clearTimeout(timer);
            resolve();
        });
    });
}

function recordLiveFrame(frameMs, preprocessMs) {
    liveStats.frames += 1;
    liveStats.lastFrameMs = frameMs;
    liveStats.lastPreprocessMs = preprocessMs;
    liveStats.avgFrameMs = liveStats.frames === 1
        ? frameMs
        : (liveStats.avgFrameMs * 0.8) + (frameMs * 0.2);
}

async function runLiveRecognition(generation) {
    setLiveRecognition('loading', 'Loading live recognition…', 'The models run only in this browser');
    let runtime;
    try {
        runtime = await startRuntime();
    } catch {
        if (generation === cameraRequestGeneration && cameraStream) {
            setLiveRecognition('error', 'Live AI is unavailable', 'Reload this page to restart local AI; camera capture still works');
        }
        return;
    }

    liveLoopGeneration = generation;
    Object.assign(liveStats, { running: true, frames: 0, lastFrameMs: 0, avgFrameMs: 0, lastPreprocessMs: 0 });
    try {
        while (generation === cameraRequestGeneration && cameraStream) {
            const busyMs = await analyseLiveFrame(runtime, generation);
            if (busyMs === null) return;
            const restMs = Math.min(
                LIVE_MAX_REST_MS,
                Math.max(LIVE_MIN_PERIOD_MS, busyMs * 2) - busyMs
            );
            await waitForNextLiveFrame(restMs, generation);
            if (generation !== cameraRequestGeneration || !cameraStream) return;
            await waitForFreshVideoFrame();
        }
    } finally {
        if (liveLoopGeneration === generation) liveStats.running = false;
    }
}

function showLiveStatus(status) {
    setLiveRecognition(status.state, status.crop, status.condition);
    announceLiveRecognition(status.announcement);
    if (status.spray !== undefined) setLiveSpray(status.spray);
}

// Runs the crop/type gate, the condition route and the frame vote for one live
// track (the whole square, or one leaf found by the leaf finder) and returns
// what that track may show. Every safeguard applies to each track on its own
// smoothed scores and its own votes. Returns null when this camera session ended.
async function assessLiveTrack(runtime, track, tensor, isCurrent, onCheckingCondition = null) {
    const cropProbabilities = await runClassifier(
        runtime.cropViewSession,
        tensor,
        runtime.metadata.cropViewClasses.length,
        'The live crop/view model'
    );
    if (!isCurrent()) return null;

    const smoothed = smoothLiveCropProbabilities(track, cropProbabilities);
    const rankedCropViews = rankClasses(smoothed, runtime.metadata.cropViewClasses);
    const topCropView = rankedCropViews[0];
    const parsed = parseCropView(topCropView.label);
    const abstention = cropAbstention(
        rankedCropViews,
        parsed,
        runtime.metadata.thresholds
    );

    if (abstention) {
        // Losing the crop clears any shown verdict at once; no hold-over.
        resetLiveConditionTracking(track);
        return {
            state: 'uncertain',
            crop: parsed.crop
                ? `Possible ${displayCropName(parsed.crop, parsed.view)} ${parsed.view}`
                : 'No supported crop yet',
            condition: parsed.crop
                ? `${scorePercent(topCropView.confidence)} weak match · keep one crop centered`
                : 'Fill the square with an apple, tomato, cucumber, or lemon',
            announcement: parsed.crop
                ? 'Crop match is not reliable yet.'
                : 'No supported crop is recognized yet.',
            spray: sprayReadoutFor(runtime, null, 'abstain'),
        };
    }

    const cropDisplay = displayCropName(parsed.crop, parsed.view);
    const cropLabel = `${cropDisplay} ${parsed.view}`;
    const family = `${parsed.crop}_${parsed.view}`;
    const routeId = conditionRouteId(runtime, family);
    if (track.conditionFamily !== family || track.conditionRoute !== routeId) {
        resetLiveConditionTracking(track, family, routeId);
    }
    if (liveSpecialistLoading(runtime, parsed.crop, parsed.view)) {
        return {
            state: 'loading',
            crop: cropLabel,
            condition: `${scorePercent(topCropView.confidence)} crop match · loading its condition model…`,
            announcement: `${cropLabel} identified. Loading its condition model.`,
            spray: sprayReadoutFor(runtime, null, 'loading'),
        };
    }
    if (!track.conditionDisplayReady && onCheckingCondition) {
        onCheckingCondition({
            state: 'identified',
            crop: cropLabel,
            condition: `${scorePercent(topCropView.confidence)} crop match · checking condition…`,
            announcement: `${cropLabel} identified. Checking condition.`,
        });
    }

    const identity = Object.freeze({
        crop: parsed.crop,
        organ: parsed.view,
        overridden: false,
        topCropView,
        automaticLabel: humanizeClass(topCropView.label),
    });
    const evaluated = await assessConditionRoute(
        runtime,
        identity,
        tensor,
        {
            live: true,
            isCurrent,
            smooth: (probabilities, route, modelId) =>
                smoothLiveConditionProbabilities(track, probabilities, family, route, modelId),
        }
    );
    if (!evaluated) return null;
    const assessment = evaluated.assessment;
    track.conditionDisplayReady = true;

    if (!assessment) {
        track.votes = [];
        track.shown = null;
        return {
            state: 'identified',
            crop: cropLabel,
            condition: `${scorePercent(topCropView.confidence)} crop match · no covered condition for this view`,
            announcement: `${cropLabel} identified. No covered condition is available for this view.`,
            spray: sprayReadoutFor(runtime, null, 'nocondition'),
        };
    }
    const passed = assessment.result.certainty === 'high-confidence screen'
        || assessment.result.certainty === 'healthy-like pattern';
    const sprayText = passed && evaluated.spray ? ` · ${sprayChipText(evaluated.spray)}` : '';
    const vote = voteLiveVerdict(
        track,
        passed ? `${family}|${assessment.result.certainty}|${assessment.result.condition}` : '',
        passed ? `${assessment.result.condition} · ${scorePercent(assessment.result.conditionScore)}${sprayText}` : ''
    );
    if (vote.shown) {
        return {
            state: 'identified',
            crop: cropLabel,
            condition: vote.shown.text,
            announcement: `${cropLabel}. ${vote.shown.text.split(' · ')[0]}.`,
            // The dose follows the same vote as the label: it appears only with a held verdict.
            spray: sprayReadoutFor(runtime, passed ? evaluated.spray : null, 'shown'),
        };
    }
    if (passed) {
        return {
            state: 'loading',
            crop: cropLabel,
            condition: `Condition pattern found · confirming (${vote.pending}/${LIVE_VOTES_TO_SHOW})…`,
            announcement: `${cropLabel} identified. Checking condition.`,
            spray: sprayReadoutFor(runtime, null, 'confirming'),
        };
    }
    return {
        state: 'uncertain',
        crop: cropLabel,
        condition: 'Condition not reliable yet · hold steady or move closer',
        announcement: `${cropLabel} identified. Condition is not reliable yet.`,
        spray: sprayReadoutFor(runtime, null, 'uncertain'),
    };
}

// Analyses one live frame. Returns the milliseconds of work done, or null when
// this camera session ended (or hit a terminal error) and the loop must stop.
async function analyseLiveFrame(runtime, generation) {
    const isCurrent = () => generation === cameraRequestGeneration && Boolean(cameraStream);
    const started = performance.now();
    let tensor = null;
    try {
        if (runtime.leafDetector && !leafFinderFailed) return await analyseLiveLeaves(runtime, isCurrent, started);

        tensor = await liveVideoTensor();
        const preprocessMs = performance.now() - started;
        if (!isCurrent()) return null;
        if (!tensor) return 0;

        const status = await assessLiveTrack(runtime, liveSquareTrack, tensor, isCurrent, showLiveStatus);
        if (!status) return null;
        showLiveStatus(status);
        recordLiveFrame(performance.now() - started, preprocessMs);
        return performance.now() - started;
    } catch (error) {
        if (!isCurrent()) return null;
        resetLiveConditionTracking(liveSquareTrack);
        liveLeafTracks.forEach((track) => resetLiveConditionTracking(track));
        renderLiveLeafBoxes([]);
        liveStats.leaves = [];
        if (error instanceof VisionError && error.code === 'specialist') {
            setLiveRecognition('error', 'Live condition model unavailable', error.message);
            announceLiveRecognition(error.message);
            return null;
        }
        setLiveRecognition('error', 'Live scan paused', 'Hold steady while CropSCOUT retries');
        announceLiveRecognition('Live scan paused.');
        return performance.now() - started;
    } finally {
        if (tensor && typeof tensor.dispose === 'function') tensor.dispose();
    }
}

/* =========================== Leaf finder ===========================
 *
 * Optional (add ?detector=1 to the page URL, and the release metadata must
 * list the model). A small YOLO26n detector finds each tomato leaf or fruit in
 * the centre square. Each one is cut from the full-resolution video and runs
 * through the same crop/type gate, condition safeguards and 3-of-4 vote as
 * the whole square, as its own track:
 *
 *   - When one box fills most of the square, or nothing is found, the whole
 *     square is analysed exactly as without the finder, so a close-up gets the
 *     same result as photo mode.
 *   - A track follows a leaf across frames by box overlap. A frame where the
 *     finder misses the leaf counts like a frame that failed a safeguard: an
 *     empty vote, which can withdraw a verdict but never confirm one. Two
 *     misses in a row end the track. Switching between the whole square and
 *     separate leaves starts every track from scratch; going back to the whole
 *     square needs two frames in a row.
 *   - Every leaf is cut from a full-resolution copy of the square taken with
 *     the detector's input, so a slow frame never mixes two video frames.
 *   - A finder that fails is switched off and the whole square is analysed.
 *   - The finder only decides where to look. It never changes a score or a
 *     threshold.
 */

function boxSide(box) {
    return Math.max(box[2] - box[0], box[3] - box[1]);
}

function boxIou(a, b) {
    const width = Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0]));
    const height = Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
    const overlap = width * height;
    const union = ((a[2] - a[0]) * (a[3] - a[1])) + ((b[2] - b[0]) * (b[3] - b[1])) - overlap;
    return union > 0 ? overlap / union : 0;
}

// The detector is exported end-to-end (no NMS step): 1 x N x 6 rows of
// x1, y1, x2, y2 (input pixels), score, class.
async function runLeafDetector(detector, input) {
    const inputName = detector.session.inputNames[0];
    const outputName = detector.session.outputNames[0];
    const outputs = await queueOnnxOperation(() => detector.session.run({ [inputName]: input }));
    const output = outputs[outputName];
    if (!output) throw new VisionError('model', 'The leaf finder returned no output.');
    try {
        if (output.dims.length !== 3 || output.dims[0] !== 1 || output.dims[2] !== 6) {
            throw new VisionError('model', 'The leaf finder returned an unexpected output.');
        }
        const data = output.data;
        const size = detector.inputSize;
        const clamp = (value) => Math.min(1, Math.max(0, value / size));
        const found = [];
        for (let row = 0; row < output.dims[1]; row += 1) {
            const offset = row * 6;
            const score = data[offset + 4];
            if (!(score >= detector.scoreThreshold)) continue;
            const box = [clamp(data[offset]), clamp(data[offset + 1]), clamp(data[offset + 2]), clamp(data[offset + 3])];
            if (box[2] <= box[0] || box[3] <= box[1]) continue;
            found.push({ box, score, kind: detector.classes[Math.round(data[offset + 5])] || 'unknown' });
        }
        return found;
    } finally {
        if (typeof output.dispose === 'function') output.dispose();
    }
}

// Matches this frame's boxes to the leaves already being followed and returns
// the tracks to classify now (at most maxLeaves, best boxes first).
function matchLiveLeafTracks(detections, detector) {
    const candidates = [];
    detections
        .filter((detection) => boxSide(detection.box) >= detector.minBoxSide)
        .sort((left, right) => right.score - left.score)
        .forEach((detection) => {
            // One object boxed twice (say as leaf and as fruit) keeps its best box.
            if (candidates.length >= detector.maxLeaves
                || candidates.some((kept) => boxIou(kept.box, detection.box) > LIVE_DUPLICATE_IOU)) return;
            candidates.push(detection);
        });
    const pairs = [];
    liveLeafTracks.forEach((track) => candidates.forEach((detection) => {
        const overlap = boxIou(track.box, detection.box);
        if (overlap >= LIVE_TRACK_MIN_IOU) pairs.push({ track, detection, overlap });
    }));
    pairs.sort((left, right) => right.overlap - left.overlap);

    const active = new Set();
    const used = new Set();
    pairs.forEach(({ track, detection }) => {
        if (active.has(track) || used.has(detection)) return;
        active.add(track);
        used.add(detection);
        Object.assign(track, { box: detection.box, score: detection.score, kind: detection.kind, misses: 0 });
    });
    liveLeafTracks = liveLeafTracks.filter((track) => {
        if (active.has(track)) return true;
        track.misses += 1;
        voteLiveVerdict(track, '', '');
        return track.misses < LIVE_TRACK_MAX_MISSES;
    });
    candidates.forEach((detection) => {
        if (used.has(detection)) return;
        const track = createLiveTrack(liveNextTrackId, detection.box);
        liveNextTrackId += 1;
        Object.assign(track, { score: detection.score, kind: detection.kind });
        liveLeafTracks.push(track);
        active.add(track);
    });
    return liveLeafTracks.filter((track) => active.has(track));
}

// Display order only: a shown verdict first (a disease before a healthy-like
// pattern), then a leaf still being confirmed, then the biggest leaf.
function liveLeafRank(track) {
    const shown = track.shown ? (track.shown.key.includes('|high-confidence screen|') ? 3 : 2) : 0;
    const pending = track.status?.state === 'loading' ? 1 : 0;
    return (shown * 10) + pending + boxSide(track.box);
}

function shortLiveLabel(track) {
    if (track.shown) {
        const name = track.shown.text.split(' · ')[0];
        return name === conditionDisplayName({ healthy: true }) ? 'healthy-like' : name;
    }
    if (track.status?.state === 'uncertain') return 'not sure';
    return 'checking…';
}

function renderLiveLeafBoxes(tracks) {
    const layer = elements.liveLeafBoxes;
    if (!layer) return;
    layer.replaceChildren(...tracks.map((track) => {
        const [x1, y1, x2, y2] = track.box;
        const outline = document.createElement('div');
        outline.className = `live-leaf-box is-${track.shown ? 'identified' : (track.status?.state || 'loading')}`;
        outline.classList.toggle('is-at-top', y1 < 0.06);
        outline.style.left = `${(x1 * 100).toFixed(2)}%`;
        outline.style.top = `${(y1 * 100).toFixed(2)}%`;
        outline.style.width = `${((x2 - x1) * 100).toFixed(2)}%`;
        outline.style.height = `${((y2 - y1) * 100).toFixed(2)}%`;
        const label = document.createElement('span');
        label.textContent = shortLiveLabel(track);
        outline.append(label);
        return outline;
    }));
    layer.hidden = tracks.length === 0;
}

function showLiveLeaves(tracks) {
    const ranked = tracks.filter((track) => track.status).sort((left, right) => liveLeafRank(right) - liveLeafRank(left));
    renderLiveLeafBoxes(ranked);
    liveStats.leaves = ranked.map((track) => ({
        id: track.id,
        box: track.box.map((value) => Math.round(value * 1000) / 1000),
        score: Math.round(track.score * 1000) / 1000,
        kind: track.kind,
        state: track.status.state,
        crop: track.status.crop,
        condition: track.status.condition,
        shown: track.shown?.key || '',
    }));
    const primary = ranked[0];
    if (!primary) {
        setLiveRecognition('uncertain', 'Leaves are too small', 'Move closer so each leaf is bigger in the square');
        announceLiveRecognition('Leaves are too small. Move closer.');
        setLiveSpray(SPRAY_IDLE);
        return;
    }
    const crop = ranked.length > 1 ? `${primary.status.crop} · ${ranked.length} found` : primary.status.crop;
    setLiveRecognition(primary.status.state, crop, primary.status.condition);
    announceLiveRecognition(primary.status.announcement);
    // With several leaves, the readout follows the one that needs the most spray.
    const sprays = ranked.map((track) => track.status.spray).filter(Boolean);
    if (sprays.length > 0) {
        const worst = sprays.reduce((best, item) => (item.percent > best.percent ? item : best), sprays[0]);
        const confirmed = sprays.find((item) => item.tone === 'remove');
        setLiveSpray(confirmed && worst.percent === 0 ? confirmed : worst);
    }
}

function recordDetectorTime(detectorMs) {
    liveStats.lastDetectorMs = detectorMs;
    liveStats.avgDetectorMs = liveStats.frames === 0
        ? detectorMs
        : (liveStats.avgDetectorMs * 0.8) + (detectorMs * 0.2);
}

async function findLeaves(detector, square) {
    const input = await squareTensor(square.rgba, square.side, detector.inputSize);
    try {
        return await runLeafDetector(detector, input);
    } finally {
        if (typeof input.dispose === 'function') input.dispose();
    }
}

// A leaf finder that fails (a model that does not fit its metadata, say) is
// switched off for this page, and live mode goes on with the whole square.
function disableLeafFinder() {
    leafFinderFailed = true;
    if (elements.cameraGuideCopy) elements.cameraGuideCopy.textContent = 'Everything inside this square will be analyzed';
    setModelState('ready', `${elements.modelStateText.textContent.replace(/ · leaf finder.*$/, '')} · leaf finder unavailable`);
}

async function analyseLiveLeaves(runtime, isCurrent, started) {
    const detector = runtime.leafDetector;
    const square = liveSquareSample();
    // Taken in the same task as the detector's input, so from the same video frame.
    const snapshot = square && snapshotLiveSquare(square);
    try {
        if (!isCurrent()) return null;
        if (!square || !snapshot) return 0;

        const detectorStarted = performance.now();
        let detections;
        try {
            detections = await findLeaves(detector, square);
        } catch {
            if (!isCurrent()) return null;
            disableLeafFinder();
            detections = [];
        }
        if (!isCurrent()) return null;
        const detectorMs = performance.now() - detectorStarted;
        const largest = detections.reduce((best, detection) => Math.max(best, boxSide(detection.box)), 0);
        const wantsSquare = detections.length === 0 || largest >= detector.wholeSquareSide;
        // Splitting into leaves takes one frame. Going back to the whole square
        // takes LIVE_TRACK_MAX_MISSES frames in a row, as ending a leaf track does.
        liveSquareStreak = wantsSquare && liveStats.mode === 'leaves' ? liveSquareStreak + 1 : 0;
        const useSquare = wantsSquare
            && (liveStats.mode !== 'leaves' || liveSquareStreak >= LIVE_TRACK_MAX_MISSES || leafFinderFailed);
        let preprocessMs = detectorStarted - started;

        if (useSquare) {
            if (liveStats.mode !== 'square') {
                liveSquareTrack = createLiveTrack('square');
                liveLeafTracks = [];
                liveSquareStreak = 0;
                renderLiveLeafBoxes([]);
                liveStats.leaves = [];
            }
            liveStats.mode = 'square';
            const resizeStarted = performance.now();
            const tensor = await squareTensor(square.rgba, square.side, IMAGE_SIZE);
            preprocessMs += performance.now() - resizeStarted;
            try {
                if (!isCurrent()) return null;
                const status = await assessLiveTrack(runtime, liveSquareTrack, tensor, isCurrent, showLiveStatus);
                if (!status) return null;
                showLiveStatus(status);
            } finally {
                if (typeof tensor.dispose === 'function') tensor.dispose();
            }
        } else {
            if (liveStats.mode !== 'leaves') {
                liveSquareTrack = createLiveTrack('square');
                liveLeafTracks = [];
            }
            liveStats.mode = 'leaves';
            const active = matchLiveLeafTracks(detections, detector);
            for (const track of active) {
                const cropStarted = performance.now();
                const tensor = await liveLeafTensor(snapshot, track.box, detector.cropPadding);
                preprocessMs += performance.now() - cropStarted;
                if (!tensor) continue;
                try {
                    if (!isCurrent()) return null;
                    track.status = await assessLiveTrack(runtime, track, tensor, isCurrent);
                    if (!track.status) return null;
                } finally {
                    if (typeof tensor.dispose === 'function') tensor.dispose();
                }
            }
            // Leaves missed this frame stay on screen until their track ends;
            // their empty vote has already been counted.
            showLiveLeaves(liveLeafTracks);
        }
        recordDetectorTime(detectorMs);
        recordLiveFrame(performance.now() - started, preprocessMs);
        return performance.now() - started;
    } finally {
        if (snapshot) {
            snapshot.width = 1;
            snapshot.height = 1;
        }
    }
}

async function captureCameraFrame() {
    const videoWidth = elements.cameraVideo.videoWidth;
    const videoHeight = elements.cameraVideo.videoHeight;
    if (!cameraStream || !videoWidth || !videoHeight) {
        setCameraStatus('The camera frame is not ready yet. Wait a moment and try again.', true);
        return;
    }

    elements.captureCamera.disabled = true;
    setCameraStatus('Capturing photo on this device…');
    const generation = cameraRequestGeneration;
    const sourceSide = Math.min(videoWidth, videoHeight);
    const sourceX = (videoWidth - sourceSide) / 2;
    const sourceY = (videoHeight - sourceSide) / 2;
    const outputSide = Math.max(1, Math.min(2048, Math.round(sourceSide)));
    const canvas = document.createElement('canvas');
    canvas.width = outputSide;
    canvas.height = outputSide;
    const context = canvas.getContext('2d');
    if (!context) {
        setCameraStatus('This browser could not capture the frame. Try a saved photo instead.', true);
        elements.captureCamera.disabled = false;
        return;
    }
    context.drawImage(
        elements.cameraVideo,
        sourceX,
        sourceY,
        sourceSide,
        sourceSide,
        0,
        0,
        outputSide,
        outputSide
    );

    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.92));
    context.clearRect(0, 0, canvas.width, canvas.height);
    canvas.width = 1;
    canvas.height = 1;
    if (generation !== cameraRequestGeneration || !cameraStream) return;
    if (!(blob instanceof Blob)) {
        setCameraStatus('This browser could not save the camera frame. Try again or choose a saved photo.', true);
        elements.captureCamera.disabled = false;
        return;
    }

    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const file = new File([blob], `cropscout-camera-${timestamp}.jpg`, {
        type: 'image/jpeg',
        lastModified: Date.now(),
    });
    selectFile(file);
}

async function switchCameraDevice() {
    if (!cameraStream) return;
    const stream = cameraStream;
    const generation = cameraRequestGeneration;
    cameraDevices = await videoDevices();
    if (generation !== cameraRequestGeneration || cameraStream !== stream) return;
    if (cameraDevices.length > 1) {
        const currentIndex = cameraDevices.findIndex((device) => device.deviceId === activeCameraDeviceId);
        const next = cameraDevices[(currentIndex + 1 + cameraDevices.length) % cameraDevices.length];
        await requestCamera({ deviceId: next.deviceId });
        return;
    }
    preferredCameraFacing = preferredCameraFacing === 'environment' ? 'user' : 'environment';
    await requestCamera({ facingMode: preferredCameraFacing });
}

function isPlainObject(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function requireText(value, path) {
    if (typeof value !== 'string' || !value.trim()) {
        throw new VisionError('metadata', `Model metadata field ${path} must be a non-empty string.`);
    }
    return value.trim();
}

function optionalText(value, path) {
    if (value === null) return null;
    return requireText(value, path);
}

function requireThreshold(value, path) {
    if (!Number.isFinite(value) || value < 0 || value > 1) {
        throw new VisionError('metadata', `Model metadata field ${path} must be between 0 and 1.`);
    }
    return value;
}

function optionalThreshold(value, path, fallback) {
    return value === undefined ? fallback : requireThreshold(value, path);
}

function normalizeFamilyThresholds(value, path) {
    if (value === undefined) return Object.freeze({});
    if (!isPlainObject(value)) {
        throw new VisionError('metadata', `Model metadata field ${path} must be an object.`);
    }
    const thresholds = {};
    Object.entries(value).forEach(([family, threshold]) => {
        if (!/^(Apple|Tomato|Cucumber|Lemon)_(fruit|leaf)$/.test(family)) {
            throw new VisionError('metadata', `Model metadata field ${path} has an invalid crop/organ key.`);
        }
        thresholds[family] = requireThreshold(threshold, `${path}.${family}`);
    });
    return Object.freeze(thresholds);
}

function requireSha256(value, path, optional = false) {
    if (optional && value === undefined) return null;
    if (typeof value !== 'string' || !/^[a-f0-9]{64}$/i.test(value)) {
        throw new VisionError('metadata', `Model metadata field ${path} must be a SHA-256 digest.`);
    }
    return value.toLowerCase();
}

function normalizeDiseaseClasses(entries, schemaVersion, field) {
    if (!Array.isArray(entries) || entries.length === 0) {
        throw new VisionError('metadata', `Model metadata field ${field} must contain condition classes.`);
    }
    const labels = new Set();
    return Object.freeze(entries.map((entry, index) => {
        const path = `${field}[${index}]`;
        if (!isPlainObject(entry)) {
            throw new VisionError('metadata', `Model metadata field ${path} must be an object.`);
        }
        if (typeof entry.healthy !== 'boolean') {
            throw new VisionError('metadata', `Model metadata field ${path}.healthy must be true or false.`);
        }
        if (!Array.isArray(entry.actions) || entry.actions.some((action) => typeof action !== 'string' || !action.trim())) {
            throw new VisionError('metadata', `Model metadata field ${path}.actions must be a list of instructions.`);
        }
        const organValue = schemaVersion >= 2
            ? requireText(entry.organ, `${path}.organ`).toLowerCase()
            : (typeof entry.organ === 'string' ? entry.organ.trim().toLowerCase() : 'leaf');
        if (organValue !== 'fruit' && organValue !== 'leaf') {
            throw new VisionError('metadata', `Model metadata field ${path}.organ must be fruit or leaf.`);
        }
        const label = requireText(entry.label, `${path}.label`);
        if (labels.has(label)) throw new VisionError('metadata', `Duplicate condition class in ${field}.`);
        labels.add(label);
        return Object.freeze({
            label,
            crop: optionalText(entry.crop, `${path}.crop`),
            cropDisplay: entry.crop_display == null
                ? optionalText(entry.crop, `${path}.crop`)
                : requireText(entry.crop_display, `${path}.crop_display`),
            organ: organValue,
            condition: entry.condition == null ? null : requireText(entry.condition, `${path}.condition`),
            diagnosis: requireText(entry.diagnosis, `${path}.diagnosis`),
            healthy: entry.healthy,
            cause: requireText(entry.cause, `${path}.cause`),
            urgency: requireText(entry.urgency, `${path}.urgency`),
            actions: Object.freeze(entry.actions.map((action) => action.trim())),
        });
    }));
}

function normalizeConditionSpecialists(value, schemaVersion, cropViewClasses) {
    if (value === undefined) return Object.freeze([]);
    if (!Array.isArray(value) || value.length > Object.keys(SPECIALIST_FAMILIES).length) {
        throw new VisionError('metadata', 'Model metadata condition_specialists must contain at most one entry per supported specialist.');
    }
    const seen = new Set();
    return Object.freeze(value.map((entry, index) => {
        const path = `condition_specialists[${index}]`;
        if (!isPlainObject(entry) || typeof entry.id !== 'string'
            || !Object.prototype.hasOwnProperty.call(SPECIALIST_FAMILIES, entry.id)
            || seen.has(entry.id)
            || !Array.isArray(entry.families) || entry.families.length !== 1
            || entry.families[0] !== SPECIALIST_FAMILIES[entry.id]
            || !cropViewClasses.includes(SPECIALIST_FAMILIES[entry.id])) {
            throw new VisionError('metadata', `Model metadata field ${path} must use a unique fixed leaf specialist and its matching family.`);
        }
        seen.add(entry.id);
        const classes = normalizeDiseaseClasses(entry.classes, schemaVersion, `${path}.classes`);
        const familyClasses = classes.filter(
            condition => `${condition.crop}_${condition.organ}` === SPECIALIST_FAMILIES[entry.id]
        );
        if (familyClasses.length === 0) {
            throw new VisionError('metadata', `The ${entry.id} specialist has no matching leaf conditions.`);
        }
        let routingPolicyId = null;
        let specialistMinConfidence = null;
        if (entry.id === 'lemon-leaf') {
            routingPolicyId = requireText(entry.routing_policy_id, `${path}.routing_policy_id`);
            if (routingPolicyId !== LEMON_HYBRID_POLICY_ID) {
                throw new VisionError('metadata', `The lemon-leaf specialist must use routing policy ${LEMON_HYBRID_POLICY_ID}.`);
            }
            specialistMinConfidence = requireThreshold(
                entry.specialist_min_confidence,
                `${path}.specialist_min_confidence`
            );
            if (specialistMinConfidence !== LEMON_SPECIALIST_MIN_CONFIDENCE) {
                throw new VisionError('metadata', `The lemon-leaf specialist must use a ${LEMON_SPECIALIST_MIN_CONFIDENCE} minimum confidence.`);
            }
            if (!familyClasses.some(condition => condition.healthy)
                || !familyClasses.some(condition => !condition.healthy)) {
                throw new VisionError('metadata', 'The lemon-leaf specialist must include healthy and nonhealthy lemon-leaf conditions.');
            }
        }
        return Object.freeze({
            id: entry.id,
            families: Object.freeze([...entry.families]),
            classes,
            routingPolicyId,
            specialistMinConfidence,
            checkpointSha256: requireSha256(entry.checkpoint_sha256, `${path}.checkpoint_sha256`),
            onnxSha256: requireSha256(entry.onnx_sha256, `${path}.onnx_sha256`),
        });
    }));
}

// Optional leaf finder entry. It only says where to look; every score and
// threshold that decides a result still comes from the classifiers above.
function normalizeLeafDetector(value) {
    if (value === undefined) return null;
    const path = 'leaf_detector';
    if (!isPlainObject(value)) {
        throw new VisionError('metadata', `Model metadata field ${path} must be an object.`);
    }
    const inputSize = value.input_size;
    if (!Number.isInteger(inputSize) || inputSize < 64 || inputSize > 1024 || inputSize % 32 !== 0) {
        throw new VisionError('metadata', `Model metadata field ${path}.input_size must be a multiple of 32.`);
    }
    if (!Array.isArray(value.classes) || value.classes.length === 0) {
        throw new VisionError('metadata', `Model metadata field ${path}.classes must list the box classes.`);
    }
    const maxLeaves = value.max_leaves;
    if (!Number.isInteger(maxLeaves) || maxLeaves < 1 || maxLeaves > 6) {
        throw new VisionError('metadata', `Model metadata field ${path}.max_leaves must be 1 to 6.`);
    }
    const cropPadding = value.crop_padding;
    if (!Number.isFinite(cropPadding) || cropPadding < 1 || cropPadding > 2) {
        throw new VisionError('metadata', `Model metadata field ${path}.crop_padding must be between 1 and 2.`);
    }
    return Object.freeze({
        inputSize,
        classes: Object.freeze(value.classes.map((label, index) => requireText(label, `${path}.classes[${index}]`))),
        scoreThreshold: requireThreshold(value.score_threshold, `${path}.score_threshold`),
        minBoxSide: requireThreshold(value.min_box_side, `${path}.min_box_side`),
        wholeSquareSide: requireThreshold(value.whole_square_side, `${path}.whole_square_side`),
        maxLeaves,
        cropPadding,
        onnxSha256: requireSha256(value.onnx_sha256, `${path}.onnx_sha256`),
    });
}

// A malformed leaf finder entry turns the finder off; it never stops the page.
function optionalLeafDetector(value) {
    try {
        return normalizeLeafDetector(value);
    } catch (error) {
        return Object.freeze({ invalid: error instanceof Error ? error.message : 'invalid entry' });
    }
}

function validateMetadata(payload) {
    if (!isPlainObject(payload) || payload.schema_version === undefined) {
        throw new VisionError('metadata', 'Model metadata is missing its schema version.');
    }
    if (!isPlainObject(payload.thresholds)) {
        throw new VisionError('metadata', 'Model metadata is missing screening thresholds.');
    }
    if (!isPlainObject(payload.crop_view) || !Array.isArray(payload.crop_view.classes)) {
        throw new VisionError('metadata', 'Model metadata is missing crop/view classes.');
    }
    if (!isPlainObject(payload.disease) || !Array.isArray(payload.disease.classes)) {
        throw new VisionError('metadata', 'Model metadata is missing disease classes.');
    }

    const schemaVersion = Number(payload.schema_version);
    if (!Number.isInteger(schemaVersion) || schemaVersion < 1) {
        throw new VisionError('metadata', 'Model metadata has an invalid schema version.');
    }

    const thresholds = Object.freeze({
        cropConfidence: requireThreshold(payload.thresholds.crop_confidence, 'thresholds.crop_confidence'),
        cropMargin: requireThreshold(payload.thresholds.crop_margin, 'thresholds.crop_margin'),
        conditionConfidence: requireThreshold(payload.thresholds.condition_confidence, 'thresholds.condition_confidence'),
        conditionConfidenceByFamily: normalizeFamilyThresholds(
            payload.thresholds.condition_confidence_by_family,
            'thresholds.condition_confidence_by_family'
        ),
        conditionMargin: requireThreshold(payload.thresholds.condition_margin, 'thresholds.condition_margin'),
        // These v2 guards are intentionally conservative when older metadata is loaded.
        conditionMass: optionalThreshold(payload.thresholds.condition_mass, 'thresholds.condition_mass', 0.35),
        healthyMargin: optionalThreshold(payload.thresholds.healthy_margin, 'thresholds.healthy_margin', 0.10),
    });

    const cropViewClasses = payload.crop_view.classes.map((label, index) =>
        requireText(label, `crop_view.classes[${index}]`));

    const diseaseClasses = normalizeDiseaseClasses(payload.disease.classes, schemaVersion, 'disease.classes');

    if (cropViewClasses.length === 0 || diseaseClasses.length === 0) {
        throw new VisionError('not-installed', 'The exported model metadata has not been installed yet.');
    }

    return Object.freeze({
        schemaVersion,
        thresholds,
        cropViewClasses: Object.freeze(cropViewClasses),
        diseaseClasses: Object.freeze(diseaseClasses),
        cropOnnxSha256: requireSha256(payload.crop_view.onnx_sha256, 'crop_view.onnx_sha256', true),
        diseaseOnnxSha256: requireSha256(payload.disease.onnx_sha256, 'disease.onnx_sha256', true),
        conditionSpecialists: normalizeConditionSpecialists(payload.condition_specialists, schemaVersion, cropViewClasses),
        // Read only behind the flag, so the default page never depends on it.
        leafDetector: LEAF_FINDER_REQUESTED ? optionalLeafDetector(payload.leaf_detector) : null,
    });
}

async function responseExcerpt(response) {
    try {
        return (await response.text()).replace(/\s+/g, ' ').trim().slice(0, 180);
    } catch {
        return '';
    }
}

async function fetchMetadata() {
    const response = await fetch(METADATA_ENDPOINT, {
        credentials: 'omit',
        cache: 'no-store',
        headers: { Accept: 'application/json' },
    });

    const contentType = (response.headers.get('content-type') || '').toLowerCase();
    if (response.redirected || contentType.includes('text/html')) {
        throw new VisionError('metadata', 'The public model endpoint returned a web page instead of model metadata. Reload, or ask the site owner to check the deployment.');
    }
    if (!response.ok) {
        throw new VisionError('metadata', `Could not load model metadata (HTTP ${response.status}).`);
    }
    if (!contentType.includes('application/json') && !contentType.includes('text/json')) {
        throw new VisionError('metadata', `The server returned the wrong metadata content type: ${contentType || 'unknown'}.`);
    }

    try {
        return validateMetadata(await response.json());
    } catch (error) {
        if (error instanceof VisionError) throw error;
        throw new VisionError('metadata', 'The model metadata is not valid JSON.');
    }
}

async function verifyModelBytes(bytes, expectedSha256, label) {
    if (!expectedSha256) return;
    if (!globalThis.crypto?.subtle) {
        throw new VisionError('model', `${label} cannot be verified in this browser.`);
    }
    const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
    const actual = Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('');
    if (actual !== expectedSha256) {
        throw new VisionError('model', `${label} does not match its installed metadata. Reload after the model update is complete.`);
    }
}

async function fetchProtectedModel(url, label, expectedSha256 = null) {
    // Metadata is fetched fresh; key cached binary responses by those same bytes.
    const requestUrl = expectedSha256
        ? `${url}${url.includes('?') ? '&' : '?'}v=${expectedSha256}`
        : url;
    const response = await fetch(requestUrl, {
        credentials: 'omit',
        cache: 'default',
        headers: { Accept: 'application/octet-stream' },
    });
    const contentType = (response.headers.get('content-type') || '').toLowerCase();

    // A failed status first: a static host answers a missing file with an HTML 404 page,
    // and "HTTP 404" says more than "returned a web page".
    if (!response.ok) {
        const detail = contentType.includes('text/html') ? '' : await responseExcerpt(response);
        throw new VisionError(
            'model',
            detail || `${label} could not be loaded (HTTP ${response.status}).`
        );
    }
    if (response.redirected || contentType.includes('text/html')) {
        throw new VisionError('model', 'The public model endpoint returned a web page instead of model data. Reload, or ask the site owner to check the deployment.');
    }
    if (!contentType.includes('application/octet-stream')) {
        throw new VisionError('model', `${label} returned the wrong content type: ${contentType || 'unknown'}.`);
    }

    const bytes = await response.arrayBuffer();
    if (bytes.byteLength === 0) {
        throw new VisionError('model', `${label} is empty.`);
    }
    await verifyModelBytes(bytes, expectedSha256, label);
    return bytes;
}

function routedConditionCount(metadata) {
    const specialists = metadata.conditionSpecialists || [];
    const replacedFamilies = new Set(specialists
        .filter(specialist => specialist.routingPolicyId !== LEMON_HYBRID_POLICY_ID)
        .flatMap(specialist => specialist.families));
    const labels = new Set(metadata.diseaseClasses
        .filter(condition => !replacedFamilies.has(`${condition.crop}_${condition.organ}`))
        .map(condition => condition.label));
    specialists.forEach(specialist => {
        specialist.classes.forEach(condition => {
            if (specialist.families.includes(`${condition.crop}_${condition.organ}`)) {
                labels.add(condition.label);
            }
        });
    });
    return labels.size;
}

async function createRuntime() {
    setModelState('loading', 'checking model metadata');
    const metadata = await fetchMetadata();

    setModelState('loading', 'loading models');
    const [cropViewBytes, diseaseBytes, sprayRules] = await Promise.all([
        fetchProtectedModel(MODEL_ENDPOINTS.cropView, 'The crop/view model', metadata.cropOnnxSha256),
        fetchProtectedModel(MODEL_ENDPOINTS.disease, 'The disease model', metadata.diseaseOnnxSha256),
        // The spray estimate is optional: without rules the page simply shows no estimate.
        loadSprayRules().catch((error) => {
            console.warn('Spray rules unavailable; no spray estimate will be shown.', error);
            return null;
        }),
    ]);

    const sessionOptions = {
        executionProviders: ['wasm'],
        graphOptimizationLevel: 'all',
    };

    setModelState('loading', 'starting local AI');
    // Create sequentially so the WASM backend cannot be initialized twice at once.
    const cropViewSession = await queueOnnxOperation(() => ort.InferenceSession.create(cropViewBytes, sessionOptions));
    const diseaseSession = await queueOnnxOperation(() => ort.InferenceSession.create(diseaseBytes, sessionOptions));

    // The leaf finder is optional: when it is missing or fails its check, live
    // mode keeps analysing the whole square.
    let leafDetector = null;
    let leafFinderNote = '';
    if (metadata.leafDetector?.invalid) {
        leafFinderNote = ' · leaf finder unavailable';
    } else if (metadata.leafDetector) {
        try {
            const bytes = await fetchProtectedModel(
                LEAF_FINDER_ENDPOINT,
                'The leaf finder model',
                metadata.leafDetector.onnxSha256
            );
            const session = await queueOnnxOperation(() => ort.InferenceSession.create(bytes, sessionOptions));
            leafDetector = Object.freeze({ ...metadata.leafDetector, session });
            leafFinderNote = ' · leaf finder on';
        } catch {
            leafFinderNote = ' · leaf finder unavailable';
        }
    } else if (LEAF_FINDER_REQUESTED) {
        leafFinderNote = ' · leaf finder not installed';
    }
    if (leafDetector && elements.cameraGuideCopy) {
        elements.cameraGuideCopy.textContent = 'Each leaf or fruit inside this square is found and checked';
    }

    const runtime = Object.freeze({ metadata, cropViewSession, diseaseSession, leafDetector, sprayRules });
    // A failed eager load is kept like any specialist failure: that crop then
    // reports its condition model as unavailable, it never falls back.
    for (const specialist of metadata.conditionSpecialists) {
        if (!EAGER_SPECIALISTS.includes(specialist.id)) continue;
        const [crop, organ] = specialist.families[0].split('_');
        await resolveConditionModel(runtime, crop, organ).catch(() => {});
    }

    setModelState(
        'ready',
        `${metadata.cropViewClasses.length} crop views · ${routedConditionCount(metadata)} conditions${leafFinderNote}`
    );

    return runtime;
}

function conditionSpecialistForFamily(runtime, family) {
    return (runtime.metadata.conditionSpecialists || [])
        .find(entry => entry.families.includes(family));
}

function baseConditionModel(runtime) {
    return Object.freeze({
        id: 'base',
        session: runtime.diseaseSession,
        classes: runtime.metadata.diseaseClasses,
    });
}

function conditionRouteId(runtime, family) {
    const specialist = conditionSpecialistForFamily(runtime, family);
    return specialist?.routingPolicyId || specialist?.id || 'base';
}

async function resolveConditionModel(runtime, crop, organ) {
    const specialist = conditionSpecialistForFamily(runtime, `${crop}_${organ}`);
    if (!specialist) {
        return baseConditionModel(runtime);
    }
    let sessions = specialistSessions.get(runtime);
    if (!sessions) {
        sessions = new Map();
        specialistSessions.set(runtime, sessions);
    }
    if (!sessions.has(specialist.id)) {
        const label = `The ${crop.toLowerCase()} leaf condition model`;
        const pending = (async () => {
            const bytes = await fetchProtectedModel(
                SPECIALIST_ENDPOINTS[specialist.id],
                label,
                specialist.onnxSha256
            );
            const session = await queueOnnxOperation(() => ort.InferenceSession.create(bytes, {
                executionProviders: ['wasm'],
                graphOptimizationLevel: 'all',
            }));
            return Object.freeze({ id: specialist.id, session, classes: specialist.classes });
        })().catch(() => {
            throw new VisionError('specialist', `${label} could not be loaded or verified. Reload this page to try again.`);
        });
        // Keep failures too: a failed specialist never silently switches models
        // or repeatedly downloads while live capture continues.
        sessions.set(specialist.id, pending);
        pending.then(
            () => settledSpecialistLoads.add(pending),
            () => settledSpecialistLoads.add(pending)
        );
    }
    return sessions.get(specialist.id);
}

// Live mode never waits on a specialist download inside a frame: it starts the
// load and reports true until the model is ready (or has failed for good).
function liveSpecialistLoading(runtime, crop, organ) {
    const specialist = conditionSpecialistForFamily(runtime, `${crop}_${organ}`);
    if (!specialist) return false;
    void resolveConditionModel(runtime, crop, organ).catch(() => {});
    const pending = specialistSessions.get(runtime)?.get(specialist.id);
    return !pending || !settledSpecialistLoads.has(pending);
}

async function resolveConditionRoute(runtime, crop, organ) {
    const family = `${crop}_${organ}`;
    const specialist = conditionSpecialistForFamily(runtime, family);
    if (!specialist) {
        return Object.freeze({ id: 'base', policyId: null, models: Object.freeze([baseConditionModel(runtime)]) });
    }
    const specialistModel = await resolveConditionModel(runtime, crop, organ);
    if (specialist.routingPolicyId === LEMON_HYBRID_POLICY_ID) {
        return Object.freeze({
            id: LEMON_HYBRID_POLICY_ID,
            policyId: LEMON_HYBRID_POLICY_ID,
            specialistMinConfidence: specialist.specialistMinConfidence,
            models: Object.freeze([baseConditionModel(runtime), specialistModel]),
        });
    }
    return Object.freeze({
        id: specialist.id,
        policyId: null,
        models: Object.freeze([specialistModel]),
    });
}

function startRuntime() {
    if (!runtimePromise) {
        runtimePromise = createRuntime().catch((error) => {
            const message = error instanceof Error ? error.message : 'The browser model could not start.';
            setModelState('error', message);
            throw error;
        });
        // The page loads models eagerly; attach a rejection observer until an analysis awaits the same promise.
        runtimePromise.catch(() => {});
    }
    return runtimePromise;
}

function roundHalfToEven(value) {
    const lower = Math.floor(value);
    const fraction = value - lower;
    if (fraction < 0.5) return lower;
    if (fraction > 0.5) return lower + 1;
    return lower % 2 === 0 ? lower : lower + 1;
}

async function decodeImage(file) {
    if (!('createImageBitmap' in window)) {
        throw new VisionError(
            'browser',
            'This browser cannot preserve the original photo colors for reliable screening. Use a current Chrome, Edge, Firefox, or Safari release.'
        );
    }
    try {
        // Training and validation use raw decoded RGB values. Disabling ICC
        // conversion keeps Display-P3/Apple-profiled photos on that contract.
        const bitmap = await createImageBitmap(file, {
            imageOrientation: 'from-image',
            colorSpaceConversion: 'none',
            premultiplyAlpha: 'none',
        });
        return {
            source: bitmap,
            width: bitmap.width,
            height: bitmap.height,
            close: () => bitmap.close(),
        };
    } catch {
        throw new VisionError(
            'image',
            'The photo could not be decoded without changing its embedded color profile. Try a current browser or export a standard JPEG copy.'
        );
    }
}

function antialiasedBilinearContributions(sourceLength, destinationLength) {
    const scale = sourceLength / destinationLength;
    const filterScale = Math.max(1, scale);
    const support = filterScale;
    return Array.from({ length: destinationLength }, (_, outputIndex) => {
        const center = (outputIndex + 0.5) * scale;
        const first = Math.max(0, Math.ceil(center - support - 0.5));
        const last = Math.min(sourceLength - 1, Math.floor(center + support - 0.5));
        const entries = [];
        let total = 0;
        for (let sourceIndex = first; sourceIndex <= last; sourceIndex += 1) {
            const distance = Math.abs(((sourceIndex + 0.5) - center) / filterScale);
            const weight = Math.max(0, 1 - distance);
            if (weight > 0) {
                entries.push([sourceIndex, weight]);
                total += weight;
            }
        }
        return entries.map(([sourceIndex, weight]) => [sourceIndex, weight / total]);
    });
}

// Canvas quality is browser-dependent. This fixed separable filter follows the
// antialiased bilinear resize used for model validation closely enough that the
// same fixture produces matching classes and nearly identical confidence.
// A background tab clamps setTimeout to about one second and stops
// requestAnimationFrame entirely, which would stall a long analysis the moment
// the operator switched away. MessageChannel keeps yielding at full speed while
// hidden and still lets a visible page paint between chunks.
function yieldToBrowser() {
    if (typeof MessageChannel !== 'function') {
        return new Promise((resolve) => setTimeout(resolve, 0));
    }
    return new Promise((resolve) => {
        const channel = new MessageChannel();
        channel.port1.onmessage = () => {
            channel.port1.close();
            resolve();
        };
        channel.port2.postMessage(0);
    });
}

async function resizeRgbAntialiased(rgba, sourceWidth, sourceHeight, destinationWidth, destinationHeight) {
    const horizontalWeights = antialiasedBilinearContributions(sourceWidth, destinationWidth);
    const verticalWeights = antialiasedBilinearContributions(sourceHeight, destinationHeight);
    const horizontal = new Float32Array(sourceHeight * destinationWidth * 3);

    for (let y = 0; y < sourceHeight; y += 1) {
        horizontalWeights.forEach((entries, outputX) => {
            entries.forEach(([sourceX, weight]) => {
                const sourceOffset = ((y * sourceWidth) + sourceX) * 4;
                const destinationOffset = ((y * destinationWidth) + outputX) * 3;
                horizontal[destinationOffset] += rgba[sourceOffset] * weight;
                horizontal[destinationOffset + 1] += rgba[sourceOffset + 1] * weight;
                horizontal[destinationOffset + 2] += rgba[sourceOffset + 2] * weight;
            });
        });
        if (y > 0 && y % 64 === 0) await yieldToBrowser();
    }

    const result = new Float32Array(destinationWidth * destinationHeight * 3);
    for (let outputY = 0; outputY < verticalWeights.length; outputY += 1) {
        const entries = verticalWeights[outputY];
        for (let x = 0; x < destinationWidth; x += 1) {
            const destinationOffset = ((outputY * destinationWidth) + x) * 3;
            entries.forEach(([sourceY, weight]) => {
                const sourceOffset = ((sourceY * destinationWidth) + x) * 3;
                result[destinationOffset] += horizontal[sourceOffset] * weight;
                result[destinationOffset + 1] += horizontal[sourceOffset + 1] * weight;
                result[destinationOffset + 2] += horizontal[sourceOffset + 2] * weight;
            });
        }
        if (outputY > 0 && outputY % 32 === 0) await yieldToBrowser();
    }
    return result;
}

async function preprocessImage(file) {
    const decoded = await decodeImage(file);
    try {
        if (!decoded.width || !decoded.height) {
            throw new VisionError('image', 'The selected image has invalid dimensions.');
        }
        if (decoded.width * decoded.height > MAX_SOURCE_PIXELS) {
            throw new VisionError('image', 'This photo has too many pixels. Resize it below 40 megapixels and try again.');
        }

        const sourceCanvas = document.createElement('canvas');
        sourceCanvas.width = decoded.width;
        sourceCanvas.height = decoded.height;
        const sourceContext = sourceCanvas.getContext('2d', { willReadFrequently: true });
        if (!sourceContext) {
            throw new VisionError('browser', 'This browser cannot prepare images for local analysis.');
        }
        sourceContext.drawImage(decoded.source, 0, 0);
        const rgba = sourceContext.getImageData(0, 0, decoded.width, decoded.height).data;
        let resizedWidth;
        let resizedHeight;
        if (decoded.width <= decoded.height) {
            resizedWidth = IMAGE_SIZE;
            resizedHeight = Math.floor((IMAGE_SIZE * decoded.height) / decoded.width);
        } else {
            resizedHeight = IMAGE_SIZE;
            resizedWidth = Math.floor((IMAGE_SIZE * decoded.width) / decoded.height);
        }
        const resizedRgb = await resizeRgbAntialiased(
            rgba,
            decoded.width,
            decoded.height,
            resizedWidth,
            resizedHeight
        );
        const cropX = roundHalfToEven((resizedWidth - IMAGE_SIZE) / 2);
        const cropY = roundHalfToEven((resizedHeight - IMAGE_SIZE) / 2);
        const planeSize = IMAGE_SIZE * IMAGE_SIZE;
        const chw = new Float32Array(3 * planeSize);
        const channelSums = [0, 0, 0];
        for (let y = 0; y < IMAGE_SIZE; y += 1) {
            for (let x = 0; x < IMAGE_SIZE; x += 1) {
                const inputOffset = ((((y + cropY) * resizedWidth) + x + cropX) * 3);
                const outputOffset = (y * IMAGE_SIZE) + x;
                for (let channel = 0; channel < 3; channel += 1) {
                    const value = Math.round(resizedRgb[inputOffset + channel]) / 255;
                    chw[(channel * planeSize) + outputOffset] = value;
                    channelSums[channel] += value;
                }
            }
        }

        const scaleX = resizedWidth / decoded.width;
        const scaleY = resizedHeight / decoded.height;
        return Object.freeze({
            tensor: new ort.Tensor('float32', chw, [1, 3, IMAGE_SIZE, IMAGE_SIZE]),
            chw,
            channelMeans: Object.freeze(channelSums.map((sum) => sum / planeSize)),
            sourceWidth: decoded.width,
            sourceHeight: decoded.height,
            cropRect: Object.freeze({
                x: cropX / scaleX,
                y: cropY / scaleY,
                width: IMAGE_SIZE / scaleX,
                height: IMAGE_SIZE / scaleY,
            }),
        });
    } finally {
        decoded.close();
    }
}

function readProbabilities(output, expectedCount, modelLabel) {
    const values = Array.from(output.data, Number);
    if (values.length !== expectedCount) {
        throw new VisionError(
            'model',
            `${modelLabel} returned ${values.length} scores, but its metadata defines ${expectedCount}.`
        );
    }
    if (values.some((value) => !Number.isFinite(value) || value < -0.00001 || value > 1.00001)) {
        throw new VisionError('model', `${modelLabel} did not return probabilities.`);
    }

    const probabilitySum = values.reduce((sum, value) => sum + value, 0);
    if (Math.abs(probabilitySum - 1) > 0.05) {
        throw new VisionError('model', `${modelLabel} output is not a probability distribution.`);
    }

    // Ultralytics classification ONNX exports already contain Softmax. Never apply it again.
    return values.map((value) => Math.max(0, Math.min(1, value)));
}

async function runClassifier(session, input, expectedCount, modelLabel) {
    const inputName = session.inputNames[0];
    const outputName = session.outputNames[0];
    if (!inputName || !outputName) {
        throw new VisionError('model', `${modelLabel} has an invalid input or output contract.`);
    }

    const outputs = await queueOnnxOperation(() => session.run({ [inputName]: input }));
    const output = outputs[outputName];
    if (!output) {
        throw new VisionError('model', `${modelLabel} did not return its expected output.`);
    }
    try {
        return readProbabilities(output, expectedCount, modelLabel);
    } finally {
        if (typeof output.dispose === 'function') output.dispose();
    }
}

function clearEvidenceOverlay() {
    lastEvidence = null;
    const context = elements.overlay.getContext('2d');
    if (context) context.clearRect(0, 0, elements.overlay.width, elements.overlay.height);
    elements.overlay.hidden = true;
    elements.evidenceLegend.hidden = true;
    elements.evidenceNote.hidden = true;
}

function occludedTensor(prepared, row, column) {
    const values = new Float32Array(prepared.chw);
    const cellSize = IMAGE_SIZE / EVIDENCE_GRID_SIZE;
    const startX = column * cellSize;
    const startY = row * cellSize;
    const planeSize = IMAGE_SIZE * IMAGE_SIZE;

    for (let channel = 0; channel < 3; channel += 1) {
        const planeOffset = channel * planeSize;
        const fillValue = prepared.channelMeans[channel];
        for (let y = startY; y < startY + cellSize; y += 1) {
            const rowOffset = planeOffset + (y * IMAGE_SIZE);
            values.fill(fillValue, rowOffset + startX, rowOffset + startX + cellSize);
        }
    }
    return new ort.Tensor('float32', values, [1, 3, IMAGE_SIZE, IMAGE_SIZE]);
}

async function buildEvidenceMap(session, prepared, classIndex, classCount, baselineConfidence, isCurrent) {
    const effects = [];
    for (let row = 0; row < EVIDENCE_GRID_SIZE; row += 1) {
        for (let column = 0; column < EVIDENCE_GRID_SIZE; column += 1) {
            if (!isCurrent()) return null;
            const tensor = occludedTensor(prepared, row, column);
            try {
                const probabilities = await runClassifier(
                    session,
                    tensor,
                    classCount,
                    'The condition evidence model'
                );
                effects.push(Math.max(0, baselineConfidence - probabilities[classIndex]));
            } finally {
                if (typeof tensor.dispose === 'function') tensor.dispose();
            }
        }
        // Let the browser paint its progress state between inference rows.
        await yieldToBrowser();
    }

    const maximumDrop = Math.max(...effects);
    if (!Number.isFinite(maximumDrop) || maximumDrop < 0.0005) return null;
    return Object.freeze({
        gridSize: EVIDENCE_GRID_SIZE,
        strengths: Object.freeze(effects.map((effect) => effect / maximumDrop)),
        sourceWidth: prepared.sourceWidth,
        sourceHeight: prepared.sourceHeight,
        cropRect: prepared.cropRect,
    });
}

function drawEvidenceOverlay(evidence) {
    const width = elements.preview.clientWidth;
    const height = elements.preview.clientHeight;
    if (!width || !height || !evidence.sourceWidth || !evidence.sourceHeight) return false;

    const pixelRatio = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
    elements.overlay.width = Math.round(width * pixelRatio);
    elements.overlay.height = Math.round(height * pixelRatio);
    const context = elements.overlay.getContext('2d');
    if (!context) return false;
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    context.clearRect(0, 0, width, height);

    // The selected-photo preview uses object-fit: cover. Map the model's
    // centre-cropped evidence through that same scale so rectangular phone and
    // upload photos keep the red explanation aligned with the visible pixels.
    const coverScale = Math.max(
        width / evidence.sourceWidth,
        height / evidence.sourceHeight
    );
    const imageWidth = evidence.sourceWidth * coverScale;
    const imageHeight = evidence.sourceHeight * coverScale;
    const imageLeft = (width - imageWidth) / 2;
    const imageTop = (height - imageHeight) / 2;
    const cropLeft = imageLeft + ((evidence.cropRect.x / evidence.sourceWidth) * imageWidth);
    const cropTop = imageTop + ((evidence.cropRect.y / evidence.sourceHeight) * imageHeight);
    const cropWidth = (evidence.cropRect.width / evidence.sourceWidth) * imageWidth;
    const cropHeight = (evidence.cropRect.height / evidence.sourceHeight) * imageHeight;
    const cellWidth = cropWidth / evidence.gridSize;
    const cellHeight = cropHeight / evidence.gridSize;

    evidence.strengths.forEach((strength, index) => {
        if (strength < 0.08) return;
        const row = Math.floor(index / evidence.gridSize);
        const column = index % evidence.gridSize;
        const centerX = cropLeft + ((column + 0.5) * cellWidth);
        const centerY = cropTop + ((row + 0.5) * cellHeight);
        const radius = Math.max(cellWidth, cellHeight) * 0.82;
        const alpha = 0.16 + (0.46 * Math.pow(strength, 0.72));
        const gradient = context.createRadialGradient(centerX, centerY, 0, centerX, centerY, radius);
        gradient.addColorStop(0, `rgba(255, 35, 25, ${alpha})`);
        gradient.addColorStop(0.5, `rgba(238, 34, 25, ${alpha * 0.68})`);
        gradient.addColorStop(1, 'rgba(211, 24, 18, 0)');
        context.fillStyle = gradient;
        context.fillRect(centerX - radius, centerY - radius, radius * 2, radius * 2);
    });

    elements.overlay.hidden = false;
    elements.evidenceLegend.hidden = false;
    return true;
}

function showEvidenceOverlay(evidence) {
    lastEvidence = evidence;
    if (!drawEvidenceOverlay(evidence)) {
        elements.preview.addEventListener('load', () => {
            if (lastEvidence === evidence) drawEvidenceOverlay(evidence);
        }, { once: true });
    }
}

function rankClasses(probabilities, classes) {
    return probabilities
        .map((confidence, index) => ({ index, label: classes[index], confidence }))
        .sort((left, right) => right.confidence - left.confidence);
}

function humanizeClass(label) {
    return label.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
}

function parseCropView(label) {
    if (label.toLowerCase() === 'other') {
        return { crop: null, view: 'other' };
    }
    const match = /^(.+?)_(fruit|leaf)$/i.exec(label);
    if (!match) return { crop: null, view: 'other' };
    const crop = SUPPORTED_CROPS.get(match[1].toLowerCase());
    return crop ? { crop, view: match[2].toLowerCase() } : { crop: null, view: 'other' };
}

function humanizeOrgan(organ) {
    return organ === 'leaf' ? 'Leaf' : organ === 'fruit' ? 'Fruit' : 'Not established';
}

function conditionDisplayName(condition) {
    if (condition.healthy) return 'No covered disease pattern detected';
    if (condition.condition) return condition.condition;
    const crop = condition.crop || '';
    const cropPrefix = new RegExp(`^(?:healthy\\s+)?${crop.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?:\\s+(?:fruit|leaf))?\\s*:?\\s*`, 'i');
    return condition.diagnosis.replace(cropPrefix, '').trim() || condition.diagnosis;
}

function identityScoreLabel(identity) {
    return identity.overridden
        ? 'Automatic crop/type score — team corrected'
        : 'Crop and photo-type match';
}

function cropViewAlternatives(ranked, excludeIndex) {
    return ranked
        .filter((candidate) => candidate.index !== excludeIndex)
        .slice(0, 3)
        .map((candidate) => ({
            label: humanizeClass(candidate.label),
            confidence: candidate.confidence,
        }));
}

function cropAbstention(ranked, parsed, thresholds) {
    const top = ranked[0];
    const runnerUp = ranked[1]?.confidence || 0;
    const lowConfidence = top.confidence < thresholds.cropConfidence;
    const lowMargin = (top.confidence - runnerUp) < thresholds.cropMargin;
    const unsupported = parsed.view === 'other' || !parsed.crop;

    if (!unsupported && !lowConfidence && !lowMargin) return null;

    return {
        resultLabel: 'crop identification',
        crop: parsed.crop || 'Not established',
        organ: parsed.crop ? humanizeOrgan(parsed.view) : 'Not established',
        condition: 'Not run',
        status: unsupported ? 'Unsupported or unclear crop' : 'Low-confidence crop/type match',
        title: unsupported ? 'We couldn’t identify this photo reliably' : 'Crop not identified confidently',
        certainty: 'no reliable match',
        lede: unsupported
            ? 'Try again with one apple, tomato, cucumber, or lemon fruit or leaf filling the square.'
            : `The closest crop/view pattern was ${humanizeClass(top.label)}, but the score was not reliable enough.`,
        identityScore: unsupported ? null : top.confidence,
        identityScoreLabel: unsupported ? 'Unsupported / other evidence' : 'Closest crop and photo-type score',
        conditionScore: null,
        summary: 'The condition model was not run because crop identity and view must be established first.',
        summaryHeading: 'Why screening stopped',
        next: [
            'Retake the photo in daylight with one crop or leaf filling most of the frame.',
            'Remove hands, labels, packaging, and unrelated plants from the background.',
            'If you know the crop and photo type, select them under Crop confirmation and analyze again.',
        ],
        alternatives: cropViewAlternatives(ranked, top.index),
        alternativesLabel: 'Closest crop and photo-type model matches',
        openAlternatives: true,
        openCorrection: true,
        disclaimer: 'No crop or disease result was issued for this image.',
    };
}

function displayCropName(crop, organ = '') {
    return CROP_DISPLAY_NAMES.get(`${crop}:${organ}`) || crop;
}

function cropOnlyResult(top, parsed, ranked) {
    const cropDisplay = displayCropName(parsed.crop, parsed.view);
    return {
        resultLabel: 'crop identification',
        crop: cropDisplay,
        organ: humanizeOrgan(parsed.view),
        condition: 'Not available for this photo type',
        status: 'Crop/type identified; condition not available',
        title: `${cropDisplay} ${parsed.view}`,
        certainty: 'confident crop match',
        lede: `The crop and ${parsed.view} view were identified, but this model has no matching condition classes.`,
        identityScore: top.confidence,
        identityScoreLabel: 'Crop and photo-type match',
        conditionScore: null,
        summary: 'This is crop identification only. No disease or healthy condition result was produced.',
        summaryHeading: 'Condition coverage',
        next: [
            `Retake a close, sharp photo with the ${parsed.view} filling most of the frame.`,
            'If symptoms are on another plant part, photograph that fruit or leaf separately.',
        ],
        alternatives: cropViewAlternatives(ranked, top.index),
        alternativesLabel: 'Other crop and photo-type model matches',
        disclaimer: 'Crop identity only — no condition result was produced from this photo.',
    };
}

function incompleteOverrideResult(top, ranked, crop, organ) {
    return {
        resultLabel: 'crop confirmation needed',
        crop: crop || 'Not established',
        organ: humanizeOrgan(organ),
        condition: 'Not run',
        status: 'One confirmation is still missing',
        title: 'Confirm both crop and photo type',
        certainty: 'team input needed',
        lede: `The automatic model’s closest match was ${humanizeClass(top.label)}, but it was not reliable enough to safely fill the missing selection.`,
        identityScore: top.confidence,
        identityScoreLabel: 'Automatic crop and photo-type score',
        conditionScore: null,
        summary: 'Choose both the crop and whether the photo shows a leaf or fruit, then analyze again.',
        summaryHeading: 'Why screening stopped',
        next: [
            'Select the known crop under Crop confirmation.',
            'Select Leaf or Fruit for the photographed plant part.',
            'Choose Analyze again to compare only the matching covered conditions.',
        ],
        alternatives: cropViewAlternatives(ranked, top.index),
        alternativesLabel: 'Automatic crop and photo-type model matches',
        openAlternatives: true,
        openCorrection: true,
        disclaimer: 'No condition result was issued until crop and photo type are established.',
    };
}

function diagnosisTitle(crop, organ, diagnosis, uncertain = false) {
    const cropDisplay = displayCropName(crop, organ);
    const escapedCrop = crop.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const cropPrefix = new RegExp(`^(?:healthy\\s+)?${escapedCrop}(?:\\s+(?:fruit|leaf))?\\s*:?\\s*`, 'i');
    const detail = diagnosis.replace(cropPrefix, '').trim();
    const complete = !detail || detail.toLowerCase() === 'healthy'
        ? `Healthy ${cropDisplay} ${organ}`
        : `${cropDisplay} ${organ}: ${detail}`;
    return uncertain ? `Possible ${complete}` : complete;
}

function sameCropOrganConditions(probabilities, diseaseClasses, crop, organ) {
    const candidates = [];
    let probabilityMass = 0;

    diseaseClasses.forEach((condition, index) => {
        if (!condition.crop || condition.crop.toLowerCase() !== crop.toLowerCase()) return;
        if (condition.organ !== organ) return;
        const confidence = probabilities[index];
        probabilityMass += confidence;
        candidates.push({ index, condition, confidence });
    });

    if (!Number.isFinite(probabilityMass) || probabilityMass < 0) {
        throw new VisionError('model', `The condition model returned invalid ${crop} ${organ} scores.`);
    }

    // Keep raw global probabilities. Renormalizing this subset would turn weak
    // crop/organ support into a falsely confident disease result.
    candidates.sort((left, right) => right.confidence - left.confidence);
    return Object.freeze({
        probabilityMass,
        candidates: Object.freeze(candidates),
    });
}

function conditionAlternatives(rankedConditions) {
    return rankedConditions.slice(1, 4).map((candidate) => ({
        label: candidate.condition.diagnosis,
        confidence: candidate.confidence,
    }));
}

function conditionGateNote({
    enoughMass,
    enoughConfidence,
    enoughMargin,
    enoughHealthSeparation,
    probabilityMass,
    topConfidence,
    requiredConfidence,
    conditionMargin,
    healthSeparation,
    thresholds,
}) {
    const reasons = [];
    if (!enoughMass) {
        reasons.push(`${scorePercent(probabilityMass)} total support for this crop/type, below the ${scorePercent(thresholds.conditionMass)} safeguard`);
    }
    if (!enoughConfidence) {
        reasons.push(`the closest condition scored ${scorePercent(topConfidence)}, below the ${scorePercent(requiredConfidence)} screening threshold`);
    }
    if (!enoughMargin) {
        reasons.push(`it led the next condition by only ${scorePercent(conditionMargin)}, below the ${scorePercent(thresholds.conditionMargin)} margin`);
    }
    if (!enoughHealthSeparation) {
        reasons.push(`disease-versus-healthy separation was only ${scorePercent(Math.max(0, healthSeparation))}, below the ${scorePercent(thresholds.healthyMargin)} safeguard`);
    }
    return `Why it was withheld: ${reasons.join('; ')}.`;
}

function conditionResult(identity, conditionMatch, thresholds) {
    const { crop, organ, topCropView, overridden, automaticLabel } = identity;
    const rankedConditions = conditionMatch.candidates;
    const top = rankedConditions[0];
    if (!top) return null;

    const runnerUp = rankedConditions[1]?.confidence || 0;
    const conditionMargin = top.confidence - runnerUp;
    const opposite = rankedConditions.find((candidate) =>
        candidate.condition.healthy !== top.condition.healthy);
    const healthSeparation = opposite ? top.confidence - opposite.confidence : 1;
    const enoughMass = conditionMatch.probabilityMass >= thresholds.conditionMass;
    const family = `${crop}_${organ}`;
    const requiredConfidence = thresholds.conditionConfidenceByFamily[family]
        ?? thresholds.conditionConfidence;
    const enoughConfidence = top.confidence >= requiredConfidence;
    const enoughMargin = conditionMargin >= thresholds.conditionMargin;
    const enoughHealthSeparation = healthSeparation >= thresholds.healthyMargin;
    const confident = enoughMass && enoughConfidence && enoughMargin && enoughHealthSeparation;
    const alternatives = conditionAlternatives(rankedConditions);
    const cropDisplay = displayCropName(crop, organ);
    const conditionName = conditionDisplayName(top.condition);
    const automaticContext = overridden
        ? ` You selected ${cropDisplay} ${organ}; the automatic crop/type model’s closest match was ${automaticLabel} at ${scorePercent(topCropView.confidence)}.`
        : '';

    if (!confident) {
        const gateNote = conditionGateNote({
            enoughMass,
            enoughConfidence,
            enoughMargin,
            enoughHealthSeparation,
            probabilityMass: conditionMatch.probabilityMass,
            topConfidence: top.confidence,
            requiredConfidence,
            conditionMargin,
            healthSeparation,
            thresholds,
        });
        return {
            result: {
                resultLabel: overridden ? 'team-confirmed crop/type' : 'AI crop/type result',
                crop: cropDisplay,
                organ: humanizeOrgan(organ),
                condition: `Closest: ${conditionName} — not a diagnosis`,
                status: 'Low-confidence condition lead',
                title: `${cropDisplay} ${organ}: no reliable condition match`,
                certainty: `uncertain ${organ} result`,
                lede: `Closest covered match: ${top.condition.diagnosis} at ${scorePercent(top.confidence)} model score. It did not pass every safeguard, so CropSCOUT is not issuing a diagnosis.${automaticContext}`,
                identityScore: topCropView.confidence,
                identityScoreLabel: identityScoreLabel(identity),
                conditionScore: top.confidence,
                conditionScoreLabel: 'Closest condition model score',
                closestMatch: {
                    label: conditionName,
                    confidence: top.confidence,
                },
                gateNote,
                summary: `This lead was compared against ${rankedConditions.length} covered conditions for ${cropDisplay} ${organ}. Treat it as a clue for a closer photo or expert review, not a diagnosis or spray decision.`,
                summaryHeading: 'Why this is uncertain',
                next: [
                    `Retake a close photo of one symptomatic ${organ} in even daylight.`,
                    organ === 'leaf'
                        ? 'Photograph both sides and keep the spots or discoloration in sharp focus.'
                        : 'Keep the damaged skin or discolored area in sharp focus and remove unrelated fruit from view.',
                    'Ask a local agronomist or plant diagnostic lab if symptoms persist or spread.',
                ],
                alternatives,
                alternativesLabel: `Other covered conditions for this ${cropDisplay} ${organ}`,
                openAlternatives: true,
                openCorrection: true,
                disclaimer: 'Uncertain screening result — confirm the condition before taking treatment action.',
                evidenceShown: false,
            },
            evidenceClassIndex: null,
            evidenceBaseline: 0,
        };
    }

    const priority = top.condition.urgency.toLowerCase() === 'none'
        ? ''
        : ` Field priority: ${top.condition.urgency}.`;
    const lede = top.condition.healthy
        ? `This ${cropDisplay.toLowerCase()} ${organ} most closely matched the healthy examples among ${rankedConditions.length} covered conditions. Conditions outside this model may still be present.${automaticContext}`
        : `Closest covered condition: ${conditionName}.${automaticContext}`;

    return {
        result: {
            resultLabel: overridden ? 'team-confirmed crop/type' : 'AI crop/type result',
            crop: cropDisplay,
            organ: humanizeOrgan(organ),
            condition: conditionName,
            status: top.condition.healthy ? 'Healthy-like pattern within covered classes' : 'High-confidence condition screen',
            title: top.condition.healthy
                ? 'No covered disease pattern detected'
                : `${cropDisplay} ${organ}: ${conditionName}`,
            certainty: top.condition.healthy ? 'healthy-like pattern' : 'high-confidence screen',
            lede,
            identityScore: topCropView.confidence,
            identityScoreLabel: identityScoreLabel(identity),
            conditionScore: top.confidence,
            conditionScoreLabel: top.condition.healthy ? 'Healthy-pattern model score' : 'Condition model score',
            summary: top.condition.healthy
                ? `No covered disease pattern passed the screening safeguards.${priority}`
                : `${top.condition.cause}${priority}`,
            summaryHeading: top.condition.healthy ? 'What this means' : 'Condition details',
            next: top.condition.actions.length > 0
                ? [...top.condition.actions]
                : ['Continue monitoring the plant and photograph any new symptoms.'],
            alternatives,
            alternativesLabel: `Other covered conditions for this ${cropDisplay} ${organ}`,
            disclaimer: DEFAULT_DISCLAIMER,
            evidenceShown: false,
        },
        evidenceClassIndex: top.condition.healthy ? null : top.index,
        evidenceBaseline: top.confidence,
    };
}

function isAcceptedHealthyAssessment(assessment) {
    return assessment?.result?.certainty === 'healthy-like pattern';
}

async function assessConditionRoute(
    runtime,
    identity,
    input,
    { live = false, isCurrent = () => true, smooth = null } = {}
) {
    const { crop, organ } = identity;
    const family = `${crop}_${organ}`;
    const route = await resolveConditionRoute(runtime, crop, organ);
    if (!isCurrent()) return null;
    const evaluations = [];

    for (const model of route.models) {
        if (!isCurrent()) return null;
        const probabilities = await runClassifier(
            model.session,
            input,
            model.classes.length,
            live ? 'The live condition model' : 'The disease model'
        );
        if (!isCurrent()) return null;
        // A live track averages scores over frames; the safeguards below then
        // run on the averaged scores with unchanged thresholds.
        const routedProbabilities = smooth
            ? smooth(probabilities, route.id, model.id)
            : probabilities;
        const conditionMatch = sameCropOrganConditions(
            routedProbabilities,
            model.classes,
            crop,
            organ
        );
        let thresholds = runtime.metadata.thresholds;
        if (route.policyId === LEMON_HYBRID_POLICY_ID && model.id === 'lemon-leaf') {
            thresholds = Object.freeze({
                ...thresholds,
                conditionConfidenceByFamily: Object.freeze({
                    ...thresholds.conditionConfidenceByFamily,
                    [family]: Math.max(
                        thresholds.conditionConfidenceByFamily[family]
                            ?? thresholds.conditionConfidence,
                        route.specialistMinConfidence
                    ),
                }),
            });
        }
        evaluations.push(Object.freeze({
            model,
            conditionMatch,
            assessment: conditionResult(
                identity,
                conditionMatch,
                thresholds
            ),
        }));
    }

    let selected = evaluations[0];
    if (route.policyId === LEMON_HYBRID_POLICY_ID) {
        const [base, specialist] = evaluations;
        const specialistTop = specialist?.conditionMatch.candidates[0];
        const considerSpecialist = Boolean(
            specialistTop
            && !specialistTop.condition.healthy
            && !isAcceptedHealthyAssessment(base?.assessment)
        );
        // A considered but weak disease lead keeps its specialist abstention.
        // It must never fall through to a potentially misleading base result.
        selected = considerSpecialist ? specialist : base;
    }

    return Object.freeze({ route, ...selected, spray: sprayEstimate(runtime, selected, input) });
}

// How much to spray for this verdict. Only a verdict that passed every
// safeguard gets a dose; healthy, non-infectious and viral conditions get none.
// Severity is the share of lesion-coloured leaf pixels in the 224 px input.
function sprayEstimate(runtime, evaluation, input) {
    const rules = runtime.sprayRules;
    const assessment = evaluation?.assessment;
    if (!rules || !assessment) return null;
    const top = evaluation.conditionMatch.candidates[0];
    const certain = assessment.result.certainty === 'high-confidence screen'
        || assessment.result.certainty === 'healthy-like pattern';
    const data = input?.data;
    const severity = data && data.length === 3 * IMAGE_SIZE * IMAGE_SIZE
        ? estimateSeverityFromTensor(data, rules, IMAGE_SIZE)
        : null;
    return decideSpray(rules, top?.condition.label ?? null, certain, severity);
}

/* =========================== Field notes ===========================
 *
 * A field note is the grower telling us whether a screening result matched
 * what they saw. Two deliberate limits keep a note helpful without letting it
 * become a wrong answer the page repeats forever:
 *
 *   1. A note never changes a screening verdict, score or safeguard. The model
 *      output shown is always the model's own. A note is displayed beside it
 *      and, at most, pins the grower's choice to the top of the alternatives.
 *   2. Nothing is retrained automatically. Notes queue for a human reviewer;
 *      only accepted ones ever become (weak) training candidates.
 *
 * Notes are remembered per photo through a 64-bit perceptual fingerprint, so
 * re-analyzing the same picture shows what was recorded last time. The
 * fingerprint is derived from the already-prepared 224 px planes: no extra
 * decode, and the photo itself never leaves the device unless the grower ticks
 * the contribute box.
 */
const FIELD_NOTE_ENDPOINT = 'feedback.php';
const FIELD_NOTE_STORAGE_KEY = 'cropscout.fieldNotes.v1';
const FIELD_NOTE_STORAGE_LIMIT = 200;
const FIELD_NOTE_MATCH_DISTANCE = 6;
// No field notes in static mode: there is no server to keep them.
const fieldNoteAvailable = Boolean(elements.fieldNote && elements.fieldNoteForm) && !STATIC_MODE;
let fieldNoteOptions = null;
let fieldNoteOptionsPromise = null;
let currentAnalysis = null;

function photoFingerprint(chw) {
    const size = IMAGE_SIZE;
    const plane = size * size;
    const columns = 9;
    const rows = 8;
    const cells = [];
    for (let row = 0; row < rows; row += 1) {
        for (let column = 0; column < columns; column += 1) {
            const startX = Math.floor((column * size) / columns);
            const endX = Math.floor(((column + 1) * size) / columns);
            const startY = Math.floor((row * size) / rows);
            const endY = Math.floor(((row + 1) * size) / rows);
            let sum = 0;
            let count = 0;
            for (let y = startY; y < endY; y += 1) {
                for (let x = startX; x < endX; x += 1) {
                    const offset = (y * size) + x;
                    sum += (0.299 * chw[offset])
                        + (0.587 * chw[plane + offset])
                        + (0.114 * chw[(2 * plane) + offset]);
                    count += 1;
                }
            }
            cells.push(count > 0 ? sum / count : 0);
        }
    }
    let hex = '';
    let nibble = 0;
    let bitsInNibble = 0;
    for (let row = 0; row < rows; row += 1) {
        for (let column = 0; column < columns - 1; column += 1) {
            const bit = cells[(row * columns) + column] > cells[(row * columns) + column + 1] ? 1 : 0;
            nibble = (nibble << 1) | bit;
            bitsInNibble += 1;
            if (bitsInNibble === 4) {
                hex += nibble.toString(16);
                nibble = 0;
                bitsInNibble = 0;
            }
        }
    }
    return hex;
}

function fingerprintDistance(left, right) {
    if (typeof left !== 'string' || typeof right !== 'string' || left.length !== right.length) return 64;
    let distance = 0;
    for (let index = 0; index < left.length; index += 1) {
        let difference = parseInt(left[index], 16) ^ parseInt(right[index], 16);
        if (!Number.isFinite(difference)) return 64;
        while (difference) {
            distance += difference & 1;
            difference >>= 1;
        }
    }
    return distance;
}

function readStoredFieldNotes() {
    try {
        const raw = window.localStorage.getItem(FIELD_NOTE_STORAGE_KEY);
        const parsed = raw ? JSON.parse(raw) : [];
        return Array.isArray(parsed) ? parsed.filter((entry) => entry && typeof entry.fingerprint === 'string') : [];
    } catch {
        // Private windows, blocked storage and cleared site data are normal.
        return [];
    }
}

function writeStoredFieldNotes(notes) {
    try {
        window.localStorage.setItem(
            FIELD_NOTE_STORAGE_KEY,
            JSON.stringify(notes.slice(-FIELD_NOTE_STORAGE_LIMIT))
        );
    } catch {
        // A note that cannot be cached locally is not an error worth surfacing.
    }
}

function findStoredFieldNote(fingerprint) {
    if (!fingerprint) return null;
    const notes = readStoredFieldNotes();
    let best = null;
    let bestDistance = FIELD_NOTE_MATCH_DISTANCE + 1;
    notes.forEach((note) => {
        const distance = fingerprintDistance(note.fingerprint, fingerprint);
        if (distance <= FIELD_NOTE_MATCH_DISTANCE && distance < bestDistance) {
            best = note;
            bestDistance = distance;
        }
    });
    return best;
}

function rememberFieldNote(note) {
    const notes = readStoredFieldNotes()
        .filter((entry) => fingerprintDistance(entry.fingerprint, note.fingerprint) > FIELD_NOTE_MATCH_DISTANCE);
    notes.push(note);
    writeStoredFieldNotes(notes);
}

async function loadFieldNoteOptions() {
    if (fieldNoteOptions) return fieldNoteOptions;
    if (!fieldNoteOptionsPromise) {
        fieldNoteOptionsPromise = fetch(`${FIELD_NOTE_ENDPOINT}?options=1`, { credentials: 'omit' })
            .then((response) => (response.ok ? response.json() : null))
            .then((payload) => {
                fieldNoteOptions = payload && typeof payload === 'object' && payload.families ? payload : null;
                return fieldNoteOptions;
            })
            .catch(() => null);
    }
    return fieldNoteOptionsPromise;
}

function fieldNoteOptionText(family, value) {
    if (!value) return '';
    if (value === 'unsure') return 'Not sure';
    if (value === 'other') return 'Something else, not in the list';
    if (value === 'wrong_identity') return 'a different crop or plant part than the one identified';
    const groups = fieldNoteOptions?.families?.[family];
    const entries = [...(groups?.covered || []), ...(groups?.not_covered || [])];
    const match = entries.find((entry) => entry.value === value);
    if (match) return match.text;
    return value.startsWith('gap:') ? value.slice(4).replace(/_/g, ' ') : humanizeClass(value);
}

function fillSelect(select, entries, placeholder) {
    if (!select) return;
    const options = [];
    if (placeholder) {
        const first = document.createElement('option');
        first.value = '';
        first.textContent = placeholder;
        options.push(first);
    }
    entries.forEach((entry) => {
        if (entry.group) {
            const group = document.createElement('optgroup');
            group.label = entry.group;
            entry.items.forEach((item) => {
                const option = document.createElement('option');
                option.value = item.value;
                option.textContent = item.text;
                group.append(option);
            });
            options.push(group);
            return;
        }
        const option = document.createElement('option');
        option.value = entry.value;
        option.textContent = entry.text;
        options.push(option);
    });
    select.replaceChildren(...options);
}

function describeStoredNote(note) {
    const when = note.at ? new Date(note.at).toLocaleDateString() : 'earlier';
    if (note.verdict === 'confirmed') {
        return `On ${when} you confirmed this photo as ${note.labelText || 'the screening result'}. The result above is still the model's own.`;
    }
    if (note.verdict === 'corrected') {
        return `On ${when} you recorded this photo as ${note.labelText || 'a different pattern'}. It is kept as a field note for review; the model has not been retrained on it, so the result above may still disagree.`;
    }
    return `On ${when} you marked this photo as uncertain.`;
}

function resetFieldNoteForm() {
    if (!fieldNoteAvailable) return;
    elements.fieldNoteForm.hidden = true;
    elements.fieldNoteLabelField.hidden = true;
    elements.fieldNoteStatus.hidden = true;
    elements.fieldNoteStatus.textContent = '';
    elements.fieldNoteStatus.classList.remove('error');
    elements.fieldNoteText.value = '';
    elements.fieldNoteContribute.checked = false;
    elements.fieldNoteSubmit.disabled = false;
    [elements.fieldNoteYes, elements.fieldNoteNo, elements.fieldNoteUnsure]
        .forEach((button) => button.classList.remove('active'));
}

async function openFieldNoteForm(verdict) {
    if (!fieldNoteAvailable || !currentAnalysis) return;
    currentAnalysis.verdict = verdict;
    [['confirmed', elements.fieldNoteYes], ['corrected', elements.fieldNoteNo], ['unsure', elements.fieldNoteUnsure]]
        .forEach(([key, button]) => button.classList.toggle('active', key === verdict));

    const options = await loadFieldNoteOptions();
    const family = `${currentAnalysis.crop}_${currentAnalysis.organ}`;
    const groups = options?.families?.[family];
    const cropDisplay = displayCropName(currentAnalysis.crop, currentAnalysis.organ);
    const entries = [];
    // When the crop call itself is wrong, no condition list applies. Offering
    // this first stops a grower from picking the nearest wrong-family disease.
    entries.push({ group: 'If the crop is wrong', items: [{
        value: 'wrong_identity',
        text: `This is not a ${cropDisplay} ${currentAnalysis.organ}`,
    }] });
    if (groups?.covered?.length) {
        entries.push({ group: 'Covered by the model', items: groups.covered });
    }
    if (groups?.not_covered?.length) {
        entries.push({ group: 'Not covered yet — reporting it asks the team to add it', items: groups.not_covered });
    }
    entries.push({ group: 'Other', items: [
        { value: 'other', text: 'Something else, not in the list' },
        { value: 'unsure', text: 'Not sure' },
    ] });
    fillSelect(elements.fieldNoteLabel, entries, 'Choose what you see…');
    fillSelect(
        elements.fieldNoteStage,
        Object.entries(options?.growth_stages || { unknown: 'Not sure' })
            .map(([value, text]) => ({ value, text })),
        'Growth stage…'
    );
    fillSelect(
        elements.fieldNoteSeverity,
        Object.entries(options?.severities || { unknown: 'Not sure' })
            .map(([value, text]) => ({ value, text })),
        'How far along…'
    );

    elements.fieldNoteLabelField.hidden = verdict !== 'corrected';
    elements.fieldNoteForm.hidden = false;
    elements.fieldNoteStatus.hidden = true;
    if (verdict === 'corrected') {
        elements.fieldNoteLabel.focus({ preventScroll: true });
    }
}

async function submitFieldNote(event) {
    event.preventDefault();
    if (!fieldNoteAvailable || !currentAnalysis?.verdict) return;
    const verdict = currentAnalysis.verdict;
    const family = `${currentAnalysis.crop}_${currentAnalysis.organ}`;
    const chosen = verdict === 'corrected' ? elements.fieldNoteLabel.value : (currentAnalysis.modelLabel || '');
    if (verdict === 'corrected' && !chosen) {
        elements.fieldNoteStatus.hidden = false;
        elements.fieldNoteStatus.classList.add('error');
        elements.fieldNoteStatus.textContent = 'Choose which pattern you actually see.';
        return;
    }

    const labelText = verdict === 'corrected'
        ? fieldNoteOptionText(family, chosen)
        : (currentAnalysis.modelDiagnosis || 'the screening result');

    rememberFieldNote({
        fingerprint: currentAnalysis.fingerprint,
        crop: currentAnalysis.crop,
        organ: currentAnalysis.organ,
        verdict,
        label: chosen || null,
        labelText,
        modelLabel: currentAnalysis.modelLabel || null,
        at: new Date().toISOString(),
    });

    elements.fieldNoteSubmit.disabled = true;
    elements.fieldNoteStatus.hidden = false;
    elements.fieldNoteStatus.classList.remove('error');
    elements.fieldNoteStatus.textContent = 'Saving your field note…';

    const body = new FormData();
    body.set('fingerprint', currentAnalysis.fingerprint);
    body.set('crop', currentAnalysis.crop);
    body.set('organ', currentAnalysis.organ);
    body.set('verdict', verdict);
    body.set('user_label', chosen || '');
    body.set('growth_stage', elements.fieldNoteStage.value || '');
    body.set('severity', elements.fieldNoteSeverity.value || '');
    body.set('note', elements.fieldNoteText.value || '');
    body.set('model_label', currentAnalysis.modelLabel || '');
    body.set('model_diagnosis', currentAnalysis.modelDiagnosis || '');
    body.set('model_status', currentAnalysis.modelStatus || '');
    if (typeof currentAnalysis.modelScore === 'number') {
        body.set('model_score', String(currentAnalysis.modelScore));
    }
    if (elements.fieldNoteContribute.checked && currentAnalysis.file) {
        body.set('contribute', '1');
        body.set('photo', currentAnalysis.file, currentAnalysis.file.name || 'photo.jpg');
    }

    try {
        const response = await fetch(FIELD_NOTE_ENDPOINT, { method: 'POST', body, credentials: 'omit' });
        const payload = await response.json().catch(() => null);
        if (!response.ok) {
            throw new Error(payload?.error || 'The server did not accept this field note.');
        }
        elements.fieldNoteForm.hidden = true;
        elements.fieldNoteStatus.textContent = payload?.stored_photo
            ? 'Saved. Your note and photo are queued for the team to review, and this photo is remembered on this device.'
            : 'Saved. Your note is queued for the team to review, and this photo is remembered on this device.';
    } catch (error) {
        elements.fieldNoteForm.hidden = true;
        elements.fieldNoteStatus.textContent = `Saved on this device only — the server could not be reached. ${error instanceof Error ? error.message : ''}`.trim();
    } finally {
        elements.fieldNoteSubmit.disabled = false;
        currentAnalysis.knownNote = findStoredFieldNote(currentAnalysis.fingerprint);
        renderFieldNotePanel();
    }
}

function renderFieldNotePanel() {
    if (!fieldNoteAvailable) return;
    if (!currentAnalysis?.crop || !currentAnalysis?.organ) {
        elements.fieldNote.hidden = true;
        return;
    }
    elements.fieldNote.hidden = false;
    const known = currentAnalysis.knownNote;
    elements.fieldNoteKnown.hidden = !known;
    if (known) {
        elements.fieldNoteKnownText.textContent = describeStoredNote(known);
    }
}

async function analyzeFile(file) {
    const problem = validateFile(file);
    if (problem) {
        renderFailure('Photo not accepted', problem);
        return;
    }

    const sequence = ++analysisSequence;
    renderBusy();
    currentAnalysis = null;
    let prepared = null;

    try {
        // A shutter press can land while the final live-preview inference is
        // finishing. Let it release the shared ONNX sessions before starting
        // the locked full report.
        const pendingLiveRecognitions = [...activeLiveRecognitions];
        if (pendingLiveRecognitions.length > 0) {
            await Promise.allSettled(pendingLiveRecognitions);
        }
        if (sequence !== analysisSequence) return;

        const runtime = await startRuntime();
        if (sequence !== analysisSequence) return;

        setBusyStage('Preparing the photo without uploading it.');
        await yieldToBrowser();
        prepared = await preprocessImage(file);
        setBusyStage('Identifying the crop and photo type.');
        await yieldToBrowser();
        if (sequence !== analysisSequence) return;
        const cropProbabilities = await runClassifier(
            runtime.cropViewSession,
            prepared.tensor,
            runtime.metadata.cropViewClasses.length,
            'The crop/view model'
        );
        if (sequence !== analysisSequence) return;

        const rankedCropViews = rankClasses(cropProbabilities, runtime.metadata.cropViewClasses);
        const topCropView = rankedCropViews[0];
        const parsed = parseCropView(topCropView.label);
        const abstention = cropAbstention(rankedCropViews, parsed, runtime.metadata.thresholds);
        const cropOverride = elements.cropOverride.value || null;
        const organOverride = elements.organOverride.value || null;
        const overridden = Boolean(cropOverride || organOverride);

        if (overridden && (!cropOverride || !organOverride)) {
            renderResult(incompleteOverrideResult(
                topCropView,
                rankedCropViews,
                cropOverride,
                organOverride
            ));
            return;
        }

        if (abstention && !overridden) {
            renderResult(abstention);
            return;
        }

        const crop = cropOverride || parsed.crop;
        const organ = organOverride || (parsed.view === 'leaf' || parsed.view === 'fruit' ? parsed.view : null);
        if (!crop || !organ) {
            renderResult(incompleteOverrideResult(topCropView, rankedCropViews, crop, organ));
            return;
        }
        const identity = Object.freeze({
            crop,
            organ,
            overridden,
            topCropView,
            automaticLabel: humanizeClass(topCropView.label),
        });

        // The fingerprint is derived from the prepared planes, so recognizing a
        // photo again costs nothing and needs no copy of the image.
        const fingerprint = photoFingerprint(prepared.chw);
        currentAnalysis = {
            fingerprint,
            crop,
            organ,
            file,
            verdict: null,
            knownNote: findStoredFieldNote(fingerprint),
            modelLabel: null,
            modelDiagnosis: null,
            modelScore: null,
            modelStatus: null,
        };

        setBusyStage(`Comparing covered conditions for ${displayCropName(crop, organ)} ${organ}.`);
        await yieldToBrowser();
        if (sequence !== analysisSequence) return;
        const evaluated = await assessConditionRoute(
            runtime,
            identity,
            prepared.tensor,
            { isCurrent: () => sequence === analysisSequence }
        );
        if (!evaluated || sequence !== analysisSequence) return;
        const { assessment, conditionMatch, model: conditionModel } = evaluated;
        const topCondition = conditionMatch.candidates[0];
        if (currentAnalysis && topCondition) {
            currentAnalysis.modelLabel = topCondition.condition.label || null;
            currentAnalysis.modelDiagnosis = topCondition.condition.diagnosis || null;
            currentAnalysis.modelScore = topCondition.confidence;
            currentAnalysis.modelStatus = assessment?.result?.status || null;
        }
        if (conditionMatch.candidates.length === 0) {
            renderResult(cropOnlyResult(topCropView, { crop, view: organ }, rankedCropViews));
            return;
        }
        if (!assessment) {
            renderResult(cropOnlyResult(topCropView, { crop, view: organ }, rankedCropViews));
            return;
        }

        let evidence = null;
        if (assessment.evidenceClassIndex !== null) {
            try {
                setBusyStage('Mapping the image regions behind this result.');
                await yieldToBrowser();
                evidence = await buildEvidenceMap(
                    conditionModel.session,
                    prepared,
                    assessment.evidenceClassIndex,
                    conditionModel.classes.length,
                    assessment.evidenceBaseline,
                    () => sequence === analysisSequence
                );
            } catch {
                // Evidence is an explanatory aid; never replace a completed
                // screening result with an error if only the map could not render.
                evidence = null;
            }
        }
        if (sequence !== analysisSequence) return;

        assessment.result.evidenceShown = Boolean(evidence);
        renderResult({ ...assessment.result, spray: evaluated.spray });
        if (evidence) showEvidenceOverlay(evidence);
    } catch (error) {
        if (sequence !== analysisSequence) return;
        const visionError = error instanceof VisionError
            ? error
            : new VisionError('browser', error instanceof Error ? error.message : 'Unknown browser inference error.');

        const titleByCode = {
            session: 'Private session expired',
            'not-installed': 'Models are not installed yet',
            metadata: 'Model configuration problem',
            model: 'Browser model unavailable',
            specialist: 'Condition model unavailable',
            image: 'Photo could not be read',
            browser: 'Local analysis could not start',
        };
        renderFailure(titleByCode[visionError.code] || 'Analysis unavailable', visionError.message);
    } finally {
        if (prepared?.tensor && typeof prepared.tensor.dispose === 'function') prepared.tensor.dispose();
    }
}

elements.input.addEventListener('change', () => {
    const [file] = elements.input.files;
    if (file) selectFile(file);
    elements.input.value = '';
});

elements.nativeInput.addEventListener('change', () => {
    const [file] = elements.nativeInput.files;
    if (file) selectFile(file);
    elements.nativeInput.value = '';
});

elements.uploadPhotoButton.addEventListener('click', () => elements.input.click());
elements.replacePhotoButton.addEventListener('click', () => elements.input.click());
elements.nativeCameraButton.addEventListener('click', () => elements.nativeInput.click());
elements.cameraFallbackButton.addEventListener('click', () => elements.nativeInput.click());

['dragenter', 'dragover'].forEach((type) => {
    elements.dropZone.addEventListener(type, (event) => {
        event.preventDefault();
        elements.dropZone.classList.add('drag-over');
    });
});

['dragleave', 'drop'].forEach((type) => {
    elements.dropZone.addEventListener(type, (event) => {
        event.preventDefault();
        elements.dropZone.classList.remove('drag-over');
    });
});

elements.dropZone.addEventListener('drop', (event) => {
    const [file] = event.dataTransfer.files;
    if (file) selectFile(file);
});

document.addEventListener('cropscout:image-selected', (event) => {
    if (event.detail?.file) void analyzeFile(event.detail.file);
});

document.addEventListener('cropscout:analyze-requested', (event) => {
    event.preventDefault();
    if (event.detail?.file) void analyzeFile(event.detail.file);
});

elements.analyze.addEventListener('click', () => {
    if (!selectedFile) return;
    document.dispatchEvent(new CustomEvent('cropscout:analyze-requested', {
        detail: { file: selectedFile },
        cancelable: true,
    }));
});

elements.openCamera.addEventListener('click', () => {
    void requestCamera();
});

elements.heroCamera?.addEventListener('click', () => {
    void requestCamera();
});

elements.heroPhoto?.addEventListener('click', () => elements.input.click());

elements.reopenCameraButton.addEventListener('click', () => {
    void requestCamera();
});

elements.captureCamera.addEventListener('click', () => {
    void captureCameraFrame();
});

elements.switchCamera.addEventListener('click', () => {
    void switchCameraDevice();
});

elements.closeCamera.addEventListener('click', () => {
    closeCamera();
});

elements.cancelCamera.addEventListener('click', () => {
    closeCamera();
});

if (fieldNoteAvailable) {
    elements.fieldNoteYes.addEventListener('click', () => void openFieldNoteForm('confirmed'));
    elements.fieldNoteNo.addEventListener('click', () => void openFieldNoteForm('corrected'));
    elements.fieldNoteUnsure.addEventListener('click', () => void openFieldNoteForm('unsure'));
    elements.fieldNoteForm.addEventListener('submit', (event) => void submitFieldNote(event));
}

elements.resultCorrectionButton.addEventListener('click', () => {
    elements.cropCorrection.open = true;
    elements.cropCorrection.scrollIntoView({ behavior: 'smooth', block: 'center' });
    window.setTimeout(() => elements.cropOverride.focus({ preventScroll: true }), 260);
});

elements.cameraPanel.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
        event.preventDefault();
        closeCamera();
    }
});

[elements.cropOverride, elements.organOverride].forEach((select) => {
    select.addEventListener('change', () => {
        if (!selectedFile || elements.analyze.disabled) return;
        elements.analyzeLabel.textContent = elements.cropOverride.value || elements.organOverride.value
            ? 'Analyze with correction'
            : 'Analyze again';
    });
});

window.addEventListener('beforeunload', () => {
    closeCamera({ restoreSurface: false, returnFocus: false });
    if (previewUrl) URL.revokeObjectURL(previewUrl);
});

window.addEventListener('pagehide', () => {
    closeCamera({ restoreSurface: false, returnFocus: false });
});

document.addEventListener('visibilitychange', () => {
    if (document.hidden && !elements.cameraPanel.hidden) {
        closeCamera({
            message: 'Camera paused when this page moved to the background.',
            returnFocus: false,
        });
    }
});

window.addEventListener('resize', () => {
    if (lastEvidence) drawEvidenceOverlay(lastEvidence);
});

window.CropScoutVision = Object.freeze({
    endpoints: MODEL_ENDPOINTS,
    analyzeFile,
    renderBusy,
    renderFailure,
    renderResult,
    requestCamera,
    captureCameraFrame,
    closeCamera,
    // Read-only snapshot of the live loop, for tests and on-device checks.
    liveStats: () => ({
        ...liveStats,
        display: { ...liveStats.display },
        leaves: liveStats.leaves.map((leaf) => ({ ...leaf, box: [...leaf.box] })),
        shownVerdict: liveStats.mode === 'leaves'
            ? (liveStats.leaves.find((leaf) => leaf.shown)?.shown || '')
            : (liveSquareTrack.shown?.key || ''),
    }),
    setModelState,
    startRuntime,
});

setModelState('loading', 'model check pending');
configureCameraAvailability();
void startRuntime();
