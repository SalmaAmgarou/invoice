
# README — Invoice OCR API (Sync + Async Jobs)

## Présentation

API FastAPI qui analyse des factures (PDF ou images) et génère 2 rapports PDF:
- non anonymisé (fournisseurs visibles)
- anonymisé (fournisseurs masqués)

Le service renvoie les PDF en Base64, ainsi qu’une courte liste de « highlights » marketing pour le front. Deux modes:
- Mode synchrone: réponse directe avec les PDF en Base64
- Mode asynchrone (jobs Celery): mise en file + webhook de résultat

—

## Sommaire
- Architecture & rôle des dossiers/fichiers
- Configuration (.env) et variables à personnaliser
- Lancer en Docker (Linux/Windows) et en local (sans Docker)
- Spécifications API (sync, async/jobs, health)
- Détail des champs d’entrée/sortie (incl. highlights)
- Décodage Base64 (PDF) & usage des highlights en front
- Intégration base de données (schémas et patterns)
- Sécurité (API Key, signatures HMAC, CORS)
- Annexes: exemples cURL, PHP, etc.

—

## Architecture du projet

```
invoice_ocr/
│── api/                      # Application FastAPI (endpoints)
│   └── app.py                # Déclare les routes sync & jobs, sécurité, CORS
│
│── services/
│   └── reporting/
│       └── engine.py         # Coeur métier: OCR/extraction + rendu PDF + highlights
│
│── core/
│   ├── config.py             # Chargement .env, constantes (tailles, CORS, brokers)
│   └── security.py           # (réservé / non utilisé si vide ici)
│
│── celery_app.py             # Instance Celery (broker/backend, sérialisation)
│── tasks.py                  # Tâches Celery (PDF/Images) + webhook + idempotence
│
│── assets/                   # Fonts (Poppins, DejaVu) + logo Pioui
│── uploads/                  # Dépôt temporaire (jobs async)
│── reports/                  # (optionnel) si vous persistez les PDFs sur disque
│── reports_internal/         # (optionnel) journaux/diagnostics
│
│── public/
│   └── invoice_ready.php     # Exemple de récepteur webhook (PHP) prêt à l’emploi
│
│── Dockerfile                # Image API (python:3.11-slim + tesseract/poppler)
│── docker-compose.yml        # Service API (ports, healthcheck, volumes)
│── requirements.txt          # Dépendances Python
│── README.md                 # Ce document
│── .env                      # Vos secrets/paramètres (non commité)
```

Rôles clés:
- `api/app.py`: routes `/v1/invoices/*` sync et `/v1/jobs/*` async, header API Key, encodage Base64, highlights
- `services/reporting/engine.py`: lecture PDF/images, extraction (LLM + heuristiques), génération des 2 PDF, composition des highlights
- `tasks.py`: pipeline Celery (retour JSON standardisé, envoi webhook sécurisé, nettoyage des fichiers)
- `public/invoice_ready.php`: exemple réaliste de consommateur webhook (écriture disque ou UPSERT DB)

—

## Configuration (.env)

Créez `.env` à la racine en remplaçant les valeurs par celles de votre infra:

```ini
# Auth API (obligatoire) — liste de clés séparées par virgules
API_KEY=cle1,cle2,cle3

# CORS — origines front autorisées (URLs), séparées par virgules
ALLOWED_ORIGINS=https://app.exemple.com,https://admin.exemple.com

# LLM
OPENAI_API_KEY=sk-...
MISTRAL_API_KEY=

# Fichiers
UPLOAD_FOLDER=uploads
REPORTS_FOLDER=reports
REPORTS_INTERNAL_FOLDER=reports_internal
MAX_CONTENT_LENGTH=16777216

# Celery / Redis (pour mode async)
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
CELERY_RESULT_EXPIRES=86400
CELERY_TASK_TIME_LIMIT=600
CELERY_TASK_SOFT_TIME_LIMIT=540

# Webhook sécurité (côté worker -> votre backend)
WEBHOOK_TOKEN=ex-secret-bearer-optional
WEBHOOK_SECRET=ex-hmac-secret-optional

# 🆕 Sécurité avancée (production)
FORCE_HTTPS=true
ALLOWED_HOSTS=your-domain.com,api.your-domain.com
```

