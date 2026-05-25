# PRD: 특허문헌 멀티모달 검색기 (Patent Multimodal Retriever)

---

## 1. 프로젝트 개요

| 항목 | 내용 |
|------|------|
| 프로젝트명 | Patent Multimodal Retriever |
| 목적 | 텍스트(청구항) 또는 이미지(도면)를 입력받아 사전 구축된 특허 벡터DB에서 유사 특허를 검색·제시 |
| 대상 사용자 | 특허 조사 담당자, R&D 엔지니어 |
| 플랫폼 | 단일 HTML 웹 페이지 + Python 백엔드 API |

---

## 2. 기술 스택 제안

### 2-1. 멀티모달 임베딩 모델

| 후보 | 특징 | 권장 여부 |
|------|------|-----------|
| **CLIP (OpenAI, ViT-L/14)** | 텍스트·이미지 동일 임베딩 공간, 오픈소스, 경량 | ★ 1순위 |
| **OpenCLIP (LAION-2B 학습)** | CLIP 대비 성능 향상, 다양한 백본 선택 가능 | ★ 1순위 대안 |
| **PatentCLIP** | 특허 도메인 특화 CLIP 파인튜닝 모델 (존재 시) | 도메인 적합성 높음 |
| **E5-Mistral / BGE-M3** | 텍스트 전용 고성능 임베딩 (텍스트DB 보완용) | 텍스트DB 보완 시 사용 |

**최종 권장:** `openai/clip-vit-large-patch14` (HuggingFace)
- 텍스트 임베딩과 이미지 임베딩이 **동일한 768차원 잠재공간**에 매핑됨
- 별도 변환 없이 VectorDB1·VectorDB2를 같은 인덱스 구조로 유지 가능
- `transformers` 라이브러리로 로컬 추론 가능

### 2-2. 벡터 데이터베이스

| 후보 | 특징 | 권장 여부 |
|------|------|-----------|
| **FAISS (Meta)** | 로컬, 고속, 의존성 없음 | ★ 1순위 |
| **ChromaDB** | 로컬 or 서버, REST API 내장, 메타데이터 필터 용이 | ★ 2순위 |
| **Qdrant** | 도커 기반, 운영 환경 확장성 우수 | 운영 단계 고려 |

**최종 권장:** `FAISS` (프로토타입) → `ChromaDB` (메타데이터 연동 필요 시)
- VectorDB1 (청구항 텍스트): FAISS `IndexFlatIP` (내적=코사인 유사도, L2 정규화 후)
- VectorDB2 (도면 이미지): 동일 구조

### 2-3. 백엔드 / 프론트엔드

| 구성 요소 | 기술 |
|-----------|------|
| API 서버 | Python + **FastAPI** |
| 프론트엔드 | 단일 `index.html` (Vanilla JS + Fetch API) |
| 이미지 전송 | multipart/form-data |
| 의존성 관리 | `C:/PJT_OFC_PTO` 가상환경 |

---

## 3. 시스템 아키텍처

```
[index.html]
    │ ① 이미지 업로드 (multipart)     ② 텍스트 입력 (JSON)
    ▼
[FastAPI 서버]
    ├── POST /search/image  →  CLIP image encoder  →  query vector
    └── POST /search/text   →  CLIP text encoder   →  query vector
              │                              │
              ▼                              ▼
        [VectorDB2]                    [VectorDB1]
    FAISS (도면 임베딩)            FAISS (청구항 임베딩)
              │                              │
              └──────── Top-K2 결과 ─────────┘
                        Top-K1 결과
                        K1+K2 통합 결과 (유사도 재정렬)
    ▼
[index.html] 결과 렌더링 (3개 컬럼)
```

---

## 4. 데이터 파이프라인 (오프라인 인덱싱)

```
특허 원문 (XML / PDF)
    │
    ├── 텍스트 추출 (독립항 1항)
    │       └── CLIP text encoder → 768-dim vector → FAISS DB1 저장
    │           메타데이터: {출원번호, 발명명칭, 출원인, 청구항 원문}
    │
    └── 도면 추출 (개별 이미지 파일)
            └── CLIP image encoder → 768-dim vector → FAISS DB2 저장
                메타데이터: {출원번호, 도면번호, 도면 파일명}
```

---

## 5. 단계별 구현 계획

---

### Phase 0: 환경 세팅 및 데이터 준비 (사전 작업)

**목표:** 개발 환경 구성 + 샘플 특허 데이터 확보

**태스크:**
- [ ] `/home/jsbaac/LGAI_EXP` venv에 의존성 설치
  ```
  pip install fastapi uvicorn python-multipart
  pip install transformers torch pillow faiss-cpu
  pip install numpy tqdm
  ```
