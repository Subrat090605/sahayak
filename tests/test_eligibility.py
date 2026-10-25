"""Tests for pure-Python eligibility evaluation engine (eligibility.py).

Verifies deterministic rules, 5 profiles from docs/TESTING.md,
missing fields, TODO handling, unknown fields, and operator evaluations.
"""

import copy
import pytest
from eligibility import evaluate_all, evaluate_scheme, load_schemes


@pytest.fixture
def schemes():
    return load_schemes()


def get_scheme(schemes, scheme_id):
    for s in schemes:
        if s["id"] == scheme_id:
            return s
    raise ValueError(f"Scheme with id '{scheme_id}' not found.")


# ===========================================================================
# 1. Five Profiles from docs/TESTING.md
# ===========================================================================


def test_profile_1_farmer_up_low_income(schemes):
    """Profile 1: Farmer, UP, 2 acres, low income -> PM-KISAN eligible or maybe, with reasons."""
    profile = {
        "name": "Ramesh Kumar",
        "occupation": "farmer",
        "state": "Uttar Pradesh",
        "district": "Unnao",
        "land_acres": 2.0,
        "annual_income": 90000,
    }
    scheme = get_scheme(schemes, "pm-kisan")
    res = evaluate_scheme(profile, scheme)

    assert res["status"] in {"eligible", "maybe"}
    assert len(res["reasons_met"]) > 0
    # Must have matched farmer occupation and land requirement
    assert any("farmer" in r.lower() or "किसान" in r for r in res["reasons_met"])
    assert any("land" in r.lower() or "भूमि" in r for r in res["reasons_met"])
    assert len(res["reasons_failed"]) == 0


def test_profile_2_student_low_family_income(schemes):
    """Profile 2: Student, low family income -> Scholarship eligible or maybe."""
    profile = {
        "name": "Priya Sharma",
        "occupation": "student",
        "annual_income": 120000,
        "age": 19,
        "education_level": "college",
        "state": "Bihar",
    }
    scheme = get_scheme(schemes, "national-scholarship")
    res = evaluate_scheme(profile, scheme)

    assert res["status"] in {"eligible", "maybe"}
    assert len(res["reasons_met"]) > 0
    assert any("student" in r.lower() or "छात्र" in r for r in res["reasons_met"])
    assert len(res["reasons_failed"]) == 0


def test_profile_3_bpl_woman_no_lpg(schemes):
    """Profile 3: BPL woman without LPG connection -> Ujjwala eligible or maybe."""
    profile = {
        "name": "Sunita Devi",
        "gender": "female",
        "age": 32,
        "bpl_household": True,
        "has_lpg_connection": False,
        "annual_income": 60000,
    }
    scheme = get_scheme(schemes, "pm-ujjwala")
    res = evaluate_scheme(profile, scheme)

    assert res["status"] in {"eligible", "maybe"}
    assert len(res["reasons_met"]) >= 3
    assert any("woman" in r.lower() or "महिला" in r for r in res["reasons_met"])
    assert any("lpg" in r.lower() or "गैस" in r for r in res["reasons_met"])
    assert len(res["reasons_failed"]) == 0


def test_profile_4_elderly_low_income(schemes):
    """Profile 4: Elderly, low income, no insurance -> Ayushman result with reasons."""
    profile = {
        "name": "Ram Lal",
        "age": 68,
        "annual_income": 95000,
        "occupation": "unemployed",
    }
    scheme = get_scheme(schemes, "pm-jay")
    res = evaluate_scheme(profile, scheme)

    assert res["status"] in {"eligible", "maybe"}
    assert len(res["reasons_met"]) > 0
    assert any("income" in r.lower() or "आय" in r or "secc" in r.lower() for r in res["reasons_met"])
    assert len(res["reasons_failed"]) == 0


