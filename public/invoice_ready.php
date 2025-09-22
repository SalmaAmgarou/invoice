<?php
// ============================================================================
// invoice_ready.php — Récepteur de webhook (POST) pour recevoir 2 PDFs en Base64
// ============================================================================
//
// RÔLE (côté PHP) :
//   - Recevoir l'appel POST envoyé par le worker Python à la fin du traitement.
//   - Vérifier (optionnel) un token Bearer et/ou une signature HMAC.
//   - Décoder les 2 PDFs (non anonymisé + anonymisé) depuis le JSON reçu.
//   - (Aujourd'hui) Écrire les fichiers sur disque dans ../uploads/  (POC/dev).
//   - (Demain) Remplacer l'écriture sur disque par un UPSERT en base (MySQL/PG).
//
// CONTRAT D’ENTRÉE (ce que le worker envoie) :
//   Headers :
//     - X-Task-Id: <uuid>                (obligatoire ; sert d’ID idempotent)
//     - Authorization: Bearer <TOKEN>    (optionnel mais recommandé)
//     - X-Webhook-Signature: <HEX>       (optionnel ; HMAC-SHA256 du body)
//
//   Body JSON :
//   {
//     "non_anonymous_report_base64": "<base64 du PDF non anonymisé>",
//     "anonymous_report_base64":     "<base64 du PDF anonymisé>"
//   }
//
// VARIABLES D’ENV À DÉFINIR (selon votre infra) :
//   - WEBHOOK_TOKEN   : si défini => on exige Authorization: Bearer <WEBHOOK_TOKEN>
//   - WEBHOOK_SECRET  : si défini => on exige X-Webhook-Signature = HMAC_SHA256(body, secret)
//
//   (Pour la future persistance en DB, voir le BLOC EXEMPLE PDO plus bas)
//   - DB_DSN   : ex MySQL  -> "mysql:host=127.0.0.1;port=3306;dbname=invoices;charset=utf8mb4"
//               ex PGSQL   -> "pgsql:host=127.0.0.1;port=5432;dbname=invoices"
//   - DB_USER  : utilisateur DB
//   - DB_PASS  : mot de passe DB
//
// RÉPONSES :
//   - 200 {"ok":true}                         => fichiers bien reçus/écrits (ou DB ok)
//   - 400 {"ok":false,"error":"bad request"}  => pas de taskId / body invalide
//   - 401 {"ok":false,"error":"unauthorized"} => mauvais Bearer
//   - 401 {"ok":false,"error":"bad signature"}=> HMAC invalide
//
// IMPORTANT EN DEV :
//   - Ce script ÉCRIT dans ../uploads/  -> assurez-vous que le dossier existe :
//       mkdir -p /chemin/vers/public/../uploads && chmod 775 …
//   - Si vous voyez “Failed to open stream: No such file or directory”, c’est que
//     le dossier n’existe pas ou n’est pas accessible en écriture.
//
// CHECKLIST RAPIDE POUR L’ÉQUIPE :
//   [ ] Exposer cette route en POST (ex. /internal/invoice-ready) derrière HTTPS.
//   [ ] Définir WEBHOOK_TOKEN (recommandé) et, si souhaité, WEBHOOK_SECRET (HMAC).
//   [ ] Créer le dossier ../uploads en dev (ou activer la partie DB plus bas).
//   [ ] Retourner 200 rapidement (<1–2s). Aucune logique lourde ici.
//   [ ] En prod : remplacez l’écriture sur disque par un UPSERT DB (voir exemple).
// ============================================================================


// -----------------------------------------------------------------------------
// Lecture du corps de la requête (JSON brut) et de l'ID de tâche
// -----------------------------------------------------------------------------
$raw = file_get_contents('php://input');
$taskId = $_SERVER['HTTP_X_TASK_ID'] ?? null;

