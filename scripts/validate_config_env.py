#!/usr/bin/env python3
"""
Validate that environment variables referenced by docker-compose manifests are
documented in config.example.env and config.schema.json.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Iterable, Set

ROOT = Path(__file__).resolve().parent.parent
CONFIG_EXAMPLE = ROOT / "config.example.env"
CONFIG_SCHEMA = ROOT / "config.schema.json"


def _gather_compose_vars(paths: Iterable[Path]) -> tuple[Set[str], Set[str]]:
    required: Set[str] = set()
    optional: Set[str] = set()
    pattern = re.compile(r"\${(?P<name>[A-Z0-9_]+)(?P<rest>[^}]*)}")

    for path in paths:
        text = path.read_text()
        for raw_line in text.splitlines():
            # strip comments to avoid matching commented examples
            line = raw_line.split("#", 1)[0]
            for match in pattern.finditer(line):
                name = match.group("name")
                rest = (match.group("rest") or "").strip()
                if rest.startswith(":-") or rest.startswith("-"):
                    optional.add(name)
                else:
                    required.add(name)

    optional -= required
    return required, optional


def _gather_env_template_keys(path: Path) -> Set[str]:
    keys: Set[str] = set()
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            if line.startswith("#") and "=" in line:
                key = line.lstrip("#").split("=", 1)[0].strip()
                if key:
                    keys.add(key)
            continue
        key = line.split("=", 1)[0].strip()
        if key:
            keys.add(key)
    return keys


def _gather_schema_keys(path: Path) -> Set[str]:
    schema = json.loads(path.read_text())
    out: Set[str] = set()

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            props = node.get("properties")
            if isinstance(props, dict):
                for key, child in props.items():
                    out.add(key)
                    _walk(child)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(schema)
    return out


def main() -> int:
    compose_files = set()
    patterns = [
        "docker-compose*.yml",
        "docker-compose*.yaml",
        "compose.*.yml",
        "compose.*.yaml",
    ]
    for pattern in patterns:
        compose_files.update(ROOT.glob(pattern))
        compose_files.update((ROOT / "ops").glob(f"**/{pattern}"))
    compose_files = sorted({path.resolve() for path in compose_files if path.is_file()})
    compose_files = sorted({path.resolve() for path in compose_files if path.is_file()})
    if not compose_files:
        print("::warning::No docker-compose manifests found", file=sys.stderr)
        return 0

    required, _optional = _gather_compose_vars(compose_files)
    template_keys = _gather_env_template_keys(CONFIG_EXAMPLE)
    schema_keys = _gather_schema_keys(CONFIG_SCHEMA)

    missing_in_example = sorted(required - template_keys)
    missing_in_schema = sorted(required - schema_keys)

    exit_code = 0
    if missing_in_example:
        print(
            f"::error::config.example.env missing required variables: {missing_in_example}"
        )
        exit_code = 1
    if missing_in_schema:
        print(
            f"::error::config.schema.json missing required variables: {missing_in_schema}"
        )
        exit_code = 1
    if exit_code == 0:
        print("Config env templates align with docker-compose manifests")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
