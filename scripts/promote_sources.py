"""Append validated candidates to the reviewed source catalog.

Usage:
  python -m scripts.promote_sources docs/research/<pack>.json --ids id1,id2,...

Pass the PROMOTE_IDS line printed by the "Validate candidate sources" workflow.
Only listed candidates are added; existing catalog entries are never changed.
The merged catalog is validated with the same loader the application uses.
"""
import argparse
from datetime import UTC, datetime
import json
from pathlib import Path

from app.sources import load_source_pack
from scripts.check_source_pack import requires_english

CATALOG = Path(__file__).resolve().parents[1] / "app" / "source_catalog.json"


def promote(pack, ids, catalog=CATALOG, today=None):
    today = today or datetime.now(UTC).date().isoformat()
    candidates = {row["id"]: row for row in json.loads(Path(pack).read_text(encoding="utf-8"))}
    missing = sorted(set(ids) - candidates.keys())
    if missing:
        raise SystemExit(f"Not in the candidate pack: {', '.join(missing)}")
    current = json.loads(catalog.read_text(encoding="utf-8"))
    known = {row["id"] for row in current}
    added = [{**candidates[ident], "reviewed_at": today,
              **({"require_english": True} if requires_english(candidates[ident]) else {})}
             for ident in ids if ident not in known]
    merged = current + added
    pending = catalog.with_suffix(".json.pending")
    pending.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        load_source_pack(pending)
    except Exception:
        pending.unlink()
        raise
    pending.replace(catalog)
    return [row["id"] for row in added]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pack", type=Path)
    parser.add_argument("--ids", required=True, help="Comma-separated candidate ids")
    args = parser.parse_args()
    ids = [ident.strip() for ident in args.ids.split(",") if ident.strip()]
    added = promote(args.pack, ids)
    print(f"Added {len(added)} sources to {CATALOG.name}.")


if __name__ == "__main__":
    main()
