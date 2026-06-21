import sqlite3
import tarfile
import zipfile
import os
import io
import re
import json
import glob
import argparse
from tqdm import tqdm
from lxml import etree

# Constants
PTGRDT_DIR = "PTGRDT"
DB_NAME = "USPTO_zip_data.db"
IMAGE_DIR = "US_patent_images"

# Updated Database Schema
DB_FIELDS = [
    "patentNumber", "grantDate", "applicationType", "applicationNumber",
    "applicationDate", "ptaDays", "cpcMain", "cpcFurther",
    "numberOfClaims", "exemplaryClaim", "inventionTitle", "cpcSearched",
    "numberOfFigures", "applicantName", "applicantCountry", "assigneeName",
    "examinerDepartment", "abstract", "briefSummary", "detailedDescription",
    "briefSummaryBackground", "briefSummarySummary", "allClaims",
    "rep_ind_Claim"
]

def setup_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    col_str = ", ".join([f"{col} TEXT" for col in DB_FIELDS])
    cursor.execute(f"CREATE TABLE IF NOT EXISTS USPTO_zip_data ({col_str})")
    conn.commit()
    return conn

def patent_exists(conn, patent_number):
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM USPTO_zip_data WHERE patentNumber = ? LIMIT 1", (patent_number,))
    return cursor.fetchone() is not None

def format_date(date_str):
    if date_str and len(date_str) == 8:
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    return date_str

def get_cpc_str(elem):
    s = elem.findtext('section') or ""
    c = elem.findtext('class') or ""
    sc = elem.findtext('subclass') or ""
    mg = elem.findtext('main-group') or ""
    sg = elem.findtext('subgroup') or ""
    return f"{s}{c}{sc} {mg}/{sg}"

def clean_tags(xml_fragment):
    """Strips all XML tags and returns plain text."""
    if not xml_fragment:
        return None
    try:
        if not xml_fragment.strip().startswith("<"):
             return xml_fragment.strip()
        content = f"<root>{xml_fragment}</root>"
        parser = etree.XMLParser(recover=True)
        tree = etree.fromstring(content.encode('utf-8'), parser=parser)
        return "".join(tree.itertext()).strip()
    except Exception:
        return re.sub(r'<[^>]+>', '', xml_fragment).strip()

