#!/usr/bin/env node
// End-to-end harness for the CropSCOUT Live camera mode.
//
// For each fixture it builds a still fake-camera clip (make_fake_camera.py),
// launches the installed Google Chrome with that clip as the camera, opens
// /vision/ from a `php -S` server, runs the live camera for a fixed window and
// records what the live overlay shows. It then closes the camera, uploads the
// exact square the camera showed, and compares the live verdict with the
// upload verdict.
//
// Usage: node live-e2e.mjs [--root <dir>] [--only a,b] [--live-seconds 25] ...
//        node live-e2e.mjs --help
//
// Works with or without window.CropScoutVision.liveStats(): when the hook is
// missing, frames and frame times are estimated from page instrumentation
// (drawImage(video) calls and #live-recognition DOM updates).

import { chromium } from 'playwright';
import { spawn, spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROOT = path.resolve(HERE, '..');
// The repo's .venv: bin/python on macOS and Linux, Scripts\python.exe on Windows.
const DEFAULT_PYTHON = process.platform === 'win32'
    ? path.resolve(HERE, '..', '.venv', 'Scripts', 'python.exe')
    : path.resolve(HERE, '..', '.venv', 'bin', 'python');
const FALLBACK_PYTHON = process.platform === 'win32' ? 'python' : 'python3';
const MAKE_CLIP = path.join(HERE, 'make_fake_camera.py');
const IMAGE_EXTENSIONS = new Set(['.jpg', '.jpeg', '.png', '.webp']);
const HEALTHY_NAME = 'No covered disease pattern detected';

const HELP = `Live-camera e2e harness for CropSCOUT Live.

Options:
  --root <dir>          site root served with php -S (must contain vision/).
                        Default: ${DEFAULT_ROOT}
  --port <n>            port for php -S (default: derived from --root, so each
                        root gets its own port)
  --fixtures <file>     fixture list (default: fixtures.local.json, falling back
                        to fixtures.example.json)
  --only <a,b>          run only fixtures whose id contains one of these
                        substrings (case-insensitive)
  --list                print the resolved fixtures and exit
  --live-seconds <n>    live observation window per fixture (default 25)
  --poll-ms <n>         poll interval during the live window (default 200)
  --stop-when-stable <ms>  end the live window early once the shown state has
                        been unchanged this long after the first settled state
                        (default 0 = always watch the full window)
  --model-timeout <s>   wait for #model-state.ready (default 120)
  --query <qs>          query string for the page, e.g. detector=1 to turn on
                        the leaf finder (default: none)
  --width/--height/--frames  fake camera clip geometry (1920/1080/30)
  --range limited|full  YUV range for the clip (default: generator default)
  --matrix bt601|bt709  YUV matrix for the clip (default: generator default)
  --headed              show the browser window
  --screenshots         save the camera view at the end of each live window
                        as <out>/<id>.live.png
  --keep-y4m            keep generated .y4m clips (about 93 MB each at 1080p)
  --keep-server         leave php -S running for the next run to reuse
  --out <dir>           output directory (default: tests/.out)
  --report <file>       also write the markdown report here
  --json <file>         also write the JSON lines here
  --python <exe>        python with numpy + opencv (env CROPSCOUT_PYTHON)
  --calibrate           measure fake-camera colour fidelity for each YUV
                        range/matrix and exit
`;

// ---------------------------------------------------------------- options

function parseArgs(argv) {
    const opts = {
        root: DEFAULT_ROOT,
        port: null,
        fixtures: null,
        only: [],
        list: false,
        liveSeconds: 25,
        pollMs: 200,
        stopWhenStable: 0,
        modelTimeout: 120,
        uploadTimeout: 90,
        query: '',
        width: 1920,
        height: 1080,
        frames: 30,
        range: null,
        matrix: null,
        headed: false,
        screenshots: false,
        keepY4m: false,
        keepServer: false,
        out: path.join(HERE, '.out'),
        report: null,
        json: null,
        python: process.env.CROPSCOUT_PYTHON || (fs.existsSync(DEFAULT_PYTHON) ? DEFAULT_PYTHON : FALLBACK_PYTHON),
        calibrate: false,
    };
    const flags = new Set(['list', 'headed', 'keep-y4m', 'keep-server', 'calibrate', 'help', 'screenshots']);
    const numbers = new Set(['port', 'live-seconds', 'poll-ms', 'stop-when-stable', 'model-timeout',
        'upload-timeout', 'width', 'height', 'frames']);
    for (let i = 0; i < argv.length; i += 1) {
        let arg = argv[i];
        if (!arg.startsWith('--')) throw new Error(`unexpected argument: ${arg}`);
        arg = arg.slice(2);
        let value = null;
        const eq = arg.indexOf('=');
        if (eq >= 0) {
            value = arg.slice(eq + 1);
            arg = arg.slice(0, eq);
        }
        if (arg === 'help') {
            process.stdout.write(HELP);
            process.exit(0);
        }
        const key = arg.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
        if (flags.has(arg)) {
            opts[key] = value === null ? true : value !== 'false';
            continue;
        }
        if (!(key in opts)) throw new Error(`unknown option --${arg}`);
        if (value === null) {
            value = argv[i + 1];
            i += 1;
            if (value === undefined) throw new Error(`--${arg} needs a value`);
        }
        if (arg === 'only') {
            opts.only.push(...value.split(',').map((s) => s.trim().toLowerCase()).filter(Boolean));
        } else if (numbers.has(arg)) {
            const n = Number(value);
            if (!Number.isFinite(n)) throw new Error(`--${arg} must be a number`);
            opts[key] = n;
        } else {
            opts[key] = value;
        }
    }
    opts.root = fs.realpathSync(path.resolve(opts.root));
    opts.out = path.resolve(opts.out);
    if (!fs.existsSync(path.join(opts.root, 'vision', 'index.php'))) {
        throw new Error(`--root ${opts.root} has no vision/index.php`);
    }
    if (opts.out === opts.root || opts.out.startsWith(opts.root + path.sep)) {
        // Only allowed for the default root (the repo that holds tests/).
        if (opts.root !== fs.realpathSync(DEFAULT_ROOT)) {
            throw new Error('--out must not be inside --root: the served root is read-only for this harness');
        }
    }
    return opts;
}

const log = (...parts) => process.stderr.write(`${parts.join(' ')}\n`);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ---------------------------------------------------------------- fixtures

function slug(text) {
    return String(text).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'fixture';
}

function firstImageIn(dir) {
    const names = fs.readdirSync(dir)
        .filter((name) => IMAGE_EXTENSIONS.has(path.extname(name).toLowerCase()))
        .sort();
    if (names.length === 0) throw new Error(`no images in ${dir}`);
    return path.join(dir, names[0]);
}

function loadFixtures(opts) {
    const local = path.join(HERE, 'fixtures.local.json');
    const example = path.join(HERE, 'fixtures.example.json');
    const file = opts.fixtures ? path.resolve(opts.fixtures) : (fs.existsSync(local) ? local : example);
    const data = JSON.parse(fs.readFileSync(file, 'utf8'));
    const entries = Array.isArray(data) ? data : data.fixtures;
    if (!Array.isArray(entries)) throw new Error(`${file}: expected a "fixtures" array`);
    const base = path.dirname(file);
    const seen = new Set();
    const fixtures = entries.map((entry, index) => {
        let source;
        let problem = null;
        try {
            if (entry.synthetic) {
                source = `synthetic:${entry.synthetic}`;
            } else if (entry.dir) {
                source = firstImageIn(path.resolve(base, entry.dir));
            } else if (entry.path) {
                source = path.resolve(base, entry.path);
                if (!fs.existsSync(source)) problem = `missing file: ${source}`;
            } else {
                problem = 'fixture needs "path", "dir" or "synthetic"';
            }
        } catch (error) {
            problem = error.message;
        }
        let id = slug(entry.id || (source ? path.basename(source, path.extname(source)) : `fixture-${index + 1}`));
        while (seen.has(id)) id = `${id}-${index + 1}`;
        seen.add(id);
        return {
            id,
            source: source || null,
            expected: entry.expected ?? '',
            note: entry.note ?? '',
            // "plant": a busy scene with several leaves. Photo mode is not the
            // reference there (one leaf no longer fills the square).
            scene: entry.scene === 'plant' ? 'plant' : 'single',
            problem,
        };
    });
    const filtered = opts.only.length
        ? fixtures.filter((f) => opts.only.some((needle) => f.id.includes(needle)))
        : fixtures;
    return { file, fixtures: filtered, usingExample: file === example };
}

// ---------------------------------------------------------------- php server

function derivePort(root) {
    const digest = crypto.createHash('sha256').update(root).digest();
    return 8700 + (digest.readUInt16BE(0) % 200);
}

function listenable(port, host) {
    return new Promise((resolve) => {
        const server = net.createServer();
        server.once('error', (error) => resolve(error.code === 'EADDRNOTAVAIL'));
        server.listen({ port, host, exclusive: true }, () => server.close(() => resolve(true)));
    });
}

async function portIsFree(port) {
    // Chrome may try ::1 first for "localhost", so both loopbacks must be free.
    return (await listenable(port, '127.0.0.1')) && (await listenable(port, '::1'));
}

function pidAlive(pid) {
    try {
        process.kill(pid, 0);
        return true;
    } catch {
        return false;
    }
}

async function httpOk(url, timeoutMs = 3000) {
    try {
        const response = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) });
        await response.arrayBuffer();
        return response.ok;
    } catch {
        return false;
    }
}

