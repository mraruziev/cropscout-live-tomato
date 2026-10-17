// Parity tests for vision/spray.js against the shared rules.  Run:  node --test tests/
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { classifyPixel, decideSpray, estimateSeverityFromTensor, spraySummary } from '../vision/spray.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const rules = JSON.parse(fs.readFileSync(path.join(here, '..', 'vision', 'spray-rules.json'), 'utf8'));

// Same synthetic leaf as live/test_spray.py: BGR green (40,150,40), brown (20,60,120), grey (128,128,128).
function leafTensor(lesionFraction, cover = 1) {
    const side = 224;
    const plane = side * side;
    const chw = new Float32Array(3 * plane);
    const rows = Math.floor(side * cover);
    const cols = Math.floor(side * lesionFraction);
    for (let y = 0; y < side; y += 1) {
        for (let x = 0; x < side; x += 1) {
            let rgb = [128, 128, 128];
            if (y < rows) rgb = x < cols ? [120, 60, 20] : [40, 150, 40];
            const i = y * side + x;
            chw[i] = rgb[0] / 255;
            chw[plane + i] = rgb[1] / 255;
            chw[2 * plane + i] = rgb[2] / 255;
        }
    }
    return chw;
}

test('pixel classes match the OpenCV thresholds', () => {
    assert.equal(classifyPixel(40 / 255, 150 / 255, 40 / 255), 'green');
    assert.equal(classifyPixel(120 / 255, 60 / 255, 20 / 255), 'lesion');
    assert.equal(classifyPixel(0.5, 0.5, 0.5), 'other');
});

test('severity bands', () => {
    assert.equal(estimateSeverityFromTensor(leafTensor(0), rules).band, 'low');
    assert.equal(estimateSeverityFromTensor(leafTensor(0.2), rules).band, 'medium');
    const high = estimateSeverityFromTensor(leafTensor(0.4), rules);
    assert.equal(high.band, 'high');
    assert.ok(Math.abs(high.lesionFraction - 0.4) < 0.03);
    assert.equal(estimateSeverityFromTensor(leafTensor(0, 0.05), rules).band, 'unknown');
});

test('healthy and unconfirmed results spray nothing', () => {
    const high = { lesionFraction: 0.5, leafCover: 0.9, band: 'high' };
    assert.equal(decideSpray(rules, 'Tomato_leaf_healthy', true, high).doseMl, 0);
    assert.equal(decideSpray(rules, 'Tomato_leaf_late_blight', false, high).action, 'wait');
    assert.equal(decideSpray(rules, 'Tomato_leaf_yellow_leaf_curl_virus', true, high).action, 'remove');
    assert.equal(decideSpray(rules, 'Tomato_fruit_blossom_end_rot', true, high).action, 'none');
});

test('dose scales with severity, same numbers as Python', () => {
    const low = decideSpray(rules, 'Tomato_leaf_early_blight', true, { lesionFraction: 0.05, leafCover: 0.9, band: 'low' });
    const high = decideSpray(rules, 'Tomato_leaf_early_blight', true, { lesionFraction: 0.5, leafCover: 0.9, band: 'high' });
    assert.equal(low.doseMl, 18);   // 30 * 0.6
    assert.equal(high.doseMl, 42);  // 30 * 1.4
    assert.equal(high.spraySeconds, 4.2);
    assert.equal(high.percent, 75);   // 42 of a 56 mL maximum
    assert.equal(low.percent, 32);
    assert.match(spraySummary(high), /^Spray 75% \(42 mL protectant fungicide/);
    const max = decideSpray(rules, 'Tomato_leaf_late_blight', true, { lesionFraction: 0.5, leafCover: 0.9, band: 'high' });
    assert.equal(max.percent, 100);
    assert.equal(decideSpray(rules, 'Tomato_leaf_healthy', true, { band: 'high', lesionFraction: 0.5 }).percent, 0);
});
