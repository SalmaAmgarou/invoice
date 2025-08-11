import os
import logging
import tempfile
from typing import Optional
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from config import Config
from database import get_db, create_tables, User, Invoice
from ocr_processor import OCRProcessor
from ai_analyzer import InvoiceAnalyzer
from pdf_generator import ProfessionalPDFGenerator

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Analyseur de Factures API",
    description="API pour l'analyse automatisée de factures avec IA",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize components
Config.create_folders()
ocr_processor = OCRProcessor()
ai_analyzer = InvoiceAnalyzer()
pdf_generator = ProfessionalPDFGenerator()


# Pydantic models
class UserCreate(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    phone: str
    accept_callback: bool = True


class UserResponse(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: str
    phone: str


class AnalysisResult(BaseModel):
    success: bool
    message: str
    ai_result: str
    pdf_url: Optional[str] = None
    savings: Optional[float] = None


class ErrorResponse(BaseModel):
    success: bool = False
    error: str


# Events
@app.on_event("startup")
async def startup_event():
    """Create database tables on startup"""
    create_tables()
    logger.info("Application démarrée")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Application fermée")


# Utility functions
def allowed_file(filename: str) -> bool:
    """Check if file extension is allowed"""
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS


def get_user_ip(request) -> str:
    """Get user IP address"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0]
    return request.client.host


# Routes
@app.get("/")
async def root():
    return {"message": "Analyseur de Factures API"}


@app.get("/health")
async def health_check():
    return {"status": "healthy", "message": "API fonctionne correctement"}


@app.post("/api/users", response_model=UserResponse)
async def create_user(
        user_data: UserCreate,
        db: Session = Depends(get_db)
):
    """Create a new user"""
    try:
        # Check for duplicate email
        existing_user = db.query(User).filter(User.email == user_data.email).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")

        # Check for duplicate phone
        existing_phone = db.query(User).filter(User.phone == user_data.phone).first()
        if existing_phone:
            raise HTTPException(status_code=400, detail="Ce numéro de téléphone est déjà utilisé")

        # Create new user
        user = User(
            first_name=user_data.first_name,
            last_name=user_data.last_name,
            email=user_data.email,
            phone=user_data.phone,
            accept_callback=user_data.accept_callback,
            ip_address="127.0.0.1"  # You can get real IP from request
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        return UserResponse(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            phone=user.phone
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la création utilisateur: {str(e)}")
        raise HTTPException(status_code=500, detail="Erreur interne du serveur")


@app.post("/api/analyze", response_model=AnalysisResult)
async def analyze_invoice(
        first_name: str = Form(...),
        last_name: str = Form(...),
        email: EmailStr = Form(...),
        phone: str = Form(...),
        accept_callback: bool = Form(True),
        user_id: Optional[int] = Form(None),
        invoice: UploadFile = File(...),
        db: Session = Depends(get_db)
):
    """Analyze invoice file and generate report"""
    try:
        # Validate file
        if not invoice.filename:
            raise HTTPException(status_code=400, detail="Aucun fichier fourni")

        if not allowed_file(invoice.filename):
            raise HTTPException(status_code=400, detail="Type de fichier non valide")

        # Create or get user
        if not user_id:
            # Check for existing user
            existing_user = db.query(User).filter(User.email == email).first()
            if existing_user:
                raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")

            existing_phone = db.query(User).filter(User.phone == phone).first()
            if existing_phone:
                raise HTTPException(status_code=400, detail="Ce numéro de téléphone est déjà utilisé")

            # Create new user
            user = User(
                first_name=first_name,
                last_name=last_name,
                email=email,
                phone=phone,
                accept_callback=accept_callback,
                ip_address="127.0.0.1"
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            user_id = user.id
        else:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise HTTPException(status_code=404, detail="Utilisateur non trouvé")

        # Save uploaded file temporarily
        file_extension = Path(invoice.filename).suffix.lower()
        unique_filename = f"invoice_{uuid.uuid4().hex}{file_extension}"
        temp_path = os.path.join(tempfile.gettempdir(), unique_filename)

        with open(temp_path, "wb") as buffer:
            content = await invoice.read()
            buffer.write(content)

        logger.info(f"Fichier sauvegardé temporairement: {temp_path}")

        # Extract text using OCR
        logger.info("Extraction du texte en cours...")
        extracted_text = ocr_processor.extract_text_from_file(temp_path)

        if not ocr_processor.is_text_extracted(extracted_text):
            raise HTTPException(
                status_code=400,
                detail="Aucun texte n'a pu être extrait du fichier. Vérifiez la qualité du document."
            )

        # Clean extracted text
        clean_text = ocr_processor.preprocess_text(extracted_text)
        logger.info(f"Texte extrait ({len(clean_text)} caractères): {clean_text[:200]}...")

        # Analyze with AI
        logger.info("Analyse IA en cours...")
        analysis_result = ai_analyzer.analyze_invoice(clean_text)

        structured_data = analysis_result['structured_data']

        # Calculate savings
        savings = ai_analyzer.calculate_savings(structured_data)

        # Generate PDF reports
        logger.info("Génération des rapports PDF...")
        internal_pdf_path, user_pdf_path = pdf_generator.generate_reports(structured_data, user_id)

        # Save invoice record
        invoice_record = Invoice(
            user_id=user_id,
            file_path=temp_path,  # In production, upload to cloud storage
            report_path=user_pdf_path,
            internal_report_path=internal_pdf_path,
            savings_12_percent=savings
        )
        db.add(invoice_record)
        db.commit()

        # Prepare popup summary
        popup_summary = pdf_generator.generate_popup_summary(structured_data)

        # Clean up temporary file
        try:
            os.unlink(temp_path)
        except Exception as e:
            logger.warning(f"Impossible de supprimer le fichier temporaire: {e}")

        return AnalysisResult(
            success=True,
            message="Analyse réussie",
            ai_result=popup_summary,
            pdf_url=user_pdf_path,  # In production, return cloud URL
            savings=savings
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de l'analyse: {str(e)}")
        # Clean up on error
        try:
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.unlink(temp_path)
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'analyse: {str(e)}")


@app.get("/api/download-report/{filename}")
async def download_report(filename: str):
    """Download generated PDF report"""
    try:
        # Check in both user and internal reports folders
        user_path = os.path.join(Config.REPORTS_FOLDER, filename)
        internal_path = os.path.join(Config.REPORTS_INTERNAL_FOLDER, filename)

        if os.path.exists(user_path):
            return FileResponse(
                user_path,
                media_type='application/pdf',
                filename=filename
            )
        elif os.path.exists(internal_path):
            return FileResponse(
                internal_path,
                media_type='application/pdf',
                filename=filename
            )
        else:
            raise HTTPException(status_code=404, detail="Rapport non trouvé")

    except Exception as e:
        logger.error(f"Erreur lors du téléchargement: {str(e)}")
        raise HTTPException(status_code=500, detail="Erreur lors du téléchargement")


@app.get("/api/users/{user_id}/invoices")
async def get_user_invoices(user_id: int, db: Session = Depends(get_db)):
    """Get all invoices for a user"""
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="Utilisateur non trouvé")

        invoices = db.query(Invoice).filter(Invoice.user_id == user_id).all()

        return {
            "user": {
                "id": user.id,
                "name": f"{user.first_name} {user.last_name}",
                "email": user.email
            },
            "invoices": [
                {
                    "id": inv.id,
                    "uploaded_at": inv.uploaded_at.isoformat(),
                    "savings": float(inv.savings_12_percent) if inv.savings_12_percent else None,
                    "report_available": bool(inv.report_path)
                }
                for inv in invoices
            ]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des factures: {str(e)}")
        raise HTTPException(status_code=500, detail="Erreur interne du serveur")


@app.post("/api/test-ocr")
async def test_ocr(file: UploadFile = File(...)):
    """Test OCR functionality on uploaded file"""
    try:
        if not allowed_file(file.filename):
            raise HTTPException(status_code=400, detail="Type de fichier non valide")

        # Save file temporarily
        file_extension = Path(file.filename).suffix.lower()
        unique_filename = f"test_{uuid.uuid4().hex}{file_extension}"
        temp_path = os.path.join(tempfile.gettempdir(), unique_filename)

        with open(temp_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

        # Extract text
        extracted_text = ocr_processor.extract_text_from_file(temp_path)
        clean_text = ocr_processor.preprocess_text(extracted_text)

        # Clean up
        os.unlink(temp_path)

        return {
            "success": True,
            "filename": file.filename,
            "text_length": len(clean_text),
            "extracted_text": clean_text[:1000] + "..." if len(clean_text) > 1000 else clean_text,
            "text_quality": "good" if ocr_processor.is_text_extracted(extracted_text) else "poor"
        }

    except Exception as e:
        logger.error(f"Erreur lors du test OCR: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erreur OCR: {str(e)}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)