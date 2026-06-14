import sqlite3
import os
import json
import torch
import numpy as np
import faiss
from tqdm import tqdm
from PIL import Image
from transformers import CLIPProcessor, CLIPModel

# Configuration
DB_NAME = "USPTO_zip_data.db"
TABLE_NAME = "USPTO_LGD"
IMAGE_DIR = os.path.join("US_patent_images", "LGD")
INDEX_DIR = "index"
MODEL_ID = "openai/clip-vit-large-patch14"

# Device setup
device = "cuda" if torch.cuda.is_available() else "cpu"
if torch.cuda.is_available():
    device = "cuda"
    device_name = torch.cuda.get_device_name(0)
else:
    try:
        import torch_directml
        if torch_directml.is_available():
            device = torch_directml.device()
            device_name = "DirectML (AMD/Intel GPU)"
        else:
            device_name = "CPU"
            device = torch.device("cpu")
    except ImportError:
        device_name = "CPU"
        device = torch.device("cpu")
print(f"Using device: {device} ({device_name})")

def setup_dirs():
    if not os.path.exists(INDEX_DIR):
        os.makedirs(INDEX_DIR)

def load_model():
    print(f"Loading CLIP model: {MODEL_ID}...")
    model = CLIPModel.from_pretrained(MODEL_ID).to(device)
    processor = CLIPProcessor.from_pretrained(MODEL_ID)
    model.eval()
    return model, processor

def get_text_embeddings(model, processor, texts, batch_size=8):
    all_embeddings = []
    for i in tqdm(range(0, len(texts), batch_size), desc="Text Embedding"):
        batch = texts[i:i+batch_size]
        inputs = processor(text=batch, return_tensors="pt", padding=True, truncation=True, max_length=77).to(device)
        with torch.no_grad():
            outputs = model.get_text_features(**inputs)
            # Ensure we have the raw tensor
            if hasattr(outputs, 'pooler_output'):
                features = outputs.pooler_output
            elif hasattr(outputs, 'last_hidden_state'):
                features = outputs.last_hidden_state[:, 0, :]
            else:
                features = outputs # It's likely already the tensor
                
            # L2 Normalize
            norm = features.norm(p=2, dim=-1, keepdim=True)
            normalized_features = features / norm
            all_embeddings.append(normalized_features.cpu().numpy())
    return np.vstack(all_embeddings)

def get_image_embeddings(model, processor, image_paths, batch_size=4):
    all_embeddings = []
    for i in tqdm(range(0, len(image_paths), batch_size), desc="Image Embedding"):
        batch_paths = image_paths[i:i+batch_size]
        images = []
        valid_indices = []
        for idx, path in enumerate(batch_paths):
            try:
                img = Image.open(path).convert("RGB")
                images.append(img)
                valid_indices.append(idx)
            except Exception as e:
                print(f"Error loading image {path}: {e}")
        
        if not images:
            continue
            
        inputs = processor(images=images, return_tensors="pt").to(device)
        with torch.no_grad():
            outputs = model.get_image_features(**inputs)
            if hasattr(outputs, 'pooler_output'):
                features = outputs.pooler_output
            else:
                features = outputs
                
            norm = features.norm(p=2, dim=-1, keepdim=True)
            normalized_features = features / norm
            
            batch_emb = np.zeros((len(batch_paths), normalized_features.shape[1]), dtype=np.float32)
            batch_emb[valid_indices] = normalized_features.cpu().numpy()
            all_embeddings.append(batch_emb)
            
    return np.vstack(all_embeddings) if all_embeddings else np.array([])

def build_indices():
    setup_dirs()
    model, processor = load_model()
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # 1. DB1: Claims
    print("\nBuilding DB1 (Claims)...")
    cursor.execute(f"SELECT patentNumber, rep_ind_Claim FROM {TABLE_NAME} WHERE rep_ind_Claim IS NOT NULL")
    records = cursor.fetchall()
    if records:
        patent_nums = [r[0] for r in records]
        claims = [r[1] for r in records]
        embeddings = get_text_embeddings(model, processor, claims)
        
        index = faiss.IndexFlatIP(embeddings.shape[1])
        index.add(embeddings.astype('float32'))
        faiss.write_index(index, os.path.join(INDEX_DIR, "db1_claims.index"))
        
        with open(os.path.join(INDEX_DIR, "db1_meta.json"), "w", encoding="utf-8") as f:
            json.dump({"ids": patent_nums, "texts": claims}, f, ensure_ascii=False)
        print(f"DB1 built with {len(records)} records.")
    
    # 2. DB2: Images
    print("\nBuilding DB2 (Images)...")
    if os.path.exists(IMAGE_DIR):
        all_image_files = sorted([f for f in os.listdir(IMAGE_DIR) if f.lower().endswith(('.tif', '.png', '.jpg', '.jpeg'))])
        if all_image_files:
            image_paths = [os.path.join(IMAGE_DIR, f) for f in all_image_files]
            embeddings = get_image_embeddings(model, processor, image_paths)
            
            if embeddings.size > 0:
                index = faiss.IndexFlatIP(embeddings.shape[1])
                index.add(embeddings.astype('float32'))
                faiss.write_index(index, os.path.join(INDEX_DIR, "db2_images.index"))
                
                with open(os.path.join(INDEX_DIR, "db2_meta.json"), "w", encoding="utf-8") as f:
                    json.dump({"filenames": all_image_files}, f, ensure_ascii=False)
                print(f"DB2 built with {len(all_image_files)} images.")
    
    # 3. DB3: Elements
    print("\nBuilding DB3 (Elements)...")
    cursor.execute(f"SELECT patentNumber, chunkFromElement FROM {TABLE_NAME} WHERE chunkFromElement IS NOT NULL")
    records = cursor.fetchall()
    if records:
        patent_nums = []
        combined_texts = []
        element_chunks = []
        for p_num, chunks_json in records:
            chunks = [c.strip() for c in chunks_json.split(",") if c.strip()]
            if chunks:
                combined_texts.append(" ".join(chunks))
                patent_nums.append(p_num)
                element_chunks.append(chunks)
        
        if combined_texts:
            embeddings = get_text_embeddings(model, processor, combined_texts)
            
            index = faiss.IndexFlatIP(embeddings.shape[1])
            index.add(embeddings.astype('float32'))
            faiss.write_index(index, os.path.join(INDEX_DIR, "db3_elements.index"))
            
            with open(os.path.join(INDEX_DIR, "db3_meta.json"), "w", encoding="utf-8") as f:
                json.dump({"ids": patent_nums, "chunks": element_chunks}, f, ensure_ascii=False)
            print(f"DB3 built with {len(combined_texts)} records.")

    conn.close()
    print("\nPhase 1 Complete: All indices saved in 'index/' directory.")

if __name__ == "__main__":
    build_indices()
