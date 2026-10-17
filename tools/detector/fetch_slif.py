"""Fetch only the detection part of SLIF-Tomato (CC BY 4.0) into data/raw/slif/.

The Kaggle archive is 6 GB, but the boxes live only in Detection_Dataset/ (about 2,670
Roboflow 640x640 copies plus YOLO .txt files). This reads the zip's central directory with
HTTP range requests and downloads just the byte span that holds those entries.

Usage: python -I tools/detector/fetch_slif.py data/raw/slif
"""
import io, os, struct, sys, urllib.request, zipfile, zlib, json

API = "https://www.kaggle.com/api/v1/datasets/download/romiyalgeorge/slif-tomato-dataset"
PREFIXES = ("Detection_Dataset/",)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def signed_url():
    opener = urllib.request.build_opener(NoRedirect)
    try:
        opener.open(API)
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307):
            return e.headers["Location"]
        raise
    raise RuntimeError("Kaggle did not redirect to a signed archive URL")


def get_range(url, start, end):
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        if r.status != 206:
            raise RuntimeError(f"range request returned {r.status}")
        return r.read()


def total_size(url):
    req = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return int(r.headers["Content-Range"].split("/")[1])


def central_directory(url, size):
    tail = get_range(url, max(0, size - 65536), size - 1)
    eocd = tail.rfind(b"PK\x05\x06")
    cd_size, cd_off = struct.unpack("<II", tail[eocd + 12:eocd + 20])
    loc = tail.rfind(b"PK\x06\x07")  # zip64 locator
    if loc != -1:
        z64_off = struct.unpack("<Q", tail[loc + 8:loc + 16])[0]
        rec = get_range(url, z64_off, z64_off + 55)
        cd_size, cd_off = struct.unpack("<QQ", rec[40:56])
    return cd_off, get_range(url, cd_off, cd_off + cd_size - 1)


def main(out):
    os.makedirs(out, exist_ok=True)
    url = signed_url()
    size = total_size(url)
    cd_off, cd = central_directory(url, size)
    # Let zipfile parse the central directory by giving it a fake file whose tail is the real CD.
    fake = io.BytesIO(cd + get_range(url, cd_off + len(cd), size - 1))
    zf = zipfile.ZipFile(_Shifted(fake, cd_off, size))
    infos = [i for i in zf.infolist() if i.filename.startswith(PREFIXES) and not i.is_dir()]
    print(f"archive {size/1e9:.2f} GB, {len(zf.infolist())} entries, {len(infos)} wanted")
    lo = min(i.header_offset for i in infos)
    hi = max(i.header_offset + 30 + len(i.filename.encode()) + 1024 + i.compress_size for i in infos)
    hi = min(hi, cd_off) - 1
    print(f"downloading bytes {lo}-{hi} ({(hi - lo)/1e6:.0f} MB)")
    blob = bytearray()
    step = 64 << 20
    for s in range(lo, hi + 1, step):
        blob += get_range(url, s, min(hi, s + step - 1))
        print(f"  {len(blob)/1e6:.0f} MB", flush=True)
    names = []
    for i in infos:
        p = i.header_offset - lo
        assert blob[p:p + 4] == b"PK\x03\x04", i.filename
        n, m = struct.unpack("<HH", blob[p + 26:p + 30])
        data = bytes(blob[p + 30 + n + m:p + 30 + n + m + i.compress_size])
        if i.compress_type == zipfile.ZIP_DEFLATED:
            data = zlib.decompress(data, -15)
        assert len(data) == i.file_size and zlib.crc32(data) == i.CRC, i.filename
        rel = os.path.normpath(i.filename)
        assert not rel.startswith("..") and not os.path.isabs(rel)
        dst = os.path.join(out, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(data)
        names.append(rel)
    # Keep the full file list too: the raw photo names tell us the base photo IDs.
    with open(os.path.join(out, "archive-listing.json"), "w") as f:
        json.dump([i.filename for i in zf.infolist()], f)
    print(f"wrote {len(names)} files to {out}")


class _Shifted(io.RawIOBase):
    """A read-only view where offset cd_off maps to the start of `inner` (the central directory)."""

    def __init__(self, inner, base, size):
        self.inner, self.base, self.size, self.pos = inner, base, size, 0

    def seekable(self):
        return True

    def readable(self):
        return True

    def seek(self, off, whence=0):
        self.pos = {0: off, 1: self.pos + off, 2: self.size + off}[whence]
        return self.pos

    def tell(self):
        return self.pos

    def read(self, n=-1):
        if self.pos < self.base:
            raise IOError("read before central directory")
        self.inner.seek(self.pos - self.base)
        b = self.inner.read(n)
        self.pos += len(b)
        return b


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/raw/slif")