def test_profile_5_high_income_salaried(schemes):
    """Profile 5: High-income salaried -> No scheme marked eligible."""
    profile = {
        "name": "Vikram Mehta",
        "occupation": "salaried",
        "annual_income": 1800000,
        "age": 38,
        "gender": "male",
        "has_lpg_connection": True,
        "bpl_household": False,
        "land_acres": 0,
    }
    all_results = evaluate_all(profile, schemes)

    # Hard requirement: NO scheme marked eligible
    for r in all_results:
        assert r["status"] != "eligible", f"Scheme {r['scheme_id']} unexpectedly marked eligible for high income profile"

    # Specific schemes must be explicitly not_eligible
    pm_kisan_res = next(r for r in all_results if r["scheme_id"] == "pm-kisan")
    pm_jay_res = next(r for r in all_results if r["scheme_id"] == "pm-jay")
    ujjwala_res = next(r for r in all_results if r["scheme_id"] == "pm-ujjwala")
    scholarship_res = next(r for r in all_results if r["scheme_id"] == "national-scholarship")

    assert pm_kisan_res["status"] == "not_eligible"
    assert pm_jay_res["status"] == "not_eligible"
    assert ujjwala_res["status"] == "not_eligible"
    assert scholarship_res["status"] == "not_eligible"


# ===========================================================================
# 2. Missing Fields Tests
# ===========================================================================


def test_missing_fields_reported(schemes):
    """Missing fields are collected and reported in missing_fields, yielding 'maybe'."""
    # Profile missing land_acres for pm-kisan
    profile = {"occupation": "farmer", "annual_income": 90000}
    scheme = get_scheme(schemes, "pm-kisan")
    res = evaluate_scheme(profile, scheme)

    assert res["status"] == "maybe"
    assert "land_acres" in res["missing_fields"]


def test_empty_profile_reports_all_missing_fields(schemes):
    """An empty profile reports missing fields and defaults to 'maybe'."""
    scheme = get_scheme(schemes, "pm-kisan")
    res = evaluate_scheme({}, scheme)

    assert res["status"] == "maybe"
    assert "occupation" in res["missing_fields"]
    assert "land_acres" in res["missing_fields"]


# ===========================================================================
# 3. TODO Value Handling Tests
# ===========================================================================


def test_todo_rule_value_yields_maybe(schemes):
    """If a rule value is 'TODO', it must be treated as 'maybe'."""
    scheme_copy = copy.deepcopy(get_scheme(schemes, "pm-kisan"))
    # Introduce a TODO rule value
    scheme_copy["eligibility"].append({
        "field": "category",
        "op": "eq",
        "value": "TODO",
        "label_en": "Special category requirement",
        "label_hi": "विशेष श्रेणी आवश्यकता",
    })

    # Even if profile provides the field, a TODO rule gives 'maybe'
    profile = {
        "occupation": "farmer",
        "land_acres": 2.0,
        "annual_income": 90000,
        "category": "obc",
    }
    res = evaluate_scheme(profile, scheme_copy)
    assert res["status"] == "maybe"


# ===========================================================================
# 4. Unknown Fields Tests
# ===========================================================================


def test_unknown_fields_do_not_crash(schemes):
    """Profiles with unexpected/unknown fields must not crash the engine."""
    profile = {
        "occupation": "farmer",
        "land_acres": 2.5,
        "annual_income": 80000,
        "favorite_cricketer": "Virat Kohli",
        "blood_group": "O+",
        "random_number": 42.195,
        "nested_garbage": {"a": [1, 2, 3]},
    }
    scheme = get_scheme(schemes, "pm-kisan")
    res = evaluate_scheme(profile, scheme)

    assert res["status"] == "eligible"
    assert len(res["reasons_met"]) > 0


# ===========================================================================
# 5. Operators Unit Tests
# ===========================================================================


def test_operator_eq_ne():
    dummy_scheme = {
        "id": "dummy",
        "eligibility": [
            {"field": "status", "op": "eq", "value": "active", "label_en": "Active", "label_hi": "सक्रिय"},
            {"field": "flag", "op": "ne", "value": "banned", "label_en": "Not banned", "label_hi": "प्रतिबंधित नहीं"},
        ],
        "exclusions": [],
    }
    # Matches
    res = evaluate_scheme({"status": "Active", "flag": "normal"}, dummy_scheme)
    assert res["status"] == "eligible"

    # Fails eq
    res = evaluate_scheme({"status": "inactive", "flag": "normal"}, dummy_scheme)
    assert res["status"] == "not_eligible"

    # Fails ne
    res = evaluate_scheme({"status": "active", "flag": "banned"}, dummy_scheme)
    assert res["status"] == "not_eligible"


def test_operator_in():
    dummy_scheme = {
        "id": "dummy",
        "eligibility": [
            {"field": "category", "op": "in", "value": ["sc", "st", "obc"], "label_en": "Reserved category", "label_hi": "आरक्षित श्रेणी"},
        ],
        "exclusions": [],
    }
    assert evaluate_scheme({"category": "SC"}, dummy_scheme)["status"] == "eligible"
    assert evaluate_scheme({"category": "general"}, dummy_scheme)["status"] == "not_eligible"


def test_operator_lte_gte_between():
    dummy_scheme = {
        "id": "dummy",
        "eligibility": [
            {"field": "age", "op": "between", "value": [18, 35], "label_en": "Age 18-35", "label_hi": "आयु 18-35"},
            {"field": "income", "op": "lte", "value": 200000, "label_en": "Income <= 2L", "label_hi": "आय 2 लाख तक"},
            {"field": "score", "op": "gte", "value": 50, "label_en": "Score >= 50", "label_hi": "अंक 50 या अधिक"},
        ],
        "exclusions": [],
    }
    # Eligible profile
    assert evaluate_scheme({"age": "25", "income": 150000, "score": 75}, dummy_scheme)["status"] == "eligible"
    # Fails between
    assert evaluate_scheme({"age": 40, "income": 150000, "score": 75}, dummy_scheme)["status"] == "not_eligible"
    # Fails lte
    assert evaluate_scheme({"age": 25, "income": 250000, "score": 75}, dummy_scheme)["status"] == "not_eligible"
    # Fails gte
    assert evaluate_scheme({"age": 25, "income": 150000, "score": 40}, dummy_scheme)["status"] == "not_eligible"


def test_operator_is_true_is_false():
    dummy_scheme = {
        "id": "dummy",
        "eligibility": [
            {"field": "is_indian", "op": "is_true", "value": True, "label_en": "Indian citizen", "label_hi": "भारतीय नागरिक"},
            {"field": "has_tax_id", "op": "is_false", "value": False, "label_en": "No PAN card", "label_hi": "पैन कार्ड नहीं"},
        ],
        "exclusions": [],
    }
    assert evaluate_scheme({"is_indian": True, "has_tax_id": False}, dummy_scheme)["status"] == "eligible"
    assert evaluate_scheme({"is_indian": "yes", "has_tax_id": "no"}, dummy_scheme)["status"] == "eligible"
    assert evaluate_scheme({"is_indian": False, "has_tax_id": False}, dummy_scheme)["status"] == "not_eligible"


# ===========================================================================
# 6. evaluate_all Sorting Test
# ===========================================================================


def test_evaluate_all_sorting(schemes):
    """evaluate_all must return schemes sorted: eligible first, then maybe, then not_eligible."""
    # Farmer profile: eligible for pm-kisan & pm-jay, maybe for ujjwala (missing gender), not_eligible for scholarship
    profile = {
        "occupation": "farmer",
        "land_acres": 2.0,
        "annual_income": 80000,
    }
    results = evaluate_all(profile, schemes)

    statuses = [r["status"] for r in results]
    # Check ordering invariant: eligible comes before maybe, maybe comes before not_eligible
    status_order = {"eligible": 0, "maybe": 1, "not_eligible": 2}
    ranks = [status_order[s] for s in statuses]
    assert ranks == sorted(ranks), f"Results are not properly sorted by status: {statuses}"
