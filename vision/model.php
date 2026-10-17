<?php
/**
 * Public, allowlisted model delivery for browser-local crop screening.
 *
 * Model files are deliberately kept beneath private/, which Apache blocks.
 * Only the fixed model aliases below may be streamed. No survey configuration,
 * credentials, training images or arbitrary paths are exposed by this route.
 */
declare(strict_types=1);

require_once __DIR__ . '/secure.php';
require_secure_vision_request();

if ($_SERVER['REQUEST_METHOD'] !== 'GET' && $_SERVER['REQUEST_METHOD'] !== 'HEAD') {
    header('Allow: GET, HEAD');
    http_response_code(405);
    exit('Method not allowed.');
}

$models = [
    'metadata' => [
        'path' => __DIR__ . '/private/model-metadata.json',
        'download_name' => 'cropscout-model-metadata.json',
        'content_type' => 'application/json; charset=utf-8',
    ],
    'crop-view' => [
        'path' => __DIR__ . '/private/cropscout-crop-view.onnx',
        'download_name' => 'cropscout-crop-view.onnx',
        'content_type' => 'application/octet-stream',
    ],
    'disease' => [
        'path' => __DIR__ . '/private/cropscout-disease.onnx',
        'download_name' => 'cropscout-disease.onnx',
        'content_type' => 'application/octet-stream',
    ],
    'cucumber-leaf' => [
        'path' => __DIR__ . '/private/cropscout-cucumber-leaf.onnx',
        'download_name' => 'cropscout-cucumber-leaf.onnx',
        'content_type' => 'application/octet-stream',
    ],
    'lemon-leaf' => [
        'path' => __DIR__ . '/private/cropscout-lemon-leaf.onnx',
        'download_name' => 'cropscout-lemon-leaf.onnx',
        'content_type' => 'application/octet-stream',
    ],
];

$requested = isset($_GET['model']) && is_string($_GET['model']) ? $_GET['model'] : '';
if (!array_key_exists($requested, $models)) {
    http_response_code(400);
    header('Content-Type: text/plain; charset=utf-8');
    exit('Unknown model alias.');
}

$model = $models[$requested];
// Merely uploading a candidate lemon model must not activate or publish it.
// Root release metadata enables this optional route only after model validation.
if ($requested === 'lemon-leaf') {
    $raw = @file_get_contents(__DIR__ . '/private/model-metadata.json');
    $metadata = is_string($raw) ? json_decode($raw, true) : null;
    $enabled = false;
    if (is_array($metadata) && isset($metadata['condition_specialists']) && is_array($metadata['condition_specialists'])) {
        foreach ($metadata['condition_specialists'] as $specialist) {
            if (is_array($specialist) && ($specialist['id'] ?? '') === 'lemon-leaf'
                && ($specialist['families'] ?? []) === ['Lemon_leaf']) {
                $enabled = true;
                break;
            }
        }
    }
    if (!$enabled) {
        http_response_code(503);
        header('Content-Type: text/plain; charset=utf-8');
        header('Cache-Control: no-store');
        exit('This optional model has not been enabled in the release metadata.');
    }
}
$path = $model['path'];
if (!is_file($path) || !is_readable($path)) {
    http_response_code(503);
    header('Content-Type: text/plain; charset=utf-8');
    header('Cache-Control: no-store');
    exit('This model has not been installed on the server yet.');
}

$size = filesize($path);
$modified = filemtime($path);
if ($size === false || $modified === false) {
    http_response_code(500);
    exit('Could not read model metadata.');
}

$etag = '"' . hash('sha256', $requested . ':' . $size . ':' . $modified) . '"';
if (isset($_SERVER['HTTP_IF_NONE_MATCH']) && trim((string)$_SERVER['HTTP_IF_NONE_MATCH']) === $etag) {
    http_response_code(304);
    header('ETag: ' . $etag);
    exit;
}

header('Content-Type: ' . $model['content_type']);
header('Content-Disposition: inline; filename="' . $model['download_name'] . '"');
header('Content-Length: ' . $size);
header('Cache-Control: public, max-age=3600, must-revalidate');
header('ETag: ' . $etag);
header('X-Content-Type-Options: nosniff');
header('X-Robots-Tag: noindex, nofollow, noarchive');

if ($_SERVER['REQUEST_METHOD'] === 'HEAD') {
    exit;
}

if (readfile($path) === false) {
    http_response_code(500);
}
