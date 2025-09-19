"""
app/main.py — Production-Ready FastAPI Wrapper

Key goals:
- Provides two async endpoints that return generated PDF reports directly.
- Does NOT save any files (uploads or reports) to the server disk.
- Uses temporary files in memory for processing, which are cleaned up automatically.
- Returns a clean JSON payload with the two reports encoded in Base64.
- The PHP client can decode these Base64 strings to get the PDF files.

Run locally:
  uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""
from __future__ import annotations
import os
import base64
import tempfile
from pathlib import Path
from typing import List, Literal
import hmac, hashlib, time
from fastapi import Depends, HTTPException, Security, FastAPI, File, UploadFile, Form
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from core.config import Config
from services.reporting.engine import (
     process_invoice_file,
     process_image_files,
     EnergyTypeError,
     EnergyTypeMismatchError,
 )

ALLOWED_IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif'}

# Use your existing app limit as a per-file guard (bytes)
MAX_IMAGE_BYTES = Config.MAX_CONTENT_LENGTH

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# ————————————————————————————————————————————————————————————————
# App setup
# ————————————————————————————————————————————————————————————————

def _unauth(msg="Unauthorized"):
    # don't leak details
    raise HTTPException(status_code=401, detail=msg)

async def require_api_key(x_api_key: str = Security(api_key_header)):
    # Require at least one configured key
    if not Config.API_KEY:
        raise HTTPException(status_code=500, detail="Server auth misconfigured")
    if not x_api_key:
        _unauth()
    ok = any(hmac.compare_digest(x_api_key, k) for k in Config.API_KEY)
    if not ok:
        _unauth()
app = FastAPI(
    title="Pioui Invoice API",
    version="2.0.0",
    description="An API to process energy invoices and generate comparison reports."
)

# CORS (adjust for your frontend origins in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ————————————————————————————————————————————————————————————————
# API Models
# ————————————————————————————————————————————————————————————————
EnergyMode = Literal["auto", "electricite", "gaz", "dual"]

class ProcessResponse(BaseModel):
    """The API response, containing both reports as Base64 encoded strings."""
    non_anonymous_report_base64: str = Field(..., description="Base64 encoded non-anonymous PDF report.")
    anonymous_report_base64: str = Field(..., description="Base64 encoded anonymous PDF report.")


# ————————————————————————————————————————————————————————————————
# Endpoints
# ————————————————————————————————————————————————————————————————
@app.get("/health", summary="Health Check")
async def health(_auth = Depends(require_api_key),):
    """A simple endpoint to confirm the API is running."""
    return {"status": "ok"}


@app.post(
    "/v1/invoices/pdf",
    response_model=ProcessResponse,
    summary="Process a single PDF invoice",
)
async def process_pdf_invoice(
    file: UploadFile = File(..., description="A single PDF invoice file."),
    energy: EnergyMode = Form("auto", description="Energy type to analyze: auto, electricite, gaz, or dual."),
    confidence_min: float = Form(0.5, ge=0.0, le=1.0, description="Confidence threshold for energy type detection."),
    strict: bool = Form(True, description="Whether to strictly enforce energy type detection."),
    _auth = Depends(require_api_key),
):
    """
    Accepts a PDF invoice, processes it, and returns the generated non-anonymous
    and anonymous reports as Base64-encoded strings in a JSON object.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Invalid file type. Only PDF is allowed.")

    # Use a temporary file to pass its path to your processing logic without saving permanently.
    # The 'with' block ensures the file is automatically deleted afterward.
    with tempfile.NamedTemporaryFile(delete=True, suffix=".pdf") as tmp_file:
        total = 0
        while True:
            chunk = file.file.read(1024 * 1024)  # 1 MB chunks
            if not chunk:
                break
            total += len(chunk)
            if total > Config.MAX_CONTENT_LENGTH:
                raise HTTPException(
                    status_code=413,
                    detail=f"PDF too large (> {Config.MAX_CONTENT_LENGTH} bytes)"
                )
            tmp_file.write(chunk)
        tmp_file.seek(0)  # Go back to the start of the file

        try:
            # Call your modified sync function (which now returns bytes) in a worker thread
            non_anon_bytes, anon_bytes = await run_in_threadpool(
                process_invoice_file,
                tmp_file.name,
                energy_mode=energy,
                confidence_min=confidence_min,
                strict=strict,
            )
        except (EnergyTypeError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        except EnergyTypeMismatchError as e:
            raise HTTPException(status_code=422, detail=f"Energy type mismatch: {e}")
        except Exception:
            raise HTTPException(status_code=500, detail="Internal Server Error")
    # Base64-encode the raw bytes to safely include them in the JSON response
    non_anon_b64 = base64.b64encode(non_anon_bytes).decode('utf-8')
    anon_b64 = base64.b64encode(anon_bytes).decode('utf-8')

    return ProcessResponse(
        non_anonymous_report_base64=non_anon_b64,
        anonymous_report_base64=anon_b64,
    )


@app.post(
    "/v1/invoices/images",
    response_model=ProcessResponse,
    summary="Process one or more invoice images"
)
async def process_image_invoices(
    files: List[UploadFile] = File(..., description="One or more image files for a single invoice."),
    energy: EnergyMode = Form("auto", description="Energy type to analyze."),
    confidence_min: float = Form(0.5, ge=0.0, le=1.0),
    strict: bool = Form(True),
    _auth=Depends(require_api_key),

):
    """
    Accepts invoice images, processes them using a vision model, and returns
    the generated reports as Base64-encoded strings.
    """
    if not files:
        raise HTTPException(status_code=400, detail="At least one image file is required.")
    # Validate each filename suffix up front
    for f in files:
        suffix = Path(f.filename or "").suffix.lower()
        if suffix not in ALLOWED_IMAGE_SUFFIXES:
            raise HTTPException(status_code=400, detail=f"Unsupported image extension: {suffix or 'unknown'}")
    if len(files) > 8:
        raise HTTPException(status_code=400, detail="At most 8 images are allowed per invoice.")
    # valider mime type
    for f in files:
        if not f.content_type or not f.content_type.lower().startswith(("image/",)):
            raise HTTPException(status_code=400, detail=f"Unsupported content type: {f.content_type or 'unknown'}")
    if len(files) > 8:
        raise HTTPException(status_code=400, detail="At most 8 images are allowed per invoice.")

    temp_files_paths = []
    try:
        # Create temporary files for each uploaded image with size enforcement
        for uploaded_file in files:
            suffix = Path(uploaded_file.filename or "").suffix  # keep original case for suffix on disk
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
                total = 0
                while True:
                    chunk = uploaded_file.file.read(1024 * 1024)  # 1 MB chunks
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_IMAGE_BYTES:
                        tmp_path = tmp_file.name
                        tmp_file.close()
                        os.remove(tmp_path)  # cleanup partial
                        raise HTTPException(
                            status_code=413,
                            detail=f"Image too large (> {MAX_IMAGE_BYTES} bytes)"
                        )
                    tmp_file.write(chunk)
                tmp_file.flush()
                temp_files_paths.append(tmp_file.name)

        # Call your modified sync function with the list of temporary image paths
        non_anon_bytes, anon_bytes = await run_in_threadpool(
            process_image_files,
            temp_files_paths,
            energy_mode=energy,
            confidence_min=confidence_min,
            strict=strict,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error during image processing: {e}")
    finally:
        # Crucial cleanup step: ensure all temporary image files are deleted
        for path in temp_files_paths:
            os.remove(path)

    # Base64-encode for the JSON response
    non_anon_b64 = base64.b64encode(non_anon_bytes).decode('utf-8')
    anon_b64 = base64.b64encode(anon_bytes).decode('utf-8')

    return ProcessResponse(
        non_anonymous_report_base64=non_anon_b64,
        anonymous_report_base64=anon_b64,
    )