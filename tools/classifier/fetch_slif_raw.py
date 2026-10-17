"""Fetch the full-resolution raw photos of SLIF-Tomato (CC BY 4.0) into data/raw/slif/Raw_Dataset/.

The 890 field photos sit in one class folder each (Early_Blight, Mosaic, Healthy, ...). Only those
entries of the 6 GB Kaggle archive are read, by HTTP range requests; every entry is CRC-checked.

Usage: python -I tools/classifier/fetch_slif_raw.py data/raw/slif
"""
import os, sys, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from remote_zip import UA, entries, fetch, total_size

API = "https://www.kaggle.com/api/v1/datasets/download/romiyalgeorge/slif-tomato-dataset"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def signed_url():
    try:
        urllib.request.build_opener(NoRedirect).open(urllib.request.Request(API, headers=UA), timeout=60)
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307):
            return e.headers["Location"]
        raise
    raise RuntimeError("Kaggle did not redirect to a signed archive URL")


def main(out):
    url = signed_url()
    es = entries(url, total_size(url))
    wanted = [e for e in es if e[0].startswith("Raw_Dataset/") and not e[0].endswith("/")]
    print(f"{len(es)} entries, {len(wanted)} wanted, {sum(e[2] for e in wanted)/1e6:.0f} MB")
    written = fetch(url, wanted, out)
    print(f"wrote {len(written)} files to {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/raw/slif")
