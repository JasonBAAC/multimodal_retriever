import sqlite3
import re
import json
import os
import argparse
from collections import Counter
import nltk
from nltk.tag import pos_tag

# Download necessary NLTK data
nltk.download('averaged_perceptron_tagger', quiet=True)
nltk.download('averaged_perceptron_tagger_eng', quiet=True)

ARGS_FILE = "90_args.txt"
word_span = 5


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


def setup_db(db_name, table_name):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    new_cols = ["elementsFromDD", "chunkFromElementDD"]
    for col in new_cols:
        try:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    return conn

def find_common_prefix(strings):
    """Finds the longest common substring (simplified as most frequent phrase)."""
    if not strings:
        return ""
    if len(strings) == 1:
        return strings[0]
    
    # Simple approach: Tokenize and find most common tokens/phrases
    # For patent elements, they often share a trailing phrase before the number
    # Example: ['and a second active layer', 'so the second active layer']
    # We want 'second active layer'
    
    words_lists = [s.split() for s in strings]
    
    # Let's find the longest common suffix of words since the number follows the name
    def get_common_suffix(lists):
        if not lists: return []
        reversed_lists = [lst[::-1] for lst in lists]
        min_len = min(len(lst) for lst in reversed_lists)
        common = []
        for i in range(min_len):
            target = reversed_lists[0][i]
            if all(lst[i] == target for lst in reversed_lists):
                common.append(target)
            else:
                break
        return common[::-1]

    common_words = get_common_suffix(words_lists)
    if common_words:
        return " ".join(common_words)
    
    # Fallback to the shortest string if no perfect common suffix
    return min(strings, key=len)

def parse_elements(db_name, table_name):
    conn = setup_db(db_name, table_name)
    cursor = conn.cursor()

    print(f"Fetching all records from {table_name} ({db_name})...")
    cursor.execute(f"SELECT rowid, patentNumber, detailedDescription FROM {table_name}")
    rows = cursor.fetchall()
    
    # Reference character pattern: number+optional letter (e.g., 230, 102a) or 1–5 consecutive uppercase letters (e.g., LCD, OLED)
    ref_pattern = re.compile(r'\b(\d+[a-zA-Z]?|[A-Z]{1,5})\b')

    for rowid, p_num, dd in rows:
        if not dd:
            print(f"Skipping {p_num}: No detailedDescription.")
            continue
            
        print(f"Processing patent {p_num}...")
        
        # Split into words while keeping punctuation? 
        # Actually, let's clean it a bit but keep context
        tokens = dd.split()
        
        elements_map = {} # { "230": ["and a second active layer", ...] }
        
        skip_words = {"FIG.", "FIGS.", "Ref.", "Equation", "Embodiment", "embodiment", "Result", "Table", "TABLE", "table", ".", ",", "Example","example","Examples","examples", "of", "OF", "DESCRIPTIOIN", "description", "THE", "the", "mini"}
        
        stop_words = {"of", "for", "to", "than", "or", "and/or", "and", "0", "1", "2", "3", "the", "a", "an", "is", "are", "was", "were", "by", "with", "as", "in", "on", "at", "from", "that", "which", "this", "these", "those", "it", "its", "be", "has", "have", "had", "but", "not", "all", "any", "some", "other", "such", "no", "if", "when", "while", "where", "who", "whom", "whose", ")", "(", "[", "]", "{", "}", ".", ",", ";", ":", "\"", "'", "-", "_", "%)", "about"}

        for i, token in enumerate(tokens):
            match = ref_pattern.fullmatch(token)
            if match:
                ref_char = match.group(1)
                
                # Filter 1: Check immediately preceding word against skip_words
                if i > 0 and tokens[i-1].strip(",") in skip_words:
                    continue

                # Filter 2: Extract preceding words (word_span), POS tag, keep allowed-POS words only
                start_idx = max(0, i - word_span)
                preceding_words = tokens[start_idx:i]

                if preceding_words:
                    word_tags = pos_tag(preceding_words)
                    allowed_pos = {"JJ", "NN", "NNS", "NNP", "NNPS", "RB", "VBG", "VBN", "VBP"}
                    preceding_words = [word for word, tag in word_tags if tag in allowed_pos]

                if not preceding_words:
                    continue

                # Filter 3: Find last stop_word in POS-filtered words, keep only what follows
                last_stop_idx = -1
                for idx, w in enumerate(preceding_words):
                    if w.strip(".,") in stop_words:
                        last_stop_idx = idx

                if last_stop_idx != -1:
                    preceding_words = preceding_words[last_stop_idx + 1:]

                if not preceding_words:
                    continue

                context = " ".join(preceding_words)
                context = re.sub(r'^[^\w]+', '', context).strip()

                if ref_char not in elements_map:
                    elements_map[ref_char] = []
                elements_map[ref_char].append(context)
        
        # Deduplicate and find common names
        final_elements = {}
        unique_chunks = set()
        
        for ref_char, descriptions in elements_map.items():
            # Filter out very short descriptions or purely numeric ones if they aren't the key
            clean_desc = [d for d in descriptions if any(c.isalpha() for c in d)]
            if not clean_desc:
                continue
                
            common_name = find_common_prefix(clean_desc)
            if common_name:
                final_elements[ref_char] = common_name
                unique_chunks.add(common_name)
        
        # Update DB
        elements_json = json.dumps(final_elements, ensure_ascii=False)
        chunks_json = ", ".join(sorted(unique_chunks))
        
        cursor.execute(f"UPDATE {table_name} SET elementsFromDD = ?, chunkFromElementDD = ? WHERE rowid = ?",
                       (elements_json, chunks_json, rowid))
        
        print(f"  - Extracted {len(final_elements)} unique elements.")

    conn.commit()
    conn.close()
    print("\nElement parsing for entire records complete.")

if __name__ == "__main__":
    saved = load_args_file()

    parser = argparse.ArgumentParser(description="USPTO Patent Element Parser")
    parser.add_argument("--dbName", default=saved.get('dbName', 'US_patent'))
    parser.add_argument("--aka",    default=saved.get('aka',    'LGD'))
    args = parser.parse_args()

    db_file    = args.dbName if args.dbName.endswith('.db') else args.dbName + '.db'
    table_name = args.aka + '_patent'

    parse_elements(db_file, table_name)
