"""
Leaf and fruit assets for the greenhouse: textured, leaf-shaped meshes.

MuJoCo's classic renderer ignores texture alpha, so every leaf is a real leaf-shaped mesh
(outline polygon -> ear-clipped triangles, two-sided) with an RGB texture:
  - procedural tomato compound leaves (healthy), drawn with PIL
  - real PlantVillage leaflet photos (diseased classes) keyed out from their grey background,
    taken from  leaf_photos/<class>/  next to this file, or from the CropSCOUT repo's
    data/raw/plantvillage/{val,train}/<class>/ when that repo sits next to this folder.

build_assets(asset_dir) -> dict with
    "healthy": [LeafAsset, ...]           procedural compound leaves
    "disease": {class_name: [LeafAsset]}  photo leaflets per PlantVillage class
and writes <asset_dir>/*.png + *.obj. LeafAsset has mesh/texture names, length (m) and class.
"""
import glob
import hashlib
import math
import os
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
PV_CLASSES = ("Tomato___healthy", "Tomato___Early_blight", "Tomato___Late_blight", "Tomato___Bacterial_spot",
              "Tomato___Leaf_Mold", "Tomato___Target_Spot", "Tomato___Septoria_leaf_spot")


@dataclass
class LeafAsset:
    name: str          # mesh + texture + material share this name
    cls: str           # "healthy" or a PlantVillage class name
    length_m: float    # extent along the leaf axis
    source: str        # "procedural" or the photo path


# ----------------------------------------------------------------------------- geometry
def _ear_clip(poly):
    """Triangulate a simple polygon (list of (x, y)), returns index triples. O(n^2), fine for <200 pts."""
    n = len(poly)
    idx = list(range(n))
    # ensure counter-clockwise
    area = sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n))
    if area < 0:
        idx.reverse()
    tris = []

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def inside(p, a, b, c):
        return cross(a, b, p) >= 0 and cross(b, c, p) >= 0 and cross(c, a, p) >= 0

    guard = 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        found = False
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = poly[i0], poly[i1], poly[i2]
            if cross(a, b, c) <= 1e-9:
                continue                                      # reflex vertex
            if any(inside(poly[j], a, b, c) for j in idx if j not in (i0, i1, i2)):
                continue
            tris.append((i0, i1, i2)); idx.pop(k); found = True
            break
        if not found:                                         # degenerate: fan the rest
            for k in range(1, len(idx) - 1):
                tris.append((idx[0], idx[k], idx[k + 1]))
            return tris
    if len(idx) == 3:
        tris.append(tuple(idx))
    return tris


