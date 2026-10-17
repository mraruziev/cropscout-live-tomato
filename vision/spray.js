// Spray estimate for a confirmed condition. Mirrors live/spray.py exactly;
// the rules come from spray-rules.json so both sides agree.
//
//   const severity = estimateSeverityFromTensor(tensor.data);   // CHW RGB 0..1, 224x224
//   const spray = decideSpray(rules, label, certain, severity);
//
// A spray is estimated only when the condition passed every CropSCOUT
// safeguard. Healthy, non-infectious and viral conditions get no spray.

export async function loadSprayRules(url = 'spray-rules.json') {
    const response = await fetch(url, { cache: 'no-cache' });
    if (!response.ok) throw new Error(`spray rules: HTTP ${response.status}`);
    const rules = await response.json();
    if (!rules || typeof rules.rules !== 'object' || !rules.severity || !rules.units) {
        throw new Error('spray rules: unexpected shape');
    }
    return Object.freeze(rules);
}

// RGB 0..1 -> HSV on OpenCV's scale (H 0..180, S and V 0..255) so the
// thresholds are the same numbers as in live/spray.py.
function rgbToHsvOpenCv(r, g, b) {
    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    const delta = max - min;
    let h = 0;
    if (delta > 0) {
        if (max === r) h = 60 * (((g - b) / delta) % 6);
        else if (max === g) h = 60 * ((b - r) / delta + 2);
        else h = 60 * ((r - g) / delta + 4);
        if (h < 0) h += 360;
    }
    const s = max > 0 ? delta / max : 0;
    return [h / 2, s * 255, max * 255];
}

const DEFAULT_COLOUR = Object.freeze({ green_min_s: 40, green_min_v: 50, brown_min_s: 60, dark_max_v: 85 });
const DEFAULT_ADJACENCY_RADIUS = 0.08;

// Colour classes on OpenCV's HSV scale; thresholds come from rules.severity.colour
// (defaults match live/spray.py). 'green' is leaf tissue, 'brown' a lesion-like colour
// (yellow, orange, brown or dark necrotic), 'other' is background.
export function classifyPixel(r, g, b, colour = DEFAULT_COLOUR) {
    const [h, s, v] = rgbToHsvOpenCv(r, g, b);
    if (h >= 35 && h <= 85 && s > colour.green_min_s && v > colour.green_min_v) return 'green';
    const brown = h >= 5 && h < 35 && s > colour.brown_min_s && v > 30;
    const dark = v < colour.dark_max_v && v >= 20 && s > 30 && (h < 35 || h > 150);
    return brown || dark ? 'brown' : 'other';
}

// Square dilation (max filter) of a 0/1 mask, separable: rows then columns.
function dilate(mask, side, radius) {
    const tmp = new Uint8Array(side * side);
    const out = new Uint8Array(side * side);
    for (let y = 0; y < side; y += 1) {
        const row = y * side;
        for (let x = 0; x < side; x += 1) {
            let hit = 0;
            const x0 = Math.max(0, x - radius);
            const x1 = Math.min(side - 1, x + radius);
            for (let k = x0; k <= x1 && !hit; k += 1) hit = mask[row + k];
            tmp[row + x] = hit;
        }
    }
    for (let x = 0; x < side; x += 1) {
        for (let y = 0; y < side; y += 1) {
            let hit = 0;
            const y0 = Math.max(0, y - radius);
            const y1 = Math.min(side - 1, y + radius);
            for (let k = y0; k <= y1 && !hit; k += 1) hit = tmp[k * side + x];
            out[y * side + x] = hit;
        }
    }
    return out;
}

// Counts leaf (green) and lesion pixels from per-pixel classes. A brown pixel is a
// lesion only when it lies within the adjacency radius of leaf tissue, grown once,
// so soil and bark away from any leaf do not count. Same steps as live/spray.py.
function countLeafAndLesion(classes, side, rules) {
    const cfg = rules.severity;
    const radius = Math.max(1, Math.round((cfg.adjacency_radius ?? DEFAULT_ADJACENCY_RADIUS) * side));
    const n = side * side;
    const green = new Uint8Array(n);
    const brown = new Uint8Array(n);
    for (let i = 0; i < n; i += 1) {
        if (classes[i] === 1) green[i] = 1;
        else if (classes[i] === 2) brown[i] = 1;
    }
    let near = dilate(green, side, radius);
    const grown = new Uint8Array(n);
    for (let i = 0; i < n; i += 1) grown[i] = green[i] | (brown[i] & near[i]);
    near = dilate(grown, side, radius);
    let nGreen = 0;
    let nLesion = 0;
    for (let i = 0; i < n; i += 1) {
        if (green[i]) nGreen += 1;
        else if (brown[i] & near[i]) nLesion += 1;
    }
    return [nGreen, nLesion];
}

const CLASS_CODE = { green: 1, brown: 2, other: 0 };

// `chw` is a Float32Array laid out [3][side][side] with RGB values in 0..1,
// exactly what the models take, so the estimate costs no extra decode.
export function estimateSeverityFromTensor(chw, rules, side = 224) {
    const plane = side * side;
    const colour = { ...DEFAULT_COLOUR, ...(rules.severity.colour || {}) };
    const classes = new Uint8Array(plane);
    for (let i = 0; i < plane; i += 1) {
        classes[i] = CLASS_CODE[classifyPixel(chw[i], chw[plane + i], chw[2 * plane + i], colour)];
    }
    const [nGreen, nLesion] = countLeafAndLesion(classes, side, rules);
    return bandSeverity(nGreen, nLesion, plane, rules);
}

