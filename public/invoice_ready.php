<?php
declare(strict_types=1);

/**
 * ---------------------------------------------------------------------------
 *  invoice_ready.php — Récepteur de webhook (POST) qui enregistre en DB
 * ---------------------------------------------------------------------------
 *
 * Rôle :
 *   - Recevoir le POST du worker Python (résultat JSON avec 2 PDFs en Base64)
 *   - Auth facultative : Authorization: Bearer <WEBHOOK_TOKEN>
 *   - Signature facultative : X-Webhook-Signature = HMAC-SHA256(body, WEBHOOK_SECRET)
 *   - Idempotence : dédupliqué par X-Task-Id (clé primaire en DB)
 *   - Persister en base (MySQL ou PostgreSQL) via PDO avec UPSERT
 *
 * Contrat d’entrée (envoyé par le worker) :
 *   Headers :
 *     - X-Task-Id: <uuid>            (obligatoire)
 *     - Authorization: Bearer ...    (optionnel mais recommandé)
 *     - X-Webhook-Signature: <hex>   (optionnel si HMAC activé)
 *   Body JSON :
 *     {
 *       "non_anonymous_report_base64": "<base64>",
 *       "anonymous_report_base64": "<base64>"
 *     }
 *
 * Variables d’environnement attendues (côté PHP) :
 *   - DB_DSN   : ex MySQL  -> "mysql:host=127.0.0.1;port=3306;dbname=invoices;charset=utf8mb4"
 *                ex PgSQL  -> "pgsql:host=127.0.0.1;port=5432;dbname=invoices"
 *   - DB_USER  : utilisateur DB
 *   - DB_PASS  : mot de passe DB
 *   - WEBHOOK_TOKEN   : si défini, on exige Authorization: Bearer <token>
 *   - WEBHOOK_SECRET  : si défini, on exige X-Webhook-Signature (HMAC du body)
 *
 * Réponses :
 *   - 200 {"ok":true,"task_id":"...","driver":"mysql|pgsql"}
 *   - 400 {"ok":false,"error":"bad request|invalid json"}
 *   - 401 {"ok":false,"error":"unauthorized|bad signature"}
 *   - 422 {"ok":false,"error":"invalid base64"}
 *   - 500 {"ok":false,"error":"db not configured|db error"}
 */

// ------------------------ Helpers de réponse JSON ----------------------------
function respond(int $code, array $payload): void {
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($payload, JSON_UNESCAPED_SLASHES);
    exit;
}

// ----------------------- 1) Lecture headers & body ---------------------------
$raw    = file_get_contents('php://input') ?: '';
$taskId = $_SERVER['HTTP_X_TASK_ID'] ?? ($_GET['task_id'] ?? null);
$auth   = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
$sig    = $_SERVER['HTTP_X_WEBHOOK_SIGNATURE'] ?? '';

if (!$taskId || $raw === '') {
    respond(400, ['ok' => false, 'error' => 'bad request']);
}
// Nettoyage minimal pour usage en logs/erreurs
$taskId = preg_replace('/[^a-zA-Z0-9._-]+/', '_', (string)$taskId);

// ----------------------- 2) Auth Bearer (optionnelle) ------------------------
$token = getenv('WEBHOOK_TOKEN') ?: '';
if ($token !== '') {
    if (!hash_equals("Bearer {$token}", $auth)) {
        respond(401, ['ok' => false, 'error' => 'unauthorized']);
    }
}

// ----------------------- 3) HMAC (optionnelle) -------------------------------
$secret = getenv('WEBHOOK_SECRET') ?: '';
if ($secret !== '') {
    $expected = hash_hmac('sha256', $raw, $secret);
    if (!hash_equals($expected, $sig)) {
        respond(401, ['ok' => false, 'error' => 'bad signature']);
    }
}

// ----------------------- 4) Parsing JSON ------------------------------------
try {
    /** @var array<string,mixed> $payload */
    $payload = json_decode($raw, true, flags: JSON_THROW_ON_ERROR);
} catch (Throwable $e) {
    respond(400, ['ok' => false, 'error' => 'invalid json']);
}