def _mask_to_polygon(mask, max_pts=90):
    """Largest outer contour of a boolean mask -> simplified polygon in pixel coords."""
    import cv2
    m8 = (mask.astype(np.uint8) * 255)
    m8 = cv2.morphologyEx(m8, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    cnts, _ = cv2.findContours(m8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.05 * mask.size:
        return None
    eps = 1.0
    while True:
        approx = cv2.approxPolyDP(c, eps, True)
        if len(approx) <= max_pts or eps > 20:
            break
        eps *= 1.4
    pts = [(float(p[0][0]), float(p[0][1])) for p in approx]
    return pts if len(pts) >= 5 else None


def _write_obj(path, poly, W, H, length_m, thickness=0.0015):
    """Two-sided leaf slab from a pixel polygon. Local frame: base of the leaf (bottom-centre of the
    image) at the origin, leaf extends along +y, texture u=x/W, v=1-y/H."""
    width_m = length_m * W / H
    tris = _ear_clip(poly)
    verts, uvs = [], []
    for (x, y) in poly:
        verts.append(((x / W - 0.5) * width_m, (1 - y / H) * length_m))
        uvs.append((x / W, 1 - y / H))
    n = len(poly)
    with open(path, "w") as f:
        f.write("# leaf slab\n")
        for z in (thickness / 2, -thickness / 2):
            for (vx, vy) in verts:
                f.write(f"v {vx:.5f} {vy:.5f} {z:.5f}\n")
        for (u, v) in uvs:
            f.write(f"vt {u:.5f} {v:.5f}\n")
        f.write("vn 0 0 1\nvn 0 0 -1\n")
        for (a, b, c) in tris:                                 # top: as triangulated (CCW)
            f.write(f"f {a+1}/{a+1}/1 {b+1}/{b+1}/1 {c+1}/{c+1}/1\n")
        for (a, b, c) in tris:                                 # bottom: reversed winding
            f.write(f"f {a+1+n}/{a+1}/2 {c+1+n}/{c+1}/2 {b+1+n}/{b+1}/2\n")


# ----------------------------------------------------------------------------- procedural leaves
def _leaflet_outline(cx, cy, length, width, angle, rng, lobes=9):
    """Ovate, toothed leaflet polygon; tip along `angle`, base at (cx, cy)."""
    pts = []
    n = 56
    phase = rng.uniform(0, 1)
    for i in range(n):
        t = i / n * 2 * math.pi
        r_l = 0.5 * length * (1 + 0.45 * math.cos(t))          # pointed tip, rounded base
        tooth = 1 + 0.06 * math.sin(lobes * t + phase) * (0.3 + 0.7 * abs(math.sin(t)))
        lobe = 1 + 0.10 * math.sin(2 * t + phase) * abs(math.sin(t))   # two shallow side lobes
        x = r_l * math.cos(t) * tooth + 0.5 * length * 0.55
        y = 0.5 * width * math.sin(t) * tooth * lobe * (1 - 0.3 * max(0.0, math.cos(t)))
        ca, sa = math.cos(angle), math.sin(angle)
        pts.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
    return pts


def _draw_leaflet(img, draw, pts, base_rgb, rng, spots=0, yellowing=0.0):
    g = tuple(int(np.clip(c * rng.uniform(0.85, 1.1), 0, 255)) for c in base_rgb)
    if yellowing > 0:
        g = (int(g[0] + (205 - g[0]) * yellowing), int(g[1] + (170 - g[1]) * yellowing * 0.6), int(g[2] * (1 - yellowing)))
    draw.polygon(pts, fill=g)
    # midrib + lateral veins
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    base = min(range(len(pts)), key=lambda i: xs[i] if False else 0)  # placeholder
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    vein = tuple(min(255, int(c * 1.25 + 20)) for c in g)
    tip = pts[0]; root = pts[len(pts) // 2]
    draw.line([root, tip], fill=vein, width=2)
    for k in range(1, 6):
        f = k / 6
        px, py = root[0] + (tip[0] - root[0]) * f, root[1] + (tip[1] - root[1]) * f
        dx, dy = tip[0] - root[0], tip[1] - root[1]
        L = math.hypot(dx, dy) * 0.16 * (1 - abs(f - 0.5))
        nx, ny = -dy / (math.hypot(dx, dy) + 1e-6), dx / (math.hypot(dx, dy) + 1e-6)
        for s in (1, -1):
            draw.line([(px, py), (px + dx * 0.12 + s * nx * L, py + dy * 0.12 + s * ny * L)], fill=vein, width=1)
    for _ in range(spots):                                     # early-blight style target spots
        sx = rng.uniform(min(xs) + 8, max(xs) - 8); sy = rng.uniform(min(ys) + 8, max(ys) - 8)
        r = rng.uniform(3, 7)
        draw.ellipse((sx - r - 2, sy - r - 2, sx + r + 2, sy + r + 2), fill=(200, 180, 60))
        draw.ellipse((sx - r, sy - r, sx + r, sy + r), fill=(110, 70, 30))
        draw.ellipse((sx - r * 0.5, sy - r * 0.5, sx + r * 0.5, sy + r * 0.5), fill=(70, 45, 20))


def draw_compound_leaf(path, seed, diseased=False, size=320):
    """Tomato compound leaf: rachis with 2-3 leaflet pairs + terminal leaflet. Returns (W, H, mask)."""
    rng = random.Random(seed)
    base_rgb = (52 + rng.randint(-8, 8), 128 + rng.randint(-15, 15), 48 + rng.randint(-8, 8))
    img = Image.new("RGB", (size, size), base_rgb)            # leaf-coloured background: no dark fringe
    draw = ImageDraw.Draw(img)
    cover = Image.new("L", (size, size), 0)                   # coverage mask drawn in parallel
    cdraw = ImageDraw.Draw(cover)
    # rachis from the bottom centre up to ~40 % height, slight curve; leaflet pairs along it
    top = size * 0.40
    pts_r = [(size * 0.5 + 10 * math.sin(t * 3.0), size * 0.98 - (size * 0.98 - top) * t) for t in np.linspace(0, 1, 12)]
    pairs = rng.choice([2, 3, 3])
    leaflets = []
    for k in range(pairs):
        t = (k + 0.5) / pairs * 0.95
        px, py = pts_r[min(11, int(t * 11))]
        L = size * rng.uniform(0.26, 0.33) * (1 - 0.1 * k)
        Wd = L * rng.uniform(0.5, 0.62)
        for s in (-1, 1):
            # leaflet axis roughly perpendicular to the rachis, tilted ~25 deg towards the leaf tip
            up = rng.uniform(0.3, 0.55)
            leaflets.append((px, py, L, Wd, (0 if s > 0 else math.pi) - s * up))
    tx, ty = pts_r[-1]
    leaflets.append((tx, ty, size * rng.uniform(0.30, 0.36), size * rng.uniform(0.17, 0.21), -math.pi / 2))
    spots = rng.randint(5, 10) if diseased else 0
    for (px, py, L, Wd, ang) in leaflets:
        poly = _leaflet_outline(px, py, L, Wd, ang, rng)
        _draw_leaflet(img, draw, poly, base_rgb, rng, spots=spots if rng.random() < 0.8 else 0,
                      yellowing=rng.uniform(0.15, 0.45) if diseased else 0.0)
        cdraw.polygon(poly, fill=255)
    draw.line(pts_r, fill=(80, 130, 60), width=4)
    cdraw.line(pts_r, fill=255, width=4)
    # low-frequency shading so the leaf is not one flat colour
    noise = Image.effect_noise((size // 8, size // 8), 40).resize((size, size), Image.BILINEAR)
    shade = np.asarray(noise, np.float32) / 255.0 * 0.5 + 0.75
    arr = (np.asarray(img).astype(np.float32) * shade[..., None]).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(0.5))
    img.save(path)
    mask = np.asarray(cover) > 127
    return size, size, mask


# ----------------------------------------------------------------------------- photo leaflets
def _key_out_leaf(img_bgr):
    """PlantVillage leaves sit on a grey background: keep saturated / non-grey pixels."""
    import cv2
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    mask = (s > 55) | ((v < 70) & (s > 25))
    mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)).astype(bool)
    return mask


def photo_dirs():
    """Candidate PlantVillage folders: leaf_photos/ next to this file, then the CropSCOUT repo."""
    cands = [HERE / "leaf_photos"]
    for repo in (HERE.parent, HERE.parent / "cropscout-live-tomato", Path.home() / "Documents" / "cropscout-live-tomato"):
        for split in ("val", "train"):
            cands.append(repo / "data" / "raw" / "plantvillage" / split)
    return [c for c in cands if c.exists()]


# ----------------------------------------------------------------------------- build
def build_assets(asset_dir, n_healthy=6, per_class=6, seed=1, leaf_len_m=0.40, leaflet_len_m=0.19):
    asset_dir = Path(asset_dir); asset_dir.mkdir(parents=True, exist_ok=True)
    out = {"healthy": [], "disease": {}}
    for i in range(n_healthy):
        name = f"leaf_h{i}"
        png, obj = asset_dir / f"{name}.png", asset_dir / f"{name}.obj"
        W, H, mask = draw_compound_leaf(png, seed * 100 + i, diseased=False)
        poly = _mask_to_polygon(mask)
        _write_obj(obj, poly, W, H, leaf_len_m)
        out["healthy"].append(LeafAsset(name, "healthy", leaf_len_m, "procedural"))
    # procedural diseased fallback (used for classes without photos)
    fallback = []
    for i in range(3):
        name = f"leaf_d{i}"
        W, H, mask = draw_compound_leaf(asset_dir / f"{name}.png", seed * 100 + 50 + i, diseased=True)
        _write_obj(asset_dir / f"{name}.obj", _mask_to_polygon(mask), W, H, leaf_len_m)
        fallback.append(LeafAsset(name, "procedural_blight", leaf_len_m, "procedural"))
    out["disease"]["procedural_blight"] = fallback
    # real photos
    try:
        import cv2
    except ImportError:
        cv2 = None
    if cv2 is not None:
        for d in photo_dirs():
            for cls_dir in sorted(p for p in d.iterdir() if p.is_dir() and p.name.startswith("Tomato___")):
                cls = cls_dir.name
                if cls in out["disease"] and len(out["disease"][cls]) >= per_class:
                    continue
                files = sorted(glob.glob(str(cls_dir / "*.[jJ][pP][gG]")) + glob.glob(str(cls_dir / "*.png")))
                random.Random(seed).shuffle(files)
                assets = out["disease"].setdefault(cls, [])
                for f in files:
                    if len(assets) >= per_class:
                        break
                    img = cv2.imread(f)
                    if img is None:
                        continue
                    img = cv2.resize(img, (256, 256), interpolation=cv2.INTER_AREA)
                    mask = _key_out_leaf(img)
                    poly = _mask_to_polygon(mask)
                    if poly is None:
                        continue
                    name = "leaf_" + hashlib.md5(f.encode()).hexdigest()[:10]
                    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                    # paint the background with the leaf's mean colour so texture sampling at the edge stays leaf-like
                    mean = rgb[mask].mean(axis=0).astype(np.uint8)
                    rgb = rgb.copy(); rgb[~mask] = mean
                    Image.fromarray(rgb).save(asset_dir / f"{name}.png")
                    _write_obj(asset_dir / f"{name}.obj", poly, 256, 256, leaflet_len_m)
                    assets.append(LeafAsset(name, cls, leaflet_len_m, f))
    # healthy photos replace procedural ones when available
    if "Tomato___healthy" in out["disease"]:
        out["healthy_photos"] = out["disease"].pop("Tomato___healthy")
    out["disease"] = {k: v for k, v in out["disease"].items() if v}
    return out


def mjcf_assets(assets):
    """<asset> entries (textures, materials, meshes) for everything in build_assets()' output."""
    lines = []
    for a in [*assets["healthy"], *assets.get("healthy_photos", []), *[x for v in assets["disease"].values() for x in v]]:
        lines.append(f'<texture name="tex_{a.name}" type="2d" file="{a.name}.png"/>')
        lines.append(f'<material name="mat_{a.name}" texture="tex_{a.name}" specular="0.15" shininess="0.2" rgba="1 1 1 1"/>')
        lines.append(f'<mesh name="{a.name}" file="{a.name}.obj"/>')
    return "\n".join(lines)


if __name__ == "__main__":
    a = build_assets(HERE / "assets")
    print("healthy:", len(a["healthy"]), "healthy photos:", len(a.get("healthy_photos", [])),
          "disease classes:", {k: len(v) for k, v in a["disease"].items()})
