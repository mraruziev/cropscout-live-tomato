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

export function classifyPixel(r, g, b) {
    const [h, s, v] = rgbToHsvOpenCv(r, g, b);
    const green = h >= 35 && h <= 85 && s > 60 && v > 50;
    if (green) return 'green';
    const brown = h >= 5 && h < 35 && s > 60 && v > 40;
    const dark = v < 60 && s > 30;
    return brown || dark ? 'lesion' : 'other';
}

// `chw` is a Float32Array laid out [3][side][side] with RGB values in 0..1,
// exactly what the models take, so the estimate costs no extra decode.
export function estimateSeverityFromTensor(chw, rules, side = 224) {
    const plane = side * side;
    let nGreen = 0;
    let nLesion = 0;
    for (let i = 0; i < plane; i += 1) {
        const kind = classifyPixel(chw[i], chw[plane + i], chw[2 * plane + i]);
        if (kind === 'green') nGreen += 1;
        else if (kind === 'lesion') nLesion += 1;
    }
    return bandSeverity(nGreen, nLesion, plane, rules);
}

// `rgba` is an ImageData.data buffer (0..255).
export function estimateSeverityFromImageData(rgba, width, height, rules) {
    let nGreen = 0;
    let nLesion = 0;
    for (let i = 0; i < rgba.length; i += 4) {
        const kind = classifyPixel(rgba[i] / 255, rgba[i + 1] / 255, rgba[i + 2] / 255);
        if (kind === 'green') nGreen += 1;
        else if (kind === 'lesion') nLesion += 1;
    }
    return bandSeverity(nGreen, nLesion, width * height, rules);
}

function bandSeverity(nGreen, nLesion, total, rules) {
    const cfg = rules.severity;
    const leafCover = (nGreen + nLesion) / total;
    if (leafCover < cfg.min_leaf_cover || nGreen + nLesion === 0) {
        return Object.freeze({ lesionFraction: 0, leafCover, band: 'unknown' });
    }
    const frac = nLesion / (nGreen + nLesion);
    const band = frac <= cfg.low_max ? 'low' : frac >= cfg.high_min ? 'high' : 'medium';
    return Object.freeze({ lesionFraction: frac, leafCover, band });
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
    const mult = rules.severity.multipliers[band] ?? 1;
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
