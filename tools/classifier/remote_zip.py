"""Read selected entries of a remote zip with HTTP range requests, without downloading the rest.

Handles zip64 archives. Each wanted entry is CRC-checked after it is inflated.
"""
import os, struct, urllib.request, zipfile, zlib

UA = {"User-Agent": "Mozilla/5.0 (cropscout-live dataset fetch)"}


def get_range(url, start, end, tries=4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={**UA, "Range": f"bytes={start}-{end}"})
            with urllib.request.urlopen(req, timeout=300) as r:
                if r.status != 206:
                    raise RuntimeError(f"range request returned {r.status}")
                data = r.read()
            if len(data) != end - start + 1:
                raise OSError("short read")
            return data
        except OSError:
            if attempt == tries - 1:
                raise


def total_size(url):
    req = urllib.request.Request(url, headers={**UA, "Range": "bytes=0-0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return int(r.headers["Content-Range"].split("/")[1])


def entries(url, size=None):
    """Return [(name, header_offset, compress_size, file_size, method, crc)] from the central directory."""
    size = size or total_size(url)
    tail = get_range(url, max(0, size - 65557), size - 1)
    eocd = tail.rfind(b"PK\x05\x06")
    cd_size, cd_off = struct.unpack("<II", tail[eocd + 12:eocd + 20])
    loc = tail.rfind(b"PK\x06\x07")
    if loc != -1:
        z64_off = struct.unpack("<Q", tail[loc + 8:loc + 16])[0]
        rec = get_range(url, z64_off, z64_off + 55)
        cd_size, cd_off = struct.unpack("<QQ", rec[40:56])
    cd = get_range(url, cd_off, cd_off + cd_size - 1)
    out, p = [], 0
    while p + 46 <= len(cd) and cd[p:p + 4] == b"PK\x01\x02":
        method, = struct.unpack("<H", cd[p + 10:p + 12])
        crc, csz, usz = struct.unpack("<III", cd[p + 16:p + 28])
        fl, el, cl = struct.unpack("<HHH", cd[p + 28:p + 34])
        off, = struct.unpack("<I", cd[p + 42:p + 46])
        name = cd[p + 46:p + 46 + fl].decode("utf-8", "replace")
        extra = cd[p + 46 + fl:p + 46 + fl + el]
        q = 0
        while q + 4 <= len(extra):  # zip64 extended information
            tag, ln = struct.unpack("<HH", extra[q:q + 4])
            if tag == 1:
                vals, r = extra[q + 4:q + 4 + ln], 0
                if usz == 0xFFFFFFFF:
                    usz, = struct.unpack("<Q", vals[r:r + 8]); r += 8
                if csz == 0xFFFFFFFF:
                    csz, = struct.unpack("<Q", vals[r:r + 8]); r += 8
                if off == 0xFFFFFFFF:
                    off, = struct.unpack("<Q", vals[r:r + 8]); r += 8
            q += 4 + ln
        out.append((name, off, csz, usz, method, crc))
        p += 46 + fl + el + cl
    return out


def fetch(url, wanted, out_dir, rename=lambda n: n, span=64 << 20):
    """Download the wanted entries (from entries()) into out_dir. Nearby entries share one request."""
    wanted = sorted(wanted, key=lambda e: e[1])
    written, i = [], 0
    while i < len(wanted):
        lo = wanted[i][1]
        j = i
        while j + 1 < len(wanted) and wanted[j + 1][1] + wanted[j + 1][2] + 1024 - lo < span:
            j += 1
        hi = wanted[j][1] + 30 + len(wanted[j][0].encode()) + 1024 + wanted[j][2]
        blob = get_range(url, lo, hi - 1) if hi - 1 >= lo else b""
        for name, off, csz, usz, method, crc in wanted[i:j + 1]:
            p = off - lo
            if p + 30 > len(blob):
                blob += get_range(url, lo + len(blob), off + 30 + 4096 + csz)
            assert blob[p:p + 4] == b"PK\x03\x04", name
            n, m = struct.unpack("<HH", blob[p + 26:p + 30])
            end = p + 30 + n + m + csz
            if end > len(blob):
                blob += get_range(url, lo + len(blob), lo + end - 1)
            data = bytes(blob[p + 30 + n + m:end])
            if method == zipfile.ZIP_DEFLATED:
                data = zlib.decompress(data, -15)
            assert len(data) == usz and zlib.crc32(data) == crc, name
            rel = os.path.normpath(rename(name))
            assert not rel.startswith("..") and not os.path.isabs(rel), name
            dst = os.path.join(out_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(data)
            written.append(rel)
        print(f"  {len(written)}/{len(wanted)}", flush=True)
        i = j + 1
    return written
