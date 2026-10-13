# Hackathon test data: patient JSON dumps

How to turn the LUVN synthetic hackathon tables into one JSON file per patient that the app can read
without an LLM. All data is synthetic. The generated files are not committed (`/testdata/` is in
`.gitignore`).

You need the `Hackathon_data` folder somewhere on your machine (it holds
`LUVN_synteettinenData_VEIL/`) and [uv](https://docs.astral.sh/uv/). The commands below have no comments
and no line breaks, so they paste into zsh as they are.

## 1. Set up

From the repository root:

```sh
cd backend
uv sync
export HACKATHON_DATA="/path/to/Hackathon_data"
```

Put the real path in `HACKATHON_DATA`. The variable only lasts for this terminal session.

## 2. Load the tables into a local database

```sh
uv run python -m scripts.luvn_dump import "$HACKATHON_DATA/LUVN_synteettinenData_VEIL/2024-2026/clinical/tables" /tmp/luvn.db
```

This reads the `*.jsonl` and `*.schema.json` files and writes a SQLite file, `/tmp/luvn.db`, in about two
seconds. It prints the row count of each table (15,000 patients, about 120,000 contacts). Running it again
replaces the file. Use `2024-2026`, not `2025`: the two cohorts have separate identifiers.

## 3. Dump the 50 best patients into `testdata`

```sh
uv run python -m scripts.luvn_dump dump /tmp/luvn.db ../testdata --top 50
```

This creates `testdata/` in the repository root with:

- `SYN-ASI-<number>.json`: one file per patient, 50 in all. Each file is the patient's rows from the
  database, one property per table under `tables`. The format is described in
  [backend/app/sources/luvn/README.md](backend/app/sources/luvn/README.md).
- `manifest.json`: the files best first, with an IPS score and counts for each (problems, active
  medications, lab results and so on). Open this first to pick a file.

"Best" means the highest IPS score: the most distinct diagnoses and active medications, plus a bonus for a
long-term diagnosis. Only what the parser maps counts, so lab results do not raise the score. The
exact rule is in `app/sources/luvn/manifest.py`. The command prints the top five files when it finishes.

If `testdata/` already exists, delete it first (`rm -r ../testdata`). A new run overwrites files with the
same name but leaves older ones behind, and `manifest.json` only lists the current run.

## 4. Try a file in the app

Upload one of the files from `testdata/` in the PWA like any JSON document. A dump is recognised
automatically and parsed without calling a paid API. Other documents still go to the extractor that is
configured. The review screen then shows the patient's problems and medications, each pointing back to its
row in the file.

## Other selections

Add these to the command in step 3, or use them instead of `--top 50`. When several are given, all must
hold.

| Option | Effect |
|---|---|
| `--top N` | The N highest-scoring patients (ranks all matching patients first). |
| `--limit N` | The first N matching patients, not the best. |
| `--with-labs` | Only patients with lab results (3,364 of 15,000). |
| `--with-procedures` | Only patients with procedures. |
| `--has-long-term-dx` | Only patients with a long-term diagnosis (4,849). |
| `--active-meds` | Only patients with a medication that has no end date or ends on or after the export date (8,401). |
| `--min-score N` | Skip patients scoring below N. |
| `--id <asiakas_id>` | A specific patient; repeat the option for several. |
| `--random-seed S` | Shuffle the candidates first, so `--limit` gives a reproducible random sample. |
| `--exported-at YYYY-MM-DD` | The reference date for "active medication"; default is today. |

For example, to dump every patient with lab results:

```sh
uv run python -m scripts.luvn_dump dump /tmp/luvn.db ../testdata-labs --with-labs
```

## Good to know

- **Not in the dumps' IPS output yet:** allergies (no table, so the section says "no information"), lab
  results, procedures and encounters. They are in the files but are not mapped to IPS sections.
- **No patient names.** The tables have none, so the Patient section shows an identifier, birth date and sex only.
- **Problem names** are Finnish display names for the 30 ICD-10 codes in this dataset (`icd10_fi.py`). The
  code itself is only a hint for the terminology lookup.
- To produce the same files from a real database, see "For the organisation that maintains the database" in
  the format description linked above.
