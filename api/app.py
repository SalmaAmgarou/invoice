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
import uuid, os
from pathlib import Path
from typing import Optional
from celery.result import AsyncResult
from pydantic import BaseModel
from celery_app import celery
# import tasks
from tasks import process_pdf_task, process_images_task
from fastapi import Form
import logging, traceback
from services.reporting.engine import (
     process_invoice_file,
     process_image_files,
     EnergyTypeError,
     EnergyTypeMismatchError,
 )

ALLOWED_IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif'}

# Use  existing app limit as a per-file guard (bytes)
MAX_IMAGE_BYTES = Config.MAX_CONTENT_LENGTH

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# ————————————————————————————————————————————————————————————————
# App setup
# ————————————————————————————————————————————————————————————————

class JobEnqueueResponse(BaseModel):
    task_id: str

class JobStatusResponse(BaseModel):
    task_id: str
    status: str
    result: Optional[ProcessResponse] = None  # reuse  existing response schema

def _save_upload_for_worker(upload: UploadFile, *, allowed_suffix: set[str], max_bytes: int, dest_dir: str) -> str:
    name = upload.filename or ""
    suffix = Path(name).suffix.lower()
    if suffix not in allowed_suffix:
        raise HTTPException(status_code=400, detail=f"Unsupported extension: {suffix or 'unknown'}")

    os.makedirs(dest_dir, exist_ok=True)
    file_id = f"{uuid.uuid4().hex}{suffix}"
    out_path = os.path.join(dest_dir, file_id)

    total = 0
    with open(out_path, "wb") as w:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                w.close()
                os.remove(out_path)
                raise HTTPException(status_code=413, detail=f"File too large (> {max_bytes} bytes)")
            w.write(chunk)
    return out_path


def _unauth(msg="Non autorisé"):
    # don't leak details
    raise HTTPException(status_code=401, detail=msg)

async def require_api_key(x_api_key: str = Security(api_key_header)):
    # Require at least one configured key
    if not Config.API_KEY:
        raise HTTPException(status_code=500, detail="Configuration d'authentification du serveur incorrecte")
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

