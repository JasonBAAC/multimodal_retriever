# PRD: 특허문헌 멀티모달 검색기 (Patent Multimodal Retriever)

---

## 1. 프로젝트 개요

| 항목 | 내용 |
|------|------|
| 프로젝트명 | Patent Multimodal Retriever (`multimodal_retriever.py`) |
| 목적 | 텍스트(User 입력, 청구항, 엘리먼트) 또는 이미지(도면)를 입력받아 사전 구축된 3개의 특허 벡터DB에서 유사 특허를 검색하여 통합 제시 |
| 대상 사용자 | 특허 조사 담당자, R&D 엔지니어 |
| 플랫폼 | 단일 HTML 웹 페이지 + Python 백엔드 (FastAPI 권장) |
| 소스 데이터 | `USPTO_zip_data.db`의 `USPTO_LGD` 테이블, `US_patent_images/LGD/` 폴더 |

---

## 2. 시스템 아키텍처 및 기술 스택

### 2-1. 임베딩 모델
- **모델**: `openai/clip-vit-large-patch14` (HuggingFace) 또는 호환되는 멀티모달 모델.
- **특징**: 텍스트와 이미지를 동일한 차원의 잠재 공간(Latent Space)으로 임베딩하여 교차 검색(Cross-modal Retrieval) 지원. GPU 사용 가능 시 자동 할당.

### 2-2. 벡터 데이터베이스 (FAISS)
3개의 개별 FAISS 인덱스(`IndexFlatIP` - 코사인 유사도)를 구축합니다.
- **VectorDB1 (청구항)**:
  - **소스**: `USPTO_LGD` 테이블의 `rep_ind_Claim` 필드.
  - **ID 매핑**: `patentNumber`
- **VectorDB2 (도면)**:
  - **소스**: `US_patent_images/LGD/` 폴더 내의 TIF/PNG 이미지 파일.
  - **ID 매핑**: 이미지 파일명.
- **VectorDB3 (엘리먼트)**:
  - **소스**: `USPTO_LGD` 테이블의 `chunkFromElement` 필드 (JSON 리스트 내의 각 단어/구문들을 합치거나 개별 임베딩 후 특허 단위로 집계).
  - **ID 매핑**: `patentNumber`

### 2-3. 백엔드 / 프론트엔드
- **백엔드**: Python, FastAPI, `faiss-cpu` (또는 `faiss-gpu`), `transformers`, `torch`, `Pillow`.
- **프론트엔드**: 단일 `06_index.html` (Vanilla JS + Fetch API), Bootstrap/Tailwind (선택적).

---

## 3. UI/UX 요구사항 (웹 페이지)

### 3-1. 상단 (입력부)
화면 개요도에 따라 두 가지 입력 방식을 지원합니다. (mixed 입력은 제외)
- **Image Input**: 파일 업로드 창 제공.
- **Text Input**: 텍스트 입력 창 제공. (내부적으로 User 입력, Claim 입력, Element 입력으로 취급되나 UI상 단일 창으로 통합 검색)
- **공통**: 검색 진행 상황을 나타내는 프로그레스 바(백엔드의 `tqdm` 진행률을 프론트로 전달하거나, 프론트에서 로딩 스피너 처리) 제공.

### 3-2. 하단 (출력부 - 4개 컬럼)
검색 결과는 4개의 리스트로 나란히 표시되며, 각 K 변수(10개)만큼 유사도 내림차순으로 정렬됩니다. **유사도는 퍼센트 단위(예: 92.3%)로 표시됩니다.**

| 컬럼 | 출처 | 텍스트 색상 | 리스트 표시 항목 | 마우스 오버 툴팁(풍선) |
|---|---|---|---|---|
| **K1 List** | VectorDB1 (청구항) | <span style="color:red">**적색 (Red)**</span> | `patentNumber` + 유사도(%) | 해당 특허의 `rep_ind_Claim` 텍스트 |
| **K3 List** | VectorDB3 (엘리먼트) | <span style="color:green">**초록색 (Green)**</span> | `patentNumber` + 유사도(%) | 해당 특허의 `chunkFromElement` 텍스트 |
| **K2 List** | VectorDB2 (도면) | <span style="color:blue">**파란색 (Blue)**</span> | 파일명 + 유사도(%) | 해당 이미지 썸네일 미리보기 |
| **K1-K3 List** | DB1, DB2, DB3 통합 | 각 출처 색상 유지 | `display_id` + 유사도(%) | (출처에 따른 툴팁) |