Notes:
- `API_KEY` accepte plusieurs valeurs (comparaison constante côté serveur).
- `ALLOWED_ORIGINS` doit contenir vos domaines front (CORS).
- Pour Windows local sans Docker, installez Tesseract/Poppler; sinon utilisez Docker.

—

## Lancer le projet

### A) Docker (recommandé)

Linux/Windows (Docker Desktop):
```bash
docker compose up --build
```
Endpoints:
- API: http://localhost:8000

Healthcheck (nécessite API Key):
```bash
curl -H "X-API-Key: $API_KEY" http://localhost:8000/health
```

Volumes: `./assets` est monté en lecture seule dans le conteneur.

### B) Exécution locale (sans Docker)

Prérequis Linux:
- Python 3.11
- tesseract-ocr, poppler-utils, ghostscript

Installation:
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export TESSERACT_CMD=tesseract
uvicorn api.app:app --host 0.0.0.0 --port 8000 --reload
```

Windows (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Installez Tesseract et Poppler via vos gestionnaires ou packages binaires
setx TESSERACT_CMD tesseract
uvicorn api.app:app --host 0.0.0.0 --port 8000 --reload
```

—

## Spécifications API

Tous les endpoints exigent le header:
```
X-API-Key: <une des clés de .env>
```

### 1) Health
GET `/health` → `{ "status": "ok" }`