# CORS (adjust for  frontend origins in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.ALLOWED_ORIGINS,
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
        raise HTTPException(status_code=400, detail="Type de fichier invalide. Seuls les PDF sont autorisés.")

    # Use a temporary file to pass its path to  processing logic without saving permanently.
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
                    detail=f"PDF trop volumineux (> {Config.MAX_CONTENT_LENGTH} octets)"
                )
            tmp_file.write(chunk)
        tmp_file.seek(0)  # Go back to the start of the file

        try:
            # Call  modified sync function (which now returns bytes) in a worker thread
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
            raise HTTPException(status_code=422, detail=f"Incompatibilité de type d'énergie : {e}")
        except Exception as e:
            logging.exception("process_pdf_invoice failed")  # <-- logs stacktrace
            raise HTTPException(status_code=500, detail="Erreur interne du serveur")
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
        raise HTTPException(status_code=400, detail="Au moins un fichier image est requis.")
    # Validate each filename suffix up front
    for f in files:
        suffix = Path(f.filename or "").suffix.lower()
        if suffix not in ALLOWED_IMAGE_SUFFIXES:
            raise HTTPException(status_code=400, detail=f"Extension d'image non supportée : {suffix or 'inconnue'}")
    if len(files) > 8:
        raise HTTPException(status_code=400, detail="Au maximum 8 images sont autorisées par facture.")
    # valider mime type
    for f in files:
        if not f.content_type or not f.content_type.lower().startswith(("image/",)):
            raise HTTPException(status_code=400, detail=f"Type de contenu non supporté : {f.content_type or 'inconnu'}")
    if len(files) > 8:
        raise HTTPException(status_code=400, detail="Au maximum 8 images sont autorisées par facture.")

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
                            detail=f"Image trop volumineuse (> {MAX_IMAGE_BYTES} octets)"
                        )
                    tmp_file.write(chunk)
                tmp_file.flush()
                temp_files_paths.append(tmp_file.name)

        # Call  modified sync function with the list of temporary image paths
        non_anon_bytes, anon_bytes = await run_in_threadpool(
            process_image_files,
            temp_files_paths,
            energy_mode=energy,
            confidence_min=confidence_min,
            strict=strict,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur inattendue lors du traitement des images : {e}")
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

@app.post("/v1/jobs/pdf", response_model=JobEnqueueResponse, summary="Enqueue PDF invoice processing")
async def enqueue_pdf_job(
    file: UploadFile = File(...),
    energy: EnergyMode = Form("auto"),
    confidence_min: float = Form(0.5, ge=0.0, le=1.0),
    strict: bool = Form(True),
    webhook_url: Optional[str] = Form(None),
    # NEW: pass-through context
    user_id: Optional[int] = Form(None),
    invoice_id: Optional[int] = Form(None),
    external_ref: Optional[str] = Form(None),
    _auth=Depends(require_api_key),
):
    # persist to shared folder for the worker
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Invalid file type. Only PDF is allowed.")

    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    path = _save_upload_for_worker(
        file, allowed_suffix={".pdf"}, max_bytes=Config.MAX_CONTENT_LENGTH, dest_dir=Config.UPLOAD_FOLDER
    )  # MAX_CONTENT_LENGTH comes from  config. :contentReference[oaicite:8]{index=8}

    task = process_pdf_task.apply_async(kwargs={
        "file_path": path,
        "energy": energy,
        "confidence_min": confidence_min,
        "strict": strict,
        "webhook_url": webhook_url,
        "user_id": user_id,
        "invoice_id": invoice_id,
        "external_ref": external_ref,
        "source_kind": "pdf",
    })
    return {"task_id": task.id}

@app.post("/v1/jobs/images", response_model=JobEnqueueResponse, summary="Enqueue image invoice processing")
async def enqueue_images_job(
    files: List[UploadFile] = File(...),
    energy: EnergyMode = Form("auto"),
    confidence_min: float = Form(0.5, ge=0.0, le=1.0),
    strict: bool = Form(True),
    webhook_url: Optional[str] = Form(None),
    user_id: Optional[int] = Form(None),
    invoice_id: Optional[int] = Form(None),
    external_ref: Optional[str] = Form(None),
    _auth=Depends(require_api_key),
):
    if not files:
        raise HTTPException(status_code=400, detail="At least one image is required.")
    if len(files) > 8:
        raise HTTPException(status_code=400, detail="At most 8 images are allowed per invoice.")

    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    paths = []
    try:
        for f in files:
            paths.append(_save_upload_for_worker(
                f, allowed_suffix={'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif'},
                max_bytes=Config.MAX_CONTENT_LENGTH, dest_dir=Config.UPLOAD_FOLDER
            ))
    except Exception:
        # clean partial
        for p in paths:
            try: os.remove(p)
            except Exception: pass
        raise

    task = process_images_task.apply_async(kwargs={
        "file_paths": paths,  # <— list of image paths
        "energy": energy,
        "confidence_min": confidence_min,
        "strict": strict,
        "webhook_url": webhook_url,
        "user_id": user_id,
        "invoice_id": invoice_id,
        "external_ref": external_ref,
        "source_kind": "images",
    })
    return {"task_id": task.id}



@app.get("/v1/jobs/{task_id}", response_model=JobStatusResponse)
def job_status(task_id: str, _auth = Depends(require_api_key)):
    res = AsyncResult(task_id, app=celery)
    status = res.status  # PENDING / STARTED / RETRY / FAILURE / SUCCESS
    body = {"task_id": task_id, "status": status}
    if res.successful():
        body["result"] = res.result  # <- this is the dict the task returned
    elif res.failed():
        raise HTTPException(status_code=500, detail="Job failed")
    return body

@app.get("/healthz")
def healthz():
    return {"ok": True}
