#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, out_path: Path, force: bool) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists() and not force:
        print(f"[skip] exists: {out_path}")
        return

    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()

    print(f"[get ] {url}")
    try:
        with urllib.request.urlopen(url) as r, tmp.open("wb") as f:
            while True:
                b = r.read(1024 * 128)
                if not b:
                    break
                f.write(b)
    except Exception as e:
        if tmp.exists():
            tmp.unlink()
        raise e

    tmp.replace(out_path)
    print(f"[ok  ] saved: {out_path} (sha256={sha256_file(out_path)[:16]}...)")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Download Mozc OSS dictionaries dictionary00.txt..dictionary09.txt into data/mozc/."
    )
    ap.add_argument("--out_dir", default="data/mozc", help="Output directory (default: data/mozc)")
    ap.add_argument(
        "--base_url",
        default="https://raw.githubusercontent.com/google/mozc/master/src/data/dictionary_oss",
        help="Base raw URL for Mozc dictionary_oss",
    )
    ap.add_argument("--force", action="store_true", help="Overwrite existing files")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    base = args.base_url.rstrip("/")

    for i in range(10):
        fname = f"dictionary{i:02d}.txt"
        url = f"{base}/{fname}"
        out_path = out_dir / fname
        download(url, out_path, force=args.force)

    print("[done] all dictionaries downloaded.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[abort] interrupted.", file=sys.stderr)
        raise SystemExit(130)