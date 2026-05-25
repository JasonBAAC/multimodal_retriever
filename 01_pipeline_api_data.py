import sqlite3
import xml.etree.ElementTree as ET
import json
import os
import io
import re
import requests
import time
from dotenv import load_dotenv

# Load .env file
load_dotenv()

DB_NAME = "USPTO_api_data.db"
IMAGE_DIR = os.path.join("US_patent_images", "LGD")
API_KEY = os.getenv("USPTO_API_KEY")
SEARCH_URL = "https://api.uspto.gov/api/v1/patent/applications/search"

# Fields requested for the DB
DB_FIELDS = [
    "applicationNumber", "publicationDate", "publicationCategory", "applicationStatusDate",
    "filingDate", "effectiveFilingDate", "grantDate", "groupArtUnit", "inventionTitle",
    "patentNumber", "applicationStatus", "cpcClassification", "applicantName",
    "assignmentDate", "assigneeName", "fileLocationURI", "xmlFileName", "applicationType",
    "claims_text", "claim_1", "background_text", "detailed_description_text", "abstract_text"
]

MAJOR_SECTIONS = {
    "BACKGROUND": ["BACKGROUND"],
    "SUMMARY": ["SUMMARY", "BRIEF SUMMARY"],
    "DETAILED DESCRIPTION": ["DETAILED DESCRIPTION"]
}

def setup_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    col_str = ", ".join([f"{col} TEXT" for col in DB_FIELDS])
    cursor.execute(f"DROP TABLE IF EXISTS USPTO_data")
    cursor.execute(f"CREATE TABLE USPTO_data ({col_str})")
    conn.commit()
    return conn

def get_major_section_text(desc_elem, section_key):
    text_parts = []
    found_section = False
    start_keywords = MAJOR_SECTIONS[section_key]
    other_keywords = []
    for k, v in MAJOR_SECTIONS.items():
        if k != section_key:
            other_keywords.extend(v)

    for child in desc_elem:
        if child.tag == 'heading':
            heading_text = (child.text or "").upper()
            if any(k in heading_text for k in start_keywords):
                found_section = True
                continue
            if found_section and any(k in heading_text for k in other_keywords):
                break
        elif found_section:
            text = "".join(child.itertext()).strip()
            if text:
                text_parts.append(text)
    return "\n\n".join(text_parts)

def extract_claim_1(full_claims_text):
    if not full_claims_text: return None
    match = re.search(r'(^1\..*?)(?=\n\s*\d+\.|\Z)', full_claims_text, re.DOTALL | re.MULTILINE)
    return match.group(1).strip() if match else None

def fetch_search_results():
    if not API_KEY:
        print("Error: USPTO_API_KEY not found in .env file.")
        return None

    headers = {"X-API-KEY": API_KEY}
    # Using GET with Lucene query as it proved successful in tests
    query_str = (
        'applicationMetaData.applicationTypeLabelName:Utility AND '
        'applicationMetaData.applicationStatusDescriptionText:"Patented Case" AND '
        'applicationMetaData.applicantBag.applicantNameText:"LG Display" AND '
        'applicationMetaData.grantDate:[2026-01-01 TO 2026-01-31]'
    )
    
    params = {
        "q": query_str,
        "limit": 20
    }

    print("Fetching patent metadata from API (GET)...")
    response = requests.get(SEARCH_URL, params=params, headers=headers)
    response.raise_for_status()
    # The response wrapper is 'patentFileWrapperDataBag' based on test results
    return response.json().get('patentFileWrapperDataBag', [])

