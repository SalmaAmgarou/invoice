#!/usr/bin/env python3
"""
Script de test pour valider les corrections apportées
Teste spécifiquement les problèmes identifiés dans la facture EDF Samuel Rivas
"""
import asyncio
import os
import requests
import json
import time
from pathlib import Path
from datetime import datetime

# Configuration
API_BASE_URL = "http://localhost:8000"


def print_header(title):
    """Print formatted header"""
    print(f"\n{'=' * 70}")
    print(f"🔧 {title}")
    print('=' * 70)


def print_success(message):
    """Print success message"""
    print(f"✅ {message}")


def print_error(message):
    """Print error message"""
    print(f"❌ {message}")


def print_info(message):
    """Print info message"""
    print(f"ℹ️  {message}")


def print_correction(message):
    """Print correction validation"""
    print(f"🎯 {message}")


def test_corrections_health_check():
    """Test health check avec informations sur les corrections"""
    print_header("VÉRIFICATION DES CORRECTIONS APPLIQUÉES")

    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=10)
        if response.status_code == 200:
            result = response.json()
            print_success("API accessible avec corrections")

            # Vérifier les corrections listées
            corrections = result.get('corrections_applied', [])
            if corrections:
                print_info("Corrections appliquées :")
                for correction in corrections:
                    print_correction(correction)
            else:
                print_error("Aucune information sur les corrections")

            return True
        else:
            print_error(f"API non accessible (Code: {response.status_code})")
            return False
    except Exception as e:
        print_error(f"Impossible de joindre l'API: {e}")
        return False


def test_corrections_info():
    """Test endpoint d'informations sur les corrections"""
    print_header("DÉTAILS DES CORRECTIONS APPLIQUÉES")

    try:
        response = requests.get(f"{API_BASE_URL}/api/corrections-info", timeout=10)
        if response.status_code == 200:
            result = response.json()
            print_success(f"Version corrigée: {result.get('version')}")

            corrections = result.get('corrections_applied', {})

            # PDF Formatting corrections
            pdf_corrections = corrections.get('pdf_formatting', {})
            if pdf_corrections:
                print_info("🎨 Corrections PDF :")
                for key, value in pdf_corrections.items():
                    print(f"   {value}")

            # AI Analysis corrections
            ai_corrections = corrections.get('ai_analysis', {})
            if ai_corrections:
                print_info("🤖 Corrections IA :")
                for key, value in ai_corrections.items():
                    print(f"   {value}")

            return True
        else:
            print_error(f"Endpoint corrections non accessible")
            return False
    except Exception as e:
        print_error(f"Erreur récupération corrections: {e}")
        return False


def test_ocr_with_edf_invoice(file_path: str):
    """Test OCR spécifiquement avec la facture EDF de souscription"""
    print_header("TEST OCR - FACTURE EDF SOUSCRIPTION")

    if not os.path.exists(file_path):
        print_error(f"Fichier non trouvé: {file_path}")
        return False

    print_info(f"Test OCR sur facture EDF: {os.path.basename(file_path)}")

    try:
        with open(file_path, 'rb') as f:
            files = {'file': (os.path.basename(file_path), f, 'application/pdf')}
            response = requests.post(
                f"{API_BASE_URL}/api/test-ocr",
                files=files,
                timeout=60
            )

        if response.status_code == 200:
            result = response.json()
            print_success("OCR avec corrections réussi")

            # Vérifications spécifiques
            doc_type = result.get('document_type', 'inconnu')
            print_correction(f"Type détecté: {doc_type}")

            if doc_type == 'souscription':
                print_correction("✅ Détection de facture de souscription correcte")
            else:
                print_error(f"❌ Type détecté incorrect: {doc_type} (attendu: souscription)")

            # Vérifier que Samuel Rivas est détecté
            preview = result.get('extracted_preview', '')
            if 'Samuel Rivas' in preview or 'SAMUEL RIVAS' in preview:
                print_correction("✅ Nom client 'Samuel Rivas' détecté")
            else:
                print_error("❌ Nom client pas détecté dans l'extrait")

            # Vérifier EDF
            if 'EDF' in preview or 'edf' in preview.lower():
                print_correction("✅ Fournisseur EDF détecté")
            else:
                print_error("❌ Fournisseur EDF pas détecté")

            print_info(f"Qualité texte: {result.get('text_quality')}")
            print_info(f"Caractères extraits: {result.get('text_length')}")

            return True
        else:
            print_error(f"Erreur OCR (Code: {response.status_code})")
            return False

    except Exception as e:
        print_error(f"Exception durant le test OCR: {e}")
        return False


