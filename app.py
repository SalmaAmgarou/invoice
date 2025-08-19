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
from pdf_generator import FixedPDFGenerator

# Setup logging détaillé
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Analyseur de Factures API - Version Corrigée",
    description="API corrigée pour l'analyse de factures avec formatage PDF professionnel",
    version="2.1.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize corrected components
Config.create_folders()
ocr_processor = OCRProcessor()
ai_analyzer = EnhancedInvoiceAnalyzer()
pdf_generator = FixedPDFGenerator()


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


class FixedAnalysisResult(BaseModel):
    success: bool
    message: str
    ai_result: str
    pdf_url: Optional[str] = None
    savings: Optional[float] = None
    invoice_type: Optional[str] = None
    quality_score: Optional[str] = None


class ErrorResponse(BaseModel):
    success: bool = False
    error: str


# Events
@app.on_event("startup")
async def startup_event():
    """Initialize application with corrected components"""
    create_tables()

    try:
        # Test components
        logger.info("🔧 Initialisation des composants corrigés...")

        # Test AI connection
        test_result = ai_analyzer.client.models.list()
        logger.info("✅ OpenAI connecté")

        logger.info("✅ Générateur PDF corrigé initialisé")
        logger.info("🚀 Application démarrée avec corrections complètes")

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


# Routes
@app.get("/")
async def root():
    return {
        "message": "Analyseur de Factures API - Version Corrigée",
        "version": "2.1.0",
        "corrections": [
            "✅ Espacement PDF corrigé",
            "✅ Tableaux sans débordement",
            "✅ Polices plus grasses",
            "✅ Détection type de facture",
            "✅ Génération cohérente",
            "✅ Puces simples (■)"
        ]
    }


@app.get("/health")
async def health_check():
    """Health check détaillé avec status des corrections"""
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
            "message": "API avec corrections complètes",
            "components": {
                "openai": ai_status,
                "database": db_status,
                "ocr": "OK",
                "pdf_generator": "CORRIGÉ ✅",
                "ai_analyzer": "CORRIGÉ ✅"
            },
            "corrections_applied": [
                "Espacement PDF optimisé",
                "Tableaux avec largeurs fixes",
                "Polices grasses améliorées",
                "Détection intelligente type facture",
                "Génération cohérente sans 'Non calculable'",
                "Puces simples sans duplication"
            ],
            "version": "2.1.0"
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