- [ ] 샘플 특허 데이터 수집 (USPTO ODP API 활용 — 기존 `OFC_PJT` 재사용 가능)
  - 최소 100건 이상 특허 확보
  - 청구항 텍스트 → `claims.jsonl` (출원번호, 독립항1항 텍스트)
  - 도면 이미지 → `figures/` 디렉토리 (출원번호_도면번호.png)
- [ ] 프로젝트 디렉토리 구조 생성
  ```
  /home/jsbaac/LGAI_EXP/patent_retriever/
  ├── data/
  │   ├── claims.jsonl
  │   └── figures/
  ├── index/
  │   ├── db1_claims.faiss
  │   ├── db1_meta.json
  │   ├── db2_figures.faiss
  │   └── db2_meta.json
  ├── build_index.py
  ├── server.py
  └── static/
      └── index.html
  ```

**완료 기준:** 샘플 데이터 100건 이상 준비, venv 의존성 설치 완료

---

### Phase 1: 인덱싱 파이프라인 구축 (`build_index.py`)

**목표:** CLIP 모델로 텍스트·이미지를 임베딩하여 FAISS 인덱스 생성

**태스크:**
- [ ] CLIP 모델 로드 (`CLIPModel`, `CLIPProcessor` from HuggingFace)
- [ ] 텍스트 임베딩 배치 처리 (청구항 → 벡터 → L2 정규화)
- [ ] 이미지 임베딩 배치 처리 (도면 파일 → 벡터 → L2 정규화)
- [ ] FAISS `IndexFlatIP` 생성 및 벡터 추가
- [ ] 메타데이터 JSON 저장 (인덱스 ID ↔ 출원번호 매핑)
- [ ] 인덱스 파일 디스크 저장 (`.faiss`, `.json`)

**핵심 구현:**
```python
# 텍스트 임베딩 예시
inputs = processor(text=claims_batch, return_tensors="pt", padding=True, truncation=True)
text_features = model.get_text_features(**inputs)
text_features = text_features / text_features.norm(dim=-1, keepdim=True)  # L2 정규화

# 이미지 임베딩 예시
inputs = processor(images=images_batch, return_tensors="pt")
image_features = model.get_image_features(**inputs)
image_features = image_features / image_features.norm(dim=-1, keepdim=True)
```

**완료 기준:** `db1_claims.faiss`, `db2_figures.faiss` 생성 및 유사도 검색 단위 테스트 통과

---

### Phase 2: 검색 API 서버 구축 (`server.py`)

**목표:** FastAPI로 텍스트/이미지 쿼리를 받아 Top-K 결과 반환

**태스크:**
- [ ] FastAPI 앱 초기화, FAISS 인덱스 + 메타데이터 서버 시작 시 로드
- [ ] `POST /search/text` 엔드포인트
  - 입력: `{ "query": "...", "k1": 5 }`
  - 처리: CLIP text encode → FAISS DB1 검색
  - 출력: `[{ "rank": 1, "score": 0.92, "app_no": "US123", "claim": "...", ... }]`
- [ ] `POST /search/image` 엔드포인트
  - 입력: `multipart/form-data` (이미지 파일, k2 파라미터)
  - 처리: CLIP image encode → FAISS DB2 검색
  - 출력: `[{ "rank": 1, "score": 0.88, "app_no": "US456", "fig_no": "FIG.1", ... }]`
- [ ] K1+K2 통합 정렬 로직: 양쪽 결과 병합 후 `score` 내림차순 정렬, 중복 출원번호 처리(최고 점수 유지)
- [ ] `GET /` → `static/index.html` 서빙
- [ ] CORS 설정 (개발 중 `*` 허용)

**완료 기준:** `curl` 또는 Postman으로 두 엔드포인트 정상 응답 확인

---

### Phase 3: 프론트엔드 구현 (`static/index.html`)

**목표:** 화면 개요에 맞는 단일 페이지 UI 구현

**레이아웃 (화면 개요 기준):**
```
┌─────────────────────────────────────────────────────┐
│  Patent Multimodal Retriever                        │
├─────────────────────────────────────────────────────┤
│  [Input docs type]                                  │
│    image │ [파일 선택 버튼]  K2: [5▼]               │
│    text  │ [텍스트 입력창]   K1: [5▼]               │
│                        [검색] 버튼                  │
├──────────────┬──────────────┬───────────────────────┤
│  K1 list     │  K2 list     │  K1&K2 list           │
│  (청구항유사) │  (도면유사)  │  (통합, 재정렬)       │
│  1. US123    │  1. US456    │  1. US123 (0.92)      │
│     score:   │     score:   │  2. US456 (0.88)      │
│     0.92     │     0.88     │  ...                  │
└──────────────┴──────────────┴───────────────────────┘
```

**태스크:**
- [ ] 이미지 업로드 UI: `<input type="file">` + 미리보기
- [ ] 텍스트 입력 UI: `<textarea>` + K1/K2 개수 선택 드롭다운
- [ ] 검색 버튼: 이미지·텍스트 중 입력된 항목만 API 호출 (둘 다 가능)
- [ ] 결과 3컬럼 렌더링:
  - K1 리스트: 출원번호, 발명명칭, 청구항 요약, 유사도 점수
  - K2 리스트: 출원번호, 도면번호, 도면 썸네일(있을 경우), 유사도 점수
  - K1&K2 통합: 출처(텍스트/이미지) 태그 포함, 유사도 내림차순
- [ ] 로딩 스피너 (API 응답 대기 중)
- [ ] 에러 메시지 표시

**완료 기준:** 브라우저에서 이미지 업로드 + 텍스트 입력 후 3컬럼 결과 정상 렌더링

---

### Phase 4: 통합 테스트 및 평가

**목표:** 검색 품질 및 시스템 안정성 검증

**태스크:**
- [ ] 텍스트 쿼리 → K1 결과 유사도 순서 적절성 확인 (수동 평가)
- [ ] 이미지 쿼리 → K2 결과 유사도 순서 적절성 확인 (수동 평가)
- [ ] 동일 특허의 청구항과 도면을 쿼리했을 때 K1&K2 통합 결과에서 해당 특허가 상위 랭크되는지 확인 (cross-modal 일치 검증)
- [ ] 대용량 인덱스 대응: FAISS `IndexIVFFlat` (1만 건 이상) 또는 `IndexHNSWFlat` 전환 검토
- [ ] K1, K2 파라미터 범위 조정 (기본값: K1=5, K2=5, 최대 20)

**완료 기준:** 수동 평가 10건 중 8건 이상 Top-5 내 정답 포함

---

### Phase 5 (선택): 고도화

**목표:** 검색 품질 및 UX 개선

- [ ] **Re-ranking:** K1, K2 결과를 LLM(Claude API)으로 쿼리 관련성 재정렬
- [ ] **특허 도메인 파인튜닝:** 특허 청구항-도면 쌍으로 CLIP 파인튜닝 (Contrastive Loss)
- [ ] **필터링:** CPC 분류코드, 출원연도, 출원인 기반 필터 추가
- [ ] **결과 상세보기:** 클릭 시 해당 특허 전체 정보 팝업 (USPTO ODP 연동)
- [ ] **ChromaDB 전환:** 메타데이터 필터 쿼리 지원

---

## 6. 파일/디렉토리 구조 (최종)

```
/home/jsbaac/LGAI_EXP/patent_retriever/
├── build_index.py          # Phase 1: 오프라인 인덱싱 스크립트
├── server.py               # Phase 2: FastAPI 서버
├── static/
│   └── index.html          # Phase 3: 프론트엔드
├── data/
│   ├── claims.jsonl        # {app_no, title, claim1} 형식
│   └── figures/            # {app_no}_{fig_no}.png
├── index/
│   ├── db1_claims.faiss
│   ├── db1_meta.json       # [{id, app_no, title, claim1}, ...]
│   ├── db2_figures.faiss
│   └── db2_meta.json       # [{id, app_no, fig_no, filename}, ...]
└── requirements.txt
```

---

## 7. 주요 파라미터 정의

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `K1` | 5 | 텍스트 쿼리 반환 건수 |
| `K2` | 5 | 이미지 쿼리 반환 건수 |
| CLIP 모델 | `openai/clip-vit-large-patch14` | 임베딩 모델 |
| 임베딩 차원 | 768 | FAISS 인덱스 차원 |
| 유사도 척도 | 코사인 유사도 (= 정규화 후 내적) | FAISS `IndexFlatIP` |
| 최대 텍스트 길이 | 77 토큰 (CLIP 제한) | 청구항 truncation 주의 |

> **주의:** CLIP의 텍스트 인코더는 77 토큰으로 제한됩니다. 독립항 1항이 길 경우 앞부분 77토큰만 사용하거나, Longformer 기반 텍스트 인코더 교체를 Phase 5에서 검토하세요.

---

## 8. 단계별 의존성 및 순서

```
Phase 0 (데이터·환경)
    └→ Phase 1 (인덱싱)
            └→ Phase 2 (API 서버)
                    ├→ Phase 3 (프론트엔드)   ← Phase 2와 병렬 가능
                    └→ Phase 4 (통합 테스트)
                                └→ Phase 5 (선택 고도화)
```
