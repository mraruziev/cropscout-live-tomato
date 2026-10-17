<?php
/**
 * CropSCOUT Vision — field-note endpoint.
 *
 * GET  ?options=1   the option lists the browser renders (covered conditions
 *                   from the installed models, plus known coverage gaps).
 * POST              record one field note. The photo is stored only when the
 *                   grower ticked "contribute this photo".
 *
 * A field note is queued for human review. Nothing posted here changes a
 * screening result, now or later: models are retrained offline, from notes a
 * reviewer accepted.
 */
declare(strict_types=1);

require_once __DIR__ . '/secure.php';
require_secure_vision_request();
require_once __DIR__ . '/lib/feedback.php';

// This route answers JSON. A stray notice or warning printed by the host's PHP
// configuration would corrupt that body, so nothing but JSON may reach output.
@ini_set('display_errors', '0');
ob_start();

header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');
header('X-Robots-Tag: noindex, nofollow, noarchive');

function feedback_json(int $status, array $payload): never
{
    while (ob_get_level() > 0) {
        ob_end_clean();
    }
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';

if ($method === 'GET' || $method === 'HEAD') {
    if (!isset($_GET['options'])) {
        feedback_json(400, ['error' => 'Add ?options=1 to read the field-note option lists.']);
    }
    try {
        $options = feedback_options();
    } catch (Throwable) {
        feedback_json(503, ['error' => 'Field notes are not available on this server yet.']);
    }
    if ($method === 'HEAD') {
        http_response_code(204);
        exit;
    }
    feedback_json(200, $options);
}

if ($method !== 'POST') {
    header('Allow: GET, HEAD, POST');
    feedback_json(405, ['error' => 'Method not allowed.']);
}

$text = static function (string $key, int $limit): string {
    $value = $_POST[$key] ?? '';
    if (!is_string($value)) {
        return '';
    }
    $value = trim(preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/u', '', $value) ?? '');
    return mb_substr($value, 0, $limit);
};

$fingerprint = $text('fingerprint', 64);
$crop = $text('crop', 32);
$organ = $text('organ', 16);
$verdict = $text('verdict', 16);
$userLabel = $text('user_label', 120);
$growthStage = $text('growth_stage', 24);
$severity = $text('severity', 16);
$note = $text('note', 600);
$modelLabel = $text('model_label', 120);
$modelDiagnosis = $text('model_diagnosis', 160);
$modelStatus = $text('model_status', 80);
$modelScoreRaw = $text('model_score', 12);

if (!preg_match('/^[0-9a-f]{16,64}$/', $fingerprint)) {
    feedback_json(422, ['error' => 'The photo fingerprint is missing or malformed.']);
}
if (!in_array($crop, ['Apple', 'Tomato', 'Cucumber', 'Lemon'], true)) {
    feedback_json(422, ['error' => 'Choose one of the supported crops.']);
}
if (!in_array($organ, ['leaf', 'fruit'], true)) {
    feedback_json(422, ['error' => 'Choose leaf or fruit.']);
}
if (!in_array($verdict, ['confirmed', 'corrected', 'unsure'], true)) {
    feedback_json(422, ['error' => 'Say whether the result matched what you saw.']);
}
$family = $crop . '_' . $organ;
if ($verdict === 'corrected') {
    if ($userLabel === '' || !feedback_label_is_allowed($family, $userLabel)) {
        feedback_json(422, ['error' => 'Choose which pattern you actually see.']);
    }
} else {
    $userLabel = $verdict === 'confirmed' ? $modelLabel : '';
}
if ($growthStage !== '' && !array_key_exists($growthStage, feedback_growth_stages())) {
    feedback_json(422, ['error' => 'Choose a listed growth stage.']);
}
if ($severity !== '' && !array_key_exists($severity, feedback_severities())) {
    feedback_json(422, ['error' => 'Choose a listed severity.']);
}
$modelScore = is_numeric($modelScoreRaw) ? max(0.0, min(1.0, (float)$modelScoreRaw)) : null;

try {
    if (feedback_rate_limit_exceeded()) {
        feedback_json(429, ['error' => 'Too many field notes from this connection in the last hour. Try again later.']);
    }

    $photo = ['name' => null, 'sha256' => null];
    $contribute = ($_POST['contribute'] ?? '') === '1';
    if ($contribute && isset($_FILES['photo']) && is_array($_FILES['photo'])) {
        try {
            $photo = feedback_store_photo($_FILES['photo']);
        } catch (RuntimeException $error) {
            feedback_json(422, ['error' => $error->getMessage()]);
        }
    }

    $covered = $userLabel !== '' && !str_starts_with($userLabel, 'gap:')
        && $userLabel !== 'unsure' && $userLabel !== 'other';

    $id = feedback_insert([
        'created_at' => feedback_now_iso(),
        'fingerprint' => $fingerprint,
        'crop' => $crop,
        'organ' => $organ,
        'family' => $family,
        'model_label' => $modelLabel !== '' ? $modelLabel : null,
        'model_diagnosis' => $modelDiagnosis !== '' ? $modelDiagnosis : null,
        'model_score' => $modelScore,
        'model_status' => $modelStatus !== '' ? $modelStatus : null,
        'verdict' => $verdict,
        'user_label' => $userLabel !== '' ? $userLabel : null,
        'user_label_covered' => $covered ? 1 : 0,
        'growth_stage' => $growthStage !== '' ? $growthStage : null,
        'severity' => $severity !== '' ? $severity : null,
        'note' => $note !== '' ? $note : null,
        'photo_name' => $photo['name'],
        'photo_sha256' => $photo['sha256'],
    ]);
    feedback_record_submission();

    feedback_json(201, [
        'id' => $id,
        'stored_photo' => $photo['name'] !== null,
        'totals' => feedback_public_totals(),
        'policy' => 'Recorded for human review. This note does not change any automatic result.',
    ]);
} catch (Throwable) {
    feedback_json(503, ['error' => 'Field notes could not be saved on this server. Your result is unaffected.']);
}
