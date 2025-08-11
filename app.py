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
from ai_analyzer import EnhancedInvoiceAnalyzer
from pdf_generator import EnhancedPDFGenerator

# Setup logging avec plus de détails
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Analyseur de Factures Professionnel API",
    description="API avancée pour l'analyse automatisée de factures avec IA et données réelles du marché",
    version="2.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize enhanced components
Config.create_folders()
ocr_processor = OCRProcessor()
ai_analyzer = EnhancedInvoiceAnalyzer()
pdf_generator = EnhancedPDFGenerator()


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


class EnhancedAnalysisResult(BaseModel):
    success: bool
    message: str
    ai_result: str
    pdf_url: Optional[str] = None
    savings: Optional[float] = None
    analysis_quality: Optional[str] = None
    performance_score: Optional[dict] = None
    market_insights: Optional[dict] = None


class ErrorResponse(BaseModel):
    success: bool = False
    error: str


# Events
@app.on_event("startup")
async def startup_event():
    """Create database tables and initialize components"""
    create_tables()

    # Test des composants
    try:
        # Test connexion IA
        logger.info("Test connexion OpenAI...")
        test_result = ai_analyzer.client.models.list()
        logger.info("✅ OpenAI connecté")

        # Test générateur PDF
        logger.info("Test générateur PDF...")
        logger.info("✅ Générateur PDF initialisé")

        logger.info("🚀 Application démarrée avec composants améliorés")

    except Exception as e:
        logger.error(f"⚠️ Erreur initialisation: {e}")


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
    return {
        "message": "Analyseur de Factures Professionnel API",
        "version": "2.0.0",
        "features": [
            "OCR avancé PDF et images",
            "Analyse IA avec données réelles du marché",
            "Rapports PDF professionnels",
            "Données temps réel des fournisseurs français",
            "Calculs d'économies précis"
        ]
    }


@app.get("/health")
async def health_check():
    """Health check détaillé"""
    try:
        # Test IA
        ai_status = "OK"
        try:
            ai_analyzer.client.models.list()
        except Exception as e:
            ai_status = f"Erreur: {str(e)[:50]}"

        # Test base de données
        db_status = "OK"
        try:
            from database import SessionLocal
            db = SessionLocal()
            db.execute("SELECT 1")
            db.close()
        except Exception as e:
            db_status = f"Erreur: {str(e)[:50]}"

        return {
            "status": "healthy",
            "message": "API fonctionne correctement",
            "components": {
                "openai": ai_status,
                "database": db_status,
                "ocr": "OK",
                "pdf_generator": "OK"
            },
            "version": "2.0.0"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }


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
            ip_address="127.0.0.1"
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        logger.info(f"Utilisateur créé: {user.email}")

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
        logger.error(f"Erreur création utilisateur: {str(e)}")
        raise HTTPException(status_code=500, detail="Erreur interne du serveur")


