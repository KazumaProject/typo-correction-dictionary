#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Iterator, List, Sequence, Set, Tuple


# -----------------------------
# Kana normalization tables
# -----------------------------

# Dakuten → seion
_DAKUTEN_TO_SEION = {
    "が": "か",
    "ぎ": "き",
    "ぐ": "く",
    "げ": "け",
    "ご": "こ",
    "ざ": "さ",
    "じ": "し",
    "ず": "す",
    "ぜ": "せ",
    "ぞ": "そ",
    "だ": "た",
    "ぢ": "ち",
    "づ": "つ",
    "で": "て",
    "ど": "と",
    "ば": "は",
    "び": "ひ",
    "ぶ": "ふ",
    "べ": "へ",
    "ぼ": "ほ",
    "ゔ": "う",
}

# Handakuten → seion
_HANDAKUTEN_TO_SEION = {
    "ぱ": "は",
    "ぴ": "ひ",
    "ぷ": "ふ",
    "ぺ": "へ",
    "ぽ": "ほ",
}

# Small hiragana → normal size
_SMALL_TO_NORMAL = {
    "ぁ": "あ",
    "ぃ": "い",
    "ぅ": "う",
    "ぇ": "え",
    "ぉ": "お",
    "ゃ": "や",
    "ゅ": "ゆ",
    "ょ": "よ",
    "っ": "つ",
    "ゎ": "わ",
    "ゕ": "か",
    "ゖ": "け",
}


def is_hiragana(ch: str) -> bool:
    if len(ch) != 1:
        return False
    o = ord(ch)
    return 0x3040 <= o <= 0x309F


def clean_char(ch: str) -> str:
    """Return cleaned char if dakuten/handakuten/small-hiragana; otherwise unchanged."""
    if ch in _DAKUTEN_TO_SEION:
        return _DAKUTEN_TO_SEION[ch]
    if ch in _HANDAKUTEN_TO_SEION:
        return _HANDAKUTEN_TO_SEION[ch]
    if ch in _SMALL_TO_NORMAL:
        return _SMALL_TO_NORMAL[ch]
    return ch


def generate_variants_for_yomi_all(yomi: str) -> Tuple[List[str], bool]:
    """
    Generate variants by scanning ALL characters in yomi.
    For each char, if it has a cleaned alternative, choose (original|cleaned).
    If none, keep fixed.

    Returns (variants, changed_possible).

    Example: "がっこう" -> positions [が, っ] are changeable -> 4 variants.
    """
    chars = list(yomi)
    if not chars:
        return [yomi], False

    options_per_pos: List[Tuple[str, ...]] = []
    changed_possible = False

    for ch in chars:
        cleaned = clean_char(ch)
        if cleaned != ch:
            options_per_pos.append((ch, cleaned))
            changed_possible = True
        else:
            options_per_pos.append((ch,))

    if not changed_possible:
        return [yomi], False

    out: List[str] = []
    seen: Set[str] = set()

    for tup in product(*options_per_pos):
        v = "".join(tup)
        if v in seen:
            continue
        seen.add(v)
        out.append(v)

    return out, True


# -----------------------------
# Mozc dictionary parsing
# -----------------------------


@dataclass(frozen=True)
class MozcEntry:
    yomi: str
    surface: str


def iter_mozc_entries(paths: Sequence[Path]) -> Iterator[MozcEntry]:
    for path in paths:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue

                cols = line.split("\t")
                # yomi, left_id, right_id, cost, surface, ...
                if len(cols) < 5:
                    continue

                yomi = cols[0].strip()
                surface = cols[4].strip()
                if not yomi or not surface:
                    continue

                # Keep behavior consistent with your prior version:
                # only accept entries whose first char is hiragana.
                if not is_hiragana(yomi[0]):
                    continue

                yield MozcEntry(yomi=yomi, surface=surface)


def find_dict_files(mozc_dir: Path) -> List[Path]:
    exact = [mozc_dir / f"dictionary{i:02d}.txt" for i in range(10)]
    if all(p.exists() for p in exact):
        return exact
    cands = sorted(mozc_dir.glob("dictionary*.txt"))
    return [p for p in cands if p.is_file()]


