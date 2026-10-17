<?php
/**
 * CropSCOUT Vision — field-note review.
 *
 * Growers' notes are candidates, not labels. A reviewer accepts, rejects, or
 * relabels each one here; only accepted notes are exported as training
 * candidates. Sign-in reuses the existing CropSCOUT team password (the same one
 * that protects the survey dashboard). The public screening page itself has no
 * sign-in and does not load this file.
 */
declare(strict_types=1);

require_once __DIR__ . '/secure.php';
require_secure_vision_request();
require_once __DIR__ . '/lib/feedback.php';

header('Cache-Control: no-store');
header('X-Robots-Tag: noindex, nofollow, noarchive');
header('Referrer-Policy: same-origin');

/**
 * Reuse the existing CropSCOUT team password, but not the survey's database.
 *
 * Only the stored bcrypt hash is read. Nothing here includes survey/lib/db.php,
 * so reviewing field notes keeps working even when the survey is unconfigured,
 * and the public screening page still has no sign-in of any kind.
 */
const REVIEW_AUTH_PATH = __DIR__ . '/../survey/data/auth.php';

function review_stored_hash(): ?string
{
    if (!is_file(REVIEW_AUTH_PATH)) {
        return null;
    }
    $data = @include REVIEW_AUTH_PATH;
    return is_array($data) && !empty($data['hash']) && is_string($data['hash']) ? $data['hash'] : null;
}

