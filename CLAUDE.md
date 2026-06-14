# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a USPTO patent data pipeline and multimodal search engine. It collects LG Display patents from the USPTO, stores them in SQLite, builds CLIP-based FAISS vector indices, and serves a single-page search UI via FastAPI.

## Running the Server

```bash
# From the project root (activates the local venv automatically via pyvenv.cfg)
python 05_multimodal_retriever.py
# Server runs at http://0.0.0.0:8000 — UI at http://localhost:8000/
```

## Pipeline Execution Order

Run each step in sequence. All scripts must be run from the project root directory.

```bash
# Step 1a — Bulk ingest from USPTO weekly TAR or ZIP archives (reads from PTGRDT/)
python 01_pipeline_zip_data.py                              # 전체 파일, 이미지 추출
python 01_pipeline_zip_data.py --grantDate 20250107         # 특정 날짜 아카이브만
python 01_pipeline_zip_data.py --image_extract n            # 이미지 추출 생략

# Step 1b — Alternative: real-time ingest via USPTO ODP API
python 01_pipeline_api_data.py

# Step 2 — Filter LG Display patents → USPTO_LGD table + copy images to US_patent_images/LGD/
python 02_target_selection.py

# Step 3 — Extract reference characters / component names from patent descriptions
python 03_element_parser.py          # regex-based
# or
python 03_element_parser_pos.py      # NLTK POS-tagging (higher precision)

# Step 4 — Build FAISS vector indices (requires GPU or CPU, downloads CLIP on first run)
python 04_build_index.py
```

## Architecture

### Data Flow

```
PTGRDT/*.tar (USPTO weekly archives)
    └─ 01_pipeline_zip_data.py ──→ USPTO_zip_data.db (table: USPTO_zip_data)
                                                │
                                   02_target_selection.py
                                                │
                                    ┌───────────┴────────────┐
                                 USPTO_LGD table       US_patent_images/LGD/
                                    │
                            03_element_parser*.py
                            (adds elementsFromDD, chunkFromElement columns)
                                    │
                             04_build_index.py
                                    │
                    ┌───────────────┼────────────────┐
              index/db1_claims   db2_images      db3_elements
              (.index + .json)
                                    │
                         05_multimodal_retriever.py (FastAPI)
                                    │
                              06_index.html (UI)
```

### Key Components

- **`USPTO_zip_data.db`** — Single SQLite database. The main raw table is `USPTO_zip_data`; the filtered working table is `USPTO_LGD`.
- **`US_patent_images/LGD/`** — TIF drawings for LG Display patents only (copied by step 2).
- **`index/`** — Three FAISS `IndexFlatIP` indices (cosine similarity via L2-normalized inner product):
  - `db1_claims.index` / `db1_meta.json` — representative independent claims (text)
  - `db2_images.index` / `db2_meta.json` — patent drawings (image)
  - `db3_elements.index` / `db3_meta.json` — extracted component name chunks (text)
- **CLIP model** — `openai/clip-vit-large-patch14` (768-dim shared embedding space). Downloaded from HuggingFace on first run; cached under `~/.cache/huggingface/`.
- **`05_multimodal_retriever.py`** — FastAPI backend. Loads all three indices and the CLIP model at startup. Serves:
  - `POST /search` — claim + element + image multimodal search. `query_element` is normalized on arrival: comma-separated terms are sorted alphabetically (case-insensitive) before embedding. When 2+ query types are active, computes **RRF (Reciprocal Rank Fusion, k=60)** scores and returns a deduplicated combined ranking (one entry per patent number, highest individual score kept as representative). Single-query mode sorts by cosine similarity.
  - `GET /api/images/{filename}` — TIF→PNG conversion on the fly.
  - `POST /api/preview` — server-side image conversion for browser upload preview.
  - `POST /export` — Excel export with embedded K2 images, **yellow keyword highlighting** in K1/K3 claim/element text cells (`write_rich_string`), and RRF scores in the overall sheet.
- **`06_index.html`** — Self-contained vanilla JS frontend (no build step). Talks to the backend via `fetch`. Results rendered in 3 colour-coded columns: red (K1 claims), green (K3 elements), blue (K2 images). Tooltips for K1/K3 highlight words matching the query input in yellow. Combined ranking shows bare patent numbers (no type suffix), with `RRF:x.xxxx | yy.y%` score when RRF is active. On search, the element textarea is sorted alphabetically by comma-separated terms and updated in place so the user sees the normalized input.

### CLIP Text Limit

CLIP's text encoder is hard-capped at **77 tokens**. Long claims are silently truncated. `max_length=77` is set explicitly in all encoding calls.

## Database Schema

`USPTO_zip_data` / `USPTO_LGD` columns (all TEXT):

`patentNumber`, `grantDate`, `applicationType`, `applicationNumber`, `applicationDate`, `ptaDays`, `cpcMain`, `cpcFurther`, `numberOfClaims`, `exemplaryClaim`, `inventionTitle`, `cpcSearched`, `numberOfFigures`, `applicantName`, `applicantCountry`, `assigneeName`, `examinerDepartment`, `abstract`, `briefSummary`, `detailedDescription`, `briefSummaryBackground`, `briefSummarySummary`, `allClaims`, `rep_ind_Claim`

Columns added by step 3: `elementsFromDD` (JSON dict of ref→name), `chunkFromElement` (JSON list of unique names).

## Environment

The project uses a local venv (`pyvenv.cfg` in the project root). Key packages from `requirements.txt`: `fastapi`, `uvicorn`, `transformers`, `torch`, `faiss-cpu`, `pillow`, `lxml`, `pandas`, `xlsxwriter`, `openpyxl`, `nltk`.

Python version: 3.13 (conda base) or the local venv. The venv is activated automatically when running scripts from this directory.
