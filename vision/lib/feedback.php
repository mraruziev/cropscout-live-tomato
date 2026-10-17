<?php
/**
 * CropSCOUT Vision — field notes (user feedback) storage.
 *
 * A field note is a grower telling us whether a screening result matched what
 * they saw, and if not, which pattern it actually was. A note is EVIDENCE FOR
 * REVIEW, never ground truth: nothing here is fed back into a model
 * automatically, and the browser never lets a note change a screening verdict.
 * Notes are queued for a human to accept or reject, and only accepted notes
 * become training candidates.
 *
 * Photos are stored only when the grower explicitly ticks "contribute this
 * photo". They are re-encoded through GD, which drops EXIF and any GPS tag.
 */
declare(strict_types=1);

const FEEDBACK_DB_PATH = __DIR__ . '/../data/feedback.sqlite';
const FEEDBACK_PHOTO_DIR = __DIR__ . '/../private/feedback';
const FEEDBACK_MAX_PHOTO_BYTES = 8 * 1024 * 1024;
const FEEDBACK_PHOTO_MAX_EDGE = 1024;
const FEEDBACK_RATE_LIMIT_PER_HOUR = 40;

/**
 * Patterns growers can report that the models do NOT cover yet.
 *
 * Every entry here is a known coverage gap. Reporting one is how the team
 * learns which class to add next, so these are kept deliberately specific and
 * are shown in the browser as "not covered yet".
 */
function feedback_gap_patterns(): array
{
    return [
        'Tomato_fruit' => [
            'blossom_end_rot' => 'Blossom-end rot (sunken dark base)',
            'anthracnose' => 'Anthracnose (sunken circular spots)',
            'late_blight_fruit' => 'Late blight on the fruit (greasy brown patches)',
            'grey_mould' => 'Grey mould / botrytis (fuzzy grey growth)',
            'bacterial_spot_fruit' => 'Bacterial spot or speck on the fruit',
            'sunscald' => 'Sunscald (pale, papery patch on the sun side)',
            'cracking' => 'Cracking or splitting',
            'catfacing' => 'Catfacing or misshapen fruit',
            'insect_damage' => 'Insect or bird damage',
            'unripe_normal' => 'Nothing wrong — just unripe',
        ],
        'Tomato_leaf' => [
            'powdery_mildew' => 'Powdery mildew (white dusty coating)',
            'nutrient_deficiency' => 'Nutrient deficiency (yellowing, no lesions)',
            'leafminer' => 'Leafminer tunnels',
            'whitefly' => 'Whitefly damage or sooty residue',
            'thrips' => 'Thrips damage (silvering)',
            'heat_or_water_stress' => 'Heat, drought or water stress',
            'herbicide_damage' => 'Herbicide or spray damage',
        ],
        'Cucumber_leaf' => [
            'angular_leaf_spot' => 'Angular leaf spot (angular water-soaked spots, shot-holes)',
            'mosaic_virus' => 'Mosaic virus (mottled yellow-green, puckering)',
            'nutrient_deficiency' => 'Nutrient deficiency (yellowing between veins)',
            'spider_mite' => 'Spider mite damage (fine stippling, webbing)',
            'whitefly' => 'Whitefly damage or sooty residue',
            'scab' => 'Scab',
            'target_leaf_spot' => 'Target leaf spot',
            'heat_or_water_stress' => 'Heat, drought or water stress',
        ],
        'Cucumber_fruit' => [
            'anthracnose' => 'Anthracnose (sunken spots)',
            'angular_leaf_spot_fruit' => 'Angular leaf spot on the fruit',
            'scab' => 'Scab (corky, gummy pits)',
            'mosaic_virus' => 'Mosaic virus mottling',
            'sunscald' => 'Sunscald',
            'misshapen' => 'Misshapen or poorly pollinated',
            'insect_damage' => 'Insect damage',
        ],
        'Apple_leaf' => [
            'powdery_mildew' => 'Powdery mildew',
            'fire_blight' => 'Fire blight (blackened shoot tips)',
            'frogeye_leaf_spot' => 'Frogeye leaf spot',
            'nutrient_deficiency' => 'Nutrient deficiency',
            'mite_damage' => 'Mite damage (bronzing)',
            'heat_or_water_stress' => 'Heat, drought or water stress',
        ],
        'Apple_fruit' => [
            'scab_fruit' => 'Scab on the fruit',
            'bitter_rot' => 'Bitter rot',
            'black_rot_fruit' => 'Black rot',
            'sooty_blotch' => 'Sooty blotch or flyspeck',
            'sunburn' => 'Sunburn',
            'codling_moth' => 'Codling moth or insect entry hole',
            'hail_damage' => 'Hail or mechanical damage',
            'russeting' => 'Russeting (rough skin, not a disease)',
        ],
        'Lemon_leaf' => [
            'powdery_mildew' => 'Powdery mildew',
            'scale_insects' => 'Scale insects',
            'aphid_damage' => 'Aphid damage (curled new growth)',
            'sunburn' => 'Sunburn',
            'salt_or_water_stress' => 'Salt, drought or waterlogging stress',
            'whitefly' => 'Whitefly',
        ],
        'Lemon_fruit' => [
            'melanose_fruit' => 'Melanose on the fruit (sandpaper specks)',
            'stem_end_rot' => 'Stem-end rot or anthracnose',
            'sooty_mould' => 'Sooty mould',
            'sunburn' => 'Sunburn',
            'wind_scarring' => 'Wind or thorn scarring',
            'splitting' => 'Splitting',
            'thrips_scarring' => 'Thrips scarring (ring around the stem end)',
            'rough_rind_normal' => 'Nothing wrong — naturally rough or coarse rind',
        ],
    ];
}

