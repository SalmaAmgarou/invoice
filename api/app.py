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

import datetime
import mimetypes
import os
import base64
import tempfile
from pathlib import Path
from typing import List, Literal
import hmac, hashlib, time
from fastapi import Depends, HTTPException, Security, FastAPI, File, UploadFile, Form, Request, BackgroundTasks
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse
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
import logging, traceback, sys
from services.storage.spaces import SpacesClient
from services.reporting.engine import (
     process_invoice_file,
     process_image_files,
     EnergyTypeError,
     EnergyTypeMismatchError,
 )

logger = logging.getLogger("pioui.spaces")
_spaces = SpacesClient()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
ALLOWED_IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif'}

# Configure secure logging to prevent API key exposure
class SecureLoggingFilter(logging.Filter):
    """Filter to remove sensitive data from logs"""
    
    SENSITIVE_HEADERS = {'x-api-key', 'authorization', 'cookie'}
    SENSITIVE_PARAMS = {'api_key', 'token', 'password', 'secret'}
    
    def filter(self, record):
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            # Remove API keys from log messages
            for header in self.SENSITIVE_HEADERS:
                record.msg = record.msg.replace(f"{header}: ", f"{header}: [REDACTED] ")
                record.msg = record.msg.replace(f'"{header}": ', f'"{header}": "[REDACTED]", ')
            
            # Remove sensitive parameters
            for param in self.SENSITIVE_PARAMS:
                record.msg = record.msg.replace(f"{param}=", f"{param}=[REDACTED]")
                record.msg = record.msg.replace(f'"{param}": ', f'"{param}": "[REDACTED]", ')
        
        return True

# Apply the filter to all loggers
secure_filter = SecureLoggingFilter()
logging.getLogger().addFilter(secure_filter)
logging.getLogger("uvicorn.access").addFilter(secure_filter)
logging.getLogger("fastapi").addFilter(secure_filter)

class HTTPSRedirectMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce HTTPS in production"""
    
    def __init__(self, app, force_https: bool = False):
        super().__init__(app)
        self.force_https = force_https
    
    async def dispatch(self, request: Request, call_next):
        # Only enforce HTTPS in production
        if self.force_https and request.url.scheme == "http":
            # Check if request is coming through a proxy (X-Forwarded-Proto)
            proto = request.headers.get("x-forwarded-proto", "http")
            if proto == "http":
                # Redirect to HTTPS
                https_url = request.url.replace(scheme="https")
                return RedirectResponse(url=str(https_url), status_code=301)
        
        response = await call_next(request)
        
        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Add HSTS header for HTTPS enforcement
        if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        return response

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

# Security middleware (add first, before CORS)
app.add_middleware(
    HTTPSRedirectMiddleware,
    force_https=os.getenv("FORCE_HTTPS", "false").lower() == "true"
)

# Trusted host middleware for additional security
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"] if os.getenv("ALLOWED_HOSTS") is None else os.getenv("ALLOWED_HOSTS").split(",")
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
    highlights: list[str] = Field(default_factory=list, description="3–4 short marketing highlights.")
    # Optional pass-through identifiers (useful for DB correlation)
    user_id: Optional[int] = Field(None, description="Optional user identifier passed in the request and echoed back.")
    invoice_id: Optional[int] = Field(None, description="Optional invoice identifier passed in the request and echoed back.")
    external_ref: Optional[str] = Field(None, description="Optional external reference string passed in the request and echoed back.")
# ————————————————————————————————————————————————————————————————
# Endpoints
# ————————————————————————————————————————————————————————————————
@app.get("/health", summary="Health Check")
async def health(_auth = Depends(require_api_key),):
    """A simple endpoint to confirm the API is running."""
    return {"status": "ok"}

@app.on_event("startup")
def _spaces_startup_probe():
    try:
        from services.storage.spaces import SpacesClient
        c = SpacesClient()
        masked = (Config.DO_SPACES_KEY or "")[:4] + "…" if Config.DO_SPACES_KEY else "NONE"
        logger.info("spaces_config", extra={
            "bucket": Config.DO_SPACES_BUCKET,
            "endpoint": Config.DO_SPACES_ENDPOINT,
            "region": Config.DO_SPACES_REGION,
            "key_prefix": masked,
        })
        # Fast sanity check (will throw if key is invalid)
        c._s3.list_buckets()
        logger.info("spaces_probe_ok")
    except Exception as e:
        logger.exception("spaces_probe_failed", exc_info=e)

def _enqueue_spaces_backup_pdf(
    *,
    background_tasks: BackgroundTasks,
    user_id: int | None,
    invoice_id: int | None,
    external_ref: str | None,
    energy_type: str,
    original_pdf_bytes: bytes,
    non_anon_bytes: bytes,
    anon_bytes: bytes,
    highlights: list | dict | None,
    customer_name: str | None = None,
):
    # 1. Generate a single, unique run_id for this processing event
    run_id = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    # 2. Use the run_id to build the versioned prefix
    prefix = _spaces.build_prefix(
        user_id=user_id,
        invoice_id=invoice_id,
        external_ref=external_ref,
        customer_name=customer_name,
        run_id=run_id  # <-- Pass the new run_id
    )
    meta = {
        "x-amz-meta-user-id": str(user_id or ""),
        "x-amz-meta-invoice-id": str(invoice_id or ""),
        "x-amz-meta-external-ref": external_ref or "",
        "x-amz-meta-source-kind": "pdf",
        "x-amz-meta-energy-type": energy_type or "",
        "x-amz-meta-run-id": run_id, # Also good to have in metadata
    }

    def _task():
        try:
            # 3. Generate the new, simplified filenames
            filenames = _spaces.make_filenames(
                energy_type=energy_type,
            )

            manifest = {
                "env": Config.ENV,
                "run_id": run_id, # Add run_id to the manifest
                "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                "user_id": user_id,
                "invoice_id": invoice_id,
                "external_ref": external_ref,
                "energy_type": energy_type,
                "customer_name": customer_name,
                "highlights": highlights or [],
            }
            keys = _spaces.upload_files_flat(
                prefix=prefix,
                filenames=filenames,
                original_pdf_bytes=original_pdf_bytes,
                non_anon_bytes=non_anon_bytes,
                anon_bytes=anon_bytes,
                manifest=manifest,
                metadata=meta,
            )
            logger.info("spaces_upload_ok", extra={"prefix": prefix, "keys": keys})
        except Exception as e:
            logger.exception("spaces_upload_error", exc_info=e)

    background_tasks.add_task(_task)


@app.post(
    "/v1/invoices/pdf",
    response_model=ProcessResponse,
    summary="Process a single PDF invoice",
)
async def create_from_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="PDF file"),
    type: str = Form(..., description="energy type enum used by engine"),
    confidence_min: float = Form(0.6),
    strict: bool = Form(False),
    # pass-through identifiers from the PHP backend:
    user_id: int | None = Form(None),
    invoice_id: int | None = Form(None),
    external_ref: str | None = Form(None),
    customer_name: str | None = Form(None),
    _auth = Depends(require_api_key),
):
    # 1) Read the original PDF fully (bounded by your existing size limit)
    original_pdf_bytes = await file.read()
    if not original_pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    # 2) Write to a NamedTemporaryFile if your engine requires a path
    with tempfile.NamedTemporaryFile(delete=True, suffix=".pdf") as tmp:
        await file.seek(0)
        tmp.write(original_pdf_bytes)
        tmp.flush()

        # 3) Run your engine using the temp path
        from services.reporting.engine import process_invoice_file
        try:
            non_anon_bytes, anon_bytes, highlights = process_invoice_file(
                tmp.name, energy_mode=type, confidence_min=confidence_min, strict=strict
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Engine error: {e}")

    # 4) Fire-and-forget Spaces backups
    _enqueue_spaces_backup_pdf(
        background_tasks=background_tasks,
        user_id=user_id,
        invoice_id=invoice_id,
        external_ref=external_ref,
        energy_type=type,  # <— add this
        original_pdf_bytes=original_pdf_bytes,
        non_anon_bytes=non_anon_bytes,
        anon_bytes=anon_bytes,
        highlights=highlights,
        customer_name=customer_name if 'customer_name' in locals() else None,
    )

    # 5) Return the same response as before (Base64 + highlights)
    return {
        "non_anonymous_report_base64": base64.b64encode(non_anon_bytes).decode("utf-8"),
        "anonymous_report_base64": base64.b64encode(anon_bytes).decode("utf-8"),
        "highlights": highlights,
        "user_id": user_id,
        "invoice_id": invoice_id,
        "external_ref": external_ref,
    }

def _enqueue_spaces_backup_images(
    *,
    background_tasks: BackgroundTasks,
    user_id: int | None,
    invoice_id: int | None,
    external_ref: str | None,
    energy_type: str,                 # NEW
    original_images: list[tuple[str, bytes]],  # (filename, bytes)
    non_anon_bytes: bytes,
    anon_bytes: bytes,
    highlights: list | dict | None,
    customer_name: str | None = None,
):
    run_id = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    prefix = _spaces.build_prefix(
        user_id=user_id, invoice_id=invoice_id, external_ref=external_ref, customer_name=customer_name, run_id=run_id
    )
    meta = {
        "x-amz-meta-user-id": str(user_id or ""),
        "x-amz-meta-invoice-id": str(invoice_id or ""),
        "x-amz-meta-external-ref": external_ref or "",
        "x-amz-meta-source-kind": "images",
        "x-amz-meta-energy-type": energy_type or "",
    }

    def _task():
        try:
            # ✅ CORRECTED a single-argument call to match the new function definition.
            filenames = _spaces.make_filenames(
                energy_type=energy_type,
            )

            manifest = {
                "env": Config.ENV,
                "run_id": run_id,  # Added for consistency
                "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                "user_id": user_id,
                "invoice_id": invoice_id,
                "external_ref": external_ref,
                "energy_type": energy_type,
                "customer_name": customer_name,
                "original_pages": [fn for fn, _ in original_images],
                "highlights": highlights or [],
            }
            # Note: I removed the original_pdf_bytes=None, as your function
            # in spaces.py doesn't expect it if it's not present.
            keys = _spaces.upload_files_flat(
                prefix=prefix,
                filenames=filenames,
                original_pdf_bytes=None,  # Explicitly pass None for clarity
                non_anon_bytes=non_anon_bytes,
                anon_bytes=anon_bytes,
                manifest=manifest,
                metadata=meta,
            )

            # This part uploads the original image files alongside the reports
            _spaces.upload_image_pages_flat(
                prefix=prefix,
                user_id=user_id,
                invoice_id=invoice_id,
                external_ref=external_ref,
                original_images=original_images,
                metadata=meta,
                include_user_in_name=False,  # Set to False to keep filenames simple (e.g., page-001.jpg)
            )

            logger.info("spaces_upload_ok", extra={"prefix": prefix, "keys": keys})
        except Exception as e:
            logger.exception("spaces_upload_error", exc_info=e)

    background_tasks.add_task(_task)



@app.post(
    "/v1/invoices/images",
    response_model=ProcessResponse,
    summary="Process one or more invoice images"
)
async def create_from_images(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(..., description="One or more image files"),
    type: str = Form(...),
    confidence_min: float = Form(0.6),
    strict: bool = Form(False),
    user_id: int | None = Form(None),
    invoice_id: int | None = Form(None),
    external_ref: str | None = Form(None),
    customer_name: str | None = Form(None),
    _auth = Depends(require_api_key),
):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    # 1) Keep original bytes in memory (respect your existing size caps upstream)
    original_images: list[tuple[str, bytes]] = []
    tmp_paths: list[str] = []

    try:
        for f in files:
            data = await f.read()
            if not data:
                raise HTTPException(status_code=400, detail=f"Empty file: {f.filename}")
            original_images.append((f.filename or "image", data))

            # If engine needs file paths, write each to temp
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(f.filename or '')[-1] or ".jpg")
            tmp.write(data)
            tmp.flush()
            tmp.close()
            tmp_paths.append(tmp.name)

        from services.reporting.engine import process_image_files
        non_anon_bytes, anon_bytes, highlights = process_image_files(
            tmp_paths, energy_mode=type, confidence_min=confidence_min, strict=strict
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Engine error: {e}")
    finally:
        # Cleanup any temp files
        for p in tmp_paths:
            try: os.remove(p)
            except Exception: pass

    # 2) Fire-and-forget Spaces backups
    _enqueue_spaces_backup_images(
        background_tasks=background_tasks,
        user_id=user_id,
        invoice_id=invoice_id,
        external_ref=external_ref,
        energy_type=type,
        original_images=original_images,
        non_anon_bytes=non_anon_bytes,
        anon_bytes=anon_bytes,
        highlights=highlights,
    )

    # 3) Return the same response as before (Base64 + highlights)
    import base64
    return {
        "non_anonymous_report_base64": base64.b64encode(non_anon_bytes).decode("utf-8"),
        "anonymous_report_base64": base64.b64encode(anon_bytes).decode("utf-8"),
        "highlights": highlights,
        "user_id": user_id,
        "invoice_id": invoice_id,
        "external_ref": external_ref,
    }

@app.post("/v1/jobs/pdf", response_model=JobEnqueueResponse, summary="Enqueue PDF invoice processing")
async def enqueue_pdf_job(
    file: UploadFile = File(...),
    type_: EnergyMode = Form("auto", alias="type"),
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
        "type": type_,
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
    type_: EnergyMode = Form("auto", alias="type"),
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
        "type": type_,
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
