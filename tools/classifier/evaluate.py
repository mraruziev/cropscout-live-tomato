"""Score classifiers on real photos with the page's own gates (pipeline.py), not on top-1 accuracy.

Sets:
- plant:    the whole-plant fixtures (tests/fixtures.local.json, "scene": "plant"), in photo mode,
            as a live square, and with the leaf finder;
- closeup:  the other fixtures: photo mode and live square should give the same verdict;
- user:     a ground-truth manifest of real user photos (--user-manifest), identity and condition;
- field:    the held-out test split of the field set (data/processed/classifier/test).

A shown verdict is "wrong" when it names a disease the photo does not have (any crop), "missed"
when it says healthy-like on a diseased photo, "right" when it matches; everything else abstains.

Usage: python -I tools/classifier/evaluate.py [--condition m.onnx] [--tomato-leaf m.onnx] [--crop-view m.onnx]
                                              [--user-manifest f.json] [--json out.json]
"""
import argparse, collections, csv, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pipeline import ROOT, Pipeline, open_rgb, photo_tensor, to_tensor, halve_to, SIZE

# Truth for the whole-plant fixtures, from each source's own label. "viral mottling" (Sichuan's
# unnamed virus) counts as right when the mosaic-virus class is named.
PLANT_TRUTH = {
    "plant-greenhouse-viral": {"Tomato_leaf_tomato_mosaic_virus"},
    "plant-greenhouse-dense": {"Tomato_leaf_tomato_mosaic_virus"},
    "plant-greenhouse-fruit": set(),  # gray mold: not a covered class
    "plant-field-potted": {"Tomato_leaf_early_blight"},
    "plant-field-stem": {"Tomato_leaf_early_blight"},
    "plant-canopy-web": {"Tomato_leaf_leaf_mold"},
}


def judge(shown, truth, healthy_ok=False):
    if shown is None:
        return "abstain"
    if shown in truth:
        return "right"
    if shown.endswith("_healthy"):
        return "right" if healthy_ok else "missed"
    return "wrong"