def extract_xml_data(xml_content):
    try:
        tree = etree.fromstring(xml_content.encode('utf-8'))
        biblio = tree.find('.//us-bibliographic-data-grant')
        if biblio is None: return None

        data = {f: None for f in DB_FIELDS}

        # 1. Basic Metadata
        pub_ref = biblio.find('.//publication-reference/document-id')
        if pub_ref is not None:
            data["patentNumber"] = pub_ref.findtext('doc-number')
            data["grantDate"] = format_date(pub_ref.findtext('date'))

        app_ref = biblio.find('.//application-reference')
        if app_ref is not None:
            data["applicationType"] = app_ref.get('appl-type')
            doc_id = app_ref.find('document-id')
            if doc_id is not None:
                data["applicationNumber"] = doc_id.findtext('doc-number')
                data["applicationDate"] = format_date(doc_id.findtext('date'))

        pta_elem = biblio.find('.//us-term-extension')
        data["ptaDays"] = pta_elem.text if pta_elem is not None else "0"

        cpc_main = biblio.find('.//classifications-cpc/main-cpc/classification-cpc')
        if cpc_main is not None:
            data["cpcMain"] = get_cpc_str(cpc_main)

        cpc_further = []
        for cf in biblio.findall('.//classifications-cpc/further-cpc/classification-cpc'):
            cpc_further.append(get_cpc_str(cf))
        data["cpcFurther"] = json.dumps(cpc_further) if cpc_further else None

        data["numberOfClaims"] = biblio.findtext('number-of-claims')
        data["exemplaryClaim"] = biblio.findtext('us-exemplary-claim')
        data["inventionTitle"] = biblio.findtext('invention-title')

        cpc_searched = [c.text for c in biblio.findall('.//us-field-of-classification-search/classification-cpc-text') if c.text]
        data["cpcSearched"] = json.dumps(cpc_searched) if cpc_searched else None

        data["numberOfFigures"] = biblio.findtext('.//figures/number-of-figures')

        applicant = biblio.find('.//us-parties/us-applicants/us-applicant/addressbook')
        if applicant is not None:
            data["applicantName"] = applicant.findtext('orgname')
            data["applicantCountry"] = applicant.findtext('.//country')

        assignee = biblio.find('.//assignees/assignee/addressbook')
        if assignee is not None:
            data["assigneeName"] = assignee.findtext('orgname')

        data["examinerDepartment"] = biblio.findtext('.//examiners/primary-examiner/department')

        # 2. Text Fields with Tag Cleaning
        abstract_elem = tree.find('abstract')
        if abstract_elem is not None:
            data["abstract"] = "".join(abstract_elem.itertext()).strip()

        claims_elem = tree.find('claims')
        if claims_elem is not None:
            data["allClaims"] = "".join(claims_elem.itertext()).strip()

            ex_num = data["exemplaryClaim"] or "1"
            try:
                target_num = f"{int(ex_num):05d}"
            except:
                target_num = "00001"
            target_claim = claims_elem.find(f".//claim[@num='{target_num}']")
            if target_claim is None:
                target_claim = claims_elem.find(f".//claim[@num='00001']")
            if target_claim is not None:
                data["rep_ind_Claim"] = "".join(target_claim.itertext()).strip()

        desc_elem = tree.find('description')
        if desc_elem is not None:
            raw_desc = etree.tostring(desc_elem, encoding='unicode')

            def get_pi_section(pattern_start, pattern_end, content):
                match = re.search(f"{re.escape(pattern_start)}(.*?){re.escape(pattern_end)}", content, re.DOTALL)
                return match.group(1).strip() if match else None

            bs_raw = get_pi_section('<?BRFSUM description="Brief Summary" end="lead"?>', '<?BRFSUM description="Brief Summary" end="tail"?>', raw_desc)
            dd_raw = get_pi_section('<?DETDESC description="Detailed Description" end="lead"?>', '<?DETDESC description="Detailed Description" end="tail"?>', raw_desc)

            data["briefSummary"] = clean_tags(bs_raw)
            data["detailedDescription"] = clean_tags(dd_raw)

            if bs_raw:
                try:
                    bs_tree = etree.fromstring(f"<root>{bs_raw}</root>")
                    def get_heading_section(keywords):
                        parts = []
                        active = False
                        for child in bs_tree:
                            if child.tag == 'heading':
                                text = (child.text or "").upper()
                                if any(k in text for k in keywords):
                                    active = True
                                    continue
                                if active: break
                            if active:
                                parts.append("".join(child.itertext()))
                        return "\n".join(parts).strip() if parts else None

                    data["briefSummaryBackground"] = get_heading_section(["BACKGROUND"])
                    data["briefSummarySummary"] = get_heading_section(["SUMMARY"])
                except: pass

        return data
    except Exception:
        return None

def _is_valid_member(name, base_prefix):
    """TAR/ZIP 내부의 inner-ZIP 경로가 처리 대상인지 확인."""
    parts = name.replace("\\", "/").split("/")
    if len(parts) < 3:
        return False
    if parts[0] != base_prefix:
        return False
    return parts[1] == "REISSUE" or parts[1].startswith("UTIL")

def process_inner_zip(z, conn, image_extract):
    """
    Returns:
        True  — 새로 삽입됨
        False — 이미 DB에 존재 (already_exists 카운트 증가용)
        None  — XML 없음 / 파싱 실패 (무시)
    """
    namelist = z.namelist()
    xml_file = next((f for f in namelist if f.lower().endswith(".xml")), None)
    if not xml_file:
        return None

    xml_content = z.read(xml_file).decode('utf-8', errors='ignore')
    data = extract_xml_data(xml_content)
    if not data:
        return None

    p_num = data["patentNumber"]
    if patent_exists(conn, p_num):
        return False

    cursor = conn.cursor()
    placeholders = ", ".join(["?" for _ in DB_FIELDS])
    cursor.execute(
        f"INSERT INTO USPTO_zip_data VALUES ({placeholders})",
        [data[f] for f in DB_FIELDS]
    )
    conn.commit()

    if image_extract:
        os.makedirs(IMAGE_DIR, exist_ok=True)
        for f in namelist:
            if f.lower().endswith(".tif"):
                with open(os.path.join(IMAGE_DIR, os.path.basename(f)), 'wb') as out_f:
                    out_f.write(z.read(f))

    return True