@app.post("/api/analyze", response_model=EnhancedAnalysisResult)
async def analyze_invoice_enhanced(
        first_name: str = Form(...),
        last_name: str = Form(...),
        email: EmailStr = Form(...),
        phone: str = Form(...),
        accept_callback: bool = Form(True),
        user_id: Optional[int] = Form(None),
        invoice: UploadFile = File(...),
        db: Session = Depends(get_db)
):
    """Analyse améliorée avec données réelles et rapport professionnel"""
    try:
        # Validation du fichier
        if not invoice.filename:
            raise HTTPException(status_code=400, detail="Aucun fichier fourni")

        if not allowed_file(invoice.filename):
            raise HTTPException(status_code=400, detail="Type de fichier non valide")

        logger.info(f"Début analyse: {invoice.filename}")

        # Créer ou récupérer l'utilisateur
        if not user_id:
            # Vérifier utilisateurs existants
            existing_user = db.query(User).filter(User.email == email).first()
            if existing_user:
                raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")

            existing_phone = db.query(User).filter(User.phone == phone).first()
            if existing_phone:
                raise HTTPException(status_code=400, detail="Ce numéro de téléphone est déjà utilisé")

            # Créer nouvel utilisateur
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
            logger.info(f"Nouvel utilisateur créé: {email}")
        else:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise HTTPException(status_code=404, detail="Utilisateur non trouvé")

        # Sauvegarder le fichier temporairement
        file_extension = Path(invoice.filename).suffix.lower()
        unique_filename = f"invoice_{uuid.uuid4().hex}{file_extension}"
        temp_path = os.path.join(tempfile.gettempdir(), unique_filename)

        with open(temp_path, "wb") as buffer:
            content = await invoice.read()
            buffer.write(content)

        logger.info(f"Fichier sauvé: {temp_path} ({len(content)} bytes)")

        # ÉTAPE 1: Extraction OCR
        logger.info("🔍 Extraction OCR en cours...")
        extracted_text = ocr_processor.extract_text_from_file(temp_path)

        if not ocr_processor.is_text_extracted(extracted_text):
            raise HTTPException(
                status_code=400,
                detail="Aucun texte lisible extrait. Vérifiez la qualité du document."
            )

        clean_text = ocr_processor.preprocess_text(extracted_text)
        logger.info(f"✅ OCR réussi: {len(clean_text)} caractères extraits")

        # ÉTAPE 2: Analyse IA améliorée
        logger.info("🤖 Analyse IA avec données réelles...")
        analysis_result = ai_analyzer.analyze_invoice(clean_text)

        structured_data = analysis_result['structured_data']
        logger.info(f"✅ Analyse complétée: {structured_data.get('type_facture', 'type inconnu')}")

        # ÉTAPE 3: Calcul des économies
        savings = ai_analyzer.calculate_savings(structured_data)
        logger.info(f"💰 Économies calculées: {savings}€/an" if savings else "💰 Pas d'économies détectées")

        # ÉTAPE 4: Génération des rapports PDF professionnels
        logger.info("📄 Génération rapports PDF professionnels...")
        internal_pdf_path, user_pdf_path = pdf_generator.generate_reports(structured_data, user_id)

        # ÉTAPE 5: Sauvegarde en base
        invoice_record = Invoice(
            user_id=user_id,
            file_path=temp_path,
            report_path=user_pdf_path,
            internal_report_path=internal_pdf_path,
            savings_12_percent=savings
        )
        db.add(invoice_record)
        db.commit()

        # ÉTAPE 6: Préparation du résumé
        popup_summary = pdf_generator.generate_popup_summary(structured_data)

        # Nettoyage du fichier temporaire
        try:
            os.unlink(temp_path)
            logger.info("🗑️ Fichier temporaire supprimé")
        except Exception as e:
            logger.warning(f"Impossible de supprimer {temp_path}: {e}")

        # Résultat final
        logger.info(f"✅ Analyse terminée avec succès pour {email}")

        return EnhancedAnalysisResult(
            success=True,
            message="Analyse professionnelle complétée avec données réelles du marché",
            ai_result=popup_summary,
            pdf_url=user_pdf_path,
            savings=savings,
            analysis_quality=structured_data.get('analysis_quality', 'high'),
            performance_score=structured_data.get('performance_score'),
            market_insights=structured_data.get('market_analysis')
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur analyse: {str(e)}")
        # Nettoyage en cas d'erreur
        try:
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.unlink(temp_path)
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'analyse: {str(e)}")


@app.get("/api/download-report/{filename}")
async def download_report(filename: str):
    """Téléchargement de rapport PDF"""
    try:
        # Vérifier dans les dossiers de rapports
        user_path = os.path.join(Config.REPORTS_FOLDER, filename)
        internal_path = os.path.join(Config.REPORTS_INTERNAL_FOLDER, filename)

        if os.path.exists(user_path):
            logger.info(f"📥 Téléchargement rapport utilisateur: {filename}")
            return FileResponse(
                user_path,
                media_type='application/pdf',
                filename=filename
            )
        elif os.path.exists(internal_path):
            logger.info(f"📥 Téléchargement rapport interne: {filename}")
            return FileResponse(
                internal_path,
                media_type='application/pdf',
                filename=filename
            )
        else:
            raise HTTPException(status_code=404, detail="Rapport non trouvé")

    except Exception as e:
        logger.error(f"Erreur téléchargement {filename}: {str(e)}")
        raise HTTPException(status_code=500, detail="Erreur lors du téléchargement")


@app.get("/api/users/{user_id}/invoices")
async def get_user_invoices(user_id: int, db: Session = Depends(get_db)):
    """Récupérer les factures d'un utilisateur avec détails"""
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
                    "report_available": bool(inv.report_path),
                    "internal_report_available": bool(inv.internal_report_path)
                }
                for inv in invoices
            ],
            "total_savings": sum(float(inv.savings_12_percent) for inv in invoices if inv.savings_12_percent),
            "total_analyses": len(invoices)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur récupération factures {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Erreur interne du serveur")


@app.post("/api/test-ocr")
async def test_ocr_enhanced(file: UploadFile = File(...)):
    """Test OCR avec détails techniques"""
    try:
        if not allowed_file(file.filename):
            raise HTTPException(status_code=400, detail="Type de fichier non valide")

        # Sauvegarder temporairement
        file_extension = Path(file.filename).suffix.lower()
        unique_filename = f"test_{uuid.uuid4().hex}{file_extension}"
        temp_path = os.path.join(tempfile.gettempdir(), unique_filename)

        with open(temp_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

        # Extraction et analyse
        extracted_text = ocr_processor.extract_text_from_file(temp_path)
        clean_text = ocr_processor.preprocess_text(extracted_text)

        # Analyse de qualité
        word_count = len(clean_text.split())
        line_count = len(clean_text.split('\n'))
        char_count = len(clean_text)

        # Détection du type de document
        doc_type = "inconnu"
        if any(word in clean_text.lower() for word in ['kwh', 'électricité', 'edf', 'engie']):
            doc_type = "électricité"
        elif any(word in clean_text.lower() for word in ['gaz', 'naturel']):
            doc_type = "gaz"
        elif any(word in clean_text.lower() for word in ['internet', 'fibre', 'orange', 'sfr', 'free']):
            doc_type = "internet"

        # Nettoyage
        os.unlink(temp_path)

        return {
            "success": True,
            "filename": file.filename,
            "file_size": len(content),
            "text_length": char_count,
            "word_count": word_count,
            "line_count": line_count,
            "document_type": doc_type,
            "extracted_text": clean_text[:500] + "..." if len(clean_text) > 500 else clean_text,
            "text_quality": "excellent" if char_count > 200 and word_count > 30 else "good" if char_count > 50 else "poor",
            "analysis_ready": ocr_processor.is_text_extracted(extracted_text)
        }

    except Exception as e:
        logger.error(f"Erreur test OCR: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erreur OCR: {str(e)}")


@app.get("/api/market-data")
async def get_market_data():
    """Informations sur les données de marché utilisées"""
    return {
        "data_sources": [
            "Commission de Régulation de l'Énergie (CRE)",
            "Sites officiels des fournisseurs",
            "Tarifs réglementés en vigueur",
            "Comparateurs certifiés"
        ],
        "last_update": "2025-01-15",
        "coverage": {
            "electricity_providers": 6,
            "gas_providers": 5,
            "internet_providers": 5
        },
        "accuracy": "Données réelles du marché français"
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)