// `rgba` is an ImageData.data buffer (0..255) of a square image.
export function estimateSeverityFromImageData(rgba, width, height, rules) {
    const colour = { ...DEFAULT_COLOUR, ...(rules.severity.colour || {}) };
    const side = Math.min(width, height);
    const classes = new Uint8Array(side * side);
    for (let y = 0; y < side; y += 1) {
        for (let x = 0; x < side; x += 1) {
            const i = (y * width + x) * 4;
            classes[y * side + x] = CLASS_CODE[classifyPixel(rgba[i] / 255, rgba[i + 1] / 255, rgba[i + 2] / 255, colour)];
        }
    }
    const [nGreen, nLesion] = countLeafAndLesion(classes, side, rules);
    return bandSeverity(nGreen, nLesion, side * side, rules);
}

export function severityBand(frac, rules) {
    const cfg = rules.severity;
    return frac <= cfg.low_max ? 'low' : frac >= cfg.high_min ? 'high' : 'medium';
}

function bandSeverity(nGreen, nLesion, total, rules) {
    const cfg = rules.severity;
    const leafCover = (nGreen + nLesion) / total;
    if (leafCover < cfg.min_leaf_cover || nGreen + nLesion === 0) {
        return Object.freeze({ lesionFraction: 0, leafCover, band: 'unknown' });
    }
    const frac = nLesion / (nGreen + nLesion);
    return Object.freeze({ lesionFraction: frac, leafCover, band: severityBand(frac, rules) });
}

// Continuous dose factor: min at 0 % lesion area, max from full_at upwards.
export function severityMultiplier(severity, rules) {
    const m = rules.severity.multiplier;
    if (!m) return rules.severity.multipliers?.[severity?.band ?? 'unknown'] ?? 1;
    if (!severity || severity.band === 'unknown') return 1;
    const t = Math.min(1, Math.max(0, severity.lesionFraction / Number(m.full_at)));
    return Number(m.min) + (Number(m.max) - Number(m.min)) * t;
}

// EMA over frames for the live loop; `state` is a plain object kept on the track.
export function smoothSeverity(state, raw, rules) {
    const alpha = Number(rules.severity.live_smoothing ?? 0.62);
    if (raw.band === 'unknown') {
        return state.frac == null
            ? raw
            : Object.freeze({ lesionFraction: state.frac, leafCover: raw.leafCover, band: 'unknown' });
    }
    if (state.frac == null) {
        state.frac = raw.lesionFraction;
        state.cover = raw.leafCover;
    } else {
        state.frac = alpha * raw.lesionFraction + (1 - alpha) * state.frac;
        state.cover = alpha * raw.leafCover + (1 - alpha) * state.cover;
    }
    return Object.freeze({ lesionFraction: state.frac, leafCover: state.cover, band: severityBand(state.frac, rules) });
}

export function decideSpray(rules, label, certain, severity) {
    const band = severity?.band ?? 'unknown';
    const lesionFraction = severity?.lesionFraction ?? 0;
    const base = { label: label || null, product: null, doseMl: 0, percent: 0, spraySeconds: 0, intervalDays: null, severityBand: band, lesionFraction };
    if (!certain || !label) {
        return Object.freeze({ ...base, action: 'wait', reason: 'The condition did not pass every safeguard, so nothing is sprayed.' });
    }
    const rule = rules.rules[label] ?? rules.default;
    const action = rule.action ?? 'none';
    if (action !== 'spray') {
        return Object.freeze({ ...base, action, reason: rule.reason ?? rules.actions?.[action] ?? '' });
    }
    const mult = severityMultiplier(severity, rules);
    const doseMl = Math.round(Number(rule.dose_ml) * mult * 10) / 10;
    const flow = Number(rules.units.pump_ml_per_second);
    const spraySeconds = flow > 0 ? Math.round((doseMl / flow) * 10) / 10 : 0;
    const maxDose = Number(rules.units.max_dose_ml) || 0;
    const percent = maxDose > 0 ? Math.max(0, Math.min(100, Math.round((100 * doseMl) / maxDose))) : 0;
    return Object.freeze({
        ...base,
        action: 'spray',
        product: rule.product,
        doseMl,
        percent,
        spraySeconds,
        intervalDays: rule.interval_days ?? null,
        reason: rule.note ?? `${rule.product} at the ${band} severity rate.`,
    });
}

export function spraySummary(decision) {
    if (!decision) return '';
    if (decision.action === 'spray') {
        const sev = decision.severityBand !== 'unknown'
            ? `, lesion area ${Math.round(decision.lesionFraction * 100)}%`
            : '';
        return `Spray ${decision.percent}% (${decision.doseMl} mL ${decision.product}, ~${decision.spraySeconds} s pump${sev})`;
    }
    if (decision.action === 'remove') return 'Spray 0%: remove this plant (virus, spraying does not help)';
    if (decision.action === 'wait') return 'Spray 0%: condition not confirmed';
    return `Spray 0%: ${decision.reason}`;
}

// Short form for the live chip.
export function sprayChipText(decision) {
    if (!decision) return '';
    if (decision.action === 'spray') return `spray ${decision.percent}%`;
    if (decision.action === 'remove') return 'spray 0%, remove plant';
    return 'spray 0%';
}