function registryPath(opts) {
    return path.join(opts.out, 'servers.json');
}

function readRegistry(opts) {
    try {
        return JSON.parse(fs.readFileSync(registryPath(opts), 'utf8'));
    } catch {
        return {};
    }
}

function writeRegistry(opts, registry) {
    fs.writeFileSync(registryPath(opts), `${JSON.stringify(registry, null, 2)}\n`);
}

async function ensureServer(opts) {
    const registry = readRegistry(opts);
    let port = opts.port ?? derivePort(opts.root);
    for (let attempt = 0; attempt < 40; attempt += 1, port += 1) {
        const entry = registry[port];
        if (await portIsFree(port)) {
            if (entry) {
                delete registry[port];
                writeRegistry(opts, registry);
            }
            return startServer(opts, port, registry);
        }
        if (entry && entry.root === opts.root && pidAlive(entry.pid)
            && await httpOk(`http://127.0.0.1:${port}/vision/`)) {
            log(`reusing php -S on port ${port} for ${opts.root} (pid ${entry.pid})`);
            return { port, reused: true, stop: async () => {} };
        }
        if (opts.port !== null) throw new Error(`port ${port} is busy and is not a php -S server for this root`);
    }
    throw new Error('no free port found for php -S');
}

async function startServer(opts, port, registry) {
    const args = ['-S', `127.0.0.1:${port}`, '-t', opts.root];
    const tail = [];
    const child = spawn('php', args, {
        cwd: opts.out,
        stdio: opts.keepServer ? 'ignore' : ['ignore', 'ignore', 'pipe'],
        detached: opts.keepServer,
    });
    if (child.stderr) {
        child.stderr.on('data', (chunk) => {
            tail.push(...String(chunk).split('\n').filter(Boolean));
            if (tail.length > 40) tail.splice(0, tail.length - 40);
        });
    }
    let exited = null;
    child.on('exit', (code) => { exited = code; });
    const deadline = Date.now() + 15000;
    while (Date.now() < deadline) {
        if (exited !== null) break;
        if (await httpOk(`http://127.0.0.1:${port}/vision/`)) {
            if (opts.keepServer) {
                child.unref();
                registry[port] = { root: opts.root, pid: child.pid, started: new Date().toISOString() };
                writeRegistry(opts, registry);
            }
            log(`php -S 127.0.0.1:${port} -t ${opts.root} (pid ${child.pid})`);
            return {
                port,
                reused: false,
                tail,
                stop: async () => {
                    if (opts.keepServer || exited !== null) return;
                    child.kill('SIGTERM');
                    await Promise.race([new Promise((r) => child.once('exit', r)), sleep(2000)]);
                },
            };
        }
        await sleep(150);
    }
    child.kill('SIGKILL');
    throw new Error(`php -S did not come up on port ${port}: ${tail.slice(-5).join(' | ')}`);
}

// ---------------------------------------------------------------- clips