// ----------------------- 5) Décodage Base64 -> bytes -------------------------
$nonAnonB64 = (string)($payload['non_anonymous_report_base64'] ?? '');
$anonB64    = (string)($payload['anonymous_report_base64'] ?? '');

$nonAnon = base64_decode($nonAnonB64, true);
$anon    = base64_decode($anonB64, true);

if ($nonAnon === false || $anon === false) {
    respond(422, ['ok' => false, 'error' => 'invalid base64']);
}

// ----------------------- 6) Connexion PDO (MySQL/Postgres) -------------------
$dsn  = getenv('DB_DSN')  ?: '';
$user = getenv('DB_USER') ?: '';
$pass = getenv('DB_PASS') ?: '';

if ($dsn === '') {
    respond(500, ['ok' => false, 'error' => 'db not configured']);
}

try {
    $pdo = new PDO($dsn, $user, $pass, [
        PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES   => false, // vrais prepares, utile pour les BLOB/bytea
    ]);
} catch (Throwable $e) {
    respond(500, ['ok' => false, 'error' => 'db error: connect failed']);
}

$driver = $pdo->getAttribute(PDO::ATTR_DRIVER_NAME); // "mysql" ou "pgsql"

// ----------------------- 7) UPSERT selon le driver ---------------------------
/**
 * Table visée : invoice_jobs (voir DDL en bas)
 * Colonnes minimales :
 *   - task_id (PK)
 *   - status  (texte)
 *   - non_anonymous_pdf (BLOB/LONGBLOB ou BYTEA)
 *   - anonymous_pdf     (BLOB/LONGBLOB ou BYTEA)
 *   - completed_at (timestamp)
 */

if ($driver === 'mysql') {
    // MySQL/MariaDB — nécessite une PK ou un index unique sur task_id
    $sql = <<<SQL
INSERT INTO invoice_jobs (task_id, status, non_anonymous_pdf, anonymous_pdf, completed_at)
VALUES (:task_id, 'SUCCESS', :non_anon, :anon, NOW())
ON DUPLICATE KEY UPDATE
  status = VALUES(status),
  non_anonymous_pdf = VALUES(non_anonymous_pdf),
  anonymous_pdf     = VALUES(anonymous_pdf),
  completed_at      = VALUES(completed_at)
SQL;
} elseif ($driver === 'pgsql') {
    // PostgreSQL — nécessite CONSTRAINT UNIQUE/PK sur task_id
    $sql = <<<SQL
INSERT INTO invoice_jobs (task_id, status, non_anonymous_pdf, anonymous_pdf, completed_at)
VALUES (:task_id, 'SUCCESS', :non_anon, :anon, NOW())
ON CONFLICT (task_id) DO UPDATE SET
  status = EXCLUDED.status,
  non_anonymous_pdf = EXCLUDED.non_anonymous_pdf,
  anonymous_pdf     = EXCLUDED.anonymous_pdf,
  completed_at      = EXCLUDED.completed_at
SQL;
} else {
    respond(500, ['ok' => false, 'error' => 'unsupported driver: '.$driver]);
}

try {
    $stmt = $pdo->prepare($sql);
    // task_id en texte
    $stmt->bindValue(':task_id', $taskId, PDO::PARAM_STR);
    // PDF en binaire – PARAM_LOB marche pour MySQL (BLOB) et PgSQL (bytea) en PDO
    $stmt->bindValue(':non_anon', $nonAnon, PDO::PARAM_LOB);
    $stmt->bindValue(':anon',     $anon,     PDO::PARAM_LOB);
    $stmt->execute();
} catch (Throwable $e) {
    // Pour débug : error_log($e->getMessage());
    respond(500, ['ok' => false, 'error' => 'db error: upsert failed']);
}

// ----------------------- 8) Réponse HTTP 200 -------------------------------
respond(200, ['ok' => true, 'task_id' => $taskId, 'driver' => $driver]);

