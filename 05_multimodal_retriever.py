import os
import json
import sqlite3
import torch
import numpy as np
import faiss
import re
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
import io
from transformers import CLIPProcessor, CLIPModel
from typing import List, Optional
from datetime import datetime
import pandas as pd
from contextlib import asynccontextmanager

# Configuration
DB_NAME = "USPTO_zip_data.db"
INDEX_DIR = "index"
IMAGE_DIR = os.path.join("US_patent_images", "LGD")
MODEL_ID = "openai/clip-vit-large-patch14"

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    load_resources()
    yield
    # Shutdown
    pass

app = FastAPI(title="Patent Multimodal Retriever API", lifespan=lifespan)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global variables for model and indices
model = None
processor = None
indices = {}
metadata = {}

def load_resources():
    global model, processor, indices, metadata
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading resources on {device}...")
    
    # 1. Load CLIP
    model = CLIPModel.from_pretrained(MODEL_ID).to(device)
    processor = CLIPProcessor.from_pretrained(MODEL_ID)
    model.eval()
    
    # 2. Load FAISS Indices
    db_configs = {
        "db1": ("db1_claims.index", "db1_meta.json"),
        "db2": ("db2_images.index", "db2_meta.json"),
        "db3": ("db3_elements.index", "db3_meta.json")
    }
    
    for key, (idx_file, meta_file) in db_configs.items():
        idx_path = os.path.join(INDEX_DIR, idx_file)
        meta_path = os.path.join(INDEX_DIR, meta_file)
        
        if os.path.exists(idx_path):
            indices[key] = faiss.read_index(idx_path)
            with open(meta_path, "r", encoding="utf-8") as f:
                metadata[key] = json.load(f)
            print(f"Loaded {key} index and metadata.")

def get_text_embedding(text: str):
    inputs = processor(text=[text], return_tensors="pt", padding=True, truncation=True, max_length=77)
    with torch.no_grad():
        outputs = model.get_text_features(**inputs.to(model.device))
        features = outputs.pooler_output if hasattr(outputs, 'pooler_output') else outputs
        features = features / features.norm(p=2, dim=-1, keepdim=True)
    return features.cpu().numpy().astype('float32')

def get_image_embedding(image_bytes: bytes):
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    inputs = processor(images=[image], return_tensors="pt")
    with torch.no_grad():
        outputs = model.get_image_features(**inputs.to(model.device))
        features = outputs.pooler_output if hasattr(outputs, 'pooler_output') else outputs
        features = features / features.norm(p=2, dim=-1, keepdim=True)
    return features.cpu().numpy().astype('float32')

def extract_epatent_number(filename: str):
    match = re.search(r'US([^-]+)', filename)
    return match.group(1) if match else "Unknown"

def tif_to_png_response(file_path_or_bytes):
    try:
        if isinstance(file_path_or_bytes, bytes):
            img = Image.open(io.BytesIO(file_path_or_bytes))
        else:
            img = Image.open(file_path_or_bytes)
            
        img_byte_arr = io.BytesIO()
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        return StreamingResponse(img_byte_arr, media_type="image/png")
    except Exception as e:
        print(f"Conversion error: {e}")
        raise HTTPException(status_code=500, detail=f"Image conversion failed: {str(e)}")

@app.post("/api/preview")
async def preview_image(file: UploadFile = File(...)):
    """Converts any uploaded image (including TIF) to PNG for browser preview."""
    content = await file.read()
    return tif_to_png_response(content)

@app.get("/api/images/{filename}")
async def get_image(filename: str):
    path = os.path.join(IMAGE_DIR, filename)
    if os.path.exists(path):
        if filename.lower().endswith(('.tif', '.tiff')):
            return tif_to_png_response(path)
        return FileResponse(path)
    raise HTTPException(status_code=404, detail="Image not found")

