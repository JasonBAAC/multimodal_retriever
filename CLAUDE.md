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

### Alternative: Target-filtered ingest (9x sub-project)

Steps 1a + 2 can be replaced by `91_extract_data.py`, which filters by target company **during** ingest (no separate selection step needed).

```bash
# 저장된 인자로 구동 (90_args.txt 기본값 사용)
python 91_extract_data.py

# 특정 날짜 아카이브만 처리
python 91_extract_data.py --grantDate 20250107

# 대상 기업 변경 (변경값은 90_args.txt에 저장되어 이후 기본값으로 사용됨)
python 91_extract_data.py --applicantName "Samsung Display" --aka "SDC" --dbName "US_samsung"
```

**인자 목록** (생략 시 `90_args.txt` 저장값 → 코드 내 기본값 순으로 적용):

| 인자 | 기본값 | 설명 |
|------|--------|------|
| `--sourceFolder` | `PTGRDT` | USPTO 아카이브 디렉토리 |
| `--applicantName` | `LG Display` | 출원인명 (부분 일치) |
| `--aka` | `LGD` | 약칭 (테이블명·이미지 폴더에 사용) |
| `--applicantCountry` | `KR` | 출원인 국가 코드 (완전 일치) |
| `--assigneeName` | `LG Display` | 양수인명 (부분 일치) |
| `--imageFolder` | `Patent_images` | TIF 저장 상위 폴더 |
| `--dbName` | `US_patent` | SQLite DB 파일명 (`.db` 자동 추가) |
| `--grantDate` | (전체) | 처리할 아카이브 날짜 (`YYYYMMDD`) |

- **DB 테이블명**: `{aka}_patent` (예: `LGD_patent`) — 자동 생성
- **이미지 저장 경로**: `{imageFolder}/{aka}/` (예: `Patent_images/LGD/`)
- **필터 조건**: `applicantCountry` 완전 일치 **AND** (`applicantName` 포함 **OR** `assigneeName` 포함)
- 각 아카이브 처리 완료 후 `NNN case extracted!` 형식으로 신규 적재 건수 출력

### 9x 파이프라인 실행 순서

```bash
# Step 91 — 대상 기업 필터링 인제스트 (steps 1a + 2 통합)
python 91_extract_data.py

# Step 92 — 특허 상세설명에서 구성요소명 추출 → {aka}_patent 테이블 업데이트
python 92_parse_element.py

# Step 93 — 도면 OCR → {aka}_drawing 테이블 생성
python 93_ocr_drawing.py

# Step 94 — FAISS 벡터 인덱스 구축
python 94_build_index.py

# Step 95 — FastAPI 검색 서버 실행 (UI: 96_index.html)
python 95_retrieve_patent.py
```

**92_parse_element.py 인자:**

| 인자 | 기본값 | 설명 |
|------|--------|------|
| `--dbName` | `US_patent` | SQLite DB 파일명 |
| `--aka` | `LGD` | 약칭 → 테이블명 `{aka}_patent` |

추가 컬럼: `elementsFromDD` (JSON dict: ref→name), `chunkFromElementDD` (정렬된 고유 name 쉼표 구분 문자열)

**93_ocr_drawing.py 인자:**

| 인자 | 기본값 | 설명 |
|------|--------|------|
| `--dbName` | `US_patent` | SQLite DB 파일명 |
| `--aka` | `LGD` | 약칭 → 이미지 테이블 `{aka}_drawing`, 특허 테이블 `{aka}_patent` |
| `--imageFolder` | `Patent_images` | TIF 저장 상위 폴더 |

**94_build_index.py 인자:**

| 인자 | 기본값 | 설명 |
|------|--------|------|
| `--dbName` | `US_patent` | SQLite DB 파일명 |
| `--aka` | `LGD` | 약칭 |
| `--imageFolder` | `Patent_images` | 이미지 상위 폴더 |
| `--indexFolder` | `index_{aka}` | FAISS 인덱스 저장 폴더 (기본: `index_LGD`) |

- **DB1**: `{aka}_patent.rep_ind_Claim` → 텍스트 임베딩
- **DB2**: `{imageFolder}/{aka}/` 내 TIF 파일 → 이미지 임베딩
- **DB3**: `{aka}_drawing.chunkFromElementDR` → 텍스트 임베딩

**95_retrieve_patent.py 인자:**

| 인자 | 기본값 | 설명 |
|------|--------|------|
| `--dbName` | `US_patent` | SQLite DB 파일명 |
| `--aka` | `LGD` | 약칭 (Excel 파일명에 반영) |
| `--imageFolder` | `Patent_images` | 이미지 상위 폴더 |
| `--indexFolder` | `index_{aka}` | FAISS 인덱스 로드 폴더 |

- 서버 시작 시 `90_args.txt`에서 설정 읽음 (`parse_known_args`로 uvicorn 인자 충돌 방지)
- UI: `96_index.html` / Excel 파일명: `MultimodalRetrieval_YYYYMMDDThhmmss_US_{aka}.xlsx`

**`{aka}_drawing` 테이블 스키마:**

