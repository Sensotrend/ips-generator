# LUVN patient dump (`luvn-clinical-dump`, version 1)

One JSON file per patient. `tables.<table>` holds that patient's rows of the LUVN clinical table, with the
original column names and the types of the table's `*.schema.json` (dates and decimals as strings, booleans
as booleans, missing values as `null`). Nothing is renamed, added or derived.

```json
{"meta": {"format": "luvn-clinical-dump", "version": 1, "exported_at": "2026-10-13"},
 "tables": {"asiakas": [{...}], "kontakti": [...], "diagnoosi": [...], "toimenpide": [...],
            "laakitys": [...], "laakitys_kontakti": [...], "vastausarkistohistoria_view": [...],
            "laboratorio_kontakti": [...], "ajanvaraus": [...], "osastohoitojakso": []}}
```

## For the organisation that maintains the database
Run one query per table. `asiakas`, `kontakti`, `diagnoosi`, `laakitys`, `vastausarkistohistoria_view`,
`ajanvaraus` and `osastohoitojakso` filter on `asiakas_id`; `toimenpide` through the patient's `kontakti_id`s;
`laakitys_kontakti` and `laboratorio_kontakti` through the patient's `laakitys_avain` / `Avain` rows
(`SELECTIONS` in `dump.py` has the exact filters). `exported_at` is the reference date for "is this
medication still active". Tables without rows are `[]`.

## Try it with the hackathon data
```sh
cd backend
uv run python -m scripts.luvn_dump import <LUVN>/2024-2026/clinical/tables /tmp/luvn.db   # ~2 s
uv run python -m scripts.luvn_dump dump /tmp/luvn.db /tmp/dumps --first 5
```
Upload a dump in the PWA like any JSON document: `StructuredFirstExtractor` (`app/pipeline/extractors.py`)
recognises `meta.format` and parses it with `parse.py` (no LLM, no cost); other documents go to the
configured extractor. The mapping rules are in the `parse.py` docstring.

## Not covered yet
Allergies (no table; the section is "no information"), results (`vastausarkistohistoria_view`, needs the
Phase 2 Results section and lab-code to LOINC mapping), procedures, encounters, and the free-text visit notes.