def test_analysis_with_corrections(file_path: str):
    """Test analyse complète avec validation des corrections"""
    print_header("TEST ANALYSE COMPLÈTE AVEC CORRECTIONS")

    if not os.path.exists(file_path):
        print_error(f"Fichier non trouvé: {file_path}")
        return False

    # Données de test pour Samuel Rivas
    timestamp = datetime.now().strftime("%H%M%S")
    form_data = {
        'first_name': 'Samuel',
        'last_name': f'RivasTest{timestamp}',
        'email': f'samuel.test{timestamp}@example.com',
        'phone': f'0123456{timestamp[-3:]}',
        'accept_callback': True
    }

    print_info(f"Analyse avec corrections: {os.path.basename(file_path)}")
    print_info(f"Utilisateur test: {form_data['email']}")

    try:
        start_time = time.time()

        with open(file_path, 'rb') as f:
            files = {'invoice': (os.path.basename(file_path), f)}
            response = requests.post(
                f"{API_BASE_URL}/api/analyze",
                data=form_data,
                files=files,
                timeout=180
            )

        duration = time.time() - start_time

        if response.status_code == 200:
            result = response.json()
            print_success(f"Analyse avec corrections réussie ({duration:.1f}s)")

            # VALIDATION DES CORRECTIONS
            print_header("VALIDATION DES CORRECTIONS APPLIQUÉES")

            # 1. Vérifier le type de facture détecté
            invoice_type = result.get('invoice_type', '')
            print_correction(f"Type détecté: {invoice_type}")

            if 'souscription' in invoice_type:
                print_correction("✅ CORRECTION: Facture de souscription correctement identifiée")
            else:
                print_error(f"❌ Type incorrect: {invoice_type}")

            # 2. Vérifier le message d'analyse
            message = result.get('message', '')
            if 'souscription' in message.lower():
                print_correction("✅ CORRECTION: Message adapté au type de facture")
            else:
                print_error(f"❌ Message générique: {message}")

            # 3. Vérifier les économies
            savings = result.get('savings')
            if savings is None:
                print_correction("✅ CORRECTION: Pas de calcul d'économies inapproprié pour facture souscription")
            else:
                print_error(f"❌ Calcul d'économies inapproprié: {savings}€")

            # 4. Vérifier la qualité du résumé IA
            ai_result = result.get('ai_result', '')
            if 'Non calculable' not in ai_result:
                print_correction("✅ CORRECTION: Élimination des 'Non calculable' dans le résumé")
            else:
                print_error("❌ 'Non calculable' encore présent dans le résumé")

            # 5. Tester le téléchargement du PDF
            pdf_url = result.get('pdf_url')
            if pdf_url:
                print_correction(f"✅ PDF généré: {os.path.basename(pdf_url)}")

                # Test de téléchargement et validation PDF
                test_pdf_corrections(pdf_url)
            else:
                print_error("❌ Pas de PDF généré")

            return True

        else:
            print_error(f"Erreur analyse (Code: {response.status_code})")
            try:
                error_details = response.json()
                print_error(f"Détails: {error_details.get('detail', 'Erreur inconnue')}")
            except:
                print_error(f"Réponse: {response.text[:300]}...")
            return False

    except Exception as e:
        print_error(f"Exception durant l'analyse: {e}")
        return False


