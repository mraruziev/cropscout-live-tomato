#!/usr/bin/env node
// Plays a real video (a Y4M clip from make_video_camera.py) to the live page as its camera
// and records what the page shows over time.
//
// Every --poll-ms it reads window.CropScoutVision.liveStats() and the live label; every
// --shot-ms it saves the camera view (overlay included) as a PNG. Output in --out:
// timeline.jsonl (one sample per poll) and frames/NNNNN.png.
//
// The page must already be served (scripts/serve.sh, or the server live-e2e.mjs starts).
//
// Usage: node live-video.mjs --clip <file.y4m> --seconds 60 [--url http://localhost:8080] [--query detector=1] [--out .out/video]

import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

function parseArgs(argv) {
    const o = { url: 'http://localhost:8080', query: '', seconds: 30, pollMs: 250, shotMs: 1000, out: '.out/video', headed: false };
    for (let i = 0; i < argv.length; i += 1) {
        const k = argv[i];
        const v = () => argv[++i];
        if (k === '--clip') o.clip = path.resolve(v());
        else if (k === '--url') o.url = v();
        else if (k === '--query') o.query = v();
        else if (k === '--seconds') o.seconds = Number(v());
        else if (k === '--poll-ms') o.pollMs = Number(v());
        else if (k === '--shot-ms') o.shotMs = Number(v());
        else if (k === '--out') o.out = path.resolve(v());
        else if (k === '--headed') o.headed = true;
        else throw new Error(`unknown option ${k}`);
    }
    if (!o.clip) throw new Error('--clip is required');
    return o;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
    const o = parseArgs(process.argv.slice(2));
    fs.mkdirSync(path.join(o.out, 'frames'), { recursive: true });
    const base = new URL(o.url);
    const browser = await chromium.launch({
        channel: 'chrome',
        headless: !o.headed,
        args: [
            '--use-fake-ui-for-media-stream',
            '--use-fake-device-for-media-stream',
            `--use-file-for-fake-video-capture=${o.clip}`,
            '--autoplay-policy=no-user-gesture-required',
            '--disable-background-timer-throttling',
            '--disable-renderer-backgrounding',
            '--disable-backgrounding-occluded-windows',
        ],
    });
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, permissions: ['camera'] });
    // Read-only: only GET/HEAD to the page's own server, never the field-note endpoint.
    await context.route('**/*', (route) => {
        const req = route.request();
        const url = new URL(req.url());
        if (url.protocol === 'data:' || url.protocol === 'blob:') return route.continue();
        const ours = url.host === base.host;
        if (!ours || !['GET', 'HEAD'].includes(req.method()) || /feedback/i.test(url.pathname)) return route.abort('blockedbyclient');
        return route.continue();
    });
    const page = await context.newPage();
    await page.goto(`${o.url}/vision/${o.query ? `?${o.query}` : ''}`);
    await page.locator('#model-state.ready').waitFor({ timeout: 120000 });
    await page.locator('#open-camera-button').click();
    const started = Date.now();
    const lines = [];
    let nextShot = 0;
    let shot = 0;
    while (Date.now() - started < o.seconds * 1000) {
        const tick = Date.now();
        const t = tick - started;
        const s = await page.evaluate(() => {
            const el = document.querySelector('#live-recognition');
            const stats = window.CropScoutVision?.liveStats?.() || null;
            return {
                state: el?.className || '',
                crop: document.querySelector('#live-crop-result')?.textContent?.trim() || '',
                cond: document.querySelector('#live-condition-result')?.textContent?.trim() || '',
                mode: stats?.mode || 'square',
                frames: stats?.frames ?? null,
                shown: stats?.shown ?? null,
                leaves: (stats?.leaves || []).map((l) => ({ box: l.box, score: l.score, state: l.state, shown: l.shown || null })),
            };
        });
        let frame = null;
        if (t >= nextShot) {
            frame = `frames/${String(shot).padStart(5, '0')}.png`;
            await page.locator('#camera-view').screenshot({ path: path.join(o.out, frame) }).catch(() => { frame = null; });
            shot += 1;
            nextShot += o.shotMs;
        }
        lines.push(JSON.stringify({ t, frame, ...s }));
        await sleep(Math.max(0, o.pollMs - (Date.now() - tick)));
    }
    fs.writeFileSync(path.join(o.out, 'timeline.jsonl'), lines.join('\n') + '\n');
    await browser.close();
    console.log(`${lines.length} samples, ${shot} frames -> ${o.out}`);
}

main().catch((e) => { console.error(e); process.exit(1); });