def process_patent_details(conn, record):
    cursor = conn.cursor()
    headers = {"X-API-KEY": API_KEY}
    
    meta = record.get("applicationMetaData", {})
    doc_meta = record.get("grantDocumentMetaData", {})
    
    data = {f: None for f in DB_FIELDS}
    data["applicationNumber"] = record.get("applicationNumberText")
    data["publicationDate"] = json.dumps(meta.get("publicationDateBag"))
    data["publicationCategory"] = json.dumps(meta.get("publicationCategoryBag"))
    data["applicationStatusDate"] = meta.get("applicationStatusDate")
    data["filingDate"] = meta.get("filingDate")
    data["effectiveFilingDate"] = meta.get("effectiveFilingDate")
    data["grantDate"] = meta.get("grantDate")
    data["groupArtUnit"] = meta.get("groupArtUnitNumber")
    data["inventionTitle"] = meta.get("inventionTitle")
    data["patentNumber"] = meta.get("patentNumber")
    data["applicationStatus"] = meta.get("applicationStatusCode")
    data["cpcClassification"] = json.dumps(meta.get("cpcClassificationBag"))
    
    applicant_bag = meta.get("applicantBag", [])
    data["applicantName"] = json.dumps([a.get("applicantNameText") for a in applicant_bag if isinstance(a, dict)])
    
    assignment_bag = meta.get("assignmentBag", [])
    if assignment_bag:
        data["assignmentDate"] = assignment_bag[0].get("assignmentRecordedDate")
        data["assigneeName"] = assignment_bag[0].get("assigneeNameText")
        
    data["fileLocationURI"] = doc_meta.get("fileLocationURI")
    data["xmlFileName"] = doc_meta.get("xmlFileName")
    data["applicationType"] = meta.get("applicationTypeLabelName")

    # Phase 3 & 4: Download and parse XML
    xml_url = data["fileLocationURI"]
    if xml_url:
        print(f"Downloading XML for {data['patentNumber']}...")
        try:
            xml_resp = requests.get(xml_url, headers=headers)
            xml_resp.raise_for_status()
            
            # Clean and parse XML
            xml_lines = xml_resp.text.splitlines()
            clean_xml = "\n".join([line for line in xml_lines if not (line.strip().startswith('<?xml') or line.strip().startswith('<!DOCTYPE'))])
            root = ET.fromstring(clean_xml)
            
            # Text extraction
            abstract_elem = root.find('.//abstract')
            data["abstract_text"] = "".join(abstract_elem.itertext()).strip() if abstract_elem is not None else None
            
            claims_elem = root.find('.//claims')
            data["claims_text"] = "".join(claims_elem.itertext()).strip() if claims_elem is not None else None
            data["claim_1"] = extract_claim_1(data["claims_text"])
            
            desc_elem = root.find('.//description')
            if desc_elem is not None:
                data["background_text"] = get_major_section_text(desc_elem, "BACKGROUND")
                data["detailed_description_text"] = get_major_section_text(desc_elem, "DETAILED DESCRIPTION")
            
            # Phase 5: Image references
            drawings = root.find('.//drawings')
            if drawings is not None and data["applicationNumber"]:
                app_num = data["applicationNumber"]
                for fig in drawings.findall('.//figure'):
                    fig_num = fig.get('num') or "0"
                    img = fig.find('img')
                    if img is not None:
                        img_file = img.get('file')
                        if img_file:
                            ext = os.path.splitext(img_file)[1]
                            try:
                                clean_fig = "".join(filter(str.isdigit, fig_num))
                                formatted_fig = f"FIG{int(clean_fig):04d}" if clean_fig else f"FIG{fig_num}"
                            except:
                                formatted_fig = f"FIG{fig_num}"
                            
                            filename = f"LGD-US{app_num}-{formatted_fig}{ext}"
                            # Simulated download of image
                            with open(os.path.join(IMAGE_DIR, filename), 'w') as f:
                                f.write(f"Image Placeholder for {img_file}")
                                
        except Exception as e:
            print(f"Error processing details for {data['patentNumber']}: {e}")

    # Insert into DB
    placeholders = ", ".join(["?" for _ in DB_FIELDS])
    cursor.execute(f"INSERT INTO USPTO_data VALUES ({placeholders})", [data[f] for f in DB_FIELDS])
    conn.commit()

def main():
    if not os.path.exists(IMAGE_DIR):
        os.makedirs(IMAGE_DIR)
    
    conn = setup_db()
    try:
        results = fetch_search_results()
        if results:
            print(f"Found {len(results)} patents. Processing details...")
            for record in results:
                process_patent_details(conn, record)
                time.sleep(0.5) # Respect API rate limits
            print("\nPipeline execution complete.")
        else:
            print("No results found or search failed.")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