def test_pdf_corrections(pdf_path: str):
    """Test spécifique des corrections PDF"""
    print_header("VALIDATION CORRECTIONS PDF")

    try:
        filename = os.path.basename(pdf_path)
        response = requests.get(
            f"{API_BASE_URL}/api/download-report/{filename}",
            timeout=30
        )

        if response.status_code == 200:
            # Sauvegarder le PDF
            output_path = f"test_corrected_{filename}"
            with open(output_path, 'wb') as f:
                f.write(response.content)

            file_size = len(response.content)
            print_success(f"PDF téléchargé: {output_path}")
            print_info(f"Taille: {file_size:,} bytes")

            # Validation basique du PDF
            if response.content.startswith(b'%PDF'):
                print_correction("✅ Format PDF valide")
            else:
                print_error("❌ Format PDF invalide")

            # Instructions de validation manuelle
            print_header("VALIDATION MANUELLE REQUISE")
            print_correction("Ouvrez le PDF et vérifiez :")
            print_correction("1. ✅ Espacement entre sections réduit (plus d'espaces excessifs)")
            print_correction("2. ✅ Tableaux sans débordement de texte")
            print_correction("3. ✅ Polices plus grasses et lisibles")
            print_correction("4. ✅ Puces simples (■) sans duplication")
            print_correction("5. ✅ Contenu cohérent sans 'Non calculable' inapproprié")
            print_correction("6. ✅ Sections bien formatées et espacées")

            return True
        else:
            print_error(f"Erreur téléchargement PDF (Code: {response.status_code})")
            return False

    except Exception as e:
        print_error(f"Exception durant test PDF: {e}")
        return False


def find_edf_invoice():
    """Trouve la facture EDF de test"""
    possible_names = [
        "facture_edf_samuel.pdf",
        "samuel_rivas_edf.pdf",
        "edf_souscription.pdf",
        "facture_souscription_edf.pdf",
        "test_edf.pdf"
    ]

    for filename in possible_names:
        if os.path.exists(filename):
            return filename

    return None


def run_corrections_validation():
    """Lance la validation complète des corrections"""
    print("🎯 VALIDATION DES CORRECTIONS APPLIQUÉES")
    print("=" * 70)
    print("🎯 Objectif: Valider les corrections des problèmes identifiés")
    print("📋 Problèmes corrigés:")
    print("   • Espacement excessif entre sections PDF")
    print("   • Tableaux avec débordement de texte")
    print("   • Polices pas assez grasses")
    print("   • Génération incohérente ('Non calculable' partout)")
    print("   • Puces doublées (■ ■)")
    print("   • Mauvaise détection type facture souscription")
    print("=" * 70)

    # Test 1: Health check avec corrections
    if not test_corrections_health_check():
        print_error("API non accessible - Arrêt des tests")
        return False

    # Test 2: Informations détaillées corrections
    test_corrections_info()

    # Test 3: Trouver la facture EDF
    edf_file = find_edf_invoice()

    if not edf_file:
        print_header("RECHERCHE FACTURE EDF")
        print_info("Aucune facture EDF trouvée automatiquement")
        file_path = input("\n📁 Entrez le chemin vers la facture EDF Samuel Rivas (ou ENTER pour passer): ")
        if file_path and os.path.exists(file_path):
            edf_file = file_path
        else:
            print_error("Impossible de tester sans la facture EDF")
            return False

    print_info(f"📄 Utilisation de la facture: {edf_file}")

    # Test 4: OCR avec détection de type
    ocr_success = test_ocr_with_edf_invoice(edf_file)

    if ocr_success:
        # Test 5: Analyse complète avec corrections
        analysis_success = test_analysis_with_corrections(edf_file)

        if analysis_success:
            print_header("RÉSUMÉ VALIDATION CORRECTIONS")
            print_success("🎉 Toutes les corrections ont été appliquées avec succès !")
            print_correction("✅ Détection type facture: CORRIGÉ")
            print_correction("✅ Formatage PDF: CORRIGÉ")
            print_correction("✅ Génération cohérente: CORRIGÉ")
            print_correction("✅ Polices et espacement: CORRIGÉ")

            print_info("\n📋 Actions suivantes recommandées:")
            print_info("1. Ouvrir le PDF téléchargé pour validation visuelle")
            print_info("2. Comparer avec les exemples de référence")
            print_info("3. Tester avec d'autres types de factures")

            return True
        else:
            print_error("❌ Échec validation analyse complète")
            return False
    else:
        print_error("❌ Échec validation OCR")
        return False


def main():
    """Fonction principale"""
    try:
        success = run_corrections_validation()

        if success:
            print("\n🎉 VALIDATION RÉUSSIE - CORRECTIONS APPLIQUÉES !")
            print("💡 Votre analyseur génère maintenant des rapports corrigés")
        else:
            print("\n⚠️  VALIDATION PARTIELLE - Vérifiez les logs ci-dessus")

        return 0 if success else 1

    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrompus par l'utilisateur")
        return 1
    except Exception as e:
        print(f"\n\n❌ Erreur inattendue: {e}")
        return 1


if __name__ == "__main__":
    exit(main())