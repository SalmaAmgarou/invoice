
# README — Invoice OCR API V1

## Présentation

Ce projet est une **API FastAPI** permettant d’analyser des factures (PDF ou images) et de générer des rapports au format **PDF**.
Deux modes sont disponibles :

1. **Mode synchrone** → L’API renvoie directement le rapport encodé en base64.
2. **Mode asynchrone (jobs avec Celery)** → Les traitements lourds sont délégués à un worker Celery, et les résultats sont envoyés via webhook. *(non prioritaire pour la première intégration)*.

---

## Architecture du projet

```
invoice_ocr/
│── api/                # Application FastAPI (endpoints)
│   └── app.py
│── services/           # Moteur de génération et OCR
│   └── reporting/
│       └── engine.py
│── celery_app.py       # Configuration Celery (broker + backend Redis)
│── tasks.py            # Définition des tâches Celery
│── config.py           # Configuration centralisée (API keys, paths, etc.)
│── uploads/            # Répertoire pour fichiers entrants
│── reports/            # Répertoire pour rapports générés
│── reports_internal/   # Répertoire pour rapports internes (debug/log)
│── docker-compose.yml  # Orchestration API + Worker + Redis + Flower
│── Dockerfile          # Image Docker de l’API
│── requirements.txt    # Dépendances Python
│── .env                # Variables d’environnement
```

Services Docker :

* **Redis** : broker et backend Celery
* **API** : FastAPI + Uvicorn
* **Worker** : Worker Celery qui exécute les tâches (OCR + génération PDF)
* **Flower** : Interface de monitoring des jobs

---

## Installation et lancement

### 1. Variables d’environnement

Créer un fichier `.env` à la racine :

```ini
API_KEY=cle_api_pour_securiser_les_endpoints
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
WEBHOOK_SECRET=secret_signature_webhook (optionnel)
```

### 2. Lancement en local (Docker Compose)

```bash
docker compose up --build
```

* API → [http://localhost:8000](http://localhost:8000)
* Flower → [http://localhost:5555](http://localhost:5555)

---

## Endpoints synchrones (prioritaires)

> Tous les endpoints nécessitent le header :
> `X-API-Key: <clé définie dans .env>`

### 1. Analyse d’un PDF

**Endpoint** :
`POST /v1/invoices/pdf`

**Form-data** :

* `file` : fichier PDF
* `energy` : `"auto" | "electricite" | "eau" | "gaz" | "telecom"`
* `confidence_min` *(optionnel)* : seuil de confiance (0.0–1.0)
* `strict` *(optionnel)* : `true`/`false`

**Exemple cURL** :

```bash
curl -X POST "http://localhost:8000/v1/invoices/pdf" \
  -H "X-API-Key: ${API_KEY}" \
  -F "file=@sample.pdf" \
  -F "energy=auto" \
  -F "confidence_min=0.5" \
  -F "strict=true"
```

**Réponse JSON** :

```json
{
  "non_anonymous_report_base64": "<PDF base64>",
  "anonymous_report_base64": "<PDF base64>",
  "non_anonymous_size": 321004,
  "anonymous_size": 320998,
  "non_anonymous_sha256": "abc123...",
  "anonymous_sha256": "def456..."
}
```

---

### 2. Analyse d’images

**Endpoint** :
`POST /v1/invoices/images`

**Form-data** :

* `files[]` : une ou plusieurs images (`.jpg`, `.jpeg`, `.png`)
* `energy` : `"auto" | "electricite" | "eau" | "gaz" | "telecom"`
* `confidence_min` *(optionnel)*
* `strict` *(optionnel)*

**Exemple cURL** :

```bash
curl -X POST "http://localhost:8000/v1/invoices/images" \
  -H "X-API-Key: ${API_KEY}" \
  -F "files=@page1.jpg" \
  -F "files=@page2.png" \
  -F "energy=electricite"
```

**Réponse JSON** : identique au PDF (base64 des deux rapports).

---

## Sécurité

* Authentification par **API Key** via header `X-API-Key`
* Validation stricte des fichiers (taille, extension)
* Génération de hash SHA-256 pour vérifier l’intégrité
* Possibilité d’ajouter signature HMAC (`WEBHOOK_SECRET`) pour webhooks (mode async)

---

## Intégration avec la base de données (à prévoir)

Les endpoints actuels **retournent uniquement le JSON avec les PDF encodés**.
Pour l’intégration avec la DB, il est recommandé de :

* Stocker les champs `sha256`, `size` et `energy` dans la table `factures`
* Conserver le PDF généré en **blob** ou sur disque avec un lien DB
* Relier l’`invoice_id` et le `user_id` passés dans la requête (mode jobs déjà prévu dans `tasks.py`).

---

## Intégration côté backend/front

Un backend (exemple PHP `decoder.php`) devra :

1. Envoyer la facture avec cURL vers `/v1/invoices/pdf` ou `/v1/invoices/images`
2. Récupérer la réponse JSON
3. Décoder le base64 pour reconstituer le PDF :

```php
$pdf_data = base64_decode($json['non_anonymous_report_base64']);
file_put_contents("rapport.pdf", $pdf_data);
```

4. Sauvegarder le résultat dans la base de données ou l’exposer au front.

---