function makeClip(opts, source, clipPath, extra = []) {
    const args = ['-I', MAKE_CLIP, source, clipPath,
        '--width', String(opts.width), '--height', String(opts.height), '--frames', String(opts.frames)];
    if (opts.range) args.push('--range', opts.range);
    if (opts.matrix) args.push('--matrix', opts.matrix);
    args.push(...extra);
    const run = spawnSync(opts.python, args, { encoding: 'utf8' });
    if (run.status !== 0) {
        throw new Error(`make_fake_camera.py failed: ${(run.stderr || run.stdout || '').trim().split('\n').pop()}`);
    }
    return clipPath.replace(/\.y4m$/i, '') + '.square.png';
}

function chromeArgs(clipPath) {
    return [
        '--use-fake-ui-for-media-stream',
        '--use-fake-device-for-media-stream',
        `--use-file-for-fake-video-capture=${clipPath}`,
        '--autoplay-policy=no-user-gesture-required',
        '--disable-background-timer-throttling',
        '--disable-renderer-backgrounding',
        '--disable-backgrounding-occluded-windows',
    ];
}

async function launchChrome(opts, clipPath) {
    return chromium.launch({
        channel: 'chrome',
        headless: !opts.headed,
        args: chromeArgs(clipPath),
    });
}

async function newHarnessContext(browser, port) {
    const context = await browser.newContext({
        viewport: { width: 1280, height: 900 },
        permissions: ['camera'],
    });
    const blocked = [];
    // Read-only guarantee for the served root: only GET/HEAD to our own server,
    // and never the field-note endpoint (it can write to disk on POST).
    await context.route('**/*', (route) => {
        const request = route.request();
        let url;
        try {
            url = new URL(request.url());
        } catch {
            return route.continue();
        }
        if (url.protocol === 'data:' || url.protocol === 'blob:') return route.continue();
        const ours = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname) && Number(url.port) === port;
        const safeMethod = request.method() === 'GET' || request.method() === 'HEAD';
        if (!ours || !safeMethod || /feedback/i.test(url.pathname)) {
            blocked.push(`${request.method()} ${url.pathname}${url.search}`);
            return route.abort('blockedbyclient');
        }
        return route.continue();
    });
    await context.addInitScript(instrumentPage);
    return { context, blocked };
}

// ---------------------------------------------------------------- page code

// Runs in the page before app.js. Records every #live-recognition change with
// a timestamp and every drawImage/createImageBitmap call on a <video> (one per
// analysed live frame), without changing app behaviour.
function instrumentPage() {
    if (window.__cropscoutHarness) return;
    const H = { t0: null, draws: [], updates: [], log: [], ignoreDraws: false, installed: false };
    Object.defineProperty(window, '__cropscoutHarness', { value: H });
    const isVideo = (source) => typeof HTMLVideoElement !== 'undefined' && source instanceof HTMLVideoElement;
    const note = (source) => {
        if (isVideo(source) && !H.ignoreDraws) H.draws.push(performance.now());
    };
    for (const Ctx of [window.CanvasRenderingContext2D, window.OffscreenCanvasRenderingContext2D]) {
        if (!Ctx || !Ctx.prototype.drawImage) continue;
        const original = Ctx.prototype.drawImage;
        Ctx.prototype.drawImage = function drawImage(...args) {
            note(args[0]);
            return original.apply(this, args);
        };
    }
    if (typeof window.createImageBitmap === 'function') {
        const original = window.createImageBitmap;
        window.createImageBitmap = function createImageBitmap(...args) {
            note(args[0]);
            return original.apply(this, args);
        };
    }
    H.read = () => {
        const box = document.querySelector('#live-recognition');
        if (!box) return null;
        const state = ['loading', 'identified', 'uncertain', 'error']
            .find((name) => box.classList.contains(`is-${name}`)) || 'none';
        return {
            state,
            crop: (document.querySelector('#live-crop-result')?.textContent || '').trim(),
            cond: (document.querySelector('#live-condition-result')?.textContent || '').trim(),
        };
    };
    const install = () => {
        const box = document.querySelector('#live-recognition');
        if (!box || H.installed) return;
        H.installed = true;
        let lastKey = '';
        const record = () => {
            const now = performance.now();
            H.updates.push(now);
            const snapshot = H.read();
            const key = `${snapshot.state}\u0001${snapshot.crop}\u0001${snapshot.cond}`;
            if (key !== lastKey) {
                lastKey = key;
                H.log.push({ t: now, ...snapshot });
            }
        };
        new MutationObserver(record).observe(box, {
            attributes: true,
            attributeFilter: ['class'],
            childList: true,
            characterData: true,
            subtree: true,
        });
        record();
    };
    document.addEventListener('click', (event) => {
        if (event.target instanceof Element
            && event.target.closest('#open-camera-button, #reopen-camera-button')) {
            H.t0 = performance.now();
        }
    }, true);
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', install, { once: true });
    } else {
        install();
    }
}

function pageSnapshot() {
    const H = window.__cropscoutHarness;
    let stats = null;
    let statsError = null;
    const api = window.CropScoutVision;
    if (api && typeof api.liveStats === 'function') {
        try {
            stats = JSON.parse(JSON.stringify(api.liveStats()));
        } catch (error) {
            statsError = String(error);
        }
    }
    return { t: performance.now(), dom: H ? H.read() : null, stats, statsError, hasLiveStats: Boolean(api && typeof api.liveStats === 'function') };
}

