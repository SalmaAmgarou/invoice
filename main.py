"""
app/main.py — FastAPI wrapper for your existing CLI pipeline (test_chatgpt.py)

Key goals:
- Keep ALL business logic in test_chatgpt.py unchanged; only wrap it behind HTTP.
- Provide 2 production‑ready async endpoints that simulate your two CLI modes:
  • POST /v1/invoices/pdf    -> python3 test_chatgpt.py <file.pdf> -e <energy>
  • POST /v1/invoices/images -> python3 test_chatgpt.py <img1> <img2> ... -e <energy>
- Persist uploads and expose generated reports via a static route (/reports/...)
- Validate inputs, run CPU/IO work in threadpool, return clean JSON payloads

Run locally:
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

Notes:
- For image invoices, set env MISTRAL_API_KEY (Pixtral) since your pipeline calls it.
- OPENAI_API_KEY must be set as in your current script.
- The wrapper saves uploads to Config.REPORTS_FOLDER so your pipeline writes reports there too.
"""
from __future__ import annotations

import os
import uuid
import shutil
from pathlib import Path
from typing import List, Literal, Optional, Tuple

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

# Import your existing logic (unchanged)
from config import Config
from test_chatgpt import (
    process_invoice_file,
    process_image_files,
    EnergyTypeError,
    EnergyTypeMismatchError,
)

# ————————————————————————————————————————————————————————————————
# App setup
# ————————————————————————————————————————————————————————————————
Config.create_folders()

app = FastAPI(title="Pioui Invoice OCR API", version="1.0.0")

# CORS (adjust for your FE origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve generated reports at /reports/*
app.mount("/reports", StaticFiles(directory=Config.REPORTS_FOLDER), name="reports")


# ————————————————————————————————————————————————————————————————
# Models
# ————————————————————————————————————————————————————————————————
EnergyMode = Literal["auto", "electricite", "gaz", "dual"]

class ProcessResponse(BaseModel):
    engine: Literal["pdf", "images"]
    energy: EnergyMode
    confidence_min: float = Field(..., ge=0, le=1)
    strict: bool
    input_saved_as: str
    non_anonymous_report_url: str
    anonymous_report_url: str


# ————————————————————————————————————————————————————————————————
# Helpers
# ————————————————————————————————————————————————————————————————
SAFE_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")

def _safe_filename(name: str) -> str:
    cleaned = "".join(ch for ch in name if ch in SAFE_CHARS) or "file"
    return cleaned.strip(".")


def _save_upload_to_reports_folder(upload: UploadFile, prefix: str) -> str:
    """Save an uploaded file into REPORTS_FOLDER with a unique name.
    Returns absolute path to the saved file.
    """
    ext = Path(upload.filename or "").suffix.lower()
    if ext not in {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif"}:
        raise HTTPException(status_code=400, detail=f"Unsupported file extension: {ext or 'unknown'}")

    uid = uuid.uuid4().hex[:8]
    fname = f"{prefix}_{uid}_{_safe_filename(upload.filename or 'upload')}{ext}"
    dest = Path(Config.REPORTS_FOLDER) / fname

    # Stream to disk
    with dest.open("wb") as out:
        shutil.copyfileobj(upload.file, out)
    return str(dest)


def _as_report_url(abs_path: str) -> str:
    name = Path(abs_path).name
    return f"/reports/{name}"


# ————————————————————————————————————————————————————————————————
# Endpoints
# ————————————————————————————————————————————————————————————————
@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/v1/invoices/pdf", response_model=ProcessResponse)
async def process_pdf_invoice(
    file: UploadFile = File(..., description="Single PDF invoice"),
    energy: EnergyMode = Form(..., description="auto | electricite | gaz | dual"),
    confidence_min: float = Form(0.5, ge=0.0, le=1.0),
    strict: bool = Form(True),
):
    """Simulates: python3 test_chatgpt.py <invoice.pdf> -e <energy> [-c <conf>] [--no-strict]

    - Upload is written into REPORTS_FOLDER, so your pipeline writes reports next to it.
    - Returns URLs to the two generated PDFs.
    """
    # Save upload (to control where pipeline writes outputs)
    saved_pdf = _save_upload_to_reports_folder(file, prefix="pdf")

    # Call your existing sync function in a worker thread
    try:
        non_anon, anon = await run_in_threadpool(
            process_invoice_file,
            saved_pdf,
            energy_mode=energy,
            confidence_min=confidence_min,
            strict=strict,
        )
    except EnergyTypeMismatchError as e:
        raise HTTPException(status_code=422, detail=f"Energy type mismatch: {e}")
    except EnergyTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")

    return ProcessResponse(
        engine="pdf",
        energy=energy,
        confidence_min=confidence_min,
        strict=strict,
        input_saved_as=_as_report_url(saved_pdf),
        non_anonymous_report_url=_as_report_url(non_anon),
        anonymous_report_url=_as_report_url(anon),
    )


@app.post("/v1/invoices/images", response_model=ProcessResponse)
async def process_image_invoices(
    files: List[UploadFile] = File(..., description="1..8 image files for a single invoice"),
    energy: EnergyMode = Form(..., description="auto | electricite | gaz | dual"),
    confidence_min: float = Form(0.5, ge=0.0, le=1.0),
    strict: bool = Form(True),
):
    """Simulates: python3 test_chatgpt.py <img1> <img2> ... -e <energy> [-c <conf>] [--no-strict]

    Your pipeline calls Pixtral; ensure MISTRAL_API_KEY is set in environment.
    """
    if not files:
        raise HTTPException(status_code=400, detail="At least one image is required")

    # Save all uploads in the reports folder so the pipeline writes reports there
    saved_images: List[str] = []
    try:
        for i, f in enumerate(files, start=1):
            saved_images.append(_save_upload_to_reports_folder(f, prefix=f"img{i:02d}"))
    finally:
        # Ensure file handles are closed
        for f in files:
            try:
                f.file.close()
            except Exception:
                pass

    # Call your existing sync function in a worker thread
    try:
        non_anon, anon = await run_in_threadpool(
            process_image_files,
            saved_images,
            energy_mode=energy,
            confidence_min=confidence_min,
            strict=strict,
        )
    except EnergyTypeMismatchError as e:
        raise HTTPException(status_code=422, detail=f"Energy type mismatch: {e}")
    except EnergyTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")

    # For convenience, point to the first uploaded image as the input reference
    return ProcessResponse(
        engine="images",
        energy=energy,
        confidence_min=confidence_min,
        strict=strict,
        input_saved_as=_as_report_url(saved_images[0]),
        non_anonymous_report_url=_as_report_url(non_anon),
        anonymous_report_url=_as_report_url(anon),
    )


# ————————————————————————————————————————————————————————————————
# Optional: simple index
# ————————————————————————————————————————————————————————————————
@app.get("/")
async def index():
    return {
        "name": "Pioui Invoice OCR API",
        "version": "1.0.0",
        "routes": [
            {"POST": "/v1/invoices/pdf"},
            {"POST": "/v1/invoices/images"},
            {"GET": "/reports/<filename>"},
        ],
    }
