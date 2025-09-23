<?php
// public/invoice_ready.php
$raw = file_get_contents('php://input');
$taskId = $_SERVER['HTTP_X_TASK_ID'] ?? null;

// Simple bearer auth (match WEBHOOK_TOKEN in your .env)
$auth = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
$token = getenv('WEBHOOK_TOKEN') ?: '';
if ($token && $auth !== "Bearer $token") {
  http_response_code(401); echo '{"ok":false,"error":"unauthorized"}'; exit;
}

// Optional HMAC verify (match WEBHOOK_SECRET)
$secret = getenv('WEBHOOK_SECRET') ?: '';
if ($secret) {
  $sig = $_SERVER['HTTP_X_WEBHOOK_SIGNATURE'] ?? '';
  $expected = hash_hmac('sha256', $raw, $secret);
  if (!hash_equals($expected, $sig)) {
    http_response_code(401); echo '{"ok":false,"error":"bad signature"}'; exit;
  }
}

$payload = json_decode($raw, true);
if (!$taskId || !is_array($payload)) {
  http_response_code(400); echo '{"ok":false,"error":"bad request"}'; exit;
}

// Decode Base64 -> bytes
$nonAnon = base64_decode($payload['non_anonymous_report_base64'] ?? '', true);
$anon    = base64_decode($payload['anonymous_report_base64'] ?? '', true);

// Idempotent upsert by task_id (pseudo DB)
// TODO: replace with your DB call (MySQL/Postgres)
file_put_contents(__DIR__."/../uploads/{$taskId}.nonanon.pdf", $nonAnon);
file_put_contents(__DIR__."/../uploads/{$taskId}.anon.pdf", $anon);

http_response_code(200);
header('Content-Type: application/json');
echo '{"ok":true}';
