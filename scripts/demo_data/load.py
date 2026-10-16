"""Load the anonymised `out/*.json` files into a NEW demo database (never a source one).

    uv run --project apps/api --with pymongo python scripts/demo_data/load.py [--db nm_demo] [--drop]

The target comes from `--target-url` or the `DEMO_MONGO_URL` env var (never printed). One collection per
file, named after the file (`ecommerce_sales_orders`, `accounting_customers`, ...), with Extended JSON
`{"$date": ...}` turned back into BSON dates. Refuses to run when the target database is named like a
source database (`ecommerce`, `accounting`, `warehouse`, `salesApp`) or when the target URL equals, or
names the same host as, any `SRC_*_URL`, so a mistyped env var can never write into production (and warns
when a `SRC_*_URL` is unset, because that host could then not be checked). A MongoDB error prints a
generic message (never a host name). `--drop` recreates the collections.
"""

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import OUT_DIR, read_out  # noqa: E402

SOURCE_DB_NAMES = {"ecommerce", "accounting", "warehouse", "salesapp"}
SOURCE_URL_VARS = ("SRC_ECOMMERCE_URL", "SRC_ACCOUNTING_URL", "SRC_WAREHOUSE_URL", "SRC_SALESAPP_URL")
DEFAULT_DB = "nm_demo"


def fail(message: str) -> int:
    print(f"LOAD REFUSED: {message}", file=sys.stderr)
    return 1


def url_database(url: str) -> str:
    """The database named in a MongoDB URL's path, or "" when there is none."""
    return urlparse(url).path.strip("/").split("?")[0]


def url_hosts(url: str) -> set[str]:
    """The lower-cased host names of a MongoDB URL (a replica set lists several, `user:pass@` is dropped)."""
    authority = url.strip().split("://", 1)[-1].split("/", 1)[0].rsplit("@", 1)[-1]
    return {host.rsplit(":", 1)[0].lower() for host in authority.split(",") if host}


def check_target(target_url: str, db_name: str) -> str | None:
    """Why the target must not be written to, or None when it is safe."""
    if not target_url:
        return "set DEMO_MONGO_URL (or pass --target-url) to the NEW demo database"
    if db_name.lower() in SOURCE_DB_NAMES:
        return f"target database {db_name!r} is a source database name; use something like {DEFAULT_DB!r}"
    if url_database(target_url).lower() in SOURCE_DB_NAMES:
        return "the target URL names a source database; point it at a different cluster or database"
    sources = {var: os.environ.get(var, "").strip() for var in SOURCE_URL_VARS}
    for var, source in sources.items():
        if source and source.rstrip("/") == target_url.strip().rstrip("/"):
            return f"target URL equals {var}; the demo must load into a different cluster or database"
        if source and url_hosts(source) & url_hosts(target_url):
            return f"target URL is on the same host as {var}; load into a different cluster"
    unset = [var for var, source in sources.items() if not source]
    if unset:
        print(
            f"warning: {', '.join(unset)} not set, so the target could not be checked against "
            "those source hosts",
            file=sys.stderr,
        )
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--target-url", default=os.environ.get("DEMO_MONGO_URL", ""), help="defaults to $DEMO_MONGO_URL"
    )
    parser.add_argument("--db", default=DEFAULT_DB, help=f"target database name (default {DEFAULT_DB})")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="directory holding out/*.json")
    parser.add_argument("--drop", action="store_true", help="drop each collection before loading")
    args = parser.parse_args(argv)

    problem = check_target(args.target_url, args.db)
    if problem:
        return fail(problem)
    data = read_out(args.out)
    if not data:
        return fail(f"no out/*.json files under {args.out}; run export.py first")

    from pymongo.errors import PyMongoError

    try:
        load(args.target_url, args.db, data, args.drop)
    except PyMongoError:
        return fail("could not write to the target database (connection or write error); check the URL")
    return 0


def load(target_url: str, db_name: str, data: dict[str, list[dict]], drop: bool) -> None:
    from pymongo import MongoClient
    from pymongo.errors import BulkWriteError

    client: MongoClient = MongoClient(target_url, serverSelectionTimeoutMS=15000)
    try:
        db = client[db_name]
        for name, docs in data.items():
            if drop:
                db[name].drop()
            if docs:
                try:
                    db[name].insert_many(docs, ordered=False)
                except BulkWriteError as error:
                    duplicates = sum(
                        1 for e in error.details.get("writeErrors", []) if e.get("code") == 11000
                    )
                    print(
                        f"{name}: {duplicates} documents already present (use --drop to recreate)",
                        file=sys.stderr,
                    )
            print(f"{db_name}.{name}: {db[name].count_documents({})} documents")
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
