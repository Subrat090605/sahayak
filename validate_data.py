"""Validate data/schemes.json against the required schema from docs/DATA_SCHEMA.md."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCHEMES_FILE = Path(__file__).parent / "data" / "schemes.json"

REQUIRED_TOP_LEVEL_KEYS = [
    "id",
    "name_en",
    "name_hi",
    "benefit_en",
    "benefit_hi",
    "official_link",
    "last_verified",
    "source_note",
    "eligibility",
    "exclusions",
    "documents",
    "form_fields",
    "deadline",
]

REQUIRED_RULE_KEYS = ["field", "op", "value", "label_en", "label_hi"]
REQUIRED_DOC_KEYS = ["id", "name_en", "name_hi", "where_to_get_en", "where_to_get_hi"]
ALLOWED_OPS = {"eq", "ne", "in", "lte", "gte", "between", "is_true", "is_false"}


def find_todos(item: Any, path: str = "") -> list[tuple[str, Any]]:
    """Recursively search for any 'TODO' strings in the data structure."""
    todos: list[tuple[str, Any]] = []
    if isinstance(item, str) and "TODO" in item:
        todos.append((path, item))
    elif isinstance(item, dict):
        for k, v in item.items():
            sub_path = f"{path}.{k}" if path else k
            todos.extend(find_todos(v, sub_path))
    elif isinstance(item, list):
        for idx, v in enumerate(item):
            todos.extend(find_todos(v, f"{path}[{idx}]"))
    return todos


def main() -> int:
    print("=" * 60)
    print("Sahayak Scheme Data Validation")
    print("=" * 60)

    if not SCHEMES_FILE.exists():
        print(f"[ERROR]: {SCHEMES_FILE} does not exist.")
        return 1

    try:
        with open(SCHEMES_FILE, "r", encoding="utf-8") as f:
            schemes = json.load(f)
    except json.JSONDecodeError as exc:
        print(f"[ERROR] Error decoding JSON: {exc}")
        return 1

    if not isinstance(schemes, list):
        print("[ERROR]: schemes.json root element must be a list of schemes.")
        return 1

    errors: list[str] = []
    print(f"Loaded {len(schemes)} schemes from {SCHEMES_FILE.name}:\n")

    for idx, scheme in enumerate(schemes, start=1):
        scheme_id = scheme.get("id", f"<unnamed index {idx}>")
        print(f"[{idx}/{len(schemes)}] Validating scheme: '{scheme_id}'")

        # 1. Top level keys
        for key in REQUIRED_TOP_LEVEL_KEYS:
            if key not in scheme:
                errors.append(f"Scheme '{scheme_id}' is missing required key: '{key}'")

        # 2. Eligibility rules
        eligibility = scheme.get("eligibility", [])
        if not isinstance(eligibility, list):
            errors.append(f"Scheme '{scheme_id}': 'eligibility' must be a list.")
        else:
            for r_idx, rule in enumerate(eligibility):
                if not isinstance(rule, dict):
                    errors.append(f"Scheme '{scheme_id}': eligibility rule #{r_idx} must be a dictionary.")
                    continue
                for r_key in REQUIRED_RULE_KEYS:
                    if r_key not in rule:
                        errors.append(f"Scheme '{scheme_id}': eligibility rule #{r_idx} missing key '{r_key}'")
                op = rule.get("op")
                if op and op not in ALLOWED_OPS:
                    errors.append(f"Scheme '{scheme_id}': rule #{r_idx} uses unsupported operator '{op}'")

        # 3. Exclusions
        exclusions = scheme.get("exclusions", [])
        if not isinstance(exclusions, list):
            errors.append(f"Scheme '{scheme_id}': 'exclusions' must be a list.")
        else:
            for e_idx, rule in enumerate(exclusions):
                if isinstance(rule, dict):
                    op = rule.get("op")
                    if op and op not in ALLOWED_OPS:
                        errors.append(f"Scheme '{scheme_id}': exclusion #{e_idx} uses unsupported operator '{op}'")

        # 4. Documents
        documents = scheme.get("documents", [])
        if not isinstance(documents, list):
            errors.append(f"Scheme '{scheme_id}': 'documents' must be a list.")
        else:
            for d_idx, doc in enumerate(documents):
                if not isinstance(doc, dict):
                    errors.append(f"Scheme '{scheme_id}': document #{d_idx} must be a dictionary.")
                    continue
                for d_key in REQUIRED_DOC_KEYS:
                    if d_key not in doc:
                        errors.append(f"Scheme '{scheme_id}': document #{d_idx} missing key '{d_key}'")

        # 5. Form fields
        form_fields = scheme.get("form_fields", [])
        if not isinstance(form_fields, list):
            errors.append(f"Scheme '{scheme_id}': 'form_fields' must be a list.")

        # 6. Verification metadata
        last_verified = scheme.get("last_verified")
        source_note = scheme.get("source_note")
        if not last_verified or last_verified == "TODO":
            errors.append(f"Scheme '{scheme_id}': 'last_verified' date must be set.")
        if not source_note or source_note == "TODO":
            errors.append(f"Scheme '{scheme_id}': 'source_note' must be specified.")

    print("\n" + "-" * 60)
    print("TODO Audit:")
    todos = find_todos(schemes)
    if todos:
        print(f"[WARN] Found {len(todos)} TODO item(s):")
        for path, val in todos:
            print(f"   * {path}: {val}")
    else:
        print("[OK] No TODO items remaining! All scheme facts are verified.")

    print("-" * 60)
    print("Schema Integrity Results:")
    if errors:
        print(f"[ERROR] {len(errors)} Schema Validation Error(s):")
        for err in errors:
            print(f"   * {err}")
        return 1
    else:
        print("[OK] All schemes conform strictly to DATA_SCHEMA.md.")
        print("[OK] All required keys and operators are present.")
        print("=" * 60)
        return 0


if __name__ == "__main__":
    sys.exit(main())
