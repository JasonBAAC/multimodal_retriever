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

ARGS_FILE = "90_args.txt"

DB_FIELDS = [
    "patentNumber", "grantDate", "applicationType", "applicationNumber",
    "applicationDate", "ptaDays", "cpcMain", "cpcFurther",
    "numberOfClaims", "exemplaryClaim", "inventionTitle", "cpcSearched",
    "numberOfFigures", "applicantName", "applicantCountry", "assigneeName",
    "examinerDepartment", "abstract", "briefSummary", "detailedDescription",
    "briefSummaryBackground", "briefSummarySummary", "allClaims",
    "rep_ind_Claim"
]


def load_args_file():
    saved = {}
    if not os.path.exists(ARGS_FILE):
        return saved
    with open(ARGS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if '=' in line:
                key, _, val = line.partition('=')
                saved[key.strip()] = val.strip().strip("'\"")
    return saved


def save_args_file(saved, updates):
    saved.update(updates)
    lines = [f"{k}='{v}'" for k, v in saved.items()]
    with open(ARGS_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def setup_db(db_name, table_name):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    col_str = ", ".join([f"{col} TEXT" for col in DB_FIELDS])
    cursor.execute(f"CREATE TABLE IF NOT EXISTS {table_name} ({col_str})")
    conn.commit()
    return conn


def patent_exists(conn, patent_number, table_name):
    cursor = conn.cursor()
    cursor.execute(f"SELECT 1 FROM {table_name} WHERE patentNumber = ? LIMIT 1", (patent_number,))
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
        if biblio is None:
            return None

        data = {f: None for f in DB_FIELDS}

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

        # v4.4+ path first; fall back to v4.2/v4.3 path used in pre-2013 grants
        applicant = (
            biblio.find('.//us-parties/us-applicants/us-applicant/addressbook') or
            biblio.find('.//parties/applicants/applicant/addressbook')
        )
        if applicant is not None:
            data["applicantName"] = applicant.findtext('orgname')
            data["applicantCountry"] = applicant.findtext('.//country')

        assignee = biblio.find('.//assignees/assignee/addressbook')
        if assignee is not None:
            data["assigneeName"] = assignee.findtext('orgname')

        data["examinerDepartment"] = biblio.findtext('.//examiners/primary-examiner/department')

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
                                if active:
                                    break
                            if active:
                                parts.append("".join(child.itertext()))
                        return "\n".join(parts).strip() if parts else None

                    data["briefSummaryBackground"] = get_heading_section(["BACKGROUND"])
                    data["briefSummarySummary"] = get_heading_section(["SUMMARY"])
                except:
                    pass

        return data
    except Exception:
        return None


def _is_valid_member(name, base_prefix):
    parts = name.replace("\\", "/").split("/")
    if len(parts) < 3:
        return False
    if parts[0] != base_prefix:
        return False
    return parts[1] == "REISSUE" or parts[1].startswith("UTIL")


def _is_target(data, applicant_name, assignee_name, applicant_country):
    """applicantCountry 일치 + (applicantName 포함 또는 assigneeName 포함) 조건 확인."""
    country = data.get("applicantCountry") or ""
    app_name = data.get("applicantName") or ""
    asgn_name = data.get("assigneeName") or ""
    if country != applicant_country:
        return False
    return (applicant_name in app_name) or (assignee_name in asgn_name)


def process_inner_zip(z, conn, args, table_name):
    """
    Returns:
        True  — 새로 삽입됨
        False — 이미 DB에 존재 (already_exists 카운트 증가용)
        None  — XML 없음 / 파싱 실패 / 대상 기업 아님 (무시)
    """
    namelist = z.namelist()
    xml_file = next((f for f in namelist if f.lower().endswith(".xml")), None)
    if not xml_file:
        return None

    xml_content = z.read(xml_file).decode('utf-8', errors='ignore')
    data = extract_xml_data(xml_content)
    if not data:
        return None

    if not _is_target(data, args.applicantName, args.assigneeName, args.applicantCountry):
        return None

    p_num = data["patentNumber"]
    if patent_exists(conn, p_num, table_name):
        return False

    cursor = conn.cursor()
    placeholders = ", ".join(["?" for _ in DB_FIELDS])
    cursor.execute(
        f"INSERT INTO {table_name} VALUES ({placeholders})",
        [data[f] for f in DB_FIELDS]
    )
    conn.commit()

    image_dir = os.path.join(args.imageFolder, args.aka)
    os.makedirs(image_dir, exist_ok=True)
    for f in namelist:
        if f.lower().endswith(".tif"):
            with open(os.path.join(image_dir, os.path.basename(f)), 'wb') as out_f:
                out_f.write(z.read(f))

    return True


def process_tar(tar_path, conn, args, table_name):
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
            extracted_count = 0
            for member in tqdm(members, desc=f"Scanning {tar_filename}"):
                if already_exists_count >= 100:
                    print(f"  Skipping rest (100 patents already exist in DB).")
                    break
                zip_data_file = tar.extractfile(member)
                if not zip_data_file:
                    continue
                try:
                    with zipfile.ZipFile(io.BytesIO(zip_data_file.read())) as z:
                        result = process_inner_zip(z, conn, args, table_name)
                        if result is True:
                            extracted_count += 1
                        elif result is False:
                            already_exists_count += 1
                except Exception:
                    pass
            print(f"  {extracted_count:05d} case extracted!")
    except Exception as e:
        print(f"Error opening TAR {tar_filename}: {e}")


def process_zip(zip_path, conn, args, table_name):
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
            extracted_count = 0
            for member in tqdm(members, desc=f"Scanning {zip_filename}"):
                if already_exists_count >= 10:
                    print(f"  Skipping rest (10 patents already exist in DB).")
                    break
                try:
                    with zipfile.ZipFile(io.BytesIO(outer_zip.read(member))) as z:
                        result = process_inner_zip(z, conn, args, table_name)
                        if result is True:
                            extracted_count += 1
                        elif result is False:
                            already_exists_count += 1
                except Exception:
                    pass
            print(f"  {extracted_count:03d} case extracted!")
    except Exception as e:
        print(f"Error opening ZIP {zip_filename}: {e}")


def process_pipeline(args):
    table_name = args.aka + "_patent"
    db_file = args.dbName if args.dbName.endswith('.db') else args.dbName + '.db'

    conn = setup_db(db_file, table_name)

    archives = (
        glob.glob(os.path.join(args.sourceFolder, "*.tar")) +
        glob.glob(os.path.join(args.sourceFolder, "*.zip"))
    )

    if args.grantDate:
        archives = [f for f in archives if args.grantDate in os.path.basename(f)]

    print(f"Found {len(archives)} archive(s) to process "
          f"(grantDate={args.grantDate or 'ALL'}).")
    print(f"Target  : {args.applicantName} / {args.assigneeName} ({args.applicantCountry})")
    print(f"DB      : {db_file}  Table: {table_name}")
    print(f"Images  : {os.path.join(args.imageFolder, args.aka)}/")

    for archive_path in archives:
        if archive_path.lower().endswith(".tar"):
            process_tar(archive_path, conn, args, table_name)
        else:
            process_zip(archive_path, conn, args, table_name)

    conn.close()
    print("\nAll Archives Processed. Pipeline Complete.")


if __name__ == "__main__":
    saved = load_args_file()

    parser = argparse.ArgumentParser(description="USPTO Patent TAR/ZIP Pipeline (target-filtered)")
    parser.add_argument("--sourceFolder",     default=saved.get('sourceFolder',     'PTGRDT'))
    parser.add_argument("--applicantName",    default=saved.get('applicantName',    'LG Display'))
    parser.add_argument("--aka",              default=saved.get('aka',              'LGD'))
    parser.add_argument("--applicantCountry", default=saved.get('applicantCountry', 'KR'))
    parser.add_argument("--assigneeName",     default=saved.get('assigneeName',     'LG Display'))
    parser.add_argument("--imageFolder",      default=saved.get('imageFolder',      'Patent_images'))
    parser.add_argument("--dbName",           default=saved.get('dbName',           'US_patent'))
    parser.add_argument("--grantDate",        default=None, metavar="YYYYMMDD",
                        help="처리할 아카이브의 날짜 문자열 (예: 20250107). 기본값: 전체 파일")
    args = parser.parse_args()

    save_args_file(saved, {
        'sourceFolder':     args.sourceFolder,
        'applicantName':    args.applicantName,
        'aka':              args.aka,
        'applicantCountry': args.applicantCountry,
        'assigneeName':     args.assigneeName,
        'imageFolder':      args.imageFolder,
        'patentTable':      args.aka + '_patent',
        'dbName':           args.dbName,
    })

    process_pipeline(args)
