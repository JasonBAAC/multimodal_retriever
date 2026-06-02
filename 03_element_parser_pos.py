import sqlite3
import re
import json
from collections import Counter
import nltk
from nltk.tag import pos_tag

# Download necessary NLTK data
nltk.download('averaged_perceptron_tagger', quiet=True)
nltk.download('averaged_perceptron_tagger_eng', quiet=True)

# Configuration
DB_NAME = "USPTO_zip_data.db"
TABLE_NAME = "USPTO_LGD"
word_span = 5

def setup_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Add new columns if they don't exist
    new_cols = ["elementsFromDD", "chunkFromElement"]
    for col in new_cols:
        try:
            cursor.execute(f"ALTER TABLE {TABLE_NAME} ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass # Already exists
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

def parse_elements():
    conn = setup_db()
    cursor = conn.cursor()
    
    # Fetch all records from USPTO_LGD
    print(f"Fetching all records from {TABLE_NAME}...")
    cursor.execute(f"SELECT rowid, patentNumber, detailedDescription FROM {TABLE_NAME}")
    rows = cursor.fetchall()
    
    # Reference character pattern: Number or Number+Letter (e.g., 230, 230a, 230A)
    # Usually, it's a standalone word or at the end of a sentence
    ref_pattern = re.compile(r'\b(\d+[a-zA-Z]?)\b')

    for rowid, p_num, dd in rows:
        if not dd:
            print(f"Skipping {p_num}: No detailedDescription.")
            continue
            
        print(f"Processing patent {p_num}...")
        
        # Split into words while keeping punctuation? 
        # Actually, let's clean it a bit but keep context
        tokens = dd.split()
        
        elements_map = {} # { "230": ["and a second active layer", ...] }
        
        skip_words = {"FIG.", "FIGS.", "of", "for", "to", "than", "or", "and/or", "and", "0", "1", "2", "3", "the", "a", "an", "is", "are", "was", "were", "by", "with", "as", "in", "on", "at", "from", "that", "which", "this", "these", "those", "it", "its", "be", "has", "have", "had", "but", "not", "all", "any", "some", "other", "such", "no", "if", "when", "while", "where", "who", "whom", "whose", ")", "(", "[", "]", "{", "}", ".", ",", ";", ":", "\"", "'", "-", "_", "%)", "Ref.", "about", "Example","example","Examples","examples"}
        
        for i, token in enumerate(tokens):
            match = ref_pattern.fullmatch(token)
            if match:
                ref_char = match.group(1)
                
                # Check immediately preceding word
                if i > 0 and tokens[i-1].strip(",") in skip_words:
                    continue
                
                # Get preceding words (word_span)
                start_idx = max(0, i - word_span)
                preceding_words = tokens[start_idx:i]
                
                if preceding_words:
                    # New Logic: If a skip_word is found in the span, delete up to that word
                    # We look for the last occurrence of any skip word in the list
                    last_skip_idx = -1
                    for idx, w in enumerate(preceding_words):
                        if w.strip(".,") in skip_words:
                            last_skip_idx = idx
                    
                    if last_skip_idx != -1:
                        preceding_words = preceding_words[last_skip_idx + 1:]
                    
                    if not preceding_words:
                        continue
                    
                    # NLTK POS Tagging Filter
                    word_tags = pos_tag(preceding_words)
                    allowed_pos = {"JJ", "NN", "NNS", "NNP", "NNPS", "RB", "VBG", "VBN", "VBP"}
                    if not all(tag in allowed_pos for word, tag in word_tags):
                        continue
                        
                    context = " ".join(preceding_words)
                    # Clean context (remove leading punctuation/stop words)
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
        chunks_json = json.dumps(list(unique_chunks), ensure_ascii=False)
        
        cursor.execute(f"UPDATE {TABLE_NAME} SET elementsFromDD = ?, chunkFromElement = ? WHERE rowid = ?", 
                       (elements_json, chunks_json, rowid))
        
        print(f"  - Extracted {len(final_elements)} unique elements.")

    conn.commit()
    conn.close()
    print("\nElement parsing for entire records complete.")

if __name__ == "__main__":
    parse_elements()
