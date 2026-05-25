import sqlite3
import os
import shutil
from tqdm import tqdm

# Configuration
DB_NAME = "USPTO_zip_data.db"
SOURCE_IMAGE_DIR = "US_patent_images"
target_company = "LG Display"
target_alias = "LGD"

# Derived paths
TARGET_TABLE = f"USPTO_{target_alias}"
TARGET_IMAGE_DIR = os.path.join(SOURCE_IMAGE_DIR, target_alias)

def select_and_copy():
    # 1. Setup Database and Target Table
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Get schema from source table
    cursor.execute("PRAGMA table_info(USPTO_zip_data)")
    columns = [row[1] for row in cursor.fetchall()] # row[1] is name
    col_str = ", ".join(columns)
    
    # Create target table with same schema
    cursor.execute(f"DROP TABLE IF EXISTS {TARGET_TABLE}")
    cursor.execute(f"CREATE TABLE {TARGET_TABLE} AS SELECT * FROM USPTO_zip_data WHERE 1=0")
    conn.commit()
    
    # 2. Select Data
    print(f"Selecting patents for company: {target_company}...")
    cursor.execute(f"SELECT * FROM USPTO_zip_data WHERE applicantName LIKE ?", (f"%{target_company}%",))
    rows = cursor.fetchall()
    
    if not rows:
        print(f"No records found for {target_company}.")
        conn.close()
        return

    # 3. Load into Target Table
    placeholders = ", ".join(["?" for _ in range(len(rows[0]))])
    cursor.executemany(f"INSERT INTO {TARGET_TABLE} VALUES ({placeholders})", rows)
    conn.commit()
    
    db_count = len(rows)
    print(f"Phase 1: Successfully copied {db_count} records to {TARGET_TABLE}.")
    
    # 4. Image Copying
    if not os.path.exists(TARGET_IMAGE_DIR):
        os.makedirs(TARGET_IMAGE_DIR)
        print(f"Created directory: {TARGET_IMAGE_DIR}")

    # Extract patent numbers for matching
    # We assume patentNumber is the first column based on DB_FIELDS in pipeline
    # Let's find the index of patentNumber
    cursor.execute(f"PRAGMA table_info({TARGET_TABLE})")
    cols_info = cursor.fetchall()
    p_num_idx = next(i for i, c in enumerate(cols_info) if c[1] == "patentNumber")
    
    patent_numbers = [row[p_num_idx] for row in rows]
    
    print("\nPhase 2: Copying associated images...")
    image_count = 0
    
    # Get list of all images once for efficiency
    all_images = [f for f in os.listdir(SOURCE_IMAGE_DIR) if os.path.isfile(os.path.join(SOURCE_IMAGE_DIR, f))]
    
    for p_num in tqdm(patent_numbers, desc="Processing Patents"):
        # Search pattern: "US" + patentNumber
        pattern = f"US{p_num}"
        matches = [img for img in all_images if pattern in img]
        
        for match in matches:
            src_path = os.path.join(SOURCE_IMAGE_DIR, match)
            dst_path = os.path.join(TARGET_IMAGE_DIR, match)
            
            # Copy file
            shutil.copy2(src_path, dst_path)
            image_count += 1
            
    conn.close()
    
    print("\n" + "="*30)
    print(f"Target Selection Task Complete.")
    print(f"- Target Table: {TARGET_TABLE} ({db_count} records)")
    print(f"- Target Folder: {TARGET_IMAGE_DIR} ({image_count} images)")
    print("="*30)

if __name__ == "__main__":
    select_and_copy()
