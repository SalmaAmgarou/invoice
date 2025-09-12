import os
import uuid
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

# Import your existing pipeline (no logic changes)
from test_chatgpt import (
    process_invoice_file,
    EnergyTypeMismatchError,
    EnergyTypeError,
)
from typing import List
import io
from PIL import Image

ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}

def _open_as_rgb(img_bytes: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(img_bytes))
    if img.mode not in ("RGB",):
        img = img.convert("RGB")
    return img

APP_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(APP_DIR, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = FastAPI(title="Pioui Report API", version="1.0.0")

# (Optional) CORS for local testing / Postman
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok"}


# --- new endpoint in app.py ---
@app.post("/process-invoice-images")
async def process_invoice_images(
    files: List[UploadFile] = File(..., description="Pages de la facture (PNG/JPG/WEBP/TIFF)"),
    energy: str = Form("auto"),
    conf: float = Form(0.5),
    strict: bool = Form(True),
):
    if not files:
        raise HTTPException(status_code=400, detail="Aucune image fournie.")

    # read + validate extensions
    contents = []
    for f in files:
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext not in ALLOWED_IMAGE_EXTS:
            raise HTTPException(status_code=400, detail=f"Extension non supportée: {ext or 'unknown'}")
        contents.append(await f.read())

    # convert all images to RGB and (optionally) upscale small pages for better OCR
    pages = []
    for b in contents:
        img = _open_as_rgb(b)
        if img.width < 2000:
            ratio = 2000 / img.width
            img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
        pages.append(img)

    # save as a single multi-page PDF in outputs/
    unique_stem = f"facture_imgs_{uuid.uuid4().hex[:8]}"
    pdf_path = os.path.join(OUTPUT_DIR, unique_stem + ".pdf")
    try:
        if len(pages) == 1:
            pages[0].save(pdf_path, "PDF", resolution=300.0)
        else:
            pages[0].save(pdf_path, "PDF", save_all=True, append_images=pages[1:], resolution=300.0)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Échec création PDF: {e}")

    # run your unchanged pipeline
    conf_clamped = max(0.0, min(1.0, float(conf)))
    try:
        non_anon, anon = process_invoice_file(
            pdf_path,
            energy_mode=energy,
            confidence_min=conf_clamped,
            strict=bool(strict),
        )
        return {
            "ok": True,
            "used_pdf": os.path.relpath(pdf_path, OUTPUT_DIR),
            "output_dir": "outputs",
            "non_anonymous_report": os.path.relpath(non_anon, OUTPUT_DIR),
            "anonymous_report": os.path.relpath(anon, OUTPUT_DIR),
            "download_example": {
                "non_anonymous": f"/download?path={os.path.relpath(non_anon, OUTPUT_DIR)}",
                "anonymous": f"/download?path={os.path.relpath(anon, OUTPUT_DIR)}",
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


@app.post("/process-invoice")
async def process_invoice(
    file: UploadFile = File(..., description="PDF energy invoice"),
    energy: str = Form("auto"),
    conf: float = Form(0.5, description="confidence threshold [0..1]"),
    strict: bool = Form(True, description="strict mode"),
):
    """
    Upload a PDF invoice and generate the two reports.
    The PDF is saved into ./outputs so all generated reports are also in ./outputs.
    """
    # Basic validation
    filename = file.filename or "invoice.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    # Save the uploaded file into outputs/ (so your script also writes reports into outputs/)
    unique_name = f"{os.path.splitext(os.path.basename(filename))[0]}_{uuid.uuid4().hex[:8]}.pdf"
    saved_pdf_path = os.path.join(OUTPUT_DIR, unique_name)
    try:
        content = await file.read()
        with open(saved_pdf_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {e}")

    # Clamp conf to [0,1] like your CLI wrapper
    conf_clamped = max(0.0, min(1.0, float(conf)))

    try:
        non_anon, anon = process_invoice_file(
            saved_pdf_path,
            energy_mode=energy,
            confidence_min=conf_clamped,
            strict=bool(strict),
        )
        # Return paths relative to outputs/ and a download helper
        return JSONResponse(
            {
                "ok": True,
                "output_dir": "outputs",
                "non_anonymous_report": os.path.relpath(non_anon, OUTPUT_DIR),
                "anonymous_report": os.path.relpath(anon, OUTPUT_DIR),
                "download_example": {
                    "non_anonymous": f"/download?path={os.path.relpath(non_anon, OUTPUT_DIR)}",
                    "anonymous": f"/download?path={os.path.relpath(anon, OUTPUT_DIR)}",
                },
            }
        )
    except EnergyTypeMismatchError as e:
        raise HTTPException(status_code=422, detail=f"Energy type mismatch: {e}")
    except EnergyTypeError as e:
        raise HTTPException(status_code=400, detail=f"Bad parameter: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")

@app.get("/download")
def download(path: str = Query(..., description="Path relative to outputs/")):
    """
    Download a generated PDF by giving its relative path (as returned by /process-invoice).
    """
    abs_path = os.path.join(OUTPUT_DIR, path)
    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        abs_path,
        media_type="application/pdf",
        filename=os.path.basename(abs_path),
    )
