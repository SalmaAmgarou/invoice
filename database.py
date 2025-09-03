from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, DECIMAL, Boolean, ForeignKey, Date, JSON
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.sql import func
from config import Config
from sqlalchemy.ext.declarative import declarative_base  # Corrigé pour être cohérent

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    # ... (votre classe User reste inchangée)
    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    phone = Column(String(30), nullable=False)
    password = Column(String(255), nullable=True)
    accept_callback = Column(Boolean, default=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    invoices = relationship("Invoice", back_populates="user", cascade="all, delete-orphan")


class Invoice(Base):
    __tablename__ = "invoices"
    # ... (votre classe Invoice reste inchangée)
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    file_path = Column(String(255), nullable=False)
    report_path = Column(String(255), nullable=True)
    internal_report_path = Column(String(512), nullable=True)
    savings_12_percent = Column(DECIMAL(10, 2), nullable=True)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    user = relationship("User", back_populates="invoices")


# ==============================================================================
# === NOUVELLE CLASSE MODÈLE POUR LES OFFRES D'ÉNERGIE ===
# ==============================================================================
class OffreEnergie(Base):
    __tablename__ = "offres_energie"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date_extraction = Column(Date, nullable=False, default=func.current_date())

    # --- Champs d'identification ---
    type_service = Column(String(50), nullable=False)    # 'electricite', 'gaz', 'duale', 'eau'
    fournisseur = Column(String(255), nullable=False)
    nom_offre = Column(String(255))
    zone_desserte = Column(String(255))

    # --- Champs de prix ---
    prix_unite_ttc = Column(DECIMAL(10, 5))
    unite_prix = Column(String(20))  # '€/kWh' ou '€/m³'
    abonnement_annuel_ttc = Column(DECIMAL(10, 2))

    # --- Champs de coût et économie ---
    budget_annuel_estime = Column(DECIMAL(10, 2))
    economie_vs_reference = Column(DECIMAL(10, 2))
    economie_vs_reference_pct = Column(DECIMAL(5, 2))

    # --- Caractéristiques ---
    type_prix = Column(String(50))
    duree_engagement = Column(String(100))
    energie_verte_pct = Column(Integer)
    caracteristiques = Column(JSON)  # Pour stocker des listes
    classement_comparateurs = Column(String(255))

    # --- Champ flexible ---
    details = Column(JSON)  # Pour les détails spécifiques (prix duals, etc.)


# ==============================================================================


# --- Le reste de votre fichier reste inchangé ---
engine = create_engine(Config.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def create_tables():
    """Crée toutes les tables, y compris la nouvelle table offres_energie"""
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()