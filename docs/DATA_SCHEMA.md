# Data schemas

## Profile fields (user)
| Field | Type | Example |
|---|---|---|
| `name` | string | "Ramesh Kumar" |
| `age` | int | 42 |
| `gender` | "male"/"female"/"other" | "male" |
| `state` | string | "Uttar Pradesh" |
| `district` | string | "Unnao" |
| `occupation` | "farmer"/"student"/"labourer"/"salaried"/"self_employed"/"unemployed"/"other" | "farmer" |
| `land_acres` | float | 2.0 |
| `annual_income` | int (INR) | 90000 |
| `category` | "general"/"obc"/"sc"/"st"/"other" | "obc" |
| `bpl_household` | bool | true |
| `education_level` | string | "class_12" |
| `has_lpg_connection` | bool | false |

Required fields differ by scheme; the engine reports which are missing.

## Scheme record (`data/schemes.json`)
```json
{
  "id": "pm-kisan",
  "name_en": "TODO",
  "name_hi": "TODO",
  "benefit_en": "TODO",
  "benefit_hi": "TODO",
  "official_link": "TODO",
  "last_verified": "YYYY-MM-DD",
  "source_note": "which official page you copied this from",
  "eligibility": [
    {"field": "occupation", "op": "eq", "value": "farmer",
     "label_en": "Must be a farmer", "label_hi": "किसान होना चाहिए"}
  ],
  "exclusions": [],
  "documents": [
    {"id": "aadhaar", "name_en": "TODO", "name_hi": "TODO",
     "where_to_get_en": "TODO", "where_to_get_hi": "TODO"}
  ],
  "form_fields": ["name", "age", "state", "district"],
  "deadline": null
}
```

## Supported operators
`eq`, `ne`, `in`, `lte`, `gte`, `between`, `is_true`, `is_false`

## Rules for filling data
1. Copy every rule, amount, document, and link from the **official** portal. Do not use LLM memory.
2. Put the page you used in `source_note` and the date in `last_verified`.
3. Use `null` for deadline unless the official page states one.
4. If a rule is unclear, set the value to `"TODO"`; the engine must treat `TODO` as "maybe".

## Engine output
```json
{
  "scheme_id": "pm-kisan",
  "status": "eligible | maybe | not_eligible",
  "reasons_met": ["..."],
  "reasons_failed": ["..."],
  "missing_fields": ["land_acres"]
}
```
