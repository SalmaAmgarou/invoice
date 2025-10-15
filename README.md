
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
│   └── app.py                # Déclare les routes sync & jobs, sécurité, CORS + backup Spaces
│
│── services/
│   ├── reporting/
│   │   └── engine.py         # Coeur métier: OCR/extraction + rendu PDF + highlights
│   └── storage/
│       └── spaces.py         # Client DigitalOcean Spaces (backup automatique S3-compatible)
│
│── core/
│   ├── config.py             # Chargement .env, constantes (tailles, CORS, brokers, Spaces)
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
│   └── invoice_ready.php     # Exemple de récepteur webhook (PHP) prêt à l'emploi
│
│── Dockerfile                # Image API (python:3.11-slim + tesseract/poppler)
│── docker-compose.yml        # Service API (ports, healthcheck, volumes)
│── requirements.txt          # Dépendances Python
│── README.md                 # Ce document
│── .env                      # Vos secrets/paramètres (non commité)
```

Rôles clés:
- `api/app.py`: routes `/v1/invoices/*` sync et `/v1/jobs/*` async, header API Key, encodage Base64, highlights + backup automatique DigitalOcean
- `services/reporting/engine.py`: lecture PDF/images, extraction (LLM + heuristiques), génération des 2 PDF, composition des highlights
- `services/storage/spaces.py`: client DigitalOcean Spaces (backup automatique des factures et rapports avec organisation hiérarchique)
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

# 🆕 DigitalOcean Spaces (backup automatique)
DO_SPACES_KEY=your-access-key
DO_SPACES_SECRET=your-secret-key
DO_SPACES_REGION=ams3
DO_SPACES_ENDPOINT=https://ams3.digitaloceanspaces.com
DO_SPACES_BUCKET=your-bucket-name
ENV=prod
```

Notes:
- `API_KEY` accepte plusieurs valeurs (comparaison constante côté serveur).
- `ALLOWED_ORIGINS` doit contenir vos domaines front (CORS).
- `DO_SPACES_*` : configuration DigitalOcean Spaces pour backup automatique (optionnel mais recommandé en production).
- `ENV` : tag d'environnement pour l'organisation des objets (dev/staging/prod).
- Pour Windows local sans Docker, installez Tesseract/Poppler; sinon utilisez Docker.

—

## 🗄️ DigitalOcean Spaces - Backup Automatique

### Vue d'ensemble technique

L'API intègre un système de backup automatique vers DigitalOcean Spaces (compatible S3) qui sauvegarde toutes les factures et rapports générés. Cette fonctionnalité s'exécute en arrière-plan et n'affecte pas les performances de l'API.

### Fonctionnement technique

**1. Déclenchement automatique :**
- Chaque traitement de facture (PDF ou images) déclenche automatiquement un backup
- Le backup s'exécute en tâche de fond (BackgroundTasks) pour ne pas ralentir la réponse API
- Aucune intervention manuelle requise

**2. Organisation hiérarchique :**
```
bucket/
├── prod/                           # Environnement (ENV)
│   ├── user-123__client-name/      # Utilisateur + nom client
│   │   ├── invoice-456/            # ID facture ou référence externe
│   │   │   ├── 20250115T143022Z/   # Timestamp unique du traitement
│   │   │   │   ├── original_electricite.pdf     # PDF original
│   │   │   │   ├── report_full_electricite.pdf  # Rapport non-anonymisé
│   │   │   │   ├── report_anon_electricite.pdf  # Rapport anonymisé
│   │   │   │   ├── page-001.jpg                 # Pages originales (si images)
│   │   │   │   ├── page-002.jpg
│   │   │   │   └── manifest.json               # Métadonnées du traitement
```

**3. Métadonnées incluses :**
- `x-amz-meta-user-id` : ID utilisateur
- `x-amz-meta-invoice-id` : ID facture
- `x-amz-meta-external-ref` : Référence externe
- `x-amz-meta-source-kind` : Type source (pdf/images)
- `x-amz-meta-energy-type` : Type d'énergie détecté
- `x-amz-meta-run-id` : ID unique du traitement

**4. Manifest JSON :**
```json
{
  "env": "prod",
  "run_id": "20250115T143022Z",
  "timestamp": "2025-01-15T14:30:22Z",
  "user_id": 123,
  "invoice_id": 456,
  "external_ref": "FAC-2025-001",
  "energy_type": "electricite",
  "customer_name": "Client Name",
  "highlights": ["Économies potentielles: 15%", "..."],
  "original_pages": ["page-001.jpg", "page-002.jpg"]
}
```

### Configuration DigitalOcean Spaces

**1. Créer un Space :**
- Connectez-vous à DigitalOcean
- Allez dans Spaces → Create a Space
- Choisissez une région proche (ex: Amsterdam `ams3`)
- Nommez votre bucket (ex: `invoice-backups-prod`)

**2. Générer les clés d'accès :**
- API → Manage Tokens → Spaces access keys
- Créez une nouvelle clé avec permissions read/write
- Copiez la clé d'accès et le secret

**3. Configuration .env :**
```ini
DO_SPACES_KEY=your-access-key-here
DO_SPACES_SECRET=your-secret-key-here
DO_SPACES_REGION=ams3
DO_SPACES_ENDPOINT=https://ams3.digitaloceanspaces.com
DO_SPACES_BUCKET=your-bucket-name
ENV=prod
```

### Avantages pour l'équipe de développement

**1. Audit et traçabilité :**
- Historique complet de tous les traitements
- Possibilité de retrouver n'importe quelle facture traitée
- Métadonnées complètes pour debugging

**2. Conformité et sécurité :**
- Chiffrement AES-256 côté serveur
- ACL privé (accès contrôlé)
- Stockage géographiquement distribué

**3. Récupération et backup :**
- Sauvegarde automatique de tous les documents
- Possibilité de restaurer des rapports perdus
- Versioning par timestamp (pas d'écrasement)

**4. Analytics et monitoring :**
- Manifest JSON pour chaque traitement
- Métriques d'usage et patterns
- Détection d'anomalies

### Monitoring et maintenance

**Vérification du service :**
```bash
# Test de connexion au démarrage (logs)
docker-compose logs api | grep "spaces_probe_ok"

# Vérification manuelle des uploads
curl -H "X-API-Key: $API_KEY" http://localhost:8000/health
```

**Logs de backup :**
```bash
# Suivre les uploads réussis
docker-compose logs -f api | grep "spaces_upload_ok"

# Détecter les erreurs de backup
docker-compose logs -f api | grep "spaces_upload_error"
```

### Coûts et optimisation

**Tarification DigitalOcean Spaces :**
- Stockage : ~0.02€/GB/mois
- Transfert sortant : ~0.01€/GB
- Requêtes : ~0.004€/10k requêtes

**Optimisations incluses :**
- Compression automatique des PDFs
- Métadonnées optimisées
- Organisation hiérarchique pour réduction des coûts de listing

### Désactivation (optionnel)

Pour désactiver le backup automatique :
```ini
# Commenter ou supprimer les variables DO_SPACES_*
# DO_SPACES_KEY=
# DO_SPACES_SECRET=
```

L'API continuera de fonctionner normalement sans backup.

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
  - `customer_name?` (string, optionnel) — nom client pour organisation backup
- **🆕 Backup automatique** : Tous les documents sont automatiquement sauvegardés vers DigitalOcean Spaces en arrière-plan

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
  - `customer_name?` (string, optionnel) — nom client pour organisation backup
- **🆕 Backup automatique** : Images originales + rapports sauvegardés vers DigitalOcean Spaces

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

## 🔧 Guide Technique - DigitalOcean Spaces pour l'Équipe Dev

### Architecture technique détaillée

**1. Client Spaces (`services/storage/spaces.py`)**
```python
class SpacesClient:
    """Client S3-compatible pour DigitalOcean Spaces"""
    
    def __init__(self):
        # Configuration boto3 avec endpoint DigitalOcean
        self._s3 = boto3.client("s3", ...)
    
    def build_prefix(self, user_id, invoice_id, customer_name, run_id):
        # Construction hiérarchique: env/user__client/invoice/timestamp/
        return f"{self.env}/{uid}/{inv}/{run_id}"
    
    def upload_files_flat(self, prefix, filenames, original_pdf_bytes, ...):
        # Upload parallèle: original, rapport_full, rapport_anon, manifest
```

**2. Intégration dans l'API (`api/app.py`)**
```python
def _enqueue_spaces_backup_pdf(background_tasks, user_id, invoice_id, ...):
    """Tâche de fond pour backup automatique"""
    def _task():
        # Upload vers DigitalOcean en arrière-plan
        keys = _spaces.upload_files_flat(...)
        logger.info("spaces_upload_ok", extra={"keys": keys})

@app.post("/v1/invoices/pdf")
async def create_from_pdf(background_tasks: BackgroundTasks, ...):
    # 1. Traitement principal (synchrone)
    non_anon_bytes, anon_bytes, highlights = process_invoice_file(...)
    
    # 2. Backup en arrière-plan (asynchrone)
    _enqueue_spaces_backup_pdf(background_tasks, ...)
    
    # 3. Retour immédiat à l'utilisateur
    return {"non_anonymous_report_base64": base64.b64encode(...)}
```

### Flux de données technique

```
1. Request → API (app.py)
   ↓
2. Validation + Upload temporaire
   ↓
3. Processing (engine.py) → PDFs générés
   ↓
4. Response immédiate (Base64)
   ↓
5. Background Task → SpacesClient
   ↓
6. Upload vers DigitalOcean (parallèle)
   ↓
7. Logs + Monitoring
```

### Métadonnées et organisation

**Structure des clés S3 :**
```
prod/user-123__client-name/invoice-456/20250115T143022Z/
├── original_electricite.pdf      # SHA-256 dans métadonnées
├── report_full_electricite.pdf   # Rapport non-anonymisé
├── report_anon_electricite.pdf   # Rapport anonymisé  
├── page-001.jpg                  # Pages originales (si images)
├── page-002.jpg
└── manifest.json                 # Métadonnées complètes
```

**Métadonnées S3 standardisées :**
```python
metadata = {
    "x-amz-meta-user-id": "123",
    "x-amz-meta-invoice-id": "456", 
    "x-amz-meta-external-ref": "FAC-2025-001",
    "x-amz-meta-source-kind": "pdf",
    "x-amz-meta-energy-type": "electricite",
    "x-amz-meta-run-id": "20250115T143022Z"
}
```

### Gestion d'erreurs et monitoring

**Logs structurés :**
```python
# Succès
logger.info("spaces_upload_ok", extra={
    "prefix": prefix, 
    "keys": keys,
    "user_id": user_id
})

# Erreurs
logger.exception("spaces_upload_error", exc_info=e)
```

**Monitoring en production :**
```bash
# Vérification des uploads
grep "spaces_upload_ok" /var/log/api.log | wc -l

# Détection des erreurs
grep "spaces_upload_error" /var/log/api.log

# Métriques de performance
grep "spaces_upload_ok" /var/log/api.log | jq '.extra.prefix'
```

### Optimisations techniques implémentées

**1. Upload parallèle :**
- Original PDF, rapport full, rapport anon uploadés simultanément
- Manifest JSON généré et uploadé en dernier
- Pas de dépendances entre les uploads

**2. Compression et optimisation :**
- PDFs déjà compressés par le moteur de rendu
- Métadonnées minimales mais complètes
- Organisation hiérarchique pour listing efficace

**3. Sécurité :**
- Chiffrement AES-256 côté serveur (automatique DigitalOcean)
- ACL privé (pas d'accès public)
- Signature S3v4 pour authentification

**4. Idempotence :**
- Timestamp unique par traitement (`run_id`)
- Pas d'écrasement accidentel
- Possibilité de retraitement sans conflit

### Configuration avancée

**Variables d'environnement détaillées :**
```ini
# DigitalOcean Spaces
DO_SPACES_KEY=your-access-key              # Clé d'accès API
DO_SPACES_SECRET=your-secret-key           # Secret API
DO_SPACES_REGION=ams3                      # Région (ams3, nyc3, sfo3, sgp1, fra1)
DO_SPACES_ENDPOINT=https://ams3.digitaloceanspaces.com  # Endpoint spécifique
DO_SPACES_BUCKET=invoice-backups-prod      # Nom du bucket
ENV=prod                                   # Tag environnement (dev/staging/prod)
```

**Configuration boto3 :**
```python
config=BotoConfig(
    signature_version="s3v4",              # Signature moderne
    retries={'max_attempts': 3},           # Retry automatique
    max_pool_connections=50                # Pool de connexions
)
```

### Intégration avec votre infrastructure

**1. Monitoring externe :**
```bash
# Script de vérification de santé
curl -f "https://api.domain.com/health" || alert_team

# Vérification des backups
aws s3 ls s3://bucket/prod/ --recursive | wc -l
```

**2. Alertes et notifications :**
```python
# Exemple d'intégration avec votre système d'alertes
if upload_failed:
    send_slack_alert(f"Backup failed for user {user_id}")
    create_jira_ticket(f"DigitalOcean backup issue: {error}")
```

**3. Analytics et reporting :**
```sql
-- Exemple de requête pour analytics
SELECT 
    DATE(created_at) as date,
    COUNT(*) as uploads_count,
    SUM(CASE WHEN spaces_upload_ok THEN 1 ELSE 0 END) as successful_backups
FROM invoice_logs 
GROUP BY DATE(created_at);
```

### Dépannage technique

**Problèmes courants :**

1. **Erreur d'authentification :**
```bash
# Vérifier les clés
aws s3 ls --endpoint-url=https://ams3.digitaloceanspaces.com
```

2. **Erreur de permissions :**
```bash
# Vérifier les ACLs du bucket
aws s3api get-bucket-acl --bucket your-bucket --endpoint-url=...
```

3. **Timeout d'upload :**
```python
# Augmenter les timeouts dans boto3
config=BotoConfig(
    read_timeout=60,
    connect_timeout=10
)
```

**Debugging avancé :**
```bash
# Logs détaillés boto3
export BOTO_CONFIG=/dev/null
export AWS_DEBUG=1

# Monitoring en temps réel
tail -f /var/log/api.log | grep "spaces_"
```

### Coûts et facturation

**Estimation des coûts (pour 1000 factures/mois) :**
- Stockage : ~50MB/facture = 50GB/mois = ~1€/mois
- Transfert : ~100MB/facture = 100GB/mois = ~1€/mois  
- Requêtes : ~10 requêtes/facture = 10k requêtes/mois = ~0.004€/mois
- **Total estimé : ~2€/mois pour 1000 factures**

**Optimisation des coûts :**
- Lifecycle policies pour archivage automatique
- Compression des objets volumineux
- Monitoring des métriques d'usage

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

