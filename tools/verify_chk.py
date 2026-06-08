#!/usr/bin/env python3
"""Verify the [Chk:] creator signature on Synapse Protocol V1 turn logs.

Re-computes the HMAC over each turn's tracker base (everything before [Chk:])
using the private signature in Config/Signature.json, and compares it to the
stored value. A match proves the log was produced by the genuine engine with
that signature AND that the tracked state was not altered.

Usage:
    python tools/verify_chk.py <campaign_dir>        # verify all T*.txt
    python tools/verify_chk.py --tracker "<string>"  # verify one tracker line
"""
import sys
import json
import hmac
import hashlib
import re
from pathlib import Path

BASE     = Path(__file__).resolve().parent.parent
SIG_PATH = BASE / "Config" / "Signature.json"

_CHK_RE = re.compile(r"\[Chk:([0-9a-f]{8})\]")


def load_signature() -> str:
    try:
        if SIG_PATH.exists() and SIG_PATH.stat().st_size:
            return (json.loads(SIG_PATH.read_text(encoding="utf-8")).get("signature") or "").strip()
    except Exception:
        pass
    return ""


def compute_chk(payload: str, sig: str) -> str:
    data = payload.encode("utf-8")
    if sig:
        return hmac.new(sig.encode("utf-8"), data, hashlib.sha256).hexdigest()[:8]
    return hashlib.sha256(data).hexdigest()[:8]


def verify_tracker(tracker: str, sig: str):
    """Return (ok, stored, expected) or (None, None, None) if no [Chk:] found."""
    m = _CHK_RE.search(tracker)
    if not m:
        return None, None, None
    base     = tracker[:m.start()]          # signed payload = everything before [Chk:]
    stored   = m.group(1)
    expected = compute_chk(base, sig)
    return (stored == expected), stored, expected


def _tracker_from_txt(text: str) -> str:
    """Pull the tracker line out of a T#.txt (the line carrying [Chk:])."""
    for line in text.splitlines():
        if "[Chk:" in line:
            return line.strip()
    return ""


def main():
    sig = load_signature()
    if not sig:
        print("⚠ No signature in Config/Signature.json — verifying as UNSIGNED (integrity only).")

    args = sys.argv[1:]
    if args and args[0] == "--tracker":
        ok, stored, expected = verify_tracker(args[1], sig)
        if ok is None:
            print("No [Chk:] found in tracker.")
            sys.exit(2)
        print(f"{'✅ MATCH' if ok else '❌ MISMATCH'}  stored={stored} expected={expected}")
        sys.exit(0 if ok else 1)

    if not args:
        print(__doc__)
        sys.exit(2)

    camp = Path(args[0])
    txt_dir = camp / "Events" / "Eternal_Logs" / "txt"
    files = sorted(txt_dir.glob("T*.txt")) if txt_dir.exists() else []
    if not files:
        print(f"No T*.txt logs under {txt_dir}")
        sys.exit(2)

    total = good = bad = skipped = 0
    for f in files:
        tracker = _tracker_from_txt(f.read_text(encoding="utf-8"))
        ok, stored, expected = verify_tracker(tracker, sig)
        total += 1
        if ok is None:
            skipped += 1
            print(f"  {f.name}: no [Chk:]")
        elif ok:
            good += 1
        else:
            bad += 1
            print(f"  {f.name}: ❌ stored={stored} expected={expected}")

    print(f"\n{good}/{total} verified ✅   {bad} mismatched   {skipped} without [Chk:]")
    sys.exit(0 if bad == 0 else 1)


if __name__ == "__main__":
    main()