| 필드 | 설명 |
|------|------|
| `patentNumber` | 파일명 중 `US`와 첫 번째 `-` 사이 값 |
| `grantDate` | 파일명 중 첫 번째 `-`와 두 번째 `-` 사이 값 (`YYYY-MM-DD`) |
| `drawing_file_name` | TIF 파일명 |
| `numericFromDR` | OCR로 추출한 참조번호 리스트 (JSON) |
| `elementsFromDR` | `numericFromDR`과 `elementsFromDD` key 매칭 결과 딕셔너리 (JSON) |
| `chunkFromElementDR` | `elementsFromDR` value 기반 정렬된 고유 name 쉼표 구분 문자열 |

## Architecture

### Data Flow

```
PTGRDT/*.tar (USPTO weekly archives)
    │
    ├─[방법 A]─ 01_pipeline_zip_data.py ──→ USPTO_zip_data.db (table: USPTO_zip_data)
    │                                                   │
    │                                      02_target_selection.py
    │                                                   │
    │                                    ┌──────────────┴─────────────┐
    │                              USPTO_LGD table          US_patent_images/LGD/
    │
    └─[방법 B]─ 91_extract_data.py ───→ {dbName}.db (table: {aka}_patent)
                (90_args.txt 설정)                        │
                                         ┌────────────────┴────────────────┐
                                   {aka}_patent table        {imageFolder}/{aka}/
                                         │
                   ┌─────────────────────┴──────────────────────┐
              [방법 A]                                       [방법 B]
         03_element_parser*.py                        92_parse_element.py
    (USPTO_LGD.elementsFromDD,                  ({aka}_patent.elementsFromDD,
      chunkFromElement)                            chunkFromElementDD)
                 │                                           │
         04_build_index.py                        93_ocr_drawing.py
    (index/ ← USPTO_LGD 기반)              ({aka}_drawing 테이블 생성,
                 │                           numericFromDR, elementsFromDR,
                 │                           chunkFromElementDR)
                 │                                           │
                 │                               94_build_index.py
                 │                      (index_{aka}/ ← {aka}_patent + {aka}_drawing)
                 │                                           │
          05_multimodal_retriever.py            95_retrieve_patent.py (FastAPI)
          (index/ · US_patent_images/)          (index_{aka}/ · {imageFolder}/{aka}/)
                 │                                           │
          06_index.html (UI)                      96_index.html (UI)
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
  - `POST /search` — claim + element + image multimodal search. On arrival, both `query_claim` and `query_element` are filtered through `SKIP_WORDS` (same word list as `03_element_parser_pos.py`) to strip stop words before embedding. `query_element` is additionally sorted alphabetically (case-insensitive) by comma-separated term. When 2+ query types are active, computes **RRF (Reciprocal Rank Fusion, k=60)** scores and a `hit_count` (how many of K1/K2/K3 indices contained the patent) per patent; returns a deduplicated combined ranking (one entry per patent number, highest individual score kept as representative). Single-query mode sorts by cosine similarity with `hit_count=1`.
  - `GET /api/images/{filename}` — TIF→PNG conversion on the fly.
  - `POST /api/preview` — server-side image conversion for browser upload preview.
  - `POST /export` — Excel export with embedded K2 images, **yellow keyword highlighting** in K1/K3 claim/element text cells (`write_rich_string`), and RRF scores in the overall sheet. Filename format: `Retrieval_YYYY_MM_DDThh_mm_ss_USPTO_LGD.xlsx`.
- **`06_index.html`** — Self-contained vanilla JS frontend (no build step). Talks to the backend via `fetch`. Results rendered in 3 colour-coded columns: red (K1 claims), green (K3 elements), blue (K2 images). Tooltips for K1/K3 highlight words matching the query input in yellow. Combined ranking shows bare patent numbers (no type suffix), with `N | RRF:x.xxxx | yy.y%` score when RRF is active (N = number of K1/K2/K3 indices that contributed to the RRF score for that patent). On search, the element textarea is sorted alphabetically by comma-separated terms and updated in place so the user sees the normalized input.

### CLIP Text Limit

CLIP's text encoder is hard-capped at **77 tokens**. Long claims are silently truncated. `max_length=77` is set explicitly in all encoding calls.

## Database Schema

`USPTO_zip_data` / `USPTO_LGD` columns (all TEXT):

`patentNumber`, `grantDate`, `applicationType`, `applicationNumber`, `applicationDate`, `ptaDays`, `cpcMain`, `cpcFurther`, `numberOfClaims`, `exemplaryClaim`, `inventionTitle`, `cpcSearched`, `numberOfFigures`, `applicantName`, `applicantCountry`, `assigneeName`, `examinerDepartment`, `abstract`, `briefSummary`, `detailedDescription`, `briefSummaryBackground`, `briefSummarySummary`, `allClaims`, `rep_ind_Claim`

Columns added by step 3: `elementsFromDD` (JSON dict of ref→name), `chunkFromElement` (JSON list of unique names).

## Environment

The project uses a local venv (`pyvenv.cfg` in the project root). Key packages from `requirements.txt`: `fastapi`, `uvicorn`, `transformers`, `torch`, `faiss-cpu`, `pillow`, `lxml`, `pandas`, `xlsxwriter`, `openpyxl`, `nltk`, `pytesseract`.

`93_ocr_drawing.py`는 추가로 시스템에 Tesseract OCR 엔진이 설치되어 있어야 합니다:
```bash
sudo apt install tesseract-ocr   # Ubuntu/WSL
pip install pytesseract
```

Python version: 3.13 (conda base) or the local venv. The venv is activated automatically when running scripts from this directory.