// Compares the centre square of a <video> with the reference PNG at 224 px.
async function pageColourCheck({ b64, selector, grid }) {
    const H = window.__cropscoutHarness || {};
    H.ignoreDraws = true;
    try {
        const video = document.querySelector(selector);
        if (!video || !video.videoWidth) return { error: 'no video frame' };
        const N = 224;
        const vw = video.videoWidth;
        const vh = video.videoHeight;
        const side = Math.min(vw, vh);
        const grab = (source, sx, sy, sw, sh) => {
            const canvas = document.createElement('canvas');
            canvas.width = N;
            canvas.height = N;
            const g = canvas.getContext('2d', { willReadFrequently: true });
            g.imageSmoothingEnabled = true;
            g.imageSmoothingQuality = 'high';
            g.drawImage(source, sx, sy, sw, sh, 0, 0, N, N);
            return g.getImageData(0, 0, N, N).data;
        };
        const live = grab(video, (vw - side) / 2, (vh - side) / 2, side, side);
        const bytes = Uint8Array.from(atob(b64), (ch) => ch.charCodeAt(0));
        const bitmap = await createImageBitmap(new Blob([bytes], { type: 'image/png' }), {
            colorSpaceConversion: 'none',
            premultiplyAlpha: 'none',
        });
        const ref = grab(bitmap, 0, 0, bitmap.width, bitmap.height);
        bitmap.close();
        const sumAbs = [0, 0, 0];
        const sumDiff = [0, 0, 0];
        let pixels = 0;
        for (let i = 0; i < live.length; i += 4) {
            for (let c = 0; c < 3; c += 1) {
                const d = live[i + c] - ref[i + c];
                sumAbs[c] += Math.abs(d);
                sumDiff[c] += d;
            }
            pixels += 1;
        }
        const round = (v) => Math.round(v * 100) / 100;
        const out = {
            video: [vw, vh],
            meanAbs: sumAbs.map((v) => round(v / pixels)),
            bias: sumDiff.map((v) => round(v / pixels)),
            meanAbsAll: round((sumAbs[0] + sumAbs[1] + sumAbs[2]) / (3 * pixels)),
        };
        if (grid) {
            const cell = N / grid;
            const sample = (data, cx, cy) => {
                const acc = [0, 0, 0];
                let n = 0;
                for (let y = cy - 3; y <= cy + 3; y += 1) {
                    for (let x = cx - 3; x <= cx + 3; x += 1) {
                        const o = ((y * N) + x) * 4;
                        acc[0] += data[o];
                        acc[1] += data[o + 1];
                        acc[2] += data[o + 2];
                        n += 1;
                    }
                }
                return acc.map((v) => Math.round(v / n));
            };
            out.patches = [];
            for (let gy = 0; gy < grid; gy += 1) {
                for (let gx = 0; gx < grid; gx += 1) {
                    const cx = Math.round((gx + 0.5) * cell);
                    const cy = Math.round((gy + 0.5) * cell);
                    out.patches.push({ live: sample(live, cx, cy), ref: sample(ref, cx, cy) });
                }
            }
        }
        return out;
    } finally {
        H.ignoreDraws = false;
    }
}

function pageUploadState() {
    const q = (s) => document.querySelector(s);
    const txt = (s) => (q(s)?.textContent || '').trim();
    const vis = (s) => Boolean(q(s)) && !q(s).hidden;
    return {
        cardVisible: vis('#result-card'),
        errorVisible: vis('#result-error'),
        errorTitle: vis('#result-error') ? txt('#error-title') : null,
        errorMessage: vis('#result-error') ? txt('#error-message') : null,
        badge: txt('#match-badge'),
        resultLabel: txt('#result-crop'),
        title: txt('#result-title'),
        crop: txt('#result-fact-crop'),
        organ: txt('#result-fact-organ'),
        condition: txt('#result-fact-condition'),
        status: txt('#result-fact-status'),
        identityScore: vis('#identity-score-card') ? txt('#identity-score-value') : null,
        conditionScore: vis('#condition-score-card') ? txt('#condition-score-value') : null,
        closestMatch: vis('#closest-match') ? `${txt('#closest-match-name')} ${txt('#closest-match-score')}`.trim() : null,
    };
}

// ---------------------------------------------------------------- verdicts

function liveVerdict(dom) {
    if (!dom) return { kind: 'none', crop: '', condition: null, score: null, text: '' };
    const crop = dom.crop || '';
    const cond = dom.cond || '';
    const text = `${crop} — ${cond}`;
    if (dom.state === 'error') return { kind: 'error', crop, condition: cond, score: null, text };
    if (dom.state === 'uncertain') {
        const noCrop = /^(no supported crop|possible\b)/i.test(crop);
        return { kind: 'abstain', reason: noCrop ? 'crop' : 'condition', crop, condition: null, score: null, text };
    }
    if (dom.state === 'identified' && !/checking|confirming|loading|starting/i.test(cond)) {
        if (/no covered condition/i.test(cond)) return { kind: 'crop-only', crop, condition: null, score: null, text };
        const [name, ...rest] = cond.split('·').map((s) => s.trim());
        if (name && !/crop match/i.test(name)) {
            const score = (rest.join(' ').match(/(<?\d+%)/) || [])[1] || null;
            return { kind: 'condition', crop, condition: name, score, text };
        }
    }
    return { kind: 'pending', crop, condition: null, score: null, text };
}

function uploadVerdict(state) {
    if (!state) return { kind: 'none', crop: '', condition: null, score: null };
    if (state.errorVisible) {
        return { kind: 'error', crop: '', condition: `${state.errorTitle}: ${state.errorMessage}`, score: null };
    }
    const organ = state.organ && state.organ !== 'Not established' ? ` ${state.organ.toLowerCase()}` : '';
    const crop = state.crop && state.crop !== 'Not established' ? `${state.crop}${organ}` : '';
    const badge = (state.badge || '').toLowerCase();
    const condition = state.condition || '';
    if (badge === 'high-confidence screen' || badge === 'healthy-like pattern'
        || /high-confidence condition|healthy-like/i.test(state.status || '')) {
        return { kind: 'condition', crop, condition, score: state.conditionScore };
    }
    if (badge === 'no reliable match' || /^not run$/i.test(condition)) {
        return { kind: 'abstain', reason: 'crop', crop, condition: null, score: null };
    }
    if (badge.startsWith('uncertain') || /^closest:/i.test(condition)) {
        const closest = condition.replace(/^closest:\s*/i, '').replace(/\s*—\s*not a diagnosis$/i, '');
        return { kind: 'abstain', reason: 'condition', crop, condition: null, closest, score: state.conditionScore };
    }
    if (badge === 'confident crop match' || /not available/i.test(condition)) {
        return { kind: 'crop-only', crop, condition: null, score: null };
    }
    return { kind: 'other', crop, condition, score: state.conditionScore };
}

function agrees(live, upload) {
    if (!live || !upload) return false;
    if (live.kind === 'condition' && upload.kind === 'condition') {
        return live.condition.trim().toLowerCase() === upload.condition.trim().toLowerCase();
    }
    if (live.kind === 'abstain' && upload.kind === 'abstain') return true;
    if (live.kind === 'crop-only' && upload.kind === 'crop-only') return true;
    return false;
}

function verdictKey(v) {
    return `${v.kind}|${v.crop}|${v.condition ?? ''}|${v.reason ?? ''}`;
}

const SETTLED = new Set(['condition', 'crop-only', 'abstain', 'error']);

// ---------------------------------------------------------------- per fixture

