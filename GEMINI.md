# Project: PJT_OFC_PTO (USPTO Patent Data Pipeline & Retriever)

## Project Overview
`PJT_OFC_PTO` is a comprehensive system designed to collect, filter, and refine patent data from the USPTO, and provide a state-of-the-art multimodal search engine for patent analysis.

---

## 1. Pipelines & Tools

### API & ZIP Pipelines
- **API (`01_pipeline_api_data.py`)**: Real-time LG Display patent collection.
- **TAR/ZIP (`01_pipeline_zip_data.py`)**: Bulk archive processing. Supports both `.tar` and `.zip` top-level archives in `PTGRDT/`. CLI args:
  - `--grantDate YYYYMMDD`: process a single archive matching the date string (default: all files)
  - `--image_extract y/n`: toggle TIF extraction to `US_patent_images/` (default: `y`)

### Refinement Tools
- **Target Selection (`02_target_selection.py`)**: Isolates LG Display data into `USPTO_LGD`.
- **Element Parser (`03_element_parser.py`)**: Extracts components and reference characters from descriptions.
- **Element Parser POS (`03_element_parser_pos.py`)**: Advanced component extraction using NLTK POS tagging for higher precision.

---

## 2. Multimodal Retriever (`05_multimodal_retriever.py`)

### Key Features
- **Unified Embedding**: Uses `openai/clip-vit-large-patch14` to map text and images to a shared 768-dim latent space.
- **Triple Indexing (FAISS)**:
    1.  **K1 (Claims)**: Search by representative claims.
    2.  **K2 (Images)**: Search by visual similarity in drawings.
    3.  **K3 (Elements)**: Search by technical component names.
- **3-Way Search**: Supports independent or simultaneous searching by Claim, Element, and Drawing.
- **Web UI (`06_index.html`)**: A Google-style single-page application featuring:
    - **2x2 Input Grid**: Optimized layout with Claim (Top-Left), Element (Bottom-Left), and Drawing (Right-Full).
    - **Reset Functionality**: One-click "초기화" button to clear all inputs and results.
    - **Similarity Scores**: Displayed as percentages with 1-decimal precision (e.g., 95.4%).
    - **Interactive Tooltips**: Text content for K1/K3, live high-quality image previews for K2.
    - **Excel Export**: Generate multi-tab reports with original-quality images in the K2 tab and adjusted row heights.
    - **Color Coding**: Red (Claims), Green (Elements), Blue (Images).

---

## 3. Utilities

- **POS Tagging (`99_text.ipynb`)**: Jupyter notebook for automated English Part-of-Speech tagging using NLTK.

---

## Environment Setup
- **Python 3.14**
- **Dependencies**: `pip install fastapi uvicorn transformers torch pillow faiss-cpu requests python-dotenv lxml tqdm pandas xlsxwriter openpyxl nltk`
- **Activation**: `.\Scripts\activate` (Windows)

## File Structure
- `01_pipeline_api_data.py` / `01_pipeline_zip_data.py`: Ingestion scripts.
- `02_target_selection.py`: Data isolation tool.
- `03_element_parser.py`: Component extraction tool.
- `04_build_index.py`: Indexing pipeline.
- `05_multimodal_retriever.py`: Search backend API.
- `06_index.html`: Frontend UI (Google Style).
- `99_text.ipynb`: NLP utility notebook.
- `index/`: Vector indices and metadata.
- `USPTO_zip_data.db`: Source database (Target table: `USPTO_LGD`).
- `US_patent_images/LGD/`: Isolated patent drawings.
- `PRD_retriever.md`: Multimodal system requirements.
