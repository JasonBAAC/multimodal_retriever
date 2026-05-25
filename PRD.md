# PRD: USPTO Patent Data Collection & Processing System

## 1. Project Overview
This project aims to build an automated pipeline to search, collect, and store patent data from the USPTO Open Data Portal (ODP) API. The system will store structured metadata in an SQLite database and download high-resolution images/drawings associated with the patents to a local directory.

## 2. Target API
- **Source:** [USPTO Patent File Wrapper API](https://data.uspto.gov/apis/patent-file-wrapper/search)
- **Endpoint:** `POST https://developer.uspto.gov/ds-api/patent/v1/search` (Note: Actual endpoint to be verified against documentation)
- **Format:** JSON response for metadata, XML for full-text content, Image files (TIFF/PDF/JPG) for drawings.

## 3. Requirements & Workflows

### Phase 1: Population Selection (Search)
- **Action:** Execute a POST request to define the collection scope.
- **Query Parameters:**
  - `applicationTypeLabelName`: Utility
  - `applicationStatusDescriptionText`: Patented Case
  - `applicantNameText`: LG Display
  - `grantDate Range`: 2026-01-01 to 2026-01-31
  - `Sort`: `filingDate` (DESC)
- **Target Fields:** All metadata fields specified in the search query (Application Number, Publication Dates, CPC Classifications, Patent Number, File Location URIs, etc.).

### Phase 2: Metadata Storage (SQLite)
- **Database Name:** `USPTO_data.db`
- **Initial Table Schema:**
  - `applicationNumberText` (PK)
  - `publicationDateBag`
  - `publicationCategoryBag`
  - `applicationStatusDate`
  - `filingDate`
  - `effectiveFilingDate`
  - `grantDate`
  - `groupArtUnitNumber`
  - `inventionTitle`
  - `patentNumber`
  - `applicationStatusCode`
  - `cpcClassificationBag`
  - `applicantNameText`
  - `assignmentRecordedDate`
  - `assigneeNameText`
  - `fileLocationURI`
  - `xmlFileName`

### Phase 3: Full-Text Acquisition & Parsing
- **Action:** Iterate through stored `fileLocationURI` links to download XML files.
- **Parsing Goal:** Extract large text blocks including:
  - Claims (특허청구범위)
  - Background (종래기술)
  - Detailed Description (발명의 상세한 설명)
  - Abstract (요약)
- **Database Update:** Add these text fields to the existing `USPTO_data` table or a related `FullText` table.

### Phase 4: Image Collection
- **Action:** Identify image references within the downloaded XML files.
- **Storage Path:** `./US_patent_images/`
- **Naming Convention:** `[PatentNumber]_[ImageID].[ext]`
- **Goal:** Download all drawings and diagrams linked to the patent.

## 4. Technical Stack
- **Language:** Python 3.14
- **Database:** SQLite
- **Libraries:**
  - `requests`: API interaction.
  - `sqlite3`: Database management.
  - `lxml` or `xml.etree.ElementTree`: XML parsing.
  - `os`/`pathlib`: File and directory management.

## 5. Success Metrics
- Successful connection and data retrieval from USPTO API.
- Complete population of SQLite database with all requested metadata and full-text fields.
- 100% download rate for images referenced in the processed XML files.
- Efficient handling of large XML files (like the ~900MB sample identified in research).

## 6. Constraints & Considerations
- **API Rate Limiting:** Must implement respect for USPTO API quotas.
- **Data Volume:** Large XML files require streaming or chunked parsing to avoid memory exhaustion.
- **Error Handling:** Robust handling for broken `fileLocationURI` links or malformed XML.