@app.post("/search")
async def search(
    query_claim: Optional[str] = Form(None),
    query_element: Optional[str] = Form(None),
    query_image: Optional[UploadFile] = File(None),
    k: int = Form(10)
):
    results = {
        "k1": [],
        "k2": [],
        "k3": [],
        "combined": []
    }
    
    # 1. Search DB1 (Claims)
    if query_claim and "db1" in indices:
        query_vec = get_text_embedding(query_claim)
        scores, ann_ids = indices["db1"].search(query_vec, k)
        for score, idx in zip(scores[0], ann_ids[0]):
            if idx == -1: continue
            p_num = metadata["db1"]["ids"][idx]
            text = metadata["db1"]["texts"][idx]
            results["k1"].append({
                "id": p_num,
                "score": float(score),
                "tooltip": text,
                "type": "claim",
                "suffix": "-claim",
                "color": "red"
            })

    # 2. Search DB3 (Elements)
    if query_element and "db3" in indices:
        query_vec = get_text_embedding(query_element)
        scores, ann_ids = indices["db3"].search(query_vec, k)
        for score, idx in zip(scores[0], ann_ids[0]):
            if idx == -1: continue
            p_num = metadata["db3"]["ids"][idx]
            chunks = metadata["db3"]["chunks"][idx]
            results["k3"].append({
                "id": p_num,
                "score": float(score),
                "tooltip": ", ".join(chunks),
                "type": "element",
                "suffix": "-element",
                "color": "green"
            })

    # 3. Search DB2 (Images)
    if query_image and "db2" in indices:
        image_bytes = await query_image.read()
        query_vec = get_image_embedding(image_bytes)
        scores, ann_ids = indices["db2"].search(query_vec, k)
        for score, idx in zip(scores[0], ann_ids[0]):
            if idx == -1: continue
            filename = metadata["db2"]["filenames"][idx]
            epatent = extract_epatent_number(filename)
            results["k2"].append({
                "id": filename,
                "score": float(score),
                "tooltip": f"/api/images/{filename}",
                "epatent": epatent,
                "type": "image",
                "suffix": "-drawing",
                "color": "blue"
            })

    # 4. Combined List
    combined = []
    for r in results["k1"]:
        combined.append({**r, "display_id": f"{r['id']}{r['suffix']}"})
    for r in results["k3"]:
        combined.append({**r, "display_id": f"{r['id']}{r['suffix']}"})
    for r in results["k2"]:
        combined.append({**r, "display_id": f"{r['epatent']}{r['suffix']}"})
    
    combined.sort(key=lambda x: x["score"], reverse=True)
    results["combined"] = combined

    return results

@app.get("/")
async def read_index():
    return FileResponse("06_index.html")

@app.post("/export")
async def export_results(
    input_text: str = Form(""),
    input_image_name: str = Form(""),
    results_json: str = Form(...)
):
    results = json.loads(results_json)
    timestamp = datetime.now().strftime("%Y_%m_%d %H_%M_%S")
    filename = f"Retrieval_{timestamp}_USPTO_LGD.xlsx"
    filepath = os.path.join(os.getcwd(), filename)
    
    with pd.ExcelWriter(filepath, engine='xlsxwriter') as writer:
        # 1. Overall
        overall_data = [["Input Type", "Content"], ["Text", input_text], ["Image", input_image_name], [], ["Rank", "Display ID", "Similarity (%)", "Type"]]
        for i, r in enumerate(results.get("combined", [])):
            overall_data.append([i+1, r["display_id"], f"{r['score'] * 100:.1f}%", r["type"]])
        pd.DataFrame(overall_data).to_excel(writer, sheet_name="overall", index=False, header=False)
        
        # 2. K1
        k1_data = [{"patentNumber": r["id"], "rep_ind_Claim": r["tooltip"]} for r in results.get("k1", [])]
        pd.DataFrame(k1_data).to_excel(writer, sheet_name="K1", index=False)
        
        # 3. K3
        k3_data = [{"patentNumber": r["id"], "chunkFromElement": r["tooltip"]} for r in results.get("k3", [])]
        pd.DataFrame(k3_data).to_excel(writer, sheet_name="K3", index=False)
        
        # 4. K2
        k2_list = results.get("k2", [])
        k2_meta = [{"EpatentNumber": r["epatent"], "파일명": r["id"], "이미지": ""} for r in k2_list]
        pd.DataFrame(k2_meta).to_excel(writer, sheet_name="K2", index=False)
        
        worksheet = writer.sheets['K2']
        worksheet.set_column('C:C', 30)
        for i, r in enumerate(k2_list):
            img_path = os.path.join(IMAGE_DIR, r["id"])
            if os.path.exists(img_path):
                try:
                    with Image.open(img_path) as img:
                        img_byte_arr = io.BytesIO()
                        if img.mode != "RGB": img = img.convert("RGB")
                        img.save(img_byte_arr, format='PNG')
                        worksheet.set_row(i + 1, 400) 
                        worksheet.insert_image(i + 1, 2, r["id"], {
                            'image_data': img_byte_arr,
                            'x_offset': 5, 'y_offset': 5,
                            'x_scale': 0.3, 'y_scale': 0.3,
                            'object_position': 1
                        })
                except Exception as e:
                    worksheet.write(i + 1, 2, f"Error: {str(e)}")
            else:
                worksheet.write(i + 1, 2, "Image file not found")

    return FileResponse(filepath, filename=filename, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
