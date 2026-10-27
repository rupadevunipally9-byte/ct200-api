# CT-200 Manual API

A backend API that reads the CardioTrack CT-200 manual (PDF), turns it into a versioned tree, lets you select sections, asks an LLM for QA test case ideas, and tells you later if those test cases may be out of date because the manual changed.

Design decisions, edge cases and known weaknesses are in [APPROACH.md](APPROACH.md).

## What it does

1. **Ingest** a PDF into a tree (sections, sub-sections, tables, lists) saved in SQLite. Each node has a heading, level, parent, body text and a content hash.
2. **Version** the manual. Ingesting the v2 PDF creates version 2 and keeps version 1. The same section in both versions shares one "logical node". Changed sections are flagged.
3. **Browse** sections, read one section, search, and ask "did this section change, and how?".
4. **Select** sections and save them as a named selection, pinned to exact versions.
5. **Generate** 3 to 5 QA test cases from a selection with an LLM. The answer is checked, retried if broken, and saved.
6. **Check staleness** when test cases are fetched. Each test case says `current`, `review`, `stale` or `source_removed`.

## Tech stack

- FastAPI, Pydantic, SQLAlchemy, SQLite (tree, versions, selections)
- PyMuPDF for reading the PDF
- LLM: Groq (OpenAI-compatible API), model `openai/gpt-oss-120b`
- **Deviation:** LLM output is stored as JSON files (one per generation, in the `store/` folder) instead of MongoDB. Reason is in APPROACH.md.

## Setup

You need Python 3.10 or newer (built and tested on Python 3.14).

Windows:
```
git clone https://github.com/rupadevunipally9-byte/ct200-api.git
cd ct200-api
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

macOS / Linux:
```
git clone https://github.com/rupadevunipally9-byte/ct200-api.git
cd ct200-api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment variables

Put them in a file called `.env` in the project folder (it is ignored by Git), or set them in your terminal.

| Variable | Needed for | Default |
|---|---|---|
| `LLM_API_KEY` | Generating test cases (free key from console.groq.com) | none |
| `LLM_MODEL` | Which model to call | `openai/gpt-oss-120b` |
| `LLM_BASE_URL` | Any OpenAI-compatible provider | `https://api.groq.com/openai/v1` |
| `DATABASE_URL` | Where the SQLite database lives | `sqlite:///ct200.db` |
| `STORE_DIR` | Where generation JSON files are saved | `store` |

Example `.env`:
```
LLM_API_KEY=your_key_here
LLM_MODEL=openai/gpt-oss-120b
```

You do not need an API key to run the tests, ingest PDFs, browse or select. Only the generate call needs it.

## Run the server

```
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs to try every endpoint.

## How to trigger the v1 to v2 re-ingestion

With the server running, from the `/docs` page (or any HTTP client):

1. `POST /versions` with body `{"file": "ct200_manual.pdf"}`. This creates **version 1** (28 nodes).
2. `POST /versions` with body `{"file": "ct200_manual_v2.pdf"}`. This creates **version 2** (29 nodes). Version 1 is kept as it was.
3. `GET /versions` lists both.

Only file names inside the `data/` folder are accepted. Sending the same file twice returns `409` and saves nothing.

You can also ingest from the command line (no server needed):
```
python scripts/ingest.py data/ct200_manual.pdf
python scripts/ingest.py data/ct200_manual_v2.pdf
```

What v2 changes, as the system reports it:

| Section | Result | What changed |
|---|---|---|
| 2.1.1.1 Battery Life | changed | 300 cycles to 250, low-battery icon 15% to 10% |
| 3.2 Cuff Inflation Sequence | changed | increments 40 mmHg to 30 mmHg |
| 4.2 Error Codes | changed | E3 time 2 s to 1.5 s, new E6 row |
| 4.3 Alarm Thresholds | changed | "E1-E5" to "E1-E6" |
| 5.3 Data Export | added | new section |
| the other 24 nodes | unchanged | |

## Run the end-to-end demo

The demo walks through the whole story using the API: ingest v1, select, generate, check staleness, ingest v2, check staleness again, retry the same selection, retrieve by section. It needs a **fresh database** and an `LLM_API_KEY`.

Window 1, start the server on a demo database.

Windows (Command Prompt):
```
.venv\Scripts\activate
set DATABASE_URL=sqlite:///demo.db
set STORE_DIR=demo_store
uvicorn app.main:app
```

Windows (PowerShell):
```
.venv\Scripts\activate
$env:DATABASE_URL="sqlite:///demo.db"
$env:STORE_DIR="demo_store"
uvicorn app.main:app
```

macOS / Linux:
```
source .venv/bin/activate
DATABASE_URL=sqlite:///demo.db STORE_DIR=demo_store uvicorn app.main:app
```

Window 2:
```
python scripts/demo.py
```

The script refuses to run if the database already has versions. Delete `demo.db` and the `demo_store` folder to run it again.

## Run the tests

```
python -m pytest -q
```

There are 44 tests. They parse the real PDFs, so the run takes about a minute. The LLM is replaced by a fake in the tests, so they need no key and no internet.

| Test file | What it checks |
|---|---|
| `test_parser.py` | The PDF irregularities: duplicate heading, skipped level, 3.4 before 3.3, list vs heading, page-break paragraphs, tables, hash changes, PDF with no text |
| `test_versioning.py` | Same logical nodes across versions, v1 not destroyed, same file refused |
| `test_ingest_api.py` | Ingesting through the API, 409 on repeat, unsafe file names rejected |
| `test_api.py` | Browse, search, node detail, change report |
| `test_selections.py` | Version-pinned selections |
| `test_generations.py` | Bad LLM output, retries, failed records, duplicate policy |
| `test_staleness.py` | Staleness labels and retrieval, including a fake v3 for wording-only and removed sections |

## API overview

| Method and path | Purpose |
|---|---|
| `POST /versions` | Ingest a PDF from `data/` as the next version |
| `GET /versions` | List versions |
| `GET /sections?version=` | Top-level sections (latest version by default) |
| `GET /nodes/{id}` | One node with children, full text, content hash |
| `GET /search?q=&version=&scope=` | Search headings, text or both |
| `GET /nodes/{id}/changes` | Did this section change across versions, with a small diff |
| `POST /selections` | Save a named, version-pinned selection |
| `GET /selections`, `GET /selections/{id}` | List or read selections |
| `POST /selections/{id}/generate?force=` | Generate test cases (reuses the saved result unless `force=true`) |
| `GET /selections/{id}/generations?against_version=` | Test cases with staleness |
| `GET /generations/{id}?against_version=` | One generation with staleness |
| `GET /nodes/{id}/generations?against_version=` | Test cases that cite this section, with staleness |

Staleness labels:

| Label | Meaning |
|---|---|
| `current` | The section text is identical to what the test case was written from |
| `review` | Wording changed but no numbers changed. A person should read the change |
| `stale` | A number changed. Treat the test case as wrong until re-checked |
| `source_removed` | The section is gone in the version being checked |

## Project layout

```
app/        parser, database models, ingestion, APIs, LLM, staleness
scripts/    ingest, demo and small exploration scripts used while studying the PDF
tests/      unit and API tests
data/       the two manual PDFs
CT200_Notes/pdf_notes.md   my notes from studying the PDFs
```
