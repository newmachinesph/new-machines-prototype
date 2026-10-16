"""Scan exported JSON for anything that still looks real (pure functions, no database).

    uv run --project apps/api python scripts/demo_data/check_leaks.py [DIR ...] [--forbid TEXT ...]

Walks every `*.json` under each directory (default: `out/`; pass the pack's `sandbox/` too) and flags,
in any string value or dict key: an email whose domain is not `example.com`, an http(s) URL, and any
`--forbid` substring (case-insensitive; a real customer or staff name, for instance). Prints one line per
file and kind with the count and a masked sample (first 3 characters only; a leaked value is never
printed in full) and exits 1 when anything was found. Phone-looking strings are not scanned: fake
phones and invoice numbers match the same pattern. `export.py` runs this at the end and deletes its
output when it fails.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

OUT_DIR = Path(__file__).resolve().parent / "out"
ALLOWED_EMAIL_DOMAINS = ("example.com",)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


@dataclass(frozen=True)
class Leak:
    path: Path
    kind: str  # "email" | "url" | "forbidden:<text>"
    count: int
    sample: str  # masked: first 3 characters + an ellipsis


def mask(value: str) -> str:
    return value[:3] + "…"


def email_allowed(email: str) -> bool:
    domain = email.rsplit("@", 1)[-1].lower()
    return any(domain == allowed or domain.endswith("." + allowed) for allowed in ALLOWED_EMAIL_DOMAINS)


def strings(value: Any):
    """Every string in a JSON value, dict keys included."""
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)
    elif isinstance(value, str):
        yield value


def scan_value(value: Any, forbid: list[str] = ()) -> dict[str, list[str]]:
    """Leak kind -> the offending strings (unmasked; callers mask before printing)."""
    found: dict[str, list[str]] = defaultdict(list)
    lowered = [text.lower() for text in forbid]
    for text in strings(value):
        for email in EMAIL_RE.findall(text):
            if not email_allowed(email):
                found["email"].append(email)
        for url in URL_RE.findall(text):
            found["url"].append(url)
        for needle, needle_lower in zip(forbid, lowered, strict=True):
            if needle_lower in text.lower():
                found[f"forbidden:{needle}"].append(text)
    return found


def scan_file(path: Path, forbid: list[str] = ()) -> list[Leak]:
    found = scan_value(json.loads(path.read_text(encoding="utf-8")), forbid)
    return [Leak(path, kind, len(values), mask(values[0])) for kind, values in sorted(found.items())]


def scan_dir(directory: Path, forbid: list[str] = ()) -> list[Leak]:
    return [leak for path in sorted(directory.rglob("*.json")) for leak in scan_file(path, forbid)]


def report(leaks: list[Leak]) -> None:
    for leak in leaks:
        print(f"LEAK {leak.path}: {leak.count} {leak.kind} (e.g. {leak.sample})", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("dirs", nargs="*", type=Path, default=[OUT_DIR], help="directories to scan")
    parser.add_argument("--forbid", action="append", default=[], help="substring that must not appear")
    args = parser.parse_args(argv)
    leaks = [leak for directory in args.dirs for leak in scan_dir(directory, args.forbid)]
    report(leaks)
    if leaks:
        print(f"{len(leaks)} leak(s) found", file=sys.stderr)
        return 1
    print(f"no leaks in {', '.join(str(d) for d in args.dirs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