def build_existing_yomi_set(dict_files: Sequence[Path]) -> Set[str]:
    """
    Build a set of yomi that already exist in Mozc dictionaries.
    Used to avoid generating variants that collide with real readings already present.
    """
    s: Set[str] = set()
    for e in iter_mozc_entries(dict_files):
        s.add(e.yomi)
    return s


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Build yomi<TAB>surface pairs from Mozc dictionaries, generating all combinations for "
            "dakuten/handakuten/small chars across the whole yomi."
        )
    )
    ap.add_argument("--mozc_dir", default="data/mozc", help="Directory containing dictionary*.txt")
    ap.add_argument("--out_tsv", default="out/mozc_pairs.tsv", help="Output TSV path")
    ap.add_argument("--dedup", action="store_true", help="Deduplicate lines globally")
    ap.add_argument("--max_lines", type=int, default=0, help="Limit output lines (0=unlimited)")

    # for quick verification
    ap.add_argument("--filter_yomi", default="", help="Only output entries whose yomi exactly matches this")
    ap.add_argument("--filter_prefix", default="", help="Only output entries whose yomi starts with this prefix")

    # output only entries where any changeable char exists (i.e., variants > 1)
    ap.add_argument("--only_changed", action="store_true", help="Only output entries where variants are generated")

    # safety valve to avoid combinatorial explosion
    ap.add_argument(
        "--max_variants_per_entry",
        type=int,
        default=0,
        help="If >0, skip entries whose number of variants would exceed this limit (0=unlimited)",
    )

    # NEW: yomi length filters
    ap.add_argument(
        "--min_yomi_len",
        type=int,
        default=0,
        help="Minimum yomi length (in characters). 0 = no minimum",
    )
    ap.add_argument(
        "--max_yomi_len",
        type=int,
        default=0,
        help="Maximum yomi length (in characters). 0 = no maximum",
    )

    # NEW: avoid generating variants that already exist as yomi in dictionaries
    # default behavior: SKIP such variants
    ap.add_argument(
        "--allow_existing_yomi_variants",
        action="store_true",
        help="Allow emitting variant yomi even if that yomi already exists in dictionaries (default: skip them).",
    )

    args = ap.parse_args()

    mozc_dir = Path(args.mozc_dir)
    out_tsv = Path(args.out_tsv)
    out_tsv.parent.mkdir(parents=True, exist_ok=True)

    dict_files = find_dict_files(mozc_dir)
    if not dict_files:
        raise SystemExit(f"[error] no dictionary*.txt found in: {mozc_dir}")

    print("[info] reading:")
    for p in dict_files:
        print(f"  - {p}")

    # Build existing yomi set (1st pass)
    skip_existing_yomi_variants = not args.allow_existing_yomi_variants
    existing_yomi: Set[str] = set()
    if skip_existing_yomi_variants:
        print("[info] building existing yomi set (to avoid generating variants that already exist)...")
        existing_yomi = build_existing_yomi_set(dict_files)
        print(f"[info] existing_yomi_count={len(existing_yomi)}")

    seen_pair: Set[str] = set()
    n_in = 0
    n_matched = 0
    n_skipped_big = 0
    n_skipped_existing_yomi_variant = 0
    n_out = 0

    # 2nd pass: actual output
    with out_tsv.open("w", encoding="utf-8", newline="\n") as w:
        for e in iter_mozc_entries(dict_files):
            n_in += 1

            if args.filter_yomi and e.yomi != args.filter_yomi:
                continue
            if args.filter_prefix and not e.yomi.startswith(args.filter_prefix):
                continue

            # yomi length filtering (based on original yomi)
            ylen = len(e.yomi)
            if args.min_yomi_len and ylen < args.min_yomi_len:
                continue
            if args.max_yomi_len and ylen > args.max_yomi_len:
                continue

            n_matched += 1

            variants, changed_possible = generate_variants_for_yomi_all(e.yomi)

            if args.only_changed and not changed_possible:
                continue

            if args.max_variants_per_entry and len(variants) > args.max_variants_per_entry:
                n_skipped_big += 1
                continue

            for v in variants:
                # NEW: skip variant yomi if it already exists as a real yomi in dictionaries
                # but NEVER skip the original yomi itself.
                if skip_existing_yomi_variants and v != e.yomi and v in existing_yomi:
                    n_skipped_existing_yomi_variant += 1
                    continue

                line = f"{v}\t{e.surface}"
                if args.dedup:
                    if line in seen_pair:
                        continue
                    seen_pair.add(line)

                w.write(line + "\n")
                n_out += 1

                if args.max_lines and n_out >= args.max_lines:
                    print(f"[done] reached --max_lines={args.max_lines}")
                    print(
                        f"[stat] entries_in={n_in}, matched={n_matched}, skipped_big={n_skipped_big}, "
                        f"skipped_existing_yomi_variant={n_skipped_existing_yomi_variant}, lines_out={n_out}"
                    )
                    print(f"[ok  ] wrote: {out_tsv}")
                    return

    print(
        f"[stat] entries_in={n_in}, matched={n_matched}, skipped_big={n_skipped_big}, "
        f"skipped_existing_yomi_variant={n_skipped_existing_yomi_variant}, lines_out={n_out}"
    )
    print(f"[ok  ] wrote: {out_tsv}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[abort] interrupted.", file=sys.stderr)
        raise SystemExit(130)