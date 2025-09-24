import os, base64, json, hmac, hashlib
from typing import List, Optional
import httpx
from celery_app import celery
from services.reporting.engine import process_invoice_file, process_image_files

def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("utf-8")

def _safe_unlink(path: str):
    try: os.remove(path)
    except Exception: pass

def _post_webhook(url: str, payload: dict, task_id: str):
    body = json.dumps(payload, separators=(",", ":"))
    headers = {
        "Content-Type": "application/json",
        "X-Task-Id": task_id,
    }
    token = os.getenv("WEBHOOK_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    secret = os.getenv("WEBHOOK_SECRET", "")
    if secret:
        sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        headers["X-Webhook-Signature"] = sig

    # non-2xx => raises => Celery autoretry kicks in
    with httpx.Client(timeout=15) as cli:
        r = cli.post(url, content=body, headers=headers)
        r.raise_for_status()

@celery.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True, retry_jitter=True, retry_kwargs={'max_retries': 6},
    name="process_pdf_task",
)
def process_pdf_task(
    self,
    file_path: str,
    type: str,
    confidence_min: float,
    strict: bool,
    webhook_url: Optional[str] = None,
    # optional context (pass-through to webhook/DB):
    user_id: Optional[int] = None,
    invoice_id: Optional[int] = None,
    external_ref: Optional[str] = None,
    source_kind: Optional[str] = "pdf",
) -> dict:
    non_anon, anon = process_invoice_file(file_path, energy_mode=type,
                                          confidence_min=confidence_min, strict=strict)

    result = {
        "non_anonymous_report_base64": _b64(non_anon),
        "anonymous_report_base64": _b64(anon),
        # optional integrity metadata (handy for DB/audits)
        "non_anonymous_size": len(non_anon),
        "anonymous_size": len(anon),
        "non_anonymous_sha256": hashlib.sha256(non_anon).hexdigest(),
        "anonymous_sha256": hashlib.sha256(anon).hexdigest(),
        # pass-through context (if the enqueue provided these)
        "user_id": user_id,
        "invoice_id": invoice_id,
        "external_ref": external_ref,
        "source_kind": source_kind or "pdf",
    }
    try:
        if webhook_url:
            _post_webhook(webhook_url, result, task_id=self.request.id)
    finally:
        _safe_unlink(file_path)
    return result

@celery.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True, retry_jitter=True, retry_kwargs={'max_retries': 6},
    name="process_images_task",
)
def process_images_task(
    self,
    file_paths: List[str],
    type: str,
    confidence_min: float,
    strict: bool,
    webhook_url: Optional[str] = None,
    # optional context:
    user_id: Optional[int] = None,
    invoice_id: Optional[int] = None,
    external_ref: Optional[str] = None,
    source_kind: Optional[str] = "images",
) -> dict:
    non_anon, anon = process_image_files(file_paths, energy_mode=type,
                                         confidence_min=confidence_min, strict=strict)

    result = {
        "non_anonymous_report_base64": _b64(non_anon),
        "anonymous_report_base64": _b64(anon),
        "non_anonymous_size": len(non_anon),
        "anonymous_size": len(anon),
        "non_anonymous_sha256": hashlib.sha256(non_anon).hexdigest(),
        "anonymous_sha256": hashlib.sha256(anon).hexdigest(),
        "user_id": user_id,
        "invoice_id": invoice_id,
        "external_ref": external_ref,
        "source_kind": source_kind or "images",
    }
    try:
        if webhook_url:
            _post_webhook(webhook_url, result, task_id=self.request.id)
    finally:
        for p in file_paths: _safe_unlink(p)
    return result