### 2) Sync — PDF unique
POST `/v1/invoices/pdf`
- Form-Data:
  - `file` (PDF, obligatoire)
  - `type` ∈ {`auto`,`electricite`,`gaz`,`dual`} (défaut: `auto`) (Très important pour le routing spécifique en fonction du type de la facture sélectionnée par User depuis l'interface)
  - `confidence_min` (float 0.0–1.0, défaut 0.5)
  - `strict` (bool, défaut true)
  - `user_id?` (int, optionnel) — renvoyé tel quel dans la réponse
  - `invoice_id?` (int, optionnel) — renvoyé tel quel dans la réponse
  - `external_ref?` (string, optionnel) — renvoyé tel quel dans la réponse

Réponse (200):
```json
{
  "non_anonymous_report_base64": "<base64>",
  "anonymous_report_base64": "<base64>",
  "highlights": ["...", "...", "..." ],
  "user_id": 123,
  "invoice_id": 456,
  "external_ref": "ABC-2025-09"
}
```

Erreurs communes:
- 400: type de fichier invalide, extension non supportée
- 413: fichier trop volumineux (> MAX_CONTENT_LENGTH)
- 422: incompatibilité de type d’énergie détectée
- 500: erreur interne (journalisée)

Exemple cURL:
```bash
curl -X POST http://localhost:8000/v1/invoices/pdf \
  -H "X-API-Key: $API_KEY" \
  -F file=@sample.pdf \
  -F type=auto -F confidence_min=0.5 -F strict=true
```

### 3) Sync — Images multiples
POST `/v1/invoices/images`
- Form-Data:
  - `files` (1..8 images .jpg/.jpeg/.png/.bmp/.tif/.tiff)
  - `type`, `confidence_min`, `strict` (mêmes règles)
  - `user_id?`, `invoice_id?`, `external_ref?` (optionnels, renvoyés dans la réponse)

Réponse identique au PDF.


—

## Champs et sémantique

- `non_anonymous_report_base64` / `anonymous_report_base64`: PDF encodés Base64.
  - Non anonymisé: fournisseurs visibles (pour archivage/backoffice).
  - Anonymisé: fournisseurs masqués (pour partage/usage public si nécessaire).
- `highlights` (liste de 3–4 lignes courtes): à afficher en UI (cartouches) pour résumer:
  - économies potentielles estimées
  - positionnement marché (écart max capé)
  - vices cachés principaux détectés

—

## Décodage Base64 et exploitation côté client

PHP (extrait minimal):
```php
$json = json_decode($raw, true);
$nonAnonBytes = base64_decode($json['non_anonymous_report_base64']);
$anonBytes = base64_decode($json['anonymous_report_base64']);
file_put_contents('rapport.nonanon.pdf', $nonAnonBytes);
file_put_contents('rapport.anon.pdf', $anonBytes);
```

JavaScript (Node/Browser):
```js
const nonAnon = Buffer.from(json.non_anonymous_report_base64, 'base64');
require('fs').writeFileSync('rapport.nonanon.pdf', nonAnon);
```

Python:
```python
import base64
pdf = base64.b64decode(resp['non_anonymous_report_base64'])
open('rapport.pdf','wb').write(pdf)
```

Affichage des highlights (front): liste de phrases courtes, à montrer sous forme de bullets ou badges informatifs à proximité du document analysé.

—

## Intégration base de données (recommandations)

Modèle minimal suggéré (à adapter à votre SI):

- Table `invoices`/`factures`
  - `id`, `user_id`, `source` (pdf|images), `type`, `created_at`
  - `non_anonymous_sha256`, `anonymous_sha256`, `non_anonymous_size`, `anonymous_size`
  - `report_non_anonymous` (BLOB/bytea) ou stockage sur disque + chemin
  - `report_anonymous` (BLOB/bytea) ou stockage sur disque + chemin

Patterns:
- Sync: insérer immédiatement à la réception de la réponse.
- Async: consommer le webhook et faire un UPSERT par `task_id` (voir `public/invoice_ready.php`).

Exemples SQL (voir aussi `public/invoice_ready.php`, bloc PDO commenté) pour MySQL/PostgreSQL.

### Schémas SQL concrets

MySQL:
```sql
CREATE TABLE users (
  id            BIGINT PRIMARY KEY AUTO_INCREMENT,
  email         VARCHAR(255) UNIQUE,
  created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE invoices (
  id            BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id       BIGINT NULL,
  external_ref  VARCHAR(255) NULL,
  source_kind   ENUM('pdf','images') NOT NULL,
  type          ENUM('auto','electricite','gaz','dual') NOT NULL,
  created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_invoices_user FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE reports (
  id                         BIGINT PRIMARY KEY AUTO_INCREMENT,
  invoice_id                 BIGINT NOT NULL,
  non_anonymous_pdf          LONGBLOB NOT NULL,
  anonymous_pdf              LONGBLOB NOT NULL,
  non_anonymous_size         INT UNSIGNED NOT NULL,
  anonymous_size             INT UNSIGNED NOT NULL,
  non_anonymous_sha256       CHAR(64) NOT NULL,
  anonymous_sha256           CHAR(64) NOT NULL,
  created_at                 TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_reports_invoice FOREIGN KEY (invoice_id) REFERENCES invoices(id),
  INDEX (non_anonymous_sha256), INDEX (anonymous_sha256)
);

-- Optionnel (mode async / file d'attente Celery)
CREATE TABLE invoice_jobs (
  task_id                    VARCHAR(64) PRIMARY KEY,
  status                     VARCHAR(16) NOT NULL,
  user_id                    BIGINT NULL,
  invoice_id                 BIGINT NULL,
  external_ref               VARCHAR(255) NULL,
  source_kind                ENUM('pdf','images') NOT NULL,
  non_anonymous_pdf          LONGBLOB NOT NULL,
  anonymous_pdf              LONGBLOB NOT NULL,
  non_anonymous_size         INT UNSIGNED NOT NULL,
  anonymous_size             INT UNSIGNED NOT NULL,
  non_anonymous_sha256       CHAR(64) NOT NULL,
  anonymous_sha256           CHAR(64) NOT NULL,
  created_at                 TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at               TIMESTAMP NULL,
  INDEX (status), INDEX (created_at)
);
```

PostgreSQL:
```sql
CREATE TABLE users (
  id            BIGSERIAL PRIMARY KEY,
  email         text UNIQUE,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TYPE type_kind AS ENUM ('auto','electricite','gaz','dual');
CREATE TYPE source_kind AS ENUM ('pdf','images');

CREATE TABLE invoices (
  id            BIGSERIAL PRIMARY KEY,
  user_id       bigint NULL REFERENCES users(id),
  external_ref  text NULL,
  source_kind   source_kind NOT NULL,
  type          type_kind NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE reports (
  id                         BIGSERIAL PRIMARY KEY,
  invoice_id                 bigint NOT NULL REFERENCES invoices(id),
  non_anonymous_pdf          bytea NOT NULL,
  anonymous_pdf              bytea NOT NULL,
  non_anonymous_size         integer NOT NULL,
  anonymous_size             integer NOT NULL,
  non_anonymous_sha256       char(64) NOT NULL,
  anonymous_sha256           char(64) NOT NULL,
  created_at                 timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX reports_nonanon_sha_idx ON reports(non_anonymous_sha256);
CREATE INDEX reports_anon_sha_idx ON reports(anonymous_sha256);

-- Optionnel (mode async / file d'attente Celery)
CREATE TABLE invoice_jobs (
  task_id                    text PRIMARY KEY,
  status                     text NOT NULL,
  user_id                    bigint NULL,
  invoice_id                 bigint NULL,
  external_ref               text NULL,
  source_kind                source_kind NOT NULL,
  non_anonymous_pdf          bytea NOT NULL,
  anonymous_pdf              bytea NOT NULL,
  non_anonymous_size         integer NOT NULL,
  anonymous_size             integer NOT NULL,
  non_anonymous_sha256       char(64) NOT NULL,
  anonymous_sha256           char(64) NOT NULL,
  created_at                 timestamptz NOT NULL DEFAULT now(),
  completed_at               timestamptz NULL
);
CREATE INDEX invoice_jobs_status_idx ON invoice_jobs(status);
CREATE INDEX invoice_jobs_created_idx ON invoice_jobs(created_at);
```

—

## Sécurité

- **API Key via `X-API-Key` (obligatoire)** - Protection contre l'accès non autorisé
- **Webhook: Bearer optionnel (`WEBHOOK_TOKEN`) et HMAC-SHA256 (`WEBHOOK_SECRET`)** - Authentification et intégrité des webhooks
- **Validation stricte des uploads** (extensions, MIME, taille max via `MAX_CONTENT_LENGTH`)
- **CORS via `ALLOWED_ORIGINS`** - Contrôle des origines autorisées
- **🆕 Protection des logs** - Les clés API sont automatiquement masquées dans les logs
- **🆕 Headers de sécurité** - Protection contre XSS, clickjacking, MIME sniffing
- **🆕 Redirection HTTPS** - Force HTTPS en production (`FORCE_HTTPS=true`)
- **🆕 HSTS** - HTTP Strict Transport Security pour la sécurité long terme

—

## Référence des fichiers importants

```1:60:api/app.py
"""
app/main.py — Production-Ready FastAPI Wrapper

Key goals:
- Provides two async endpoints that return generated PDF reports directly.
... (voir le fichier complet)
"""
```

```1:42:core/config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    API_KEY = [s.strip() for s in os.getenv("API_KEY", "").split(",") if s.strip()]
    ALLOWED_ORIGINS = [s.strip() for s in os.getenv("ALLOWED_ORIGINS", "").split(",") if s.strip()]
    ...
```

```1:117:tasks.py
@celery.task(name="process_pdf_task")
def process_pdf_task(...):
    # construit le payload webhook et nettoie les fichiers temporaires
    return result
```

```1:260:public/invoice_ready.php
// Récepteur webhook prêt à l’emploi (écriture disque ou UPSERT DB via PDO)
```

—

## Exemples d’utilisation

Sync PDF:
```bash
curl -X POST "http://localhost:8000/v1/invoices/pdf" \
  -H "X-API-Key: ${API_KEY}" \
  -F "file=@sample.pdf" \
-F "type=auto" -F "confidence_min=0.5" -F "strict=true" \
  -F "user_id=123" -F "invoice_id=456" -F "external_ref=ABC-2025-09"
```

Async PDF -> webhook PHP local:
```bash
WEBHOOK_TOKEN=secret php -S 127.0.0.1:8088 -t public

curl -X POST "http://localhost:8000/v1/jobs/pdf" \
  -H "X-API-Key: ${API_KEY}" \
  -F "file=@sample.pdf" \
-F "type=auto" \
  -F "webhook_url=http://127.0.0.1:8088/invoice_ready.php"
```

—

## Points à implémenter côté intégrateurs (à faire par votre équipe)

- Backend:
  - Consommation des endpoints sync OU mise en place des jobs async + webhook.
  - Décodage Base64 et persistance des PDF (BLOB ou disque + chemin).
  - Stockage des métadonnées: tailles, SHA-256, type d’énergie, user/invoice IDs.

- Frontend:
  - Affichage des highlights (3–4 lignes), clair et concis.
  - Téléchargement/affichage des rapports PDF (non-anon/anonymisé selon contexte).

- DevOps:
  - Remplacer les valeurs `.env` par celles de votre serveur (API_KEY, CORS, Redis, secrets).
  - Exposer l’API derrière HTTPS, configurer les origins CORS exacts.
  - Mettre en place la base de données et les schémas suggérés.

—

## 🐳 Guide d'Intégration Docker pour l'Équipe PHP

### Déploiement Recommandé

**Le service Python doit être déployé comme conteneur Docker séparé** pour les raisons suivantes:
- ✅ Isolation des dépendances (Python, Tesseract, bibliothèques AI)
- ✅ Cohérence entre environnements (dev/staging/prod)
- ✅ Facilité de déploiement et scaling
- ✅ Aucune installation sur les serveurs PHP

### Architecture d'Intégration

```
PHP Application (Frontend/Backend)
    ↓ HTTP/HTTPS API calls
Docker Container (Service Python OCR)
    ↓ Redis (pour les jobs Celery)
Workers Celery (Background processing)
```

### Étapes d'Intégration pour l'Équipe PHP

#### 1. Déploiement du Service Python
```bash
# Sur le serveur dédié au service Python
git clone <votre-repo>
cd invoice_ocr
cp .env.example .env
# Éditer .env avec vos valeurs

# Déployer avec Docker
docker-compose up -d

# Vérifier que le service fonctionne
curl -H "X-API-Key: votre-cle" http://localhost:8000/health
```

#### 2. Configuration PHP
```php
// Configuration dans votre application PHP
$ocr_api_url = 'https://api-ocr.votre-domaine.com';  // URL du service Python
$ocr_api_key = 'votre-cle-api';                       // Clé API partagée

// Exemple d'appel API
function callOcrApi($filePath, $type = 'auto') {
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $ocr_api_url . '/v1/invoices/pdf');
    curl_setopt($ch, CURLOPT_POST, true);
    curl_setopt($ch, CURLOPT_HTTPHEADER, [
        'X-API-Key: ' . $ocr_api_key,
        'Content-Type: multipart/form-data'
    ]);
    curl_setopt($ch, CURLOPT_POSTFIELDS, [
        'file' => new CURLFile($filePath),
        'type' => $type,
        'user_id' => $_SESSION['user_id'],
        'invoice_id' => $invoiceId
    ]);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    
    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    
    if ($httpCode === 200) {
        $data = json_decode($response, true);
        // Décoder les PDFs Base64
        $nonAnonPdf = base64_decode($data['non_anonymous_report_base64']);
        $anonPdf = base64_decode($data['anonymous_report_base64']);
        // Sauvegarder ou afficher les PDFs
        return $data;
    } else {
        throw new Exception("Erreur API OCR: " . $response);
    }
}
```

#### 3. Mode Asynchrone (Recommandé pour Production)
```php
// Pour les gros volumes, utilisez le mode asynchrone
function enqueueOcrJob($filePath, $webhookUrl) {
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $ocr_api_url . '/v1/jobs/pdf');
    curl_setopt($ch, CURLOPT_POST, true);
    curl_setopt($ch, CURLOPT_HTTPHEADER, [
        'X-API-Key: ' . $ocr_api_key
    ]);
    curl_setopt($ch, CURLOPT_POSTFIELDS, [
        'file' => new CURLFile($filePath),
        'webhook_url' => $webhookUrl,
        'user_id' => $_SESSION['user_id']
    ]);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    
    $response = curl_exec($ch);
    $data = json_decode($response, true);
    curl_close($ch);
    
    return $data['task_id'];  // ID de la tâche pour suivi
}

// Webhook handler (public/invoice_ready.php déjà fourni)
// Recevra automatiquement les résultats via POST
```

### Variables d'Environnement Requises

```bash
# Sur le serveur Python
API_KEY=votre-cle-partagee
ALLOWED_ORIGINS=https://votre-frontend.com
FORCE_HTTPS=true
ALLOWED_HOSTS=votre-domaine.com

# Base de données (si nécessaire)
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
```

### Monitoring et Maintenance

```bash
# Vérifier la santé du service
curl -H "X-API-Key: votre-cle" https://api-ocr.votre-domaine.com/health

# Logs du service
docker-compose logs -f api

# Redémarrer le service
docker-compose restart api
```

### Points Importants pour l'Équipe PHP

1. **Aucune connaissance Python requise** - Simple appel API HTTP
2. **Service isolé** - Ne nécessite aucune modification des serveurs PHP
3. **Scalable** - Peut déployer plusieurs instances derrière un load balancer
4. **Monitoring intégré** - Endpoint `/health` pour vérification
5. **Documentation complète** - Exemples PHP fournis dans `php_scripts_examples/`

### Timeline d'Intégration Estimé
- **Configuration Docker**: 1-2 jours
- **Intégration PHP**: 1-2 semaines
- **Tests et déploiement**: 1 semaine
- **Total**: 2-3 semaines

### 🔄 Intégration avec votre Base de Données

**Mon service Python est STATELESS** - il ne stocke rien en base. Toute la persistance se fait côté PHP.

#### Architecture avec Docker

Le fait que mon service soit dockerisé **N'IMPACTE PAS** la logique de base de données que je vous ai fournie. Voici pourquoi :

**✅ Votre base de données reste sur vos serveurs PHP**
- Les tables `invoices`, `reports`, `invoice_jobs` restent identiques
- Mon service Docker communique avec votre base via les **webhooks**
- Aucune modification des schémas SQL que je vous ai donnés

#### Flux de Données avec Docker

```
1. PHP → Docker (API) : Envoi facture + user_id, invoice_id, external_ref
2. Docker (Traitement) : OCR + génération PDFs
3. Docker → PHP (Webhook) : Retour PDFs + métadonnées + vos IDs
4. PHP → Base de Données : Insertion dans vos tables existantes
```

#### Exemple Concret d'Intégration

**1. Côté PHP - Appel API avec vos IDs :**
```php
// Vous envoyez vos IDs comme je l'ai documenté
$response = callOcrApi($filePath, [
    'type' => 'auto',
    'user_id' => 123,           // Votre user_id
    'invoice_id' => 456,        // Votre invoice_id  
    'external_ref' => 'FAC-2025-001'  // Votre référence
]);
```

**2. Côté Docker - Mon service retourne vos IDs :**
```json
{
  "non_anonymous_report_base64": "...",
  "anonymous_report_base64": "...", 
  "highlights": ["...", "..."],
  "user_id": 123,              // Vos IDs sont renvoyés
  "invoice_id": 456,
  "external_ref": "FAC-2025-001"
}
```

**3. Côté PHP - Webhook reçoit tout :**
```php
// public/invoice_ready.php reçoit automatiquement :
// - Les PDFs Base64
// - Vos user_id, invoice_id, external_ref
// - Les métadonnées (tailles, SHA256)

// Vous insérez dans VOS tables comme prévu :
INSERT INTO reports (invoice_id, non_anonymous_pdf, anonymous_pdf, ...)
VALUES (?, ?, ?, ...);
```

#### Points Importants

1. **Mes schémas SQL restent valides** - Docker ne change rien
2. **Vos IDs sont préservés** - user_id, invoice_id, external_ref transitent intact
3. **Webhook fonctionne identiquement** - même logique que sans Docker
4. **Votre base reste indépendante** - aucun accès direct de mon service
5. **Monitoring identique** - même tracking via vos tables

#### Configuration Docker Requise

```bash
# Dans votre .env pour le service Docker
API_KEY=votre-cle-partagee
ALLOWED_ORIGINS=https://votre-frontend.com
WEBHOOK_URL=https://votre-domaine.com/internal/invoice-ready
WEBHOOK_TOKEN=votre-token-secret
WEBHOOK_SECRET=votre-secret-hmac
```

**Résumé : Docker n'affecte AUCUNE logique de base de données. Tout fonctionne exactement comme je vous l'ai documenté initialement.**

—

Pour toute question technique: se référer aux fichiers `api/app.py`, `services/reporting/engine.py`, `tasks.py`, et à l'exemple `public/invoice_ready.php`.

