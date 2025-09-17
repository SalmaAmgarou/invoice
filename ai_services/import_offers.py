import json
from sqlalchemy.orm import Session
from database import SessionLocal, OffreEnergie, create_tables  # On importe depuis vos fichiers
from config import Config

# Le chemin vers votre fichier JSON contenant les offres
JSON_FILE_PATH = 'donnees_energie.json'


def populate_offers():
    """
    Script pour lire le fichier JSON et peupler la table offres_energie
    en utilisant la session SQLAlchemy du projet.
    """
    # On crée une session de base de données, comme dans votre application
    db: Session = SessionLocal()
    print("✅ Connexion à la base de données via SQLAlchemy réussie.")

    try:
        # Charger les données depuis le fichier JSON
        with open(JSON_FILE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)

        total_inserted = 0

        # --- Vider la table avant d'insérer de nouvelles données ---
        # C'est une bonne pratique pour éviter les doublons à chaque exécution
        num_rows_deleted = db.query(OffreEnergie).delete()
        db.commit()
        print(f"🧹 Anciennes données purgées : {num_rows_deleted} offres supprimées.")

        # --- Traitement des offres d'électricité ---
        for offre_data in data.get('offres_electricite', []):
            new_offer = OffreEnergie(
                type_service='electricite',
                fournisseur=offre_data.get('fournisseur'),
                nom_offre=offre_data.get('nom_offre'),
                prix_unite_ttc=offre_data.get('prix_kwh_ttc'),
                unite_prix='€/kWh',
                abonnement_annuel_ttc=offre_data.get('abonnement_annuel_ttc'),
                budget_annuel_estime=offre_data.get('budget_annuel_6000kwh'),
                economie_vs_reference=-offre_data.get('economie_vs_trv', 0),
                economie_vs_reference_pct=-offre_data.get('economie_vs_trv_pct', 0),
                type_prix=offre_data.get('type_prix'),
                duree_engagement=offre_data.get('duree_engagement'),
                energie_verte_pct=offre_data.get('energie_verte_pct'),
                caracteristiques=offre_data.get('caracteristiques'),
                classement_comparateurs=offre_data.get('classement_comparateurs'),
                details={"option_verte": offre_data.get('option_verte'), "label_vert": offre_data.get('label_vert')}
            )
            db.add(new_offer)
            total_inserted += 1

        # --- Traitement des offres de gaz ---
        for offre_data in data.get('offres_gaz', []):
            new_offer = OffreEnergie(
                type_service='gaz',
                fournisseur=offre_data.get('fournisseur'),
                nom_offre=offre_data.get('nom_offre'),
                prix_unite_ttc=offre_data.get('prix_kwh_ttc'),
                unite_prix='€/kWh',
                abonnement_annuel_ttc=offre_data.get('abonnement_annuel_ttc'),
                budget_annuel_estime=offre_data.get('budget_annuel_10000kwh'),
                economie_vs_reference=-offre_data.get('economie_vs_prvg', 0),
                economie_vs_reference_pct=-offre_data.get('economie_vs_prvg_pct', 0),
                type_prix=offre_data.get('type_prix'),
                duree_engagement=offre_data.get('duree_engagement'),
                energie_verte_pct=offre_data.get('energie_verte_pct'),
                caracteristiques=offre_data.get('caracteristiques'),
                classement_comparateurs=offre_data.get('classement_comparateurs'),
                details={"option_biogaz": offre_data.get('option_biogaz'), "type_biogaz": offre_data.get('type_biogaz')}
            )
            db.add(new_offer)
            total_inserted += 1

        # --- Traitement des offres duales ---
        for offre_data in data.get('offres_duales', []):
            details_duale = {
                "prix_kwh_electricite_ttc": offre_data.get('prix_kwh_electricite_ttc'),
                "prix_kwh_gaz_ttc": offre_data.get('prix_kwh_gaz_ttc'),
                "abonnement_electricite_ttc": offre_data.get('abonnement_electricite_ttc'),
                "abonnement_gaz_ttc": offre_data.get('abonnement_gaz_ttc'),
                "energie_verte_electricite_pct": offre_data.get('energie_verte_electricite_pct'),
                "energie_verte_gaz_pct": offre_data.get('energie_verte_gaz_pct')
            }
            new_offer = OffreEnergie(
                type_service='duale',
                fournisseur=offre_data.get('fournisseur'),
                nom_offre=offre_data.get('nom_offre'),
                budget_annuel_estime=offre_data.get('budget_annuel_dual'),
                economie_vs_reference=-offre_data.get('economie_vs_references', 0),
                economie_vs_reference_pct=-offre_data.get('economie_vs_references_pct', 0),
                type_prix=offre_data.get('type_prix'),
                duree_engagement=offre_data.get('duree_engagement'),
                caracteristiques=offre_data.get('caracteristiques'),
                classement_comparateurs=offre_data.get('classement_comparateurs'),
                details=details_duale
            )
            db.add(new_offer)
            total_inserted += 1

        # --- Traitement des distributeurs d'eau ---
        for dist_data in data.get('distributeurs_eau', []):
            abonnement = dist_data.get('abonnement_annuel_ttc')
            try:
                abonnement_float = float(abonnement) if abonnement and str(abonnement).replace('.', '',
                                                                                               1).isdigit() else None
            except (ValueError, TypeError):
                abonnement_float = None

            new_offer = OffreEnergie(
                type_service='eau',
                fournisseur=dist_data.get('distributeur'),
                nom_offre=dist_data.get('type'),
                zone_desserte=dist_data.get('zone_desserte'),
                prix_unite_ttc=dist_data.get('prix_m3_ttc'),
                unite_prix='€/m³',
                abonnement_annuel_ttc=abonnement_float,
                budget_annuel_estime=dist_data.get('budget_annuel_120m3'),
                caracteristiques=dist_data.get('caracteristiques')
            )
            db.add(new_offer)
            total_inserted += 1

        # On valide toutes les transactions en une seule fois
        db.commit()
        print(f"🎉 Opération terminée. {total_inserted} offres ont été insérées dans la table 'offres_energie'.")

    except FileNotFoundError:
        print(f"❌ Erreur : Le fichier '{JSON_FILE_PATH}' est introuvable.")
    except Exception as e:
        print(f"❌ Une erreur est survenue : {e}")
        db.rollback()  # En cas d'erreur, on annule tout
    finally:
        db.close()
        print("🔌 Connexion à la base de données fermée.")


if __name__ == "__main__":
    # La première fois, assurez-vous que la table est créée
    print("Création des tables si elles n'existent pas...")
    create_tables()

    # Ensuite, on peuple la table avec les données du JSON
    populate_offers()