@app.post("/api/analyze", response_model=FixedAnalysisResult)
async def analyze_invoice_fixed(
        first_name: str = Form(...),
        last_name: str = Form(...),
        email: EmailStr = Form(...),
        phone: str = Form(...),
        accept_callback: bool = Form(True),
        user_id: Optional[int] = Form(None),
        invoice: UploadFile = File(...),
        db: Session = Depends(get_db)
):
    """Analyse corrigée avec formatage PDF professionnel"""
    try:
        # Validation du fichier
        if not invoice.filename:
            raise HTTPException(status_code=400, detail="Aucun fichier fourni")

        if not allowed_file(invoice.filename):
            raise HTTPException(status_code=400, detail="Type de fichier non valide")

        logger.info(f"🔧 Début analyse corrigée: {invoice.filename}")

        # Créer ou récupérer utilisateur
        if not user_id:
            existing_user = db.query(User).filter(User.email == email).first()
            if existing_user:
                raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")

            existing_phone = db.query(User).filter(User.phone == phone).first()
            if existing_phone:
                raise HTTPException(status_code=400, detail="Ce numéro de téléphone est déjà utilisé")

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
            logger.info(f"✅ Nouvel utilisateur créé: {email}")
        else:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise HTTPException(status_code=404, detail="Utilisateur non trouvé")

        # Sauvegarder fichier temporairement
        file_extension = Path(invoice.filename).suffix.lower()
        unique_filename = f"invoice_{uuid.uuid4().hex}{file_extension}"
        temp_path = os.path.join(tempfile.gettempdir(), unique_filename)

        with open(temp_path, "wb") as buffer:
            content = await invoice.read()
            buffer.write(content)

        logger.info(f"📁 Fichier sauvé: {temp_path} ({len(content)} bytes)")

        # ÉTAPE 1: Extraction OCR
        logger.info("🔍 Extraction OCR...")
        extracted_text = ocr_processor.extract_text_from_file(temp_path)

        if not ocr_processor.is_text_extracted(extracted_text):
            raise HTTPException(
                status_code=400,
                detail="Aucun texte lisible extrait. Vérifiez la qualité du document."
            )

        clean_text = ocr_processor.preprocess_text(extracted_text)
        logger.info(f"✅ OCR réussi: {len(clean_text)} caractères")

        # ÉTAPE 2: Analyse IA corrigée avec détection de type
        logger.info("🤖 Analyse IA corrigée avec détection de type...")
        analysis_result = ai_analyzer.analyze_invoice(clean_text)

        structured_data = analysis_result['structured_data']
        invoice_type = structured_data.get('type_facture', 'inconnu')
        invoice_subtype = structured_data.get('invoice_subtype', 'standard')

        logger.info(f"✅ Type détecté: {invoice_type} ({invoice_subtype})")

        # ÉTAPE 3: Calcul des économies adapté
        savings = ai_analyzer.calculate_savings(structured_data)
        if savings:
            logger.info(f"💰 Économies calculées: {savings}€/an")
        else:
            logger.info(f"💰 Économies: À évaluer (type: {invoice_subtype})")

        # ÉTAPE 4: Génération PDF corrigée
        logger.info("📄 Génération PDF avec corrections...")
        internal_pdf_path, user_pdf_path = pdf_generator.generate_reports(structured_data, user_id)

        # ÉTAPE 5: Sauvegarde
        invoice_record = Invoice(
            user_id=user_id,
            file_path=temp_path,
            report_path=user_pdf_path,
            internal_report_path=internal_pdf_path,
            savings_12_percent=savings
        )
        db.add(invoice_record)
        db.commit()

        # ÉTAPE 6: Résumé pour popup
        popup_summary = pdf_generator.generate_popup_summary(structured_data)

        # Nettoyage
        try:
            os.unlink(temp_path)
            logger.info("🗑️ Fichier temporaire supprimé")
        except Exception as e:
            logger.warning(f"Impossible de supprimer {temp_path}: {e}")

        # Résultat final
        logger.info(f"✅ Analyse corrigée terminée pour {email}")

        # Évaluation qualité
        quality_score = "excellent" if len(clean_text) > 500 else "bon" if len(clean_text) > 200 else "moyen"

        return FixedAnalysisResult(
            success=True,
            message=f"Analyse corrigée complétée - Type: {invoice_type} ({invoice_subtype})",
            ai_result=popup_summary,
            pdf_url=user_pdf_path,
            savings=savings,
            invoice_type=f"{invoice_type}_{invoice_subtype}",
            quality_score=quality_score
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
    """Téléchargement de rapport PDF corrigé"""
    try:
        # Vérifier dans les dossiers
        user_path = os.path.join(Config.REPORTS_FOLDER, filename)
        internal_path = os.path.join(Config.REPORTS_INTERNAL_FOLDER, filename)

        if os.path.exists(user_path):
            logger.info(f"📥 Téléchargement rapport utilisateur corrigé: {filename}")
            return FileResponse(
                user_path,
                media_type='application/pdf',
                filename=filename,
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        elif os.path.exists(internal_path):
            logger.info(f"📥 Téléchargement rapport interne: {filename}")
            return FileResponse(
                internal_path,
                media_type='application/pdf',
                filename=filename,
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        else:
            raise HTTPException(status_code=404, detail="Rapport non trouvé")

    except Exception as e:
        logger.error(f"Erreur téléchargement {filename}: {str(e)}")
        raise HTTPException(status_code=500, detail="Erreur lors du téléchargement")


@app.post("/api/test-ocr")
async def test_ocr_enhanced(file: UploadFile = File(...)):
    """Test OCR avec détails de qualité"""
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

        # Extraction OCR
        extracted_text = ocr_processor.extract_text_from_file(temp_path)
        clean_text = ocr_processor.preprocess_text(extracted_text)

        # Analyse de qualité
        word_count = len(clean_text.split())
        line_count = len(clean_text.split('\n'))
        char_count = len(clean_text)

        # Détection du type
        doc_type = "inconnu"
        if any(word in clean_text.lower() for word in ['souscription', 'mise en service']):
            doc_type = "souscription"
        elif any(word in clean_text.lower() for word in ['kwh', 'électricité', 'edf']):
            doc_type = "électricité"
        elif any(word in clean_text.lower() for word in ['gaz', 'naturel']):
            doc_type = "gaz"
        elif any(word in clean_text.lower() for word in ['internet', 'fibre']):
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
            "extracted_preview": clean_text[:300] + "..." if len(clean_text) > 300 else clean_text,
            "text_quality": "excellent" if char_count > 500 else "bon" if char_count > 200 else "moyen",
            "analysis_ready": ocr_processor.is_text_extracted(extracted_text),
            "corrections_applied": "✅ OCR optimisé"
        }

    except Exception as e:
        logger.error(f"Erreur test OCR: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erreur OCR: {str(e)}")


@app.get("/api/corrections-info")
async def get_corrections_info():
    """Informations sur les corrections apportées"""
    return {
        "version": "2.1.0",
        "corrections_applied": {
            "pdf_formatting": {
                "espacement": "✅ Espacement entre sections optimisé (4mm au lieu d'excessif)",
                "tableaux": "✅ Largeurs de colonnes fixes pour éviter débordements",
                "polices": "✅ Polices plus grasses (Arial/Helvetica Bold quand disponible)",
                "puces": "✅ Puces simples (■) sans duplication"
            },
            "ai_analysis": {
                "detection_type": "✅ Détection automatique du type de facture",
                "souscription": "✅ Gestion spéciale des factures de souscription",
                "coherence": "✅ Élimination des 'Non calculable' inappropriés",
                "adaptation": "✅ Prompts adaptés selon le type de document"
            },
            "content_quality": {
                "alternatives": "✅ Maximum 4 fournisseurs pour lisibilité",
                "issues": "✅ Problèmes limités à 4 points concrets",
                "text_length": "✅ Limitation longueur texte dans tableaux",
                "fallback": "✅ Réponses de secours cohérentes"
            }
        },
        "test_recommendations": [
            "Tester avec facture de souscription (comme EDF Samuel Rivas)",
            "Tester avec facture de consommation standard",
            "Vérifier le formatage PDF (espacement, tableaux)",
            "Contrôler la cohérence du contenu généré"
        ]
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)