<?php
/**
 * Keep the public camera and model routes on a secure origin.
 *
 * Browsers expose getUserMedia() only to HTTPS pages (localhost is the
 * development exception). The fixed canonical host also avoids reflecting an
 * untrusted Host header into a redirect response.
 */
declare(strict_types=1);

function cropscout_remote_is_loopback(): bool {
    $remote = trim((string)($_SERVER['REMOTE_ADDR'] ?? ''));
    return $remote === '::1' || preg_match('/^127(?:\.[0-9]{1,3}){3}$/', $remote) === 1;
}

function cropscout_request_is_https(): bool {
    if (!empty($_SERVER['HTTPS']) && strtolower((string)$_SERVER['HTTPS']) !== 'off') {
        return true;
    }
    if ((string)($_SERVER['SERVER_PORT'] ?? '') === '443') {
        return true;
    }
    // Only trust a forwarded scheme from a proxy on this machine. A public
    // requester must not be able to spoof this header to keep the camera on HTTP.
    if (cropscout_remote_is_loopback()) {
        $forwarded = strtolower(trim(explode(',', (string)($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? ''))[0]));
        return $forwarded === 'https';
    }
    return false;
}

function cropscout_request_is_local(): bool {
    $host = (string)($_SERVER['HTTP_HOST'] ?? '');
    return cropscout_remote_is_loopback()
        && preg_match('/^(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]+)?$/i', $host) === 1;
}

function require_secure_vision_request(): void {
    if (cropscout_request_is_https() || cropscout_request_is_local()) {
        return;
    }

    $requestUri = (string)($_SERVER['REQUEST_URI'] ?? '/vision/');
    if ($requestUri === '' || $requestUri[0] !== '/' || preg_match('/[\r\n]/', $requestUri) === 1) {
        $requestUri = '/vision/';
    }

    header('Location: https://crop-scout.com' . $requestUri, true, 302);
    exit;
}
