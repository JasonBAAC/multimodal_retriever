import sqlite3
import os
import re
import json
import argparse
import glob
from PIL import Image
import pytesseract

ARGS_FILE = "90_args.txt"

DRAWING_FIELDS = [
    "patentNumber", "grantDate", "drawing_file_name",
    "numericFromDR", "elementsFromDR", "chunkFromElementDR"
]

REF_PATTERN = re.compile(r'\b(\d+[a-zA-Z]?)\b')


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


def setup_db(db_name, image_table):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    col_str = ", ".join([f"{col} TEXT" for col in DRAWING_FIELDS])
    cursor.execute(f"CREATE TABLE IF NOT EXISTS {image_table} ({col_str})")
    conn.commit()
    return conn


def drawing_exists(conn, image_table, drawing_file_name):
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT 1 FROM {image_table} WHERE drawing_file_name = ? LIMIT 1",
        (drawing_file_name,)
    )
    return cursor.fetchone() is not None


def parse_filename(filename):
    """
    US12597375-20260407-D00000.TIF
      patentNumber : 12597375  (US와 첫 번째 '-' 사이)
      grantDate    : 2026-04-07 (첫 번째 '-'와 두 번째 '-' 사이, YYYY-MM-DD 변환)
    """
    name = os.path.splitext(os.path.basename(filename))[0]
    if name.upper().startswith("US"):
        name = name[2:]
    parts = name.split("-")
    patent_number = parts[0] if parts else None
    grant_date = None
    if len(parts) > 1:
        raw = parts[1]
        grant_date = f"{raw[:4]}-{raw[4:6]}-{raw[6:]}" if len(raw) == 8 else raw
    return patent_number, grant_date


def ocr_image(image_path):
    """이미지 OCR 후 참조번호(숫자·숫자+문자) 중복제거 리스트 반환."""
    try:
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img)
        seen = set()
        result = []
        for m in REF_PATTERN.findall(text):
            if m not in seen:
                seen.add(m)
                result.append(m)
        return result
    except Exception as e:
        print(f"    OCR error: {e}")
        return []


def get_elements_dd(conn, patent_table, patent_number):
    """patentTable에서 해당 특허의 elementsFromDD 딕셔너리 반환."""
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT elementsFromDD FROM {patent_table} WHERE patentNumber = ? LIMIT 1",
        (patent_number,)
    )
    row = cursor.fetchone()
    if row and row[0]:
        try:
            return json.loads(row[0])
        except Exception:
            return {}
    return {}


def process_drawings(db_file, patent_table, image_table, image_dir):
    conn = setup_db(db_file, image_table)
    cursor = conn.cursor()

    tif_files = sorted(set(
        glob.glob(os.path.join(image_dir, "*.tif")) +
        glob.glob(os.path.join(image_dir, "*.TIF")) +
        glob.glob(os.path.join(image_dir, "*.tiff")) +
        glob.glob(os.path.join(image_dir, "*.TIFF"))
    ))

    print(f"Found {len(tif_files)} image(s) in {image_dir}")
    print(f"DB: {db_file}  Image table: {image_table}  Patent table: {patent_table}")

    for image_path in tif_files:
        filename = os.path.basename(image_path)

        if drawing_exists(conn, image_table, filename):
            print(f"  Skipping {filename} (already in DB)")
            continue

        patent_number, grant_date = parse_filename(filename)
        if not patent_number:
            print(f"  Skipping {filename} (cannot parse patent number)")
            continue

        print(f"  Processing {filename} ...")

        # OCR → 참조번호 리스트
        numeric_list = ocr_image(image_path)
        numeric_json = json.dumps(numeric_list, ensure_ascii=False)

        # elementsFromDD key와 매칭 → elementsFromDR 딕셔너리
        elements_dd = get_elements_dd(conn, patent_table, patent_number)
        elements_dr = {k: v for k, v in elements_dd.items() if k in numeric_list}
        elements_json = json.dumps(elements_dr, ensure_ascii=False)

        # chunkFromElementDR: elementsFromDR value 기반 정렬된 고유값 문자열
        chunk_str = ", ".join(sorted(set(elements_dr.values())))

        cursor.execute(
            f"INSERT INTO {image_table} VALUES ({', '.join(['?'] * len(DRAWING_FIELDS))})",
            [patent_number, grant_date, filename, numeric_json, elements_json, chunk_str]
        )
        conn.commit()
        print(f"    → {len(numeric_list)} refs found, {len(elements_dr)} matched")

    conn.close()
    print("\nDrawing OCR complete.")


if __name__ == "__main__":
    saved = load_args_file()

    parser = argparse.ArgumentParser(description="USPTO Patent Drawing OCR Pipeline")
    parser.add_argument("--dbName",      default=saved.get('dbName',      'US_patent'))
    parser.add_argument("--aka",         default=saved.get('aka',         'LGD'))
    parser.add_argument("--imageFolder", default=saved.get('imageFolder', 'Patent_images'))
    args = parser.parse_args()

    db_file      = args.dbName if args.dbName.endswith('.db') else args.dbName + '.db'
    patent_table = args.aka + '_patent'
    image_table  = args.aka + '_drawing'
    image_dir    = os.path.join(args.imageFolder, args.aka)

    process_drawings(db_file, patent_table, image_table, image_dir)