/**
 * =======================================================================
 *  CHECKLIST pour l’équipe PHP (DB)
 * =======================================================================
 * ✅ Exposer cette route en POST (ex: /internal/invoice-ready) via HTTPS en prod
 * ✅ Définir les variables d’environnement :
 *      - DB_DSN, DB_USER, DB_PASS
 *      - WEBHOOK_TOKEN (recommandé) et/ou WEBHOOK_SECRET (HMAC)
 * ✅ Créer la table `invoice_jobs` (DDL ci-dessous) avec PK sur task_id
 * ✅ Vérifier que le worker envoie bien X-Task-Id + JSON avec les 2 champs Base64
 * ✅ Retourner 200 rapidement (≤ 1–2 s). Pas de logique lourde ici.
 * ✅ Idempotence : UPSERT par task_id (déjà géré par ce script)
 * ✅ Monitoring : garder un oeil sur les logs (erreurs DB, base64 invalide)
 *
 * -----------------------------------------------------------------------
 *  DDL MySQL (utf8mb4)
 * -----------------------------------------------------------------------
 * CREATE TABLE invoice_jobs (
 *   task_id            VARCHAR(64) PRIMARY KEY,
 *   status             VARCHAR(16) NOT NULL,
 *   non_anonymous_pdf  LONGBLOB    NOT NULL,
 *   anonymous_pdf      LONGBLOB    NOT NULL,
 *   created_at         TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
 *   completed_at       TIMESTAMP   NULL     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
 * ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
 *
 * -- Option : index additionnels si vous requêtez souvent par dates
 * -- CREATE INDEX idx_invoice_jobs_completed_at ON invoice_jobs (completed_at);
 *
 * -----------------------------------------------------------------------
 *  DDL PostgreSQL
 * -----------------------------------------------------------------------
 * CREATE TABLE public.invoice_jobs (
 *   task_id            text PRIMARY KEY,
 *   status             text        NOT NULL,
 *   non_anonymous_pdf  bytea       NOT NULL,
 *   anonymous_pdf      bytea       NOT NULL,
 *   created_at         timestamptz NOT NULL DEFAULT now(),
 *   completed_at       timestamptz NULL
 * );
 * -- Option : index sur completed_at
 * -- CREATE INDEX idx_invoice_jobs_completed_at ON public.invoice_jobs (completed_at);
 *
 * -----------------------------------------------------------------------
 *  TEST RAPIDE (sans le worker)
 * -----------------------------------------------------------------------
 * 1) Lancer le serveur PHP :
 *    DB_DSN='mysql:host=127.0.0.1;port=3306;dbname=invoices;charset=utf8mb4' \
 *    DB_USER='root' DB_PASS='root' \
 *    WEBHOOK_TOKEN='secret' \
 *    php -S 127.0.0.1:8088 -t public
 *
 * 2) Envoyer un POST factice :
 *    body='{"non_anonymous_report_base64":"Tk8=","anonymous_report_base64":"Tk8="}'
 *    curl -i -X POST http://127.0.0.1:8088/invoice_ready.php \
 *      -H "Content-Type: application/json" \
 *      -H "Authorization: Bearer secret" \
 *      -H "X-Task-Id: test-123" \
 *      -d "$body"
 *
 * 3) Vérifier en SQL que la ligne existe (et contient des octets) :
 *    -- MySQL : SELECT task_id, status, OCTET_LENGTH(non_anonymous_pdf) AS n1, OCTET_LENGTH(anonymous_pdf) AS n2 FROM invoice_jobs WHERE task_id='test-123';
 *    -- PgSQL : SELECT task_id, status, OCTET_LENGTH(non_anonymous_pdf) AS n1, OCTET_LENGTH(anonymous_pdf) AS n2 FROM invoice_jobs WHERE task_id='test-123';
 *
 * -----------------------------------------------------------------------
 *  REMARQUES
 * -----------------------------------------------------------------------
 * - Ce script n’a PAS changé la logique métier : il remplace l’écriture “fichier”
 *   par un UPSERT DB. Le contrat JSON côté worker/API reste identique.
 * - Pour de très gros volumes/fichiers, envisagez le stockage objet (S3/MinIO) :
 *   le worker enverra des URL au lieu des blobs (même squelette d’UPSERT).
 * - Si vous avez appliqué le patch Python proposant retry + X-Task-Id + HMAC,
 *   la livraison devient encore plus robuste (mais le présent handler fonctionne
 *   aussi sans HMAC/Bearer).
 */