### 3-3. 엑셀 내보내기 (Excel Export)
- **기능**: 검색 결과를 엑셀 파일로 저장하는 버튼 제공.
- **파일명**: `Retrieval_YYYY_MM_DD HH_MM_SS_USPTO_LGD.xlsx`
- **시트 구성**:
    - `overall`: 입력값(텍스트/이미지) 및 통합 결과 리스트.
    - `K1`: `patentNumber`, `rep_ind_Claim` 상세.
    - `K3`: `patentNumber`, `chunkFromElement` 상세.
    - `K2`: `EpatentNumber`, `파일명`, `이미지` 경로 정보.

#### 통합 리스트 (K1-K3 List) 상세 규칙
- 3개 DB의 검색 결과를 하나의 리스트로 병합하고 유사도 내림차순으로 재정렬합니다.
- 리스트 아이템 뒤에 출처를 나타내는 첨자를 추가합니다:
  - K1 (청구항) 출처: `-c` (적색)
  | K2 (도면) 출처: `-d` (파란색)
  | K3 (엘리먼트) 출처: `-e` (초록색)
- **EpatentNumber 추출**: K2(도면) 결과의 파일명(예: `US12628718-20260519-D00000.TIF`)에서 `US`와 첫 번째 `-` 사이의 값(`12628718`)을 추출하여 통합 리스트에 표시합니다.

---

## 4. 단계별 구현 계획

### Phase 1: 임베딩 및 인덱싱 파이프라인 (`build_index.py`)
1.  **환경 설정**: GPU 가용성 확인(`torch.cuda.is_available()`) 및 CLIP 모델 로드.
2.  **데이터 로드**: SQLite DB(`USPTO_LGD`) 및 로컬 이미지 폴더(`US_patent_images/LGD`) 연결.
3.  **임베딩 생성 (with `tqdm`)**:
    - DB1: `rep_ind_Claim` 텍스트 임베딩.
    - DB2: 도면 이미지 파일 로드 및 임베딩.
    - DB3: `chunkFromElement` 텍스트 임베딩.
4.  **FAISS 저장**: `db1_claims.index`, `db2_images.index`, `db3_elements.index` 및 각각의 메타데이터 매핑 파일(`.json`) 저장.

### Phase 2: 검색 API 백엔드 (`multimodal_retriever.py`)
1.  **서버 세팅**: FastAPI 앱 생성, 서버 시작 시 FAISS 인덱스 및 CLIP 모델 메모리 로드.
2.  **검색 로직 구현**:
    - 입력받은 텍스트/이미지를 CLIP 임베딩으로 변환.
    - 각 FAISS 인덱스에서 `Search(query_vector, K=10)` 수행.
3.  **통합 로직 구현**: K1, K2, K3 결과를 병합, 유사도 재정렬, EpatentNumber 추출 및 첨자(`-c`, `-d`, `-e`) 할당.
4.  **API 엔드포인트**: `/search` (multipart/form-data 및 JSON 지원).

### Phase 3: 프론트엔드 UI (`06_index.html`)
1.  **레이아웃 구성**: 상단 입력부(파일 업로드, 텍스트 입력창, 검색 버튼), 하단 4컬럼 출력부.
2.  **스타일링**: K1(Red), K3(Green), K2(Blue) 색상 규칙 적용.
3.  **인터랙션**: JavaScript Fetch API를 통한 백엔드 통신, 툴팁(Tooltip) 구현(텍스트 및 이미지 팝업).

### Phase 4: 테스트 및 최적화
1.  이미지 및 텍스트 쿼리에 대한 교차 검색 정확도 테스트.
2.  메모리 사용량 및 응답 속도 최적화.
