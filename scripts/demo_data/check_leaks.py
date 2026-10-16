"""Scan exported JSON for anything that still looks real (pure functions, no database).

    uv run --project apps/api python scripts/demo_data/check_leaks.py [DIR ...] [--forbid TEXT ...]
        [--forbid-file FILE]

Walks every `*.json` under each directory (default: `out/`; pass the pack's `sandbox/` and the
connector's `sandbox/` too) and flags, in any string value or dict key: an email whose domain is not
`example.com`, a URL of any scheme (`http(s)://`, `gs://`, `ftp://`, ...) or a `www.` address, a phone
number outside the fictional `+63 900 000 XXXX` range, a TIN-like number (`123-456-789-000`, or a number
after the word TIN), and any forbidden substring (case-insensitive). The forbid list is read from the
untracked file `scripts/demo_data/forbid.txt` (one real name, street or company per line; `#` starts a
comment) plus any `--forbid`. Prints one line per file and kind with the count and a masked sample
(first 3 characters only; a leaked value is never printed in full, and a forbidden entry is only
numbered, its sample shown as `(hidden)`) and exits 1 when anything was found. `export.py` runs this at
the end and deletes its output when it fails.
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
FORBID_FILE = Path(__file__).resolve().parent / "forbid.txt"
FORBIDDEN_KIND = "forbidden#"
HIDDEN = "(hidden)"
ALLOWED_EMAIL_DOMAINS = ("example.com",)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s\"'<>]+|\bwww\.[^\s\"'<>]+", re.IGNORECASE)
# Same shapes as anonymize.PHONE_RE: PH mobiles, landlines written with separators, bare 11-digit mobiles.
PHONE_RE = re.compile(
    r"(?:\+?63|\b0)\s?9\d{2}[\s.-]?\d{3}[\s.-]?\d{4}\b"
    r"|\(?\b\d{2,3}\)?[\s.-]\d{3}[\s.-]\d{4}\b"
    r"|\b09\d{9}\b"
)
FICTIONAL_PHONE_RE = re.compile(r"\+63 900 000 \d{4}")
TIN_RE = re.compile(
    r"\b\d{3}[- ]\d{3}[- ]\d{3}(?:[- ]\d{3,5})?\b|\bTIN\b[\s:#.-]*\d[\d -]{7,}", re.IGNORECASE
)


@dataclass(frozen=True)
class Leak:
    path: Path
    kind: str  # "email" | "url" | "phone" | "tin" | "forbidden#<n>"
    count: int
    sample: str  # masked: first 3 characters + an ellipsis; "(hidden)" for a forbidden-list hit


def mask(value: str, kind: str = "") -> str:
    """A forbidden-list hit shows nothing (even 3 characters could name the real entry)."""
    return HIDDEN if kind.startswith(FORBIDDEN_KIND) else value[:3] + "…"


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


def load_forbid(path: Path = FORBID_FILE) -> list[str]:
    """The forbidden substrings in the untracked `forbid.txt` (none when the file does not exist)."""
    if not path.is_file():
        return []
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def scan_value(value: Any, forbid: list[str] = ()) -> dict[str, list[str]]:
    """Leak kind -> the offending strings (unmasked; callers mask before printing)."""
    found: dict[str, list[str]] = defaultdict(list)
    lowered = [text.lower() for text in forbid if text.strip()]
    for text in strings(value):
        for email in EMAIL_RE.findall(text):
            if not email_allowed(email):
                found["email"].append(email)
        for url in URL_RE.findall(text):
            found["url"].append(url)
        for match in PHONE_RE.finditer(text):
            if not FICTIONAL_PHONE_RE.fullmatch(match.group(0)):
                found["phone"].append(match.group(0))
        for tin in TIN_RE.findall(text):
            found["tin"].append(tin)
        for number, needle_lower in enumerate(lowered, start=1):
            if needle_lower in text.lower():
                found[f"{FORBIDDEN_KIND}{number}"].append(text)  # numbered: the entry is never echoed
    return found


def scan_file(path: Path, forbid: list[str] = ()) -> list[Leak]:
    found = scan_value(json.loads(path.read_text(encoding="utf-8")), forbid)
    return [Leak(path, kind, len(values), mask(values[0], kind)) for kind, values in sorted(found.items())]


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
    parser.add_argument(
        "--forbid-file", type=Path, default=FORBID_FILE, help="untracked file of forbidden substrings"
    )
    args = parser.parse_args(argv)
    forbid = [*load_forbid(args.forbid_file), *args.forbid]
    leaks = [leak for directory in args.dirs for leak in scan_dir(directory, forbid)]
    report(leaks)
    if leaks:
        print(f"{len(leaks)} leak(s) found", file=sys.stderr)
        return 1
    print(f"no leaks in {', '.join(str(d) for d in args.dirs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
