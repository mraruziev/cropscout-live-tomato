"""Fetch the raw tomato part of CCMT (Mensah Kwabena et al. 2023, Mendeley bwh3zbpkpv v1, CC BY 4.0).

Only "Raw Data/CCMT Dataset/Tomato/<class>/" is fetched (5,805 files, 0.3 GB of the 8.4 GB release
zip), by HTTP range requests; every entry is CRC-checked. The augmented folders are skipped: three
quarters of their test set are byte copies of the train set. (The per-file API lists at most 1,000
files per folder, which would cut septoria short, so the zip is read instead.)

Usage: python -I tools/classifier/fetch_ccmt.py data/raw/ccmt
"""
import os, sys, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from remote_zip import UA, entries, fetch, total_size

ZIP = "https://data.mendeley.com/public-api/zip/bwh3zbpkpv/download/1"
PREFIX = "Raw Data/CCMT Dataset/Tomato/"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def signed_url():
    try:
        urllib.request.build_opener(NoRedirect).open(urllib.request.Request(ZIP, headers=UA), timeout=60)
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307):
            return e.headers["Location"]
        raise
    raise RuntimeError("Mendeley did not redirect to a signed archive URL")


def main(out):
    url = signed_url()
    es = entries(url, total_size(url))
    wanted = [e for e in es if PREFIX in e[0] and not e[0].endswith("/")]
    print(f"{len(es)} entries, {len(wanted)} wanted, {sum(e[2] for e in wanted)/1e6:.0f} MB")
    written = fetch(url, wanted, out, rename=lambda n: n.split(PREFIX, 1)[1])
    print(f"wrote {len(written)} files to {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/raw/ccmt")