function review_boot_session(): void
{
    if (session_status() === PHP_SESSION_ACTIVE) {
        return;
    }
    $https = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off')
        || (($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https');
    session_set_cookie_params([
        'lifetime' => 0,
        'path' => '/vision/',
        'httponly' => true,
        'secure' => $https,
        'samesite' => 'Lax',
    ]);
    session_name('cropscout_vision_review');
    session_start();
}

function review_is_admin(): bool
{
    review_boot_session();
    if (empty($_SESSION['vision_review'])) {
        return false;
    }
    if (time() - (int)($_SESSION['login_time'] ?? 0) > 60 * 60 * 12) {
        $_SESSION = [];
        return false;
    }
    return true;
}

review_boot_session();

if (isset($_GET['signout'])) {
    $_SESSION = [];
    if (ini_get('session.use_cookies')) {
        $params = session_get_cookie_params();
        setcookie(session_name(), '', time() - 42000, $params['path'], $params['domain'], $params['secure'], $params['httponly']);
    }
    session_destroy();
    header('Location: feedback-review.php');
    exit;
}

$loginError = '';
if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST' && isset($_POST['password'])) {
    $hash = review_stored_hash();
    usleep(random_int(150000, 400000));
    if ($hash === null) {
        $loginError = 'No team password is configured on this server yet. Set one at /survey/setup.php.';
    } elseif (password_verify((string)$_POST['password'], $hash)) {
        session_regenerate_id(true);
        $_SESSION['vision_review'] = true;
        $_SESSION['login_time'] = time();
        header('Location: feedback-review.php');
        exit;
    } else {
        $loginError = 'That password was not accepted.';
    }
}

function review_escape(?string $value): string
{
    return htmlspecialchars((string)$value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

if (!review_is_admin()) {
    http_response_code(401);
    ?><!DOCTYPE html>
    <html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="robots" content="noindex, nofollow">
    <title>Field notes — team sign-in</title>
    <link rel="stylesheet" href="styles.css"></head>
    <body class="review-body">
    <main class="review-shell">
        <h1>Field notes</h1>
        <p class="review-lede">Grower feedback waiting for review. Sign in with the CropSCOUT team password.</p>
        <?php if ($loginError !== ''): ?><p class="review-error"><?= review_escape($loginError) ?></p><?php endif; ?>
        <form method="post" class="review-login">
            <label for="password">Team password</label>
            <input type="password" id="password" name="password" autocomplete="current-password" required>
            <button type="submit">Sign in</button>
        </form>
        <p class="review-foot"><a href="index.php">Back to screening</a></p>
    </main></body></html>
    <?php
    exit;
}

$pdo = feedback_db();
$flash = '';

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST' && isset($_POST['note_id'])) {
    $id = (int)$_POST['note_id'];
    $action = (string)($_POST['action'] ?? '');
    $reviewerLabel = trim((string)($_POST['reviewer_label'] ?? ''));
    if (in_array($action, ['accepted', 'rejected', 'new'], true) && $id > 0) {
        $statement = $pdo->prepare(
            'UPDATE field_notes SET review_state = ?, reviewer_label = ?, reviewed_at = ? WHERE id = ?'
        );
        $statement->execute([
            $action,
            $reviewerLabel !== '' ? mb_substr($reviewerLabel, 0, 120) : null,
            feedback_now_iso(),
            $id,
        ]);
        $flash = "Note #{$id} marked {$action}.";
    }
}

if (isset($_GET['export'])) {
    $rows = $pdo->query('SELECT * FROM field_notes ORDER BY id')->fetchAll();
    header('Content-Type: text/csv; charset=utf-8');
    header('Content-Disposition: attachment; filename="cropscout-field-notes.csv"');
    $out = fopen('php://output', 'wb');
    if ($rows !== []) {
        fputcsv($out, array_keys($rows[0]));
        foreach ($rows as $row) {
            fputcsv($out, array_values($row));
        }
    } else {
        fputcsv($out, ['id', 'created_at', 'fingerprint', 'crop', 'organ', 'verdict']);
    }
    fclose($out);
    exit;
}

if (isset($_GET['photos'])) {
    if (!class_exists('ZipArchive')) {
        http_response_code(503);
        exit('The zip extension is not installed on this server. Download the CSV and copy vision/private/feedback/ over SFTP instead.');
    }
    $rows = $pdo->query(
        "SELECT * FROM field_notes WHERE review_state = 'accepted' AND photo_name IS NOT NULL AND photo_name <> '' ORDER BY id"
    )->fetchAll();
    $temporary = tempnam(sys_get_temp_dir(), 'cropscout-notes-');
    $zip = new ZipArchive();
    if ($temporary === false || $zip->open($temporary, ZipArchive::OVERWRITE) !== true) {
        http_response_code(500);
        exit('The export could not be created.');
    }
    $manifest = [];
    foreach ($rows as $row) {
        $path = FEEDBACK_PHOTO_DIR . '/' . $row['photo_name'];
        if (!is_file($path)) {
            continue;
        }
        $label = $row['reviewer_label'] ?: $row['user_label'];
        $entry = 'photos/' . $row['id'] . '_' . preg_replace('/[^A-Za-z0-9_.-]/', '_', (string)$label) . '.jpg';
        $zip->addFile($path, $entry);
        $manifest[] = [
            'id' => (int)$row['id'],
            'file' => $entry,
            'crop' => $row['crop'],
            'organ' => $row['organ'],
            'reviewed_label' => $label,
            'grower_label' => $row['user_label'],
            'grower_verdict' => $row['verdict'],
            'model_label' => $row['model_label'],
            'model_score' => $row['model_score'],
            'growth_stage' => $row['growth_stage'],
            'severity' => $row['severity'],
            'created_at' => $row['created_at'],
            'photo_sha256' => $row['photo_sha256'],
        ];
    }
    $zip->addFromString('manifest.json', json_encode([
        'schema_version' => 1,
        'exported_at' => feedback_now_iso(),
        'scope' => 'accepted field notes with a contributed photo',
        'caution' => 'Reviewer labels are field observations, not laboratory diagnoses. Treat them as weak labels and keep them in a separate source group when training.',
        'notes' => $manifest,
    ], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES));
    $zip->close();
    header('Content-Type: application/zip');
    header('Content-Disposition: attachment; filename="cropscout-accepted-field-notes.zip"');
    header('Content-Length: ' . (string)filesize($temporary));
    readfile($temporary);
    @unlink($temporary);
    exit;
}

if (isset($_GET['photo'])) {
    $id = (int)$_GET['photo'];
    $statement = $pdo->prepare('SELECT photo_name FROM field_notes WHERE id = ?');
    $statement->execute([$id]);
    $name = (string)$statement->fetchColumn();
    $path = realpath(FEEDBACK_PHOTO_DIR . '/' . $name);
    $root = realpath(FEEDBACK_PHOTO_DIR);
    if ($name === '' || $path === false || $root === false || !str_starts_with($path, $root) || !is_file($path)) {
        http_response_code(404);
        exit('No photo for that note.');
    }
    header('Content-Type: image/jpeg');
    header('Content-Length: ' . (string)filesize($path));
    readfile($path);
    exit;
}

$filter = (string)($_GET['state'] ?? 'new');
if (!in_array($filter, ['new', 'accepted', 'rejected', 'all'], true)) {
    $filter = 'new';
}
$notes = $filter === 'all'
    ? $pdo->query('SELECT * FROM field_notes ORDER BY id DESC LIMIT 300')->fetchAll()
    : (static function (PDO $pdo, string $state): array {
        $statement = $pdo->prepare('SELECT * FROM field_notes WHERE review_state = ? ORDER BY id DESC LIMIT 300');
        $statement->execute([$state]);
        return $statement->fetchAll();
    })($pdo, $filter);

$counts = [];
foreach ($pdo->query('SELECT review_state, COUNT(*) AS total FROM field_notes GROUP BY review_state') as $row) {
    $counts[$row['review_state']] = (int)$row['total'];
}
$byGap = $pdo->query(
    "SELECT user_label, COUNT(*) AS total FROM field_notes WHERE user_label LIKE 'gap:%' GROUP BY user_label ORDER BY total DESC LIMIT 12"
)->fetchAll();
$byStage = $pdo->query(
    "SELECT growth_stage, severity, COUNT(*) AS total FROM field_notes WHERE growth_stage IS NOT NULL GROUP BY growth_stage, severity ORDER BY total DESC LIMIT 12"
)->fetchAll();
?><!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Field notes — review</title>
<link rel="stylesheet" href="styles.css">
</head>
<body class="review-body">
<main class="review-shell wide">
    <header class="review-head">
        <div>
            <h1>Field notes</h1>
            <p class="review-lede">Grower feedback on screening results. Accept a note only when the photo supports the label. Accepted notes become weak training candidates, never ground truth.</p>
        </div>
        <a class="review-signout" href="?signout=1">Sign out</a>
    </header>

    <?php if ($flash !== ''): ?><p class="review-flash"><?= review_escape($flash) ?></p><?php endif; ?>

    <section class="review-summary">
        <div><strong><?= (int)($counts['new'] ?? 0) ?></strong><span>waiting</span></div>
        <div><strong><?= (int)($counts['accepted'] ?? 0) ?></strong><span>accepted</span></div>
        <div><strong><?= (int)($counts['rejected'] ?? 0) ?></strong><span>rejected</span></div>
        <div><strong><?= (int)feedback_public_totals()['photos'] ?></strong><span>photos contributed</span></div>
    </section>

    <?php if ($byGap !== []): ?>
    <section class="review-block">
        <h2>Most reported gaps — patterns the models cannot name yet</h2>
        <ul class="review-list">
            <?php foreach ($byGap as $row): ?>
            <li><span><?= review_escape(str_replace('gap:', '', (string)$row['user_label'])) ?></span><strong><?= (int)$row['total'] ?></strong></li>
            <?php endforeach; ?>
        </ul>
        <p class="review-hint">These are the classes to add in the next training round.</p>
    </section>
    <?php endif; ?>

    <?php if ($byStage !== []): ?>
    <section class="review-block">
        <h2>Growth stage and severity of reported problems</h2>
        <ul class="review-list">
            <?php foreach ($byStage as $row): ?>
            <li><span><?= review_escape((string)$row['growth_stage']) ?> · <?= review_escape((string)($row['severity'] ?? 'unknown')) ?></span><strong><?= (int)$row['total'] ?></strong></li>
            <?php endforeach; ?>
        </ul>
        <p class="review-hint">Early-stage reports are the ones worth chasing: CropSCOUT sprays to save a crop, so the models must fire before symptoms are severe.</p>
    </section>
    <?php endif; ?>

    <nav class="review-filters">
        <?php foreach (['new' => 'Waiting', 'accepted' => 'Accepted', 'rejected' => 'Rejected', 'all' => 'All'] as $key => $text): ?>
            <a class="<?= $filter === $key ? 'active' : '' ?>" href="?state=<?= $key ?>"><?= $text ?></a>
        <?php endforeach; ?>
        <a href="?export=1">Download CSV</a>
        <a href="?photos=1">Download accepted photos (ZIP)</a>
    </nav>

    <?php if ($notes === []): ?>
        <p class="review-empty">No field notes in this view yet.</p>
    <?php endif; ?>

    <?php foreach ($notes as $note): ?>
    <article class="review-note">
        <?php if (!empty($note['photo_name'])): ?>
            <img src="?photo=<?= (int)$note['id'] ?>" alt="Contributed photo for note <?= (int)$note['id'] ?>" loading="lazy">
        <?php else: ?>
            <div class="review-nophoto"><span>no photo<br>contributed</span></div>
        <?php endif; ?>
        <div class="review-note-body">
            <p class="review-note-head">
                #<?= (int)$note['id'] ?> · <?= review_escape($note['crop']) ?> <?= review_escape($note['organ']) ?>
                · <?= review_escape($note['created_at']) ?>
                · <span class="review-state <?= review_escape($note['review_state']) ?>"><?= review_escape($note['review_state']) ?></span>
            </p>
            <dl class="review-facts">
                <div><dt>Model said</dt><dd><?= review_escape($note['model_diagnosis'] ?: ($note['model_label'] ?: 'nothing accepted')) ?><?= $note['model_score'] !== null ? ' · ' . (int)round(((float)$note['model_score']) * 100) . '%' : '' ?></dd></div>
                <div><dt>Grower said</dt><dd><?= review_escape($note['verdict']) ?><?= $note['user_label'] ? ' · ' . review_escape($note['user_label']) : '' ?></dd></div>
                <div><dt>Stage</dt><dd><?= review_escape($note['growth_stage'] ?: 'not given') ?> · <?= review_escape($note['severity'] ?: 'severity not given') ?></dd></div>
                <?php if (!empty($note['note'])): ?><div><dt>Note</dt><dd><?= review_escape($note['note']) ?></dd></div><?php endif; ?>
            </dl>
            <form method="post" class="review-actions">
                <input type="hidden" name="note_id" value="<?= (int)$note['id'] ?>">
                <input type="text" name="reviewer_label" placeholder="Authoritative label (optional)" value="<?= review_escape($note['reviewer_label'] ?? '') ?>" maxlength="120">
                <button type="submit" name="action" value="accepted">Accept</button>
                <button type="submit" name="action" value="rejected">Reject</button>
                <button type="submit" name="action" value="new" class="ghost">Reset</button>
            </form>
        </div>
    </article>
    <?php endforeach; ?>

    <p class="review-foot">
        Accepted notes are weak labels from one photograph. Keep them in their own source group when training, and never let them outvote an expert-labelled dataset.
        <a href="index.php">Back to screening</a>
    </p>
</main>
</body>
</html>