def fixtures():
    path = os.path.join(ROOT, "tests", "fixtures.local.json")
    out = []
    for f in json.load(open(path))["fixtures"]:
        p = f.get("path")
        if f.get("dir"):
            p = os.path.join(f["dir"], sorted(os.listdir(f["dir"]))[0])
        if p:
            out.append(dict(id=f["id"], path=p, scene=f.get("scene", "single"), expected=f.get("expected", "")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--condition")
    ap.add_argument("--crop-view")
    ap.add_argument("--tomato-leaf", help="candidate tomato-leaf specialist")
    ap.add_argument("--user-manifest")
    ap.add_argument("--json")
    ap.add_argument("--sets", default="plant,closeup,user,field")
    args = ap.parse_args()
    sets = set(args.sets.split(","))
    on = Pipeline(args.condition, args.crop_view, detector=True, tomato_leaf=args.tomato_leaf)
    off = Pipeline(args.condition, args.crop_view, detector=False, tomato_leaf=args.tomato_leaf)
    report = {}

    if "plant" in sets or "closeup" in sets:
        plant, closeup = [], []
        for f in fixtures():
            img = open_rgb(f["path"])
            if f["scene"] == "plant":
                truth = PLANT_TRUTH.get(f["id"], set())
                ph = off.photo(img)
                sq = off.live(img)["results"][0]
                lv = on.live(img)
                leaves = [dict(verdict=r["verdict"], judged=judge(r["shown"], truth)) for r in lv["results"]]
                plant.append(dict(id=f["id"], photo=ph["verdict"], photo_judged=judge(ph["shown"], truth),
                                  square=sq["verdict"], square_judged=judge(sq["shown"], truth),
                                  finder_mode=lv["mode"], finder=leaves))
            elif "plant" in sets or "closeup" in sets:
                # live-e2e.mjs uploads the 1080 px square the camera showed, so photo mode sees that
                ph = off.photo(off.camera_square(img))
                sq = off.live(img)["results"][0]
                lv = on.live(img)
                closeup.append(dict(id=f["id"], expected=f["expected"], photo=ph["verdict"], square=sq["verdict"],
                                    same=ph["shown"] == sq["shown"], finder_mode=lv["mode"],
                                    finder=[r["verdict"] for r in lv["results"]]))
        report["plant"], report["closeup"] = plant, closeup
        print("\n## Whole-plant scenes\n")
        print("| scene | photo | live, finder off | finder on |")
        print("|---|---|---|---|")
        for r in plant:
            fin = " · ".join(f"{l['verdict']} [{l['judged']}]" for l in r["finder"])
            print(f"| {r['id']} | {r['photo']} [{r['photo_judged']}] | {r['square']} [{r['square_judged']}] | {r['finder_mode']}: {fin} |")
        wrong_off = sum(r["square_judged"] == "wrong" for r in plant)
        wrong_on = sum(any(l["judged"] == "wrong" for l in r["finder"]) for r in plant)
        print(f"\nScenes with a confident wrong disease name: finder off {wrong_off}, finder on {wrong_on}.")
        print("\n## Close-up fixtures\n")
        print("| fixture | expected | photo | live square | same | finder |")
        print("|---|---|---|---|---|---|")
        for r in closeup:
            print(f"| {r['id']} | {r['expected']} | {r['photo']} | {r['square']} | {'yes' if r['same'] else 'NO'} | {r['finder_mode']}: {' · '.join(r['finder'])} |")
        print(f"\nPhoto = live square on {sum(r['same'] for r in closeup)}/{len(closeup)}.")

    if "user" in sets and args.user_manifest:
        base = os.path.dirname(os.path.dirname(os.path.abspath(args.user_manifest)))
        rows = []
        for r in json.load(open(args.user_manifest))["images"]:
            p = os.path.join(base, r["path"])
            if not os.path.exists(p):
                continue
            res = off.photo(open_rgb(p))
            ident = r.get("identity_labels") or []
            cond = set(r.get("condition_labels") or [])
            g = res["crop_gate"]
            id_state = "abstain" if not g["ok"] else ("right" if g["label"] in ident else "wrong")
            shown = res.get("shown")
            if shown is None:
                c_state = "abstain"
            elif cond:
                c_state = "right" if shown in cond else ("missed" if shown.endswith("_healthy") else "wrong")
            else:
                # no verified condition: only a healthy-like or a different-crop disease can be judged
                same_crop = any(shown.startswith(i + "_") for i in ident)
                c_state = "unverified" if same_crop else "wrong"
            rows.append(dict(id=r["id"], identity=ident, crop=f"{g['label']} {g['conf']:.0%}", identity_state=id_state,
                             verdict=res["verdict"], condition_state=c_state))
        report["user"] = rows
        print("\n## User photos\n")
        print("| photo | truth | crop gate | verdict | identity | condition |")
        print("|---|---|---|---|---|---|")
        for r in rows:
            print(f"| {r['id']} | {','.join(r['identity'])} | {r['crop']} | {r['verdict']} | {r['identity_state']} | {r['condition_state']} |")
        c = collections.Counter(r["identity_state"] for r in rows)
        d = collections.Counter(r["condition_state"] for r in rows)
        print(f"\nIdentity: {c['right']} right, {c['wrong']} wrong, {c['abstain']} abstain of {len(rows)}. Condition: {dict(d)}.")

    if "field" in sets:
        d = os.path.join(ROOT, "data", "processed", "classifier")
        stats = collections.defaultdict(collections.Counter)
        for r in csv.DictReader(open(os.path.join(d, "manifest.csv"))):
            if r["split"] != "test":
                continue
            img = open_rgb(os.path.join(d, r["file"]))
            res = off.classify(to_tensor(img, SIZE))
            state = judge(res.get("shown"), {r["label"]}, healthy_ok=r["label"].endswith("_healthy"))
            if r["label"].endswith("_healthy") and res.get("shown") and not res["shown"].endswith("_healthy"):
                state = "wrong"
            key = f"{r['source']}:{r['kind']}"
            stats[key][state] += 1
            stats["all"][state] += 1
            stats[f"label:{r['label']}"][state] += 1
        report["field"] = {k: dict(v) for k, v in stats.items()}
        print("\n## Field test split (held out)\n")
        print("| set | images | right | wrong | missed | abstain | wrong among shown |")
        print("|---|---|---|---|---|---|---|")
        for k in sorted(stats, key=lambda k: (k != "all", k)):
            v = stats[k]
            n = sum(v.values())
            shown = v["right"] + v["wrong"] + v["missed"]
            print(f"| {k} | {n} | {v['right']} | {v['wrong']} | {v['missed']} | {v['abstain']} | "
                  f"{(v['wrong'] + v['missed']) / shown:.0%} |" if shown else f"| {k} | {n} | 0 | 0 | 0 | {v['abstain']} | — |")

    if args.json:
        json.dump(report, open(args.json, "w"), indent=1)


if __name__ == "__main__":
    main()