function feedback_growth_stages(): array
{
    return [
        'seedling' => 'Seedling or transplant',
        'vegetative' => 'Growing, before flowering',
        'flowering' => 'Flowering',
        'fruiting' => 'Fruit setting or filling',
        'mature' => 'Mature or near harvest',
        'unknown' => 'Not sure',
    ];
}

function feedback_severities(): array
{
    return [
        'early' => 'Just starting — a few small spots',
        'moderate' => 'Spreading — clearly visible',
        'severe' => 'Severe — most of the plant affected',
        'unknown' => 'Not sure',
    ];
}

/** Covered condition labels, read from the installed release metadata. */
function feedback_covered_labels(): array
{
    static $cache = null;
    if ($cache !== null) {
        return $cache;
    }
    $cache = [];
    $raw = @file_get_contents(__DIR__ . '/../private/model-metadata.json');
    $metadata = is_string($raw) ? json_decode($raw, true) : null;
    if (!is_array($metadata)) {
        return $cache;
    }
    $blocks = [];
    if (isset($metadata['disease']['classes']) && is_array($metadata['disease']['classes'])) {
        $blocks[] = $metadata['disease']['classes'];
    }
    foreach ($metadata['condition_specialists'] ?? [] as $specialist) {
        if (is_array($specialist) && isset($specialist['classes']) && is_array($specialist['classes'])) {
            $blocks[] = $specialist['classes'];
        }
    }
    foreach ($blocks as $classes) {
        foreach ($classes as $entry) {
            if (!is_array($entry) || !isset($entry['label']) || !is_string($entry['label'])) {
                continue;
            }
            $label = $entry['label'];
            $family = implode('_', array_slice(explode('_', $label), 0, 2));
            $cache[$family][$label] = is_string($entry['diagnosis'] ?? null) ? $entry['diagnosis'] : $label;
        }
    }
    foreach ($cache as $family => $labels) {
        ksort($labels);
        $cache[$family] = $labels;
    }
    return $cache;
}

/** The full option set the browser renders, and the server validates against. */
function feedback_options(): array
{
    $covered = feedback_covered_labels();
    $gaps = feedback_gap_patterns();
    $families = array_unique(array_merge(array_keys($covered), array_keys($gaps)));
    sort($families);
    $result = [];
    foreach ($families as $family) {
        $result[$family] = [
            'covered' => array_map(
                static fn(string $label, string $text): array => ['value' => $label, 'text' => $text],
                array_keys($covered[$family] ?? []),
                array_values($covered[$family] ?? [])
            ),
            'not_covered' => array_map(
                static fn(string $slug, string $text): array => ['value' => 'gap:' . $slug, 'text' => $text],
                array_keys($gaps[$family] ?? []),
                array_values($gaps[$family] ?? [])
            ),
        ];
    }
    return [
        'families' => $result,
        'growth_stages' => feedback_growth_stages(),
        'severities' => feedback_severities(),
        'policy' => 'A field note is recorded for human review. It never changes an automatic screening result.',
    ];
}

