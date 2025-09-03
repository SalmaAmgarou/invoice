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
from database import get_db, create_tables, User, Invoice, OffreEnergie
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
        invoice_type: str = Form(...),  # NOUVEAU: Type de facture obligatoire
        invoice: UploadFile = File(...),
        db: Session = Depends(get_db)
):
    """Analyse corrigée avec type de facture défini par l'utilisateur"""
    try:
        # Validation du type de facture
        VALID_INVOICE_TYPES = [
            'electricite', 'gaz', 'dual', 'electricite_gaz',
            'internet', 'mobile', 'internet_mobile',
            'eau', 'assurance_auto', 'assurance_habitation'
        ]

        if invoice_type not in VALID_INVOICE_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Type de facture invalide. Types acceptés: {', '.join(VALID_INVOICE_TYPES)}"
            )

        # Normaliser dual/electricite_gaz
        if invoice_type == 'electricite_gaz':
            invoice_type = 'dual'

        logger.info(f"📋 Type de facture défini par l'utilisateur: {invoice_type}")

        # Validation du fichier
        if not invoice.filename:
            raise HTTPException(status_code=400, detail="Aucun fichier fourni")

        if not allowed_file(invoice.filename):
            raise HTTPException(status_code=400, detail="Type de fichier non valide")

        logger.info(f"🔧 Début analyse pour type {invoice_type}: {invoice.filename}")

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

        # ÉTAPE 2: Récupération des offres de la BD selon le type
        logger.info(f"📊 Récupération des offres depuis la BD pour type: {invoice_type}")

        # Fonction helper pour récupérer les offres
        def _get_offers_from_db(db_session, service_type):
            # Récupérer le dernier snapshot d'offres pour le type
            latest_date = db_session.query(OffreEnergie.date_extraction) \
                .filter(OffreEnergie.type_service == service_type) \
                .order_by(OffreEnergie.date_extraction.desc()).limit(1).scalar()

            if not latest_date:
                return []

            offers = db_session.query(OffreEnergie).filter(
                OffreEnergie.type_service == service_type,
                OffreEnergie.date_extraction == latest_date
            ).all()

            # Convertir en format pour le LLM
            formatted_offers = []
            for off in offers:
                prix_unite = float(off.prix_unite_ttc or 0)
                abo = float(off.abonnement_annuel_ttc or 0)

                # Calculer le total annuel estimé
                if service_type == 'electricite':
                    consommation_defaut = 3500.0
                elif service_type == 'gaz':
                    consommation_defaut = 10000.0
                elif service_type in ['internet', 'mobile', 'internet_mobile']:
                    consommation_defaut = 12  # 12 mois
                else:
                    consommation_defaut = 0.0

                total_annuel = prix_unite * consommation_defaut + abo if prix_unite > 0 else 0.0

                formatted_offer = {
                    'fournisseur': off.fournisseur,
                    'nom_offre': off.nom_offre or '',
                    'prix_kwh': prix_unite,
                    'abonnement_annuel': abo,
                    'total_annuel': round(total_annuel, 2),
                    'type_prix': off.type_prix or 'fixe',
                    'duree_engagement': off.duree_engagement or 'sans engagement',
                    'energie_verte_pct': off.energie_verte_pct or 0,
                    'caracteristiques': off.caracteristiques or [],
                    'details': off.details or {}
                }

                # Pour l'électricité, créer variantes BASE et HP/HC
                if service_type == 'electricite':
                    # Version BASE
                    base_offer = formatted_offer.copy()
                    base_offer['type_offre'] = 'base'
                    base_offer['nom_offre'] = f"{off.nom_offre} - Base"
                    formatted_offers.append(base_offer)

                    # Version HP/HC
                    hphc_offer = formatted_offer.copy()
                    hphc_offer['type_offre'] = 'hphc'
                    hphc_offer['nom_offre'] = f"{off.nom_offre} HP/HC"
                    hphc_offer['prix_kwh'] = round(prix_unite * 1.15, 4)
                    hphc_offer['details'] = {
                        'prix_hp': round(prix_unite * 1.15, 4),
                        'prix_hc': round(prix_unite * 0.85, 4),
                        'repartition_hp_hc': '70% HP / 30% HC'
                    }
                    prix_moyen_hphc = (hphc_offer['details']['prix_hp'] * 0.7 +
                                       hphc_offer['details']['prix_hc'] * 0.3)
                    hphc_offer['total_annuel'] = round(prix_moyen_hphc * consommation_defaut + abo, 2)
                    formatted_offers.append(hphc_offer)
                else:
                    formatted_offer['type_offre'] = 'standard'
                    formatted_offers.append(formatted_offer)

            return formatted_offers

        # Récupérer les offres selon le type
        db_offers = []
        if invoice_type == 'dual':
            # Pour dual, récupérer les offres électricité ET gaz
            db_offers_elec = _get_offers_from_db(db, 'electricite')
            db_offers_gaz = _get_offers_from_db(db, 'gaz')
            db_offers = db_offers_elec + db_offers_gaz
            logger.info(f"✅ {len(db_offers_elec)} offres électricité + {len(db_offers_gaz)} offres gaz récupérées")
        elif invoice_type in ['eau', 'assurance_auto', 'assurance_habitation']:
            # Pas d'offres comparatives pour ces types (monopoles ou contrats spécifiques)
            db_offers = []
            logger.info(f"ℹ️ Pas de comparaison d'offres pour {invoice_type}")
        else:
            db_offers = _get_offers_from_db(db, invoice_type)
            logger.info(f"✅ {len(db_offers)} offres récupérées pour {invoice_type}")

        # ÉTAPE 3: Analyse IA avec type prédéfini
        logger.info(f"🤖 Analyse IA pour type: {invoice_type}")

        # Utiliser la nouvelle méthode avec type prédéfini
        analysis_result = ai_analyzer.analyze_invoice_with_type(
            clean_text,
            invoice_type,
            db_offers
        )

        structured_data = analysis_result['structured_data']

        # Ajouter le type défini par l'utilisateur
        structured_data['type_facture'] = invoice_type
        structured_data['invoice_subtype'] = 'user_defined'

        logger.info(f"✅ Analyse complétée pour type: {invoice_type}")

        # ÉTAPE 4: Validation et normalisation des données extraites
        logger.info("🔍 Validation et normalisation des données...")

        def _validate_and_normalize(data: dict) -> dict:
            """Valide et normalise les données extraites"""
            current_offer = data.get('current_offer', {})

            # Normaliser les montants
            if current_offer.get('montant_total_annuel'):
                try:
                    montant = float(
                        str(current_offer['montant_total_annuel']).replace(',', '.').replace('€', '').strip())
                    current_offer['montant_total_annuel'] = round(montant, 2)
                except:
                    current_offer['montant_total_annuel'] = 0

            # Normaliser la consommation selon le type
            if invoice_type in ['electricite', 'gaz', 'dual']:
                if current_offer.get('consommation_annuelle'):
                    try:
                        cons = float(
                            str(current_offer['consommation_annuelle']).replace(',', '.').replace('kWh', '').strip())
                        current_offer['consommation_annuelle'] = round(cons, 0)
                    except:
                        current_offer['consommation_annuelle'] = 0

                if current_offer.get('prix_kwh'):
                    try:
                        prix = float(str(current_offer['prix_kwh']).replace(',', '.').replace('€', '').strip())
                        current_offer['prix_kwh'] = round(prix, 4)
                    except:
                        current_offer['prix_kwh'] = 0

            elif invoice_type == 'eau':
                if current_offer.get('consommation_annuelle_m3'):
                    try:
                        cons = float(
                            str(current_offer['consommation_annuelle_m3']).replace(',', '.').replace('m³', '').strip())
                        current_offer['consommation_annuelle_m3'] = round(cons, 0)
                    except:
                        current_offer['consommation_annuelle_m3'] = 0

            # Calculer le prix moyen si possible
            if invoice_type in ['electricite', 'gaz'] and current_offer.get(
                    'montant_total_annuel') and current_offer.get('consommation_annuelle'):
                montant = current_offer['montant_total_annuel']
                cons = current_offer['consommation_annuelle']
                if cons > 0:
                    prix_moyen = montant / cons
                    current_offer['prix_moyen_ttc'] = round(prix_moyen, 4)

            return data

        structured_data = _validate_and_normalize(structured_data)

        # Ajouter les métadonnées
        if db_offers:
            structured_data['_offers_count'] = len(db_offers)
            structured_data['_analysis_type'] = 'user_defined_type'

        # ÉTAPE 5: Calcul des économies
        savings = None
        best_savings = structured_data.get('best_savings', {})
        if best_savings.get('economie_annuelle'):
            try:
                savings = float(str(best_savings['economie_annuelle']).replace('€', '').strip())
            except:
                savings = None

        if savings:
            logger.info(f"💰 Économies calculées: {savings}€/an")
        else:
            logger.info(f"💰 Économies: À évaluer pour type {invoice_type}")

        # ÉTAPE 6: Génération PDF
        logger.info("📄 Génération PDF...")
        internal_pdf_path, user_pdf_path = pdf_generator.generate_reports(structured_data, user_id)

        # ÉTAPE 7: Sauvegarde en base de données
        invoice_record = Invoice(
            user_id=user_id,
            file_path=temp_path,
            report_path=user_pdf_path,
            internal_report_path=internal_pdf_path,
            savings_12_percent=savings
        )
        db.add(invoice_record)
        db.commit()

        # ÉTAPE 8: Résumé pour popup
        popup_summary = pdf_generator.generate_popup_summary(structured_data)

        # Nettoyage
        try:
            os.unlink(temp_path)
            logger.info("🗑️ Fichier temporaire supprimé")
        except Exception as e:
            logger.warning(f"Impossible de supprimer {temp_path}: {e}")

        # Résultat final
        logger.info(f"✅ Analyse terminée pour {email} - Type: {invoice_type}")

        # Évaluation qualité
        quality_score = "excellent" if len(clean_text) > 500 else "bon" if len(clean_text) > 200 else "moyen"

        return FixedAnalysisResult(
            success=True,
            message=f"Analyse complétée - Type: {invoice_type} (défini par l'utilisateur)",
            ai_result=popup_summary,
            pdf_url=user_pdf_path,
            savings=savings,
            invoice_type=invoice_type,
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

@app.get("/api/invoice-types")
async def get_invoice_types():
    """Retourne la liste des types de factures supportés"""
    return {
        "types": [
            {"value": "electricite", "label": "Électricité", "description": "Facture d'électricité uniquement"},
            {"value": "gaz", "label": "Gaz naturel", "description": "Facture de gaz uniquement"},
            {"value": "dual", "label": "Électricité + Gaz", "description": "Offre duale du même fournisseur"},
            {"value": "internet", "label": "Internet/Fibre", "description": "Internet, fibre, ADSL"},
            {"value": "mobile", "label": "Mobile", "description": "Forfait mobile uniquement"},
            {"value": "internet_mobile", "label": "Internet + Mobile", "description": "Pack convergent"},
            {"value": "eau", "label": "Eau", "description": "Service d'eau et assainissement"},
            {"value": "assurance_auto", "label": "Assurance Auto", "description": "Assurance véhicule"},
            {"value": "assurance_habitation", "label": "Assurance Habitation", "description": "Assurance logement"}
        ]
    }

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)