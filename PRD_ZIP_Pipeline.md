# PRD: USPTO ZIP Data Extraction & Processing Pipeline

## 1. Project Overview
This sub-project aims to build a robust pipeline to process bulk patent data archives from the USPTO. The system will traverse a large TAR file, extract data from nested ZIP archives, and store structured patent information in an SQLite database. Additionally, it will manage and rename patent drawings (TIF files) based on figure references found within the patent XML.

## 2. Input Data Specifications
- **Main Archive**: `PTGRDT/I20260519.tar` (~4.2GB)
- **Archive Structure**:
  - Root: `20260519/`
  - Target Folders: `UTIL*` (Utility Patents)
  - Content: Individual ZIP files (one per patent), each containing:
    - 1 XML file (Bibliographic + Full Text)
    - Multiple TIF files (Drawings)

## 3. Functional Requirements

### 3.1 Archive Traversal
- Navigate through the TAR file without full extraction to disk.
- Identify and iterate through ZIP files located in `20260519/UTIL*`.
- Provide real-time progress monitoring using `tqdm` for both TAR and internal ZIP files.

### 3.2 Metadata Extraction & Storage
Extract the following fields and store them in `USPTO_zip_data.db`:

#### Bibliographic Fields:
- **patentNumber**: Patent number (Doc Number).
- **grantDate**: Converted to `YYYY-MM-DD`.
- **applicationType**: Attribute `appl-type`.
- **applicationNumber**: Application Doc Number.
- **applicationDate**: Converted to `YYYY-MM-DD`.
- **ptaDays**: Patent Term Adjustment extension days.
- **cpcMain**: Combined section, class, subclass, group/subgroup.
- **cpcFurther**: List of additional CPC classifications.
- **numberOfClaims**: Total claim count.
- **exemplaryClaim**: Index of the representative claim.
- **inventionTitle**: Title of the patent.
- **cpcSearched**: List of searched CPC classifications.
- **numberOfFigures**: Total drawing count.
- **applicantName / applicantCountry**: Organization name and country.
- **assigneeName**: Assignee organization name.
- **examinerDepartment**: Primary examiner's department.

#### Full-Text Fields:
- **abstract**: Full text of the abstract.
- **allClaims**: Complete text of all claims.
- **rep_ind_Claim**: Text of the specific claim indicated by `exemplaryClaim` (fallback to Claim 1).
- **detailedDescription**: Text between `<?DETDESC ... end="lead"?>` and `end="tail"?>`.
- **briefSummary**: Text between `<?BRFSUM ... end="lead"?>` and `end="tail"?>`.
  - **briefSummaryBackground**: Subset of summary where heading is "BACKGROUND".
  - **briefSummarySummary**: Subset of summary where heading is "SUMMARY".

### 3.3 Figure Name Parsing & Validation
- **Action**: Parse XML for `FIG. <b>` tags to extract figure IDs (e.g., "1", "2a", "2b").
- **Processing**: Remove duplicates and sort IDs in ascending order.
- **Validation**: Ensure the count of extracted figure names matches `numberOfFigures`.
- **Storage**: Store the list of figure names in a new field `nameOfFigures`.

### 3.4 Image Management (TIF Processing)
- **Target Directory**: `US_patent_images/`
- **Naming Logic**:
  - **First TIF**: Keep original filename (e.g., `...D00000.TIF`).
  - **Subsequent TIFs**: Rename `...D0000[N].TIF` using the parsed figure names.
  - **Example**: `fig_names = ["1", "2a", "2b"]` results in:
    - `...D00001.TIF`
    - `...D0002a.TIF`
    - `...D0002b.TIF`

## 4. Technical Stack
- **Language**: Python 3.14
- **Libraries**:
  - `tarfile`, `zipfile`: Archive handling.
  - `lxml`: High-performance XML parsing (XPath support).
  - `sqlite3`: Database management.
  - `tqdm`: Progress visualization.
  - `re`: Section extraction and cleanup.

## 5. Performance & Constraints
- **Streaming**: Must process archives in a stream-like fashion to avoid 4GB+ memory spikes.
- **Error Handling**: Graceful skipping of malformed ZIPs or XMLs with logging.
- **Data Integrity**: Commit to DB in batches to ensure performance.