// -----------------------------------------------------------------------------
// Authentification simple par Bearer (facultative)
//   - Si WEBHOOK_TOKEN est défini côté serveur, on exige "Authorization: Bearer <token>"
// -----------------------------------------------------------------------------
$auth = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
$token = getenv('WEBHOOK_TOKEN') ?: '';
if ($token && $auth !== "Bearer $token") {
  http_response_code(401); echo '{"ok":false,"error":"unauthorized"}'; exit;
}

// -----------------------------------------------------------------------------
// Vérification HMAC (facultative)
//   - Si WEBHOOK_SECRET est défini, on exige X-Webhook-Signature égal au
//     HMAC-SHA256(body, WEBHOOK_SECRET). Cela assure l'intégrité du message.
// -----------------------------------------------------------------------------
$secret = getenv('WEBHOOK_SECRET') ?: '';
if ($secret) {
  $sig = $_SERVER['HTTP_X_WEBHOOK_SIGNATURE'] ?? '';
  $expected = hash_hmac('sha256', $raw, $secret);
  if (!hash_equals($expected, $sig)) {
    http_response_code(401); echo '{"ok":false,"error":"bad signature"}'; exit;
  }
}

// -----------------------------------------------------------------------------
// Parsing du JSON reçu et contrôle de présence de X-Task-Id
// -----------------------------------------------------------------------------
$payload = json_decode($raw, true);
if (!$taskId || !is_array($payload)) {
  http_response_code(400); echo '{"ok":false,"error":"bad request"}'; exit;
}

// -----------------------------------------------------------------------------
// Décodage Base64 -> octets binaires (2 PDFs)
//   - $nonAnon : PDF non anonymisé
//   - $anon    : PDF anonymisé
// -----------------------------------------------------------------------------
$nonAnon = base64_decode($payload['non_anonymous_report_base64'] ?? '', true);
$anon    = base64_decode($payload['anonymous_report_base64'] ?? '', true);

// -----------------------------------------------------------------------------
// PERSISTENCE ACTUELLE (POC/DEV) : ÉCRITURE SUR DISQUE
//   - Le nom de fichier inclut le taskId pour l'idempotence : si le webhook est
//     re-livré, on écrase les mêmes fichiers.
//   - Dossier cible : ../uploads  (par rapport à /public)
//   - ⚠️ Assurez-vous que ../uploads existe et est accessible en écriture.
// -----------------------------------------------------------------------------

// Idempotent upsert by task_id (pseudo DB)
// TODO: replace with your DB call (MySQL/Postgres)
file_put_contents(__DIR__."/../uploads/{$taskId}.nonanon.pdf", $nonAnon);
file_put_contents(__DIR__."/../uploads/{$taskId}.anon.pdf", $anon);

// -----------------------------------------------------------------------------
// Réponse HTTP 200 (OK). Le client n’a pas besoin d’autre chose.
// -----------------------------------------------------------------------------
http_response_code(200);
header('Content-Type: application/json');
echo '{"ok":true}';


