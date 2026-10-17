import sys, glob, os, time, statistics
import numpy as np, onnx, onnxruntime as ort
from collections import Counter
D = sys.argv[1]
models = sorted(glob.glob(os.path.join(D, "*.onnx")))
def shp(vi):
    return [d.dim_value if d.dim_value else (d.dim_param or "?") for d in vi.type.tensor_type.shape.dim]
for p in models:
    m = onnx.load(p, load_external_data=False)
    ops = Counter(n.op_type for n in m.graph.node)
    params = sum(int(np.prod(t.dims)) for t in m.graph.initializer)
    print(f"== {os.path.basename(p)}  {os.path.getsize(p)/1e6:.1f} MB  opset={[o.version for o in m.opset_import]}  params={params/1e6:.2f}M  nodes={len(m.graph.node)}")
    for i in m.graph.input: print("  in ", i.name, shp(i), onnx.TensorProto.DataType.Name(i.type.tensor_type.elem_type))
    for o in m.graph.output: print("  out", o.name, shp(o), onnx.TensorProto.DataType.Name(o.type.tensor_type.elem_type))
    print("  top ops:", ops.most_common(8))
    md = {p.key: p.value[:120] for p in m.metadata_props}
    if md: print("  meta:", {k: md[k] for k in list(md)[:8]})
print()
res = {}
for p in models:
    name = os.path.basename(p)
    for th in (1, 4):
        so = ort.SessionOptions(); so.intra_op_num_threads = th; so.inter_op_num_threads = 1
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        s = ort.InferenceSession(p, so, providers=["CPUExecutionProvider"])
        inp = s.get_inputs()[0]
        shape = [d if isinstance(d, int) else 1 for d in inp.shape]
        x = np.random.rand(*shape).astype(np.float32)
        for _ in range(5): s.run(None, {inp.name: x})
        ts = []
        for _ in range(50):
            t0 = time.perf_counter(); s.run(None, {inp.name: x}); ts.append((time.perf_counter()-t0)*1000)
        res[(name, th)] = statistics.median(ts)
        print(f"{name:32s} threads={th}  median={statistics.median(ts):7.2f} ms  p90={np.percentile(ts,90):7.2f}  min={min(ts):7.2f}")
