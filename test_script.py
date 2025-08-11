#!/usr/bin/env python3
"""
Script de test avancé pour l'analyseur de factures avec rapports professionnels
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


def print_section(title):
    """Print a formatted section title"""
    print(f"\n{'=' * 60}")
    print(f"🔵 {title}")
    print('=' * 60)


def print_success(message):
    """Print success message"""
    print(f"✅ {message}")


def print_error(message):
    """Print error message"""
    print(f"❌ {message}")


def print_info(message):
    """Print info message"""
    print(f"ℹ️  {message}")


def test_health_check():
    """Test API health check"""
    print_section("TEST DE SANTÉ DE L'API")
    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=10)
        if response.status_code == 200:
            result = response.json()
            print_success("API accessible")
            print(f"   Status: {result.get('status', 'unknown')}")
            print(f"   Message: {result.get('message', '')}")
            return True
        else:
            print_error(f"API non accessible (Code: {response.status_code})")
            return False
    except Exception as e:
        print_error(f"Impossible de joindre l'API: {e}")
        return False


def test_ocr_extraction(file_path: str):
    """Test OCR text extraction"""
    print_section("TEST D'EXTRACTION OCR")

    if not os.path.exists(file_path):
        print_error(f"Fichier non trouvé: {file_path}")
        return False

    print_info(f"Test OCR sur: {os.path.basename(file_path)}")

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
            print_success("Extraction OCR réussie")
            print(f"   Qualité du texte: {result.get('text_quality', 'unknown')}")
            print(f"   Caractères extraits: {result.get('text_length', 0)}")

            # Show extracted text preview
            extracted_text = result.get('extracted_text', '')
            if extracted_text:
                print(f"   Aperçu du texte:")
                print(f"   {'-' * 40}")
                # Show first 3 lines of extracted text
                lines = extracted_text.split('\n')[:3]
                for line in lines:
                    if line.strip():
                        print(f"   {line.strip()[:60]}...")
                print(f"   {'-' * 40}")

            return result.get('text_quality') == 'good'
        else:
            print_error(f"Erreur OCR (Code: {response.status_code})")
            try:
                error_details = response.json()
                print(f"   Détails: {error_details}")
            except:
                print(f"   Réponse: {response.text[:200]}...")
            return False

    except Exception as e:
        print_error(f"Exception durant le test OCR: {e}")
        return False


def test_full_analysis(file_path: str, test_user_suffix: str = None):
    """Test complete analysis with professional report generation"""
    print_section("TEST D'ANALYSE COMPLÈTE AVEC RAPPORT PROFESSIONNEL")

    if not os.path.exists(file_path):
        print_error(f"Fichier non trouvé: {file_path}")
        return False

    # Generate unique user data
    timestamp = datetime.now().strftime("%H%M%S")
    suffix = test_user_suffix or timestamp

    form_data = {
        'first_name': 'Jean',
        'last_name': f'TestUser{suffix}',
        'email': f'jean.test{suffix}@example.com',
        'phone': f'0123456{suffix[-3:]}',
        'accept_callback': True
    }

    print_info(f"Analyse de: {os.path.basename(file_path)}")
    print_info(f"Utilisateur test: {form_data['email']}")

    try:
        start_time = time.time()

        with open(file_path, 'rb') as f:
            files = {'invoice': (os.path.basename(file_path), f)}
            response = requests.post(
                f"{API_BASE_URL}/api/analyze",
                data=form_data,
                files=files,
                timeout=180  # 3 minutes timeout for AI processing
            )

        duration = time.time() - start_time

        if response.status_code == 200:
            result = response.json()
            print_success(f"Analyse complète réussie ({duration:.1f}s)")

            # Display results
            print(f"\n📊 RÉSULTATS DE L'ANALYSE:")
            print(f"   Message: {result.get('message', 'N/A')}")

            savings = result.get('savings')
            if savings:
                print(f"   💰 Économies potentielles: {savings}€/an")
            else:
                print("   💰 Économies: Non calculées")

            pdf_url = result.get('pdf_url')
            if pdf_url:
                print(f"   📄 Rapport PDF: {os.path.basename(pdf_url)}")

                # Test PDF download
                test_pdf_download(pdf_url)

            # Display AI summary
            ai_summary = result.get('ai_result', '')
            if ai_summary:
                print(f"\n🤖 RÉSUMÉ IA:")
                print(f"   {'-' * 50}")
                # Show first few lines of summary
                lines = ai_summary.split('\n')[:5]
                for line in lines:
                    if line.strip():
                        print(f"   {line.strip()}")
                if len(ai_summary.split('\n')) > 5:
                    print("   ...")
                print(f"   {'-' * 50}")

            return True

        else:
            print_error(f"Erreur analyse (Code: {response.status_code})")
            try:
                error_details = response.json()
                print(f"   Erreur: {error_details.get('detail', 'Erreur inconnue')}")
            except:
                print(f"   Réponse brute: {response.text[:300]}...")
            return False

    except Exception as e:
        print_error(f"Exception durant l'analyse: {e}")
        return False


def test_pdf_download(pdf_path: str):
    """Test PDF report download"""
    print_section("TEST DE TÉLÉCHARGEMENT DU RAPPORT")

    try:
        filename = os.path.basename(pdf_path)
        response = requests.get(
            f"{API_BASE_URL}/api/download-report/{filename}",
            timeout=30
        )

        if response.status_code == 200:
            # Save downloaded PDF
            output_path = f"downloaded_{filename}"
            with open(output_path, 'wb') as f:
                f.write(response.content)

            file_size = len(response.content)
            print_success("Téléchargement du rapport réussi")
            print(f"   Taille du fichier: {file_size:,} bytes")
            print(f"   Fichier sauvé: {output_path}")

            # Basic PDF validation
            if response.content.startswith(b'%PDF'):
                print_success("Format PDF valide")
            else:
                print_error("Format PDF invalide")

            return True
        else:
            print_error(f"Erreur téléchargement (Code: {response.status_code})")
            return False

    except Exception as e:
        print_error(f"Exception durant le téléchargement: {e}")
        return False


def find_test_files():
    """Find available test files"""
    possible_files = [
        "rapport_comparatif_gaz.pdf",
        "rapport_comparatif_electricite.pdf",
        "facture_test.pdf",
        "sample_invoice.pdf",
        "test.pdf"
    ]

    found_files = []
    for filename in possible_files:
        if os.path.exists(filename):
            found_files.append(filename)

    return found_files


def run_comprehensive_test():
    """Run comprehensive test suite"""
    print("🚀 ANALYSEUR DE FACTURES - TESTS COMPLETS")
    print("🎯 Version avec rapports professionnels améliorés")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Test 1: Health check
    if not test_health_check():
        print_error("API non accessible - Arrêt des tests")
        return False

    # Find test files
    test_files = find_test_files()

    if not test_files:
        print_section("RECHERCHE DE FICHIERS DE TEST")
        print_info("Aucun fichier de test trouvé automatiquement")

        # Ask user for file path
        file_path = input("\n📁 Entrez le chemin vers un fichier PDF de facture (ou ENTER pour passer): ")
        if file_path and os.path.exists(file_path):
            test_files = [file_path]
        else:
            print_error("Aucun fichier de test disponible")
            return False

    # Run tests on found files
    overall_success = True

    for i, file_path in enumerate(test_files):
        print(f"\n🔄 TEST {i + 1}/{len(test_files)}: {os.path.basename(file_path)}")

        # Test OCR
        ocr_success = test_ocr_extraction(file_path)

        if ocr_success:
            # Test full analysis
            analysis_success = test_full_analysis(file_path, str(i + 1))
            if not analysis_success:
                overall_success = False
        else:
            print_error("OCR échoué - Passage du test d'analyse")
            overall_success = False

        # Small delay between tests
        if i < len(test_files) - 1:
            time.sleep(2)

    # Final summary
    print_section("RÉSUMÉ FINAL")
    if overall_success:
        print_success("Tous les tests ont réussi ! 🎉")
        print_info("Les rapports générés utilisent le nouveau format professionnel")
        print_info("Vérifiez les fichiers PDF téléchargés pour voir les améliorations")
    else:
        print_error("Certains tests ont échoué")
        print_info("Vérifiez les logs ci-dessus pour plus de détails")

    return overall_success


def main():
    """Main function"""
    try:
        success = run_comprehensive_test()
        exit_code = 0 if success else 1

        print(f"\n{'🎉' if success else '⚠️ '} Tests terminés (Code de sortie: {exit_code})")

        if success:
            print("\n💡 CONSEILS POUR LA SUITE:")
            print("   - Consultez les rapports PDF téléchargés")
            print("   - Comparez avec les exemples fournis")
            print("   - Testez avec vos propres factures")
            print("   - Consultez la documentation sur http://localhost:8000/docs")

        return exit_code

    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrompus par l'utilisateur")
        return 1
    except Exception as e:
        print(f"\n\n❌ Erreur inattendue: {e}")
        return 1


if __name__ == "__main__":
    exit(main())