import fs from 'node:fs';
import path from 'node:path';
const [ortPath, modelDir, threadsArg] = process.argv.slice(2);
const ort = await import(ortPath);
const threads = Number(threadsArg);
ort.env.wasm.numThreads = threads;
ort.env.wasm.proxy = false; if (process.env.WASM_DIR) ort.env.wasm.wasmPaths = process.env.WASM_DIR;
const files = fs.readdirSync(modelDir).filter(f => f.endsWith('.onnx')).sort();
for (const f of files) {
  const bytes = fs.readFileSync(path.join(modelDir, f));
  const s = await ort.InferenceSession.create(bytes, { executionProviders: ['wasm'], graphOptimizationLevel: 'all' });
  const n = 3 * 224 * 224;
  const data = new Float32Array(n); for (let i = 0; i < n; i++) data[i] = Math.random();
  const t = new ort.Tensor('float32', data, [1, 3, 224, 224]);
  const feeds = { [s.inputNames[0]]: t };
  for (let i = 0; i < 5; i++) await s.run(feeds);
  const ts = [];
  for (let i = 0; i < 50; i++) { const t0 = performance.now(); await s.run(feeds); ts.push(performance.now() - t0); }
  ts.sort((a, b) => a - b);
  const med = (ts[24] + ts[25]) / 2;
  console.log(`${f.padEnd(32)} wasm threads=${threads} median=${med.toFixed(2)} ms p90=${ts[44].toFixed(2)} min=${ts[0].toFixed(2)}`);
  await s.release();
}
