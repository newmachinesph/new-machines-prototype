"""CLI: python -m app.defs validate|apply|export."""

import argparse
import sys
from pathlib import Path

from app import db, settings
from app.defs import registry
from app.defs.loader import LoadError, load_bundle
from app.defs.validate import validate_bundle


def _load_valid(directory: Path):
    try:
        bundle = load_bundle(directory)
    except LoadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None
    errors = validate_bundle(bundle)
    for e in errors:
        print(f"error: {e}", file=sys.stderr)
    return None if errors else bundle


def _cmd_validate(args) -> int:
    bundle = _load_valid(args.dir)
    if bundle is None:
        return 1
    print(f"ok: {len(bundle.items)} definitions")
    return 0


def _cmd_apply(args) -> int:
    bundle = _load_valid(args.dir)
    if bundle is None:
        return 1
    with db.connect() as conn:
        created = registry.apply_bundle(conn, bundle, force=args.force)
        conn.commit()
    for v in created:
        print(f"{v.kind}/{v.key} v{v.version}")
    if not created:
        print("no changes")
    return 0


def _cmd_export(args) -> int:
    out = Path(args.out)
    with db.connect() as conn:
        latest = registry.latest_all(conn)
    count = 0
    for v in latest:
        for rel, text in registry.export_files(v).items():
            target = out / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
            count += 1
    print(f"wrote {count} files to {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.defs")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, fn in (("validate", _cmd_validate), ("apply", _cmd_apply)):
        p = sub.add_parser(name)
        p.add_argument("--dir", type=Path, default=None)
        p.set_defaults(fn=fn)
        if name == "apply":
            p.add_argument(
                "--force", action="store_true", help="apply files over versions published from the console"
            )
    p = sub.add_parser("export")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=_cmd_export)
    args = parser.parse_args(argv)
    if hasattr(args, "dir") and args.dir is None:
        args.dir = settings.defs_dir()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
