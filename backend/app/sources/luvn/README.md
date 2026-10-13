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
uv run python -m scripts.luvn_dump dump /tmp/luvn.db /tmp/dumps --limit 5
uv run python -m scripts.luvn_dump dump /tmp/luvn.db /tmp/rich --with-labs --active-meds \
    --min-score 20 --random-seed 1 --limit 20
```

### Choosing what is dumped
Filters (all that are given must hold): `--id <id>` (repeatable), `--with-labs`, `--with-procedures`,
`--has-long-term-dx`, `--active-meds` (a medication with no end date, or ending on/after the export date;
`--exported-at YYYY-MM-DD` sets that date, default today), `--min-score N`, `--random-seed S` (shuffle the
candidates), `--limit N` (stop after N dumps that pass every filter). The database filters run in SQL;
`--min-score` is checked on each dump before it is written.

### `manifest.json`
Written next to the dumps: the files best first, with ids and counts only (no row contents).
```json
{"meta": {"format": "luvn-dump-manifest", "version": 1, "exported_at": "...", "filters": {...}, "scoring": "..."},
 "patients": [{"file": "SYN-ASI-....json", "asiakas_id": "SYN-ASI-...", "score": 22,
               "ips_sections": ["problems", "medications"],
               "counts": {"problems": 9, "long_term_problems": 2, "medications": 50, "active_medications": 8},
               "not_mapped": {"lab_results": 4, "procedures": 0, "encounters": 12}}]}
```
Score = `min(problems, 10) + min(active_medications, 10)` + 5 if there is a long-term diagnosis. Only what
`parse.py` maps scores; labs, procedures and encounters are listed under `not_mapped` (present, but no IPS
section yet). The score and the parser must stay in step (a test compares the counts).

Upload a dump in the PWA like any JSON document: `StructuredFirstExtractor` (`app/pipeline/extractors.py`)
recognises `meta.format` and parses it with `parse.py` (no LLM, no cost); other documents go to the
configured extractor. The mapping rules are in the `parse.py` docstring.

## Not covered yet
Allergies (no table; the section is "no information"), results (`vastausarkistohistoria_view`, needs the
Phase 2 Results section and lab-code to LOINC mapping), procedures, encounters, and the free-text visit notes.