def process_tar(tar_path, conn, image_extract):
    tar_filename = os.path.basename(tar_path)
    base_prefix = os.path.splitext(tar_filename)[0].split('_')[0]
    print(f"\nProcessing TAR: {tar_filename}")
    try:
        with tarfile.open(tar_path, 'r') as tar:
            members = [
                m for m in tar.getmembers()
                if m.name.lower().endswith(".zip")
                and _is_valid_member(m.name, base_prefix)
            ]
            print(f"  Found {len(members)} relevant ZIP files.")
            already_exists_count = 0
            for member in tqdm(members, desc=f"Scanning {tar_filename}"):
                if already_exists_count >= 10:
                    print(f"  Skipping rest (10 patents already exist in DB).")
                    break
                zip_data_file = tar.extractfile(member)
                if not zip_data_file:
                    continue
                try:
                    with zipfile.ZipFile(io.BytesIO(zip_data_file.read())) as z:
                        result = process_inner_zip(z, conn, image_extract)
                        if result is False:
                            already_exists_count += 1
                except Exception:
                    pass
    except Exception as e:
        print(f"Error opening TAR {tar_filename}: {e}")

def process_zip(zip_path, conn, image_extract):
    zip_filename = os.path.basename(zip_path)
    base_prefix = os.path.splitext(zip_filename)[0].split('_')[0]
    print(f"\nProcessing ZIP: {zip_filename}")
    try:
        with zipfile.ZipFile(zip_path, 'r') as outer_zip:
            members = [
                name for name in outer_zip.namelist()
                if name.lower().endswith(".zip")
                and _is_valid_member(name, base_prefix)
            ]
            print(f"  Found {len(members)} relevant ZIP files.")
            already_exists_count = 0
            for member in tqdm(members, desc=f"Scanning {zip_filename}"):
                if already_exists_count >= 10:
                    print(f"  Skipping rest (10 patents already exist in DB).")
                    break
                try:
                    with zipfile.ZipFile(io.BytesIO(outer_zip.read(member))) as z:
                        result = process_inner_zip(z, conn, image_extract)
                        if result is False:
                            already_exists_count += 1
                except Exception:
                    pass
    except Exception as e:
        print(f"Error opening ZIP {zip_filename}: {e}")

def process_pipeline(image_extract=True, grant_date=None):
    conn = setup_db()

    archives = (
        glob.glob(os.path.join(PTGRDT_DIR, "*.tar")) +
        glob.glob(os.path.join(PTGRDT_DIR, "*.zip"))
    )

    if grant_date:
        archives = [f for f in archives if grant_date in os.path.basename(f)]

    print(f"Found {len(archives)} archive(s) to process "
          f"(image_extract={image_extract}, grantDate={grant_date or 'ALL'}).")

    for archive_path in archives:
        if archive_path.lower().endswith(".tar"):
            process_tar(archive_path, conn, image_extract)
        else:
            process_zip(archive_path, conn, image_extract)

    conn.close()
    print("\nAll Archives Processed. Pipeline Complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="USPTO Patent TAR/ZIP Pipeline")
    parser.add_argument(
        "--image_extract", choices=["y", "n"], default="y",
        help="TIF 이미지 추출 여부 (y/n). 기본값: y"
    )
    parser.add_argument(
        "--grantDate", default=None, metavar="YYYYMMDD",
        help="처리할 아카이브의 날짜 문자열 (예: 20250107). 기본값: 전체 파일"
    )
    args = parser.parse_args()

    process_pipeline(
        image_extract=(args.image_extract == "y"),
        grant_date=args.grantDate,
    )