async function runLive(page, pngPath, opts) {
    const open = page.locator('#open-camera-button');
    await open.waitFor({ state: 'visible', timeout: 5000 });
    await open.click();
    const t0 = await page.evaluate(() => window.__cropscoutHarness.t0 ?? performance.now());
    const samples = [];
    const started = Date.now();
    const windowMs = opts.liveSeconds * 1000;
    while (Date.now() - started < windowMs) {
        const tick = Date.now();
        samples.push(await page.evaluate(pageSnapshot));
        if (opts.stopWhenStable > 0) {
            const H = await page.evaluate(() => window.__cropscoutHarness.log.slice(-1)[0] || null);
            const last = samples[samples.length - 1];
            if (H && SETTLED.has(liveVerdict(H).kind) && last.t - H.t >= opts.stopWhenStable) break;
        }
        await sleep(Math.max(0, opts.pollMs - (Date.now() - tick)));
    }
    const windowEnd = samples.length ? samples[samples.length - 1].t : t0;
    const colour = await page.evaluate(pageColourCheck, {
        b64: fs.readFileSync(pngPath).toString('base64'),
        selector: '#camera-video',
        grid: 0,
    }).catch((error) => ({ error: error.message }));
    const H = await page.evaluate(() => {
        const h = window.__cropscoutHarness;
        return { log: h.log, draws: h.draws, updates: h.updates, installed: h.installed };
    });
    const cameraStatus = (await page.locator('#camera-status').textContent().catch(() => '') || '').trim();
    if (opts.screenshots) {
        await page.locator('#camera-view').screenshot({ path: pngPath.replace(/\.square\.png$/, '.live.png') }).catch(() => {});
    }
    await page.locator('#close-camera-button').click();
    await page.locator('#camera-panel').waitFor({ state: 'hidden', timeout: 5000 });

    // Timeline (DOM changes since the click, plus the state shown at the click).
    const before = H.log.filter((e) => e.t < t0).slice(-1);
    const entries = [...before, ...H.log.filter((e) => e.t >= t0 && e.t <= windowEnd + 1)].map((e) => ({
        ms: Math.max(0, Math.round(e.t - t0)),
        state: e.state,
        crop: e.crop,
        cond: e.cond,
        verdict: liveVerdict(e),
    }));
    const firstVerdict = entries.find((e) => e.verdict.kind === 'condition') || null;
    const firstSettledIndex = entries.findIndex((e) => SETTLED.has(e.verdict.kind));
    const firstSettled = firstSettledIndex >= 0 ? entries[firstSettledIndex] : null;

    // Flicker: shown-state changes (score stripped) after the first settled state.
    let flicker = 0;
    let verdictFlips = 0;
    if (firstSettledIndex >= 0) {
        let lastSettledKey = verdictKey(entries[firstSettledIndex].verdict);
        for (let i = firstSettledIndex + 1; i < entries.length; i += 1) {
            const key = verdictKey(entries[i].verdict);
            if (key !== verdictKey(entries[i - 1].verdict)) flicker += 1;
            if (SETTLED.has(entries[i].verdict.kind) && key !== lastSettledKey) {
                verdictFlips += 1;
                lastSettledKey = key;
            }
        }
    }
    // Literal count: raw #live-condition-result text changes after the first condition verdict.
    let conditionTextChanges = 0;
    if (firstVerdict) {
        const startIndex = entries.indexOf(firstVerdict);
        for (let i = startIndex + 1; i < entries.length; i += 1) {
            if (entries[i].cond !== entries[i - 1].cond) conditionTextChanges += 1;
        }
    }

    const lastSample = samples[samples.length - 1] || null;
    const finalDom = lastSample?.dom || (entries.length ? entries[entries.length - 1] : null);
    const final = liveVerdict(finalDom);
    const hasLiveStats = samples.some((s) => s.hasLiveStats);
    const stats = lastSample?.stats || null;

    // liveStats-based shown verdict changes (only when the hook exists).
    let statsVerdictChanges = null;
    if (hasLiveStats) {
        statsVerdictChanges = 0;
        let previous = null;
        for (const sample of samples) {
            const shown = sample.stats?.shownVerdict ?? null;
            if (!shown) continue;
            if (previous !== null && shown !== previous) statsVerdictChanges += 1;
            previous = shown;
        }
    }

    // Instrumentation estimates (always computed, used when liveStats is absent).
    const draws = H.draws.filter((t) => t >= t0 && t <= windowEnd);
    const updates = H.updates.filter((t) => t >= t0);
    const durations = [];
    for (let i = 0; i < draws.length; i += 1) {
        const startT = draws[i];
        const stopT = i + 1 < draws.length ? draws[i + 1] : null;
        if (stopT === null && draws.length > 1) break; // last frame may be cut off by the window
        let lastUpdate = null;
        for (const u of updates) {
            if (u > startT && (stopT === null || u <= stopT)) lastUpdate = u;
        }
        if (lastUpdate !== null) durations.push(lastUpdate - startT);
    }
    const mean = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
    const estimated = {
        frames: draws.length,
        avgFrameMs: mean(durations),
        avgCycleMs: draws.length > 1 ? (draws[draws.length - 1] - draws[0]) / (draws.length - 1) : null,
        firstFrameMs: draws.length ? draws[0] - t0 : null,
    };
    const useStats = hasLiveStats && stats && Number.isFinite(stats.frames);
    const round = (v) => (v === null || v === undefined || !Number.isFinite(v) ? null : Math.round(v));

    // Leaf finder (only when the page reports it): how often it split the
    // square into leaves, and what each leaf showed at the end of the window.
    const modeSamples = samples.filter((sample) => sample.stats?.mode);
    const leafSamples = modeSamples.filter((sample) => sample.stats.mode === 'leaves');
    const leafFinder = modeSamples.length && Number.isFinite(stats?.avgDetectorMs) && stats.avgDetectorMs > 0
        ? {
            leavesModeShare: Math.round((100 * leafSamples.length) / modeSamples.length),
            maxLeaves: Math.max(0, ...leafSamples.map((sample) => sample.stats.leaves?.length || 0)),
            finalMode: stats.mode,
            finalLeaves: (stats.leaves || []).map((leaf) => ({
                box: leaf.box,
                score: leaf.score,
                kind: leaf.kind,
                state: leaf.state,
                crop: leaf.crop,
                condition: leaf.condition,
                shown: leaf.shown,
            })),
            shownLeaves: (stats.leaves || []).filter((leaf) => leaf.shown).length,
            avgDetectorMs: round(stats.avgDetectorMs),
        }
        : null;

    return {
        verdict: final,
        finalText: finalDom ? { state: finalDom.state, crop: finalDom.crop, cond: finalDom.cond } : null,
        firstVerdict: firstVerdict ? { ms: firstVerdict.ms, ...firstVerdict.verdict } : null,
        timeToVerdictMs: firstVerdict ? firstVerdict.ms : null,
        timeToSettledMs: firstSettled ? firstSettled.ms : null,
        flicker,
        verdictFlips,
        conditionTextChanges,
        statsVerdictChanges,
        frames: useStats ? stats.frames : estimated.frames,
        avgFrameMs: round(useStats ? stats.avgFrameMs : estimated.avgFrameMs),
        framesSource: useStats ? 'liveStats' : 'estimated',
        estimated: {
            frames: estimated.frames,
            avgFrameMs: round(estimated.avgFrameMs),
            avgCycleMs: round(estimated.avgCycleMs),
            firstFrameMs: round(estimated.firstFrameMs),
        },
        hasLiveStats,
        liveStats: stats,
        leafFinder,
        statsError: lastSample?.statsError || null,
        windowMs: Math.round(windowEnd - t0),
        instrumentationInstalled: H.installed,
        colour,
        cameraStatus,
        distinctTexts: [...new Set(entries.map((e) => `${e.state} | ${e.crop} | ${e.cond}`))],
        timeline: entries.map((e) => ({ ms: e.ms, state: e.state, crop: e.crop, cond: e.cond })),
    };
}

