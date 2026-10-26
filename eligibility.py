"""Eligibility evaluation engine for Sahayak.

Decides scheme eligibility deterministically using pure Python rules (no LLM).
Source of truth: data/schemes.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMES_FILE = Path(__file__).parent / "data" / "schemes.json"


def load_schemes(path: Path | str | None = None) -> list[dict[str, Any]]:
    """Load verified schemes from JSON file."""
    target = Path(path) if path else SCHEMES_FILE
    with open(target, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Operator implementations
# ---------------------------------------------------------------------------


def _op_eq(profile_val: Any, rule_val: Any) -> bool:
    if isinstance(rule_val, bool) or isinstance(profile_val, bool):
        return bool(profile_val) is bool(rule_val)
    if isinstance(rule_val, (int, float)) and not isinstance(rule_val, bool):
        try:
            return float(profile_val) == float(rule_val)
        except (ValueError, TypeError):
            return False
    if isinstance(rule_val, str) and isinstance(profile_val, str):
        return profile_val.strip().lower() == rule_val.strip().lower()
    return profile_val == rule_val


def _op_ne(profile_val: Any, rule_val: Any) -> bool:
    return not _op_eq(profile_val, rule_val)


def _op_in(profile_val: Any, rule_val: Any) -> bool:
    if isinstance(rule_val, (list, tuple, set)):
        if isinstance(profile_val, str):
            p_clean = profile_val.strip().lower()
            return any(
                p_clean == (str(x).strip().lower() if isinstance(x, str) else str(x).lower())
                for x in rule_val
            )
        return profile_val in rule_val
    if isinstance(rule_val, str) and isinstance(profile_val, str):
        return profile_val.strip().lower() in rule_val.strip().lower()
    return False


def _op_lte(profile_val: Any, rule_val: Any) -> bool:
    try:
        return float(profile_val) <= float(rule_val)
    except (ValueError, TypeError):
        return False


def _op_gte(profile_val: Any, rule_val: Any) -> bool:
    try:
        return float(profile_val) >= float(rule_val)
    except (ValueError, TypeError):
        return False


def _op_between(profile_val: Any, rule_val: Any) -> bool:
    if not isinstance(rule_val, (list, tuple)) or len(rule_val) != 2:
        return False
    try:
        val = float(profile_val)
        low = float(rule_val[0])
        high = float(rule_val[1])
        return low <= val <= high
    except (ValueError, TypeError):
        return False


def _op_is_true(profile_val: Any, rule_val: Any = None) -> bool:
    if isinstance(profile_val, bool):
        return profile_val is True
    if isinstance(profile_val, (int, float)):
        return profile_val != 0
    if isinstance(profile_val, str):
        return profile_val.strip().lower() in {"true", "1", "yes", "y", "हाँ", "ha", "haan"}
    return bool(profile_val)


def _op_is_false(profile_val: Any, rule_val: Any = None) -> bool:
    if isinstance(profile_val, bool):
        return profile_val is False
    if isinstance(profile_val, (int, float)):
        return profile_val == 0
    if isinstance(profile_val, str):
        return profile_val.strip().lower() in {"false", "0", "no", "n", "नहीं", "nahi", "nahin"}
    return not bool(profile_val)


OPERATOR_MAP = {
    "eq": _op_eq,
    "ne": _op_ne,
    "in": _op_in,
    "lte": _op_lte,
    "gte": _op_gte,
    "between": _op_between,
    "is_true": _op_is_true,
    "is_false": _op_is_false,
}


def _evaluate_op(op_name: str, profile_val: Any, rule_val: Any) -> bool:
    normalized_op = op_name.strip().lower().replace(" ", "_").replace("-", "_")
    handler = OPERATOR_MAP.get(normalized_op)
    if not handler:
        return False
    return handler(profile_val, rule_val)


def _format_reason(rule: dict[str, Any], lang: str | None = None) -> str:
    """Format rule reasons using English and Hindi labels."""
    en = str(rule.get("label_en", "")).strip()
    hi = str(rule.get("label_hi", "")).strip()
    if lang == "en":
        return en or hi or str(rule.get("field", ""))
    if lang == "hi":
        return hi or en or str(rule.get("field", ""))
    if en and hi:
        return f"{en} / {hi}"
    return en or hi or str(rule.get("field", ""))


# ---------------------------------------------------------------------------
# Scheme evaluation
# ---------------------------------------------------------------------------


def evaluate_scheme(
    profile: dict[str, Any],
    scheme: dict[str, Any],
    lang: str | None = None,
) -> dict[str, Any]:
    """Evaluate a user profile against a single scheme's rules.

    Returns:
        dict matching docs/DATA_SCHEMA.md:
        {
            "scheme_id": str,
            "status": "eligible" | "maybe" | "not_eligible",
            "reasons_met": list[str],
            "reasons_failed": list[str],
            "missing_fields": list[str],
        }
    """
    scheme_id = scheme.get("id", "")
    reasons_met: list[str] = []
    reasons_failed: list[str] = []
    missing_fields: list[str] = []

    has_maybe = False
    has_failed = False

    # 1. Eligibility criteria
    for rule in scheme.get("eligibility", []):
        field = rule.get("field")
        rule_val = rule.get("value")
        op = rule.get("op", "")
        reason = _format_reason(rule, lang)

        profile_val = profile.get(field) if field in profile else None
        # Domain rule: Households with annual income > 2.5 Lakhs are income tax assessees and not BPL
        if field == "bpl_household" and profile_val is None:
            inc = profile.get("annual_income")
            if inc is not None:
                try:
                    if float(inc) > 250000:
                        profile_val = False
                except (ValueError, TypeError):
                    pass

        if profile_val is None or profile_val == "":
            if field and field not in missing_fields:
                missing_fields.append(field)
            has_maybe = True
        elif rule_val == "TODO":
            has_maybe = True
        else:
            passed = _evaluate_op(op, profile_val, rule_val)
            if passed:
                reasons_met.append(reason)
            else:
                reasons_failed.append(reason)
                has_failed = True

    # 2. Exclusions criteria
    for rule in scheme.get("exclusions", []):
        field = rule.get("field")
        rule_val = rule.get("value")
        op = rule.get("op", "")
        reason = _format_reason(rule, lang)

        if field not in profile or profile.get(field) is None or profile.get(field) == "":
            if field and field not in missing_fields:
                missing_fields.append(field)
            has_maybe = True
        elif rule_val == "TODO":
            has_maybe = True
        else:
            profile_val = profile[field]
            triggered = _evaluate_op(op, profile_val, rule_val)
            if triggered:
                reasons_failed.append(reason)
                has_failed = True

    # 3. Determine status
    if has_failed:
        status = "not_eligible"
    elif has_maybe:
        status = "maybe"
    else:
        status = "eligible"

    return {
        "scheme_id": scheme_id,
        "status": status,
        "reasons_met": reasons_met,
        "reasons_failed": reasons_failed,
        "missing_fields": missing_fields,
    }


def evaluate_all(
    profile: dict[str, Any],
    schemes: list[dict[str, Any]] | None = None,
    lang: str | None = None,
) -> list[dict[str, Any]]:
    """Run evaluate_scheme for every scheme and sort results:

    'eligible' first, then 'maybe', then 'not_eligible'.
    """
    if schemes is None:
        schemes = load_schemes()

    results = [evaluate_scheme(profile, scheme, lang=lang) for scheme in schemes]
    status_priority = {"eligible": 0, "maybe": 1, "not_eligible": 2}
    return sorted(results, key=lambda r: status_priority.get(r.get("status", "not_eligible"), 99))
