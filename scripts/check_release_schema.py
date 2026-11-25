"""Compare declared database contracts across release revisions."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import TypedDict


class ColumnContract(TypedDict):
    type: str
    nullable: bool
    default: bool


class TableContract(TypedDict):
    columns: dict[str, ColumnContract]
    primary_key: list[str]
    unique: list[list[str]]


DESTRUCTIVE_SQL = re.compile(
    r"\b(?:DROP\s+(?:TABLE|SCHEMA|COLUMN|TYPE|DATABASE|CONSTRAINT)|"
    r"TRUNCATE\s+(?:TABLE\s+)?[A-Z_]|"
    r"RENAME\s+(?:COLUMN|TO|CONSTRAINT)|"
    r"ALTER\s+(?:COLUMN\s+)?[\w\".]+\s+(?:TYPE\b|SET\s+NOT\s+NULL\b))",
    re.IGNORECASE,
)


def schema_snapshot() -> dict[str, TableContract]:
    from sqlalchemy import UniqueConstraint
    from sqlalchemy.dialects.postgresql.base import PGDialect

    from app import server  # noqa: F401 - load routers and register the archive tables
    from app.launch_store import schema

    dialect = PGDialect()  # type: ignore[no-untyped-call]
    return {
        table.name: {
            "columns": {
                col.name: {
                    "type": str(col.type.compile(dialect=dialect)),
                    "nullable": bool(col.nullable),
                    "default": col.server_default is not None,
                }
                for col in table.columns
            },
            "primary_key": list(table.primary_key.columns.keys()),
            "unique": sorted(
                [
                    list(constraint.columns.keys())
                    for constraint in table.constraints
                    if isinstance(constraint, UniqueConstraint)
                ]
                + [
                    list(index.columns.keys())
                    for index in table.indexes
                    if index.unique
                ]
            ),
        }
        for table in schema.tables.values()
    }


def compare(
    before: dict[str, TableContract], after: dict[str, TableContract]
) -> list[str]:
    failures = []
    for name, old in before.items():
        new = after.get(name)
        if new is None:
            failures.append(f"{name}: table removed or renamed")
            continue
        if old["primary_key"] != new["primary_key"]:
            failures.append(f"{name}: primary key changed")
        if any(columns not in old["unique"] for columns in new["unique"]):
            failures.append(
                f"{name}: new uniqueness constraint can reject existing rows or old writers"
            )
        for column, previous in old["columns"].items():
            current = new["columns"].get(column)
            if current is None:
                failures.append(f"{name}.{column}: column removed or renamed")
            elif (
                previous["type"] != current["type"]
                or (previous["nullable"] and not current["nullable"])
                or (
                    previous["default"]
                    and not current["default"]
                    and not current["nullable"]
                )
            ):
                failures.append(
                    f"{name}.{column}: incompatible type, nullability, or default change"
                )
        for column in new["columns"].keys() - old["columns"].keys():
            current = new["columns"][column]
            if not current["nullable"] and not current["default"]:
                failures.append(
                    f"{name}.{column}: existing writers need a nullable column or server default"
                )
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path, nargs="?")
    parser.add_argument("after", type=Path, nargs="?")
    parser.add_argument("--sql-diff", type=Path)
    args = parser.parse_args()
    if args.before is None and args.after is None:
        print(json.dumps(schema_snapshot(), sort_keys=True))
        return
    if args.before is None or args.after is None:
        parser.error("provide both schema snapshots")
    failures = compare(
        json.loads(args.before.read_text()), json.loads(args.after.read_text())
    )
    if args.sql_diff is not None:
        additions = "\n".join(
            line[1:]
            for line in args.sql_diff.read_text(encoding="utf-8").splitlines()
            if line.startswith("+") and not line.startswith("+++")
        )
        if DESTRUCTIVE_SQL.search(additions):
            failures.append(
                "Changed SQL contains a destructive or incompatible operation. Use a staged migration."
            )
    for failure in failures:
        print(f"::error::{failure}")
    if failures:
        raise SystemExit(1)
    print("Archive schema changes are compatible with existing writers.")


if __name__ == "__main__":
    main()