// ============================================================================
// BLOC EXEMPLE — PERSISTENCE EN BASE (MySQL/PostgreSQL) AVEC PDO (COMMENTÉ)
// ============================================================================
//
// ➜ Objectif : remplacer les 2 file_put_contents(...) ci-dessus par un UPSERT DB.
// ➜ Comment faire :
//    1) Décommentez la fonction save_reports_to_db(...) ci-dessous.
//    2) Décommentez l’appel juste après le décodage Base64 (et commentez l’écriture fichier).
//    3) Assurez-vous d’avoir installé l’extension PDO correspondante :
//         - MySQL : pdo_mysql   (Ubuntu : sudo apt install php8.x-mysql)
//         - PGSQL : pdo_pgsql   (Ubuntu : sudo apt install php8.x-pgsql)
//    4) Exportez les variables DB_DSN / DB_USER / DB_PASS avant de lancer le serveur.
//
//    SCHÉMA MINIMAL (une table unique façon “cache de résultats”):
//      MySQL :
//        CREATE TABLE invoice_jobs (
//          task_id            VARCHAR(64) PRIMARY KEY,
//          status             VARCHAR(16) NOT NULL,
//          non_anonymous_pdf  LONGBLOB    NOT NULL,
//          anonymous_pdf      LONGBLOB    NOT NULL,
//          created_at         TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
//          completed_at       TIMESTAMP   NULL
//        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
//
//      PostgreSQL :
//        CREATE TABLE public.invoice_jobs (
//          task_id            text PRIMARY KEY,
//          status             text   NOT NULL,
//          non_anonymous_pdf  bytea  NOT NULL,
//          anonymous_pdf      bytea  NOT NULL,
//          created_at         timestamptz NOT NULL DEFAULT now(),
//          completed_at       timestamptz NULL
//        );
//
//    NOTE : En production, vous aurez souvent un modèle plus riche (users, invoices,
//           jobs, reports, audit_events). Ce bloc montre le plus simple possible.
//
// ----------------------------------------------------------------------------
// EXEMPLE D’APPEL (à mettre à la place des file_put_contents) :
//
//    // save_reports_to_db($taskId, $nonAnon, $anon);   // <— décommentez ceci
//
// ----------------------------------------------------------------------------
// EXEMPLE D’IMPLÉMENTATION PDO (commentée) :
//
/*
function save_reports_to_db(string $taskId, string $nonAnonBytes, string $anonBytes): void {
    // 0) Récupérer la configuration DB (depuis l’environnement)
    $dsn  = getenv('DB_DSN')  ?: '';
    $user = getenv('DB_USER') ?: '';
    $pass = getenv('DB_PASS') ?: '';

    if ($dsn === '') {
        http_response_code(500);
        header('Content-Type: application/json');
        echo json_encode(['ok'=>false,'error'=>'db not configured']);
        exit;
    }

    // 1) Connexion PDO (erreurs en exceptions)
    try {
        $pdo = new PDO($dsn, $user, $pass, [
            PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES   => false,
        ]);
    } catch (Throwable $e) {
        http_response_code(500);
        header('Content-Type: application/json');
        echo json_encode(['ok'=>false,'error'=>'db connect failed']);
        exit;
    }

    // 2) Déterminer le driver (mysql | pgsql) pour choisir la syntaxe UPSERT
    $driver = $pdo->getAttribute(PDO::ATTR_DRIVER_NAME);

    if ($driver === 'mysql') {
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
        http_response_code(500);
        header('Content-Type: application/json');
        echo json_encode(['ok'=>false,'error'=>'unsupported driver']);
        exit;
    }

    // 3) Exécution (idempotent sur task_id)
    try {
        $stmt = $pdo->prepare($sql);
        $stmt->bindValue(':task_id', $taskId,    PDO::PARAM_STR);
        $stmt->bindValue(':non_anon', $nonAnonBytes, PDO::PARAM_LOB);
        $stmt->bindValue(':anon',     $anonBytes,    PDO::PARAM_LOB);
        $stmt->execute();
    } catch (Throwable $e) {
        http_response_code(500);
        header('Content-Type: application/json');
        echo json_encode(['ok'=>false,'error'=>'db upsert failed']);
        exit;
    }
}
*/
// ============================================================================
//
// TESTS RAPIDES (dev) :
//   1) Lancer le serveur PHP dans le dossier du fichier :
//        WEBHOOK_TOKEN='secret' php -S 127.0.0.1:8088 -t public
//   2) Simuler un POST webhook :
//        body='{"non_anonymous_report_base64":"Tk8=","anonymous_report_base64":"Tk8="}'
//        curl -i -X POST http://127.0.0.1:8088/invoice_ready.php \
//          -H "Content-Type: application/json" \
//          -H "Authorization: Bearer secret" \
//          -H "X-Task-Id: test-123" \
//          -d "$body"
//   3) Vérifier : deux fichiers test-123.nonanon.pdf / test-123.anon.pdf dans ../uploads
//
//   (Si vous activez la DB)
//   - Assurez-vous d’avoir pdo_mysql OU pdo_pgsql (php -m | grep -Ei 'pdo|mysql|pgsql')
//   - Exportez DB_DSN/DB_USER/DB_PASS puis décommentez save_reports_to_db(...)
// ============================================================================

