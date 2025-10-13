# services/storage/spaces.py
from __future__ import annotations
import json, hashlib, datetime, mimetypes, logging
from typing import Dict, List, Tuple, Optional
import boto3
from botocore.config import Config as BotoConfig
from core.config import Config
import re, unicodedata

def _slugify_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:40]  # keep short

logger = logging.getLogger(__name__)

def _sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def _now_utc() -> datetime.datetime:
    return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)

class SpacesClient:
    """Thin wrapper around DigitalOcean Spaces (S3-compatible)."""
    def __init__(self):
        self._s3 = boto3.client(
            "s3",
            region_name=Config.DO_SPACES_REGION,
            endpoint_url=Config.DO_SPACES_ENDPOINT,
            aws_access_key_id=Config.DO_SPACES_KEY,
            aws_secret_access_key=Config.DO_SPACES_SECRET,
            config=BotoConfig(signature_version="s3v4"),
        )
        self._bucket = Config.DO_SPACES_BUCKET
        self._env = Config.ENV

    @property
    def env(self) -> str:
        return self._env

    def _invoice_token(self, invoice_id: Optional[int], external_ref: Optional[str]) -> str:
        if invoice_id is not None:
            return f"invoice-{invoice_id}"
        if external_ref:
            return f"extref-{external_ref}"
        return "invoice-unknown"

    def _run_tag(self) -> str:
        # used to keep history without folders; comment out to always overwrite
        return datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    def upload_image_pages_flat(
            self,
            *,
            prefix: str,
            user_id: Optional[int],
            invoice_id: Optional[int],
            external_ref: Optional[str],
            original_images: list[tuple[str, bytes]],
            metadata: Dict[str, str],
            include_user_in_name: bool = True,
    ) -> list[str]:
        """Uploads pages next to the reports as ..._page-001.jpg, etc."""
        keys: list[str] = []
        tok = self._invoice_token(invoice_id, external_ref)
        user_prefix = f"user-{user_id}_" if (include_user_in_name and user_id is not None) else ""
        for i, (fname, data) in enumerate(original_images, start=1):
            ext = (fname.rsplit(".", 1)[-1].lower() if "." in fname else "jpg")
            ctype = mimetypes.guess_type(fname)[0] or "application/octet-stream"
            key = f"{prefix}/{user_prefix}{tok}_page-{i:03d}.{ext}"
            self.put_bytes(key, data, ctype, metadata)
            keys.append(key)
        return keys

    def put_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        metadata: Optional[Dict[str, str]] = None,
    ) -> str:
        self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            Metadata=metadata or {},
            ACL="private",
            ServerSideEncryption="AES256",
        )
        return f"s3://{self._bucket}/{key}"

    def build_prefix(
            self,
            *,
            user_id: Optional[int] = None,
            invoice_id: Optional[int] = None,
            external_ref: Optional[str] = None,
            customer_name: Optional[str] = None,
            run_id: str,  # <-- ADD THIS a unique ID for the run
    ) -> str:
        uid = f"user-{user_id}" if user_id is not None else "user-unknown"
        if customer_name:
            slug = _slugify_name(customer_name)
            if slug:
                uid = f"{uid}__{slug}"

        inv = (
            f"invoice-{invoice_id}"
            if invoice_id is not None
            else (f"extref-{external_ref}" if external_ref else "invoice-unknown")
        )
        # Append the unique run_id to the path
        return f"{self.env}/{uid}/{inv}/{run_id}"  # <-- MODIFIED to add env and run_id

    def make_filenames(
            self,
            *,
            energy_type: str,
    ) -> Dict[str, str]:
        # This function becomes much simpler. The filenames are now generic
        # because the context is entirely in the prefix (folder path).
        etype = _slugify_name(energy_type or "unknown")
        return {
            # We add the energy type to distinguish between, for example,
            # an original electricity PDF and a gas one if they were processed in the same run.
            "original_pdf": f"original_{etype}.pdf",
            "report_full": f"report_full_{etype}.pdf",
            "report_anon": f"report_anon_{etype}.pdf",
            "manifest": "manifest.json",  # Manifest is unique to the run
        }

    def upload_files_flat(
            self,
            *,
            prefix: str,
            filenames: Dict[str, str],
            original_pdf_bytes: Optional[bytes],
            non_anon_bytes: bytes,
            anon_bytes: bytes,
            manifest: Dict,
            metadata: Dict[str, str],
    ) -> Dict[str, str]:
        """Uploads all files directly under `prefix/` with descriptive names."""
        keys: Dict[str, str] = {}

        # original pdf (if provided)
        if original_pdf_bytes is not None:
            k = f"{prefix}/{filenames['original_pdf']}"
            self.put_bytes(k, original_pdf_bytes, "application/pdf", metadata)
            keys["original_pdf"] = k

        # reports
        k_full = f"{prefix}/{filenames['report_full']}"
        self.put_bytes(k_full, non_anon_bytes, "application/pdf", metadata)
        keys["report_full"] = k_full

        k_anon = f"{prefix}/{filenames['report_anon']}"
        self.put_bytes(k_anon, anon_bytes, "application/pdf", metadata)
        keys["report_anon"] = k_anon

        # manifest
        k_manifest = f"{prefix}/{filenames['manifest']}"
        data = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.put_bytes(k_manifest, data, "application/json", metadata)
        keys["manifest"] = k_manifest

        return keys

    def upload_original_image(
        self, prefix: str, page_index: int, filename: str, data: bytes, meta: Dict[str, str]
    ) -> Tuple[str, Dict[str, int | str]]:
        sha = _sha256_hex(data)
        ext = (filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin")
        guessed = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        key = f"{prefix}/original/page-{page_index:03d}-{sha}.{ext}"
        self.put_bytes(key, data, guessed, meta)
        return key, {"sha256": sha, "size": len(data), "filename": filename}