function feedback_label_is_allowed(string $family, string $label): bool
{
    // wrong_identity is the most valuable report we can receive: the crop or
    // leaf/fruit call itself was wrong, so no condition list applied at all.
    if ($label === 'unsure' || $label === 'other' || $label === 'wrong_identity') {
        return true;
    }
    $options = feedback_options()['families'][$family] ?? null;
    if (!is_array($options)) {
        return false;
    }
    foreach (array_merge($options['covered'], $options['not_covered']) as $entry) {
        if ($entry['value'] === $label) {
            return true;
        }
    }
    return false;
}

function feedback_db(): PDO
{
    static $pdo = null;
    if ($pdo instanceof PDO) {
        return $pdo;
    }
    $directory = dirname(FEEDBACK_DB_PATH);
    if (!is_dir($directory) && !@mkdir($directory, 0770, true) && !is_dir($directory)) {
        throw new RuntimeException('Feedback storage directory could not be created.');
    }
    $pdo = new PDO('sqlite:' . FEEDBACK_DB_PATH, null, null, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);
    $pdo->exec('PRAGMA journal_mode = WAL');
    $pdo->exec('PRAGMA foreign_keys = ON');
    $pdo->exec(<<<'SQL'
        CREATE TABLE IF NOT EXISTS field_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            crop TEXT NOT NULL,
            organ TEXT NOT NULL,
            family TEXT NOT NULL,
            model_label TEXT,
            model_diagnosis TEXT,
            model_score REAL,
            model_status TEXT,
            verdict TEXT NOT NULL,
            user_label TEXT,
            user_label_covered INTEGER NOT NULL DEFAULT 0,
            growth_stage TEXT,
            severity TEXT,
            note TEXT,
            photo_name TEXT,
            photo_sha256 TEXT,
            review_state TEXT NOT NULL DEFAULT 'new',
            reviewer_label TEXT,
            reviewed_at TEXT
        )
    SQL);
    $pdo->exec('CREATE INDEX IF NOT EXISTS field_notes_fingerprint ON field_notes (fingerprint)');
    $pdo->exec('CREATE INDEX IF NOT EXISTS field_notes_review ON field_notes (review_state, created_at)');
    $pdo->exec(<<<'SQL'
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            client_hash TEXT NOT NULL
        )
    SQL);
    $pdo->exec('CREATE INDEX IF NOT EXISTS submissions_window ON submissions (client_hash, created_at)');
    $pdo->exec(<<<'SQL'
        CREATE TABLE IF NOT EXISTS install (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    SQL);
    return $pdo;
}

function feedback_now_iso(): string
{
    return (new DateTimeImmutable('now', new DateTimeZone('UTC')))->format(DATE_ATOM);
}

/** Per-install salt so a stored client hash cannot be reversed to an address. */
function feedback_client_hash(): string
{
    $pdo = feedback_db();
    $statement = $pdo->prepare('SELECT value FROM install WHERE key = ?');
    $statement->execute(['client_salt']);
    $salt = $statement->fetchColumn();
    if (!is_string($salt) || $salt === '') {
        $salt = bin2hex(random_bytes(16));
        $insert = $pdo->prepare('INSERT OR REPLACE INTO install (key, value) VALUES (?, ?)');
        $insert->execute(['client_salt', $salt]);
    }
    $address = (string)($_SERVER['REMOTE_ADDR'] ?? 'unknown');
    return hash('sha256', $salt . '|' . $address);
}

function feedback_rate_limit_exceeded(): bool
{
    $pdo = feedback_db();
    $since = (new DateTimeImmutable('-1 hour', new DateTimeZone('UTC')))->format(DATE_ATOM);
    $pdo->prepare('DELETE FROM submissions WHERE created_at < ?')
        ->execute([(new DateTimeImmutable('-2 days', new DateTimeZone('UTC')))->format(DATE_ATOM)]);
    $statement = $pdo->prepare('SELECT COUNT(*) FROM submissions WHERE client_hash = ? AND created_at >= ?');
    $statement->execute([feedback_client_hash(), $since]);
    return (int)$statement->fetchColumn() >= FEEDBACK_RATE_LIMIT_PER_HOUR;
}

function feedback_record_submission(): void
{
    feedback_db()
        ->prepare('INSERT INTO submissions (created_at, client_hash) VALUES (?, ?)')
        ->execute([feedback_now_iso(), feedback_client_hash()]);
}

/**
 * Re-encode an uploaded photo through GD.
 *
 * This is deliberately a full decode/encode rather than a copy: it drops EXIF,
 * GPS coordinates and any trailing payload, and it caps the stored resolution.
 */
function feedback_store_photo(array $file): array
{
    if (($file['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_OK) {
        throw new RuntimeException('The photo did not upload completely.');
    }
    if (($file['size'] ?? 0) > FEEDBACK_MAX_PHOTO_BYTES) {
        throw new RuntimeException('The photo is larger than 8 MB.');
    }
    $temporary = (string)($file['tmp_name'] ?? '');
    if ($temporary === '' || !is_uploaded_file($temporary)) {
        throw new RuntimeException('The photo upload was not accepted.');
    }
    $info = @getimagesize($temporary);
    if (!is_array($info) || !in_array($info[2], [IMAGETYPE_JPEG, IMAGETYPE_PNG, IMAGETYPE_WEBP], true)) {
        throw new RuntimeException('Use a JPEG, PNG or WebP photo.');
    }
    $image = match ($info[2]) {
        IMAGETYPE_JPEG => @imagecreatefromjpeg($temporary),
        IMAGETYPE_PNG => @imagecreatefrompng($temporary),
        IMAGETYPE_WEBP => @imagecreatefromwebp($temporary),
        default => false,
    };
    if ($image === false) {
        throw new RuntimeException('The photo could not be read.');
    }
    try {
        $width = imagesx($image);
        $height = imagesy($image);
        $longest = max($width, $height);
        if ($longest > FEEDBACK_PHOTO_MAX_EDGE) {
            $scale = FEEDBACK_PHOTO_MAX_EDGE / $longest;
            $resized = imagescale($image, (int)round($width * $scale), (int)round($height * $scale));
            if ($resized !== false) {
                $image = $resized;
            }
        }
        $month = (new DateTimeImmutable('now', new DateTimeZone('UTC')))->format('Y-m');
        $directory = FEEDBACK_PHOTO_DIR . '/' . $month;
        if (!is_dir($directory) && !@mkdir($directory, 0770, true) && !is_dir($directory)) {
            throw new RuntimeException('Photo storage directory could not be created.');
        }
        feedback_protect_directory(FEEDBACK_PHOTO_DIR);
        $name = bin2hex(random_bytes(16)) . '.jpg';
        $path = $directory . '/' . $name;
        if (!imagejpeg($image, $path, 88)) {
            throw new RuntimeException('The photo could not be stored.');
        }
        return [
            'name' => $month . '/' . $name,
            'sha256' => hash_file('sha256', $path) ?: '',
        ];
    } finally {
        // PHP 8 frees GdImage objects with the variable; imagedestroy() is
        // deprecated there and its notice would corrupt the JSON response.
        unset($image);
    }
}

function feedback_protect_directory(string $directory): void
{
    $htaccess = $directory . '/.htaccess';
    if (is_file($htaccess)) {
        return;
    }
    @file_put_contents($htaccess, "Options -Indexes\n\n<IfModule mod_authz_core.c>\n    Require all denied\n</IfModule>\n<IfModule !mod_authz_core.c>\n    Order allow,deny\n    Deny from all\n</IfModule>\n");
}

function feedback_insert(array $note): int
{
    $pdo = feedback_db();
    $statement = $pdo->prepare(<<<'SQL'
        INSERT INTO field_notes (
            created_at, fingerprint, crop, organ, family,
            model_label, model_diagnosis, model_score, model_status,
            verdict, user_label, user_label_covered,
            growth_stage, severity, note, photo_name, photo_sha256
        ) VALUES (
            :created_at, :fingerprint, :crop, :organ, :family,
            :model_label, :model_diagnosis, :model_score, :model_status,
            :verdict, :user_label, :user_label_covered,
            :growth_stage, :severity, :note, :photo_name, :photo_sha256
        )
    SQL);
    $statement->execute($note);
    return (int)$pdo->lastInsertId();
}

/** Counts shown back to the grower so contributing feels like progress. */
function feedback_public_totals(): array
{
    $pdo = feedback_db();
    return [
        'notes' => (int)$pdo->query('SELECT COUNT(*) FROM field_notes')->fetchColumn(),
        'photos' => (int)$pdo->query("SELECT COUNT(*) FROM field_notes WHERE photo_name IS NOT NULL AND photo_name <> ''")->fetchColumn(),
    ];
}