async function runUpload(page, pngPath, opts) {
    const started = Date.now();
    await page.setInputFiles('#image-input', pngPath);
    const visibleAny = () => {
        const vis = (s) => {
            const el = document.querySelector(s);
            return Boolean(el) && !el.hidden;
        };
        return vis('#result-busy') || vis('#result-card') || vis('#result-error');
    };
    // The page may start analysing as soon as a file is selected; press
    // Analyze only if it did not.
    const autoStarted = await page.waitForFunction(visibleAny, null, { timeout: 2500, polling: 50 })
        .then(() => true).catch(() => false);
    if (!autoStarted) await page.locator('#analyze-button').click({ timeout: 10000 });
    await page.waitForFunction(() => {
        const vis = (s) => {
            const el = document.querySelector(s);
            return Boolean(el) && !el.hidden;
        };
        return !vis('#result-busy') && (vis('#result-card') || vis('#result-error'));
    }, null, { timeout: opts.uploadTimeout * 1000, polling: 100 });
    const state = await page.evaluate(pageUploadState);
    return { ...state, verdict: uploadVerdict(state), autoStarted, ms: Date.now() - started };
}

async function runFixture(fixture, opts, server) {
    const result = {
        id: fixture.id,
        source: fixture.source,
        expected: fixture.expected,
        scene: fixture.scene,
        ok: false,
        error: null,
    };
    if (fixture.problem) {
        result.error = fixture.problem;
        return result;
    }
    const started = Date.now();
    const clipPath = path.join(opts.out, `${fixture.id}.y4m`);
    let browser = null;
    try {
        const pngPath = makeClip(opts, fixture.source, clipPath);
        result.square = pngPath;
        browser = await launchChrome(opts, clipPath);
        result.chrome = browser.version();
        const { context, blocked } = await newHarnessContext(browser, server.port);
        const page = await context.newPage();
        const pageErrors = [];
        page.on('pageerror', (error) => pageErrors.push(String(error.message || error)));
        page.on('console', (message) => {
            if (message.type() === 'error') pageErrors.push(`console: ${message.text()}`);
        });
        const loadStart = Date.now();
        const query = opts.query ? `?${opts.query.replace(/^\?/, '')}` : '';
        await page.goto(`http://localhost:${server.port}/vision/${query}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
        const modelState = await page.waitForFunction(() => {
            const el = document.querySelector('#model-state');
            if (!el) return null;
            if (el.classList.contains('ready')) return 'ready';
            if (el.classList.contains('error')) return `error: ${(document.querySelector('#model-state-text')?.textContent || '').trim()}`;
            return null;
        }, null, { timeout: opts.modelTimeout * 1000, polling: 100 }).then((handle) => handle.jsonValue());
        result.modelLoadMs = Date.now() - loadStart;
        if (modelState !== 'ready') throw new Error(`models not ready (${modelState})`);

        result.live = await runLive(page, pngPath, opts);
        result.upload = await runUpload(page, pngPath, opts);
        result.agree = agrees(result.live.verdict, result.upload.verdict);
        result.pageErrors = pageErrors;
        result.blockedRequests = blocked;
        result.ok = true;
    } catch (error) {
        result.error = String(error.message || error).split('\n')[0];
    } finally {
        if (browser) await browser.close().catch(() => {});
        if (!opts.keepY4m) fs.rmSync(clipPath, { force: true });
        result.fixtureMs = Date.now() - started;
    }
    return result;
}

// ---------------------------------------------------------------- report

const md = (value) => String(value ?? '').replace(/\|/g, '\\|').replace(/\n/g, ' ');
const seconds = (ms) => (ms === null || ms === undefined ? '—' : `${(ms / 1000).toFixed(1)} s`);

function shortCondition(name) {
    return name === HEALTHY_NAME ? 'healthy-like' : name;
}

function describeLive(v) {
    if (!v) return '—';
    switch (v.kind) {
        case 'condition': return `${v.crop}: ${shortCondition(v.condition)}${v.score ? ` ${v.score}` : ''}`;
        case 'crop-only': return `${v.crop}: no covered condition`;
        case 'abstain': return v.reason === 'crop' ? `abstain (${v.crop})` : `abstain (${v.crop}; condition unreliable)`;
        case 'error': return `error: ${v.crop}`;
        default: return `pending: ${v.text}`;
    }
}

function describeUpload(v) {
    if (!v) return '—';
    switch (v.kind) {
        case 'condition': return `${v.crop}: ${shortCondition(v.condition)}${v.score ? ` ${v.score}` : ''}`;
        case 'crop-only': return `${v.crop}: no covered condition`;
        case 'abstain': return v.reason === 'crop'
            ? `abstain (no reliable crop${v.crop ? `; closest ${v.crop}` : ''})`
            : `abstain (${v.crop}; closest ${shortCondition(v.closest || '?')}${v.score ? ` ${v.score}` : ''})`;
        case 'error': return `error: ${v.condition}`;
        default: return `${v.kind}: ${v.crop} ${v.condition ?? ''}`.trim();
    }
}

function buildReport(results, meta) {
    const lines = [];
    lines.push('# CropSCOUT Live camera e2e');
    lines.push('');
    lines.push(`- Date: ${meta.date}`);
    lines.push(`- Root: \`${meta.root}\` (served with php -S on port ${meta.port})`);
    if (meta.query) lines.push(`- Page: \`/vision/?${meta.query.replace(/^\?/, '')}\``);
    lines.push(`- Fixtures: \`${meta.fixturesFile}\` (${results.length} run)`);
    lines.push(`- Browser: Google Chrome ${meta.chrome || '?'} (${meta.headed ? 'headed' : 'headless'})`);
    lines.push(`- Fake camera: ${meta.width}x${meta.height} Y4M, still frame; live window ${meta.liveSeconds} s, poll ${meta.pollMs} ms`);
    lines.push(`- Total run time: ${seconds(meta.totalMs)}`);
    lines.push('');
    lines.push('| fixture | expected | live verdict | upload verdict | agree? | time-to-verdict | frames | avg ms | flicker count |');
    lines.push('|---|---|---|---|---|---|---|---|---|');
    let estimatedUsed = false;
    for (const r of results) {
        if (!r.ok) {
            lines.push(`| ${md(r.id)} | ${md(r.expected)} | ERROR: ${md(r.error)} | | | | | | |`);
            continue;
        }
        const live = r.live;
        const star = live.framesSource === 'estimated' ? '*' : '';
        if (star) estimatedUsed = true;
        const ttv = live.timeToVerdictMs !== null
            ? seconds(live.timeToVerdictMs)
            : (live.timeToSettledMs !== null ? `— (settled ${seconds(live.timeToSettledMs)})` : '—');
        lines.push([
            '', md(r.id), md(r.expected), md(describeLive(live.verdict)), md(describeUpload(r.upload.verdict)),
            r.agree ? 'yes' : 'NO', ttv, `${live.frames ?? '—'}${star}`,
            `${live.avgFrameMs ?? '—'}${live.avgFrameMs !== null ? star : ''}`, String(live.flicker), '',
        ].join(' | ').trim());
    }
    const ok = results.filter((r) => r.ok);
    const single = ok.filter((r) => r.scene !== 'plant');
    const plants = ok.filter((r) => r.scene === 'plant');
    lines.push('');
    lines.push(`Agreement: ${single.filter((r) => r.agree).length}/${single.length}. `
        + `Live condition verdicts: ${single.filter((r) => r.live.verdict.kind === 'condition').length}/${single.length}.`
        + (plants.length ? ` (${plants.length} whole-plant scene${plants.length > 1 ? 's' : ''} not counted: photo mode is not the reference there.)` : ''));
    lines.push('');
    lines.push('- time-to-verdict: from the Live camera click to the first `is-identified` state showing a condition '
        + '(not "checking"/"confirming"). If no condition verdict appeared, the time to the first settled state '
        + '(abstain or crop-only) is shown in brackets.');
    lines.push('- flicker count: changes of the shown live state (state + crop + condition name, score stripped) '
        + 'after the first settled state. A steady still frame should give 0.');
    if (estimatedUsed) {
        lines.push('- `*` frames / avg ms estimated by page instrumentation (no `liveStats()` hook): one frame = one '
            + '`drawImage(video)`; frame ms = time from that draw to the last overlay update before the next draw.');
    }
    const finder = ok.filter((r) => r.live.leafFinder);
    if (finder.length) {
        lines.push('');
        lines.push('## Leaf finder');
        lines.push('');
        lines.push('| fixture | scene | frames split into leaves | most leaves in a frame | leaves at the end (shown verdict, else state) | detector ms | frame ms | cycle ms |');
        lines.push('|---|---|---|---|---|---|---|---|');
        for (const r of finder) {
            const f = r.live.leafFinder;
            const leaves = f.finalMode === 'leaves' && f.finalLeaves.length
                ? f.finalLeaves.map((leaf) => {
                    const shown = leaf.shown ? leaf.shown.split('|').pop() : '';
                    return `${leaf.kind.replace('tomato_', '')} ${Math.round(leaf.score * 100)}%: ${shown ? shortCondition(shown) : leaf.state}`;
                }).join('; ')
                : 'whole square';
            const cycle = r.live.frames > 1 ? Math.round(r.live.windowMs / r.live.frames) : '—';
            lines.push(['', md(r.id), r.scene, `${f.leavesModeShare}%`, f.maxLeaves, md(leaves),
                f.avgDetectorMs ?? '—', r.live.avgFrameMs ?? '—', cycle, ''].join(' | ').trim());
        }
        lines.push('');
        lines.push('- detector ms: the leaf finder on the 320 px square (resize included). frame ms: all work for one frame '
            + '(detector, cutting out each leaf, both classifiers per leaf). cycle ms: live window / frames analysed. '
            + 'Box scores are the detector\'s; every verdict comes from the classifiers and safeguards.');
    }
    lines.push('');
    lines.push('## Diagnostics');
    lines.push('');
    lines.push('| fixture | upload title | identity | live first frame | live cycle ms | verdict flips | raw cond. text changes | camera vs PNG colour error (mean abs R,G,B) | model load |');
    lines.push('|---|---|---|---|---|---|---|---|---|');
    for (const r of ok) {
        const c = r.live.colour || {};
        const colour = c.meanAbs ? `${c.meanAbs.join(', ')} (bias ${c.bias.join(', ')}) @ ${c.video.join('x')}` : md(c.error || '—');
        lines.push([
            '', md(r.id), md(r.upload.title), md(r.upload.identityScore ?? '—'),
            seconds(r.live.estimated.firstFrameMs), r.live.estimated.avgCycleMs ?? '—',
            r.live.verdictFlips, r.live.conditionTextChanges, colour, seconds(r.modelLoadMs), '',
        ].join(' | ').trim());
    }
    const notes = [];
    for (const r of ok) {
        if (r.pageErrors?.length) notes.push(`- ${r.id}: page errors: ${md(r.pageErrors.slice(0, 3).join(' / '))}`);
        if (r.blockedRequests?.length) notes.push(`- ${r.id}: blocked requests: ${md(r.blockedRequests.slice(0, 3).join(', '))}`);
        if (r.live.statsError) notes.push(`- ${r.id}: liveStats() threw: ${md(r.live.statsError)}`);
    }
    if (notes.length) {
        lines.push('');
        lines.push('## Notes');
        lines.push('');
        lines.push(...notes);
    }
    return `${lines.join('\n')}\n`;
}

// ---------------------------------------------------------------- calibrate

async function calibrate(opts, server) {
    const variants = [['limited', 'bt601'], ['full', 'bt601'], ['limited', 'bt709'], ['full', 'bt709']];
    const rows = [];
    for (const [range, matrix] of variants) {
        const clip = path.join(opts.out, `calibrate-${range}-${matrix}.y4m`);
        const png = makeClip({ ...opts, range, matrix, frames: 4 }, 'synthetic:patches', clip);
        const browser = await launchChrome(opts, clip);
        try {
            const { context } = await newHarnessContext(browser, server.port);
            const page = await context.newPage();
            await page.goto(`http://localhost:${server.port}/vision/model.php?model=metadata`);
            await page.evaluate(async () => {
                const stream = await navigator.mediaDevices.getUserMedia({
                    audio: false,
                    video: { width: { ideal: 1920 }, height: { ideal: 1080 } },
                });
                const video = document.createElement('video');
                video.id = 'harness-video';
                video.muted = true;
                video.playsInline = true;
                video.srcObject = stream;
                document.body.append(video);
                await video.play();
                await new Promise((resolve) => setTimeout(resolve, 800));
            });
            const check = await page.evaluate(pageColourCheck, {
                b64: fs.readFileSync(png).toString('base64'),
                selector: '#harness-video',
                grid: 6,
            });
            const patchErr = check.patches
                ? check.patches.reduce((acc, p) => acc + p.live.reduce((a, v, i) => a + Math.abs(v - p.ref[i]), 0) / 3, 0) / check.patches.length
                : null;
            rows.push({ range, matrix, ...check, patchMeanAbs: patchErr === null ? null : Math.round(patchErr * 100) / 100 });
        } finally {
            await browser.close().catch(() => {});
            if (!opts.keepY4m) fs.rmSync(clip, { force: true });
        }
    }
    const lines = ['| range | matrix | video | mean abs R,G,B | bias R,G,B | patch-centre mean abs | black patch | white patch | pure red patch |',
        '|---|---|---|---|---|---|---|---|---|'];
    for (const r of rows) {
        const p = (i) => (r.patches ? `${r.patches[i].live.join(',')} (ref ${r.patches[i].ref.join(',')})` : '—');
        lines.push(`| ${r.range} | ${r.matrix} | ${r.video?.join('x') ?? '—'} | ${r.meanAbs?.join(', ') ?? r.error} | ${r.bias?.join(', ') ?? ''} | ${r.patchMeanAbs ?? '—'} | ${p(0)} | ${p(5)} | ${p(6)} |`);
    }
    const best = rows.filter((r) => r.patchMeanAbs !== null).sort((a, b) => a.patchMeanAbs - b.patchMeanAbs)[0];
    const text = `${lines.join('\n')}\n\nBest: --range ${best?.range} --matrix ${best?.matrix}\n`;
    process.stdout.write(text);
    fs.writeFileSync(path.join(opts.out, 'calibration.md'), text);
}

// ---------------------------------------------------------------- main

async function main() {
    const opts = parseArgs(process.argv.slice(2));
    fs.mkdirSync(opts.out, { recursive: true });

    const { file: fixturesFile, fixtures, usingExample } = loadFixtures(opts);
    if (opts.list) {
        for (const f of fixtures) {
            process.stdout.write(`${f.id}\t${f.expected}\t${f.source ?? ''}${f.problem ? `\t[${f.problem}]` : ''}\n`);
        }
        return 0;
    }
    if (!opts.calibrate && fixtures.length === 0) throw new Error('no fixtures selected');
    if (usingExample && fixtures.every((f) => f.problem || !f.source?.startsWith('synthetic:'))) {
        log('note: using fixtures.example.json (placeholder paths). Copy it to fixtures.local.json and fill in real image paths.');
    }

    const server = await ensureServer(opts);
    const stopAll = async () => {
        await server.stop();
    };
    process.once('SIGINT', () => {
        stopAll().finally(() => process.exit(130));
    });

    try {
        if (opts.calibrate) {
            await calibrate(opts, server);
            return 0;
        }
        const runStarted = Date.now();
        const results = [];
        const jsonLines = [];
        let chrome = null;
        for (const [index, fixture] of fixtures.entries()) {
            log(`[${index + 1}/${fixtures.length}] ${fixture.id} ...`);
            const result = await runFixture(fixture, opts, server);
            chrome = chrome || result.chrome;
            results.push(result);
            const line = JSON.stringify(result);
            jsonLines.push(line);
            process.stdout.write(`${line}\n`);
            if (result.ok) {
                log(`    live: ${describeLive(result.live.verdict)} | upload: ${describeUpload(result.upload.verdict)} | `
                    + `agree=${result.agree} ttv=${seconds(result.live.timeToVerdictMs)} frames=${result.live.frames} `
                    + `flicker=${result.live.flicker} (${seconds(result.fixtureMs)})`);
            } else {
                log(`    ERROR: ${result.error}`);
            }
        }
        const report = buildReport(results, {
            date: new Date().toISOString(),
            root: opts.root,
            port: server.port,
            fixturesFile: path.relative(HERE, fixturesFile),
            chrome,
            headed: opts.headed,
            width: opts.width,
            height: opts.height,
            liveSeconds: opts.liveSeconds,
            pollMs: opts.pollMs,
            query: opts.query,
            totalMs: Date.now() - runStarted,
        });
        process.stdout.write(`\n${report}`);
        fs.writeFileSync(path.join(opts.out, 'last-run.md'), report);
        fs.writeFileSync(path.join(opts.out, 'last-run.jsonl'), `${jsonLines.join('\n')}\n`);
        if (opts.report) fs.writeFileSync(path.resolve(opts.report), report);
        if (opts.json) fs.writeFileSync(path.resolve(opts.json), `${jsonLines.join('\n')}\n`);
        return results.every((r) => r.ok) ? 0 : 2;
    } finally {
        await stopAll();
    }
}

main().then((code) => {
    process.exitCode = code;
}, (error) => {
    log(`live-e2e: ${error.stack || error.message || error}`);
    process.exitCode = 1;
});
