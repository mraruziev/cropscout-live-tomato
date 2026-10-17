<?php
/** Backwards-compatible bookmark: public Vision no longer has a login. */
declare(strict_types=1);
require_once __DIR__ . '/secure.php';
require_secure_vision_request();
header('Cache-Control: no-store');
header('Location: index.php', true, 303);
exit;
