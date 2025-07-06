-- =============================================================================
-- MIGRATION: V001_core_schema.sql
-- DESCRIPTION: Userbot uchun asosiy yadro jadvallari.
-- =============================================================================

-- 1. Foydalanuvchi akkauntlari
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_name TEXT NOT NULL UNIQUE,
    api_id INTEGER NOT NULL,
    api_hash TEXT NOT NULL,
    telegram_id INTEGER UNIQUE,
    status TEXT DEFAULT 'stopped',
    is_active BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 2. Bot ma'murlari va ularning ruxsat darajalari
CREATE TABLE IF NOT EXISTS admins (
    user_id BIGINT PRIMARY KEY NOT NULL,
    permission_level INTEGER NOT NULL DEFAULT 50,
    added_by BIGINT,
    added_date DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 3. Dinamik o'zgaruvchi sozlamalar
CREATE TABLE IF NOT EXISTS dynamic_settings (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT,
    type TEXT NOT NULL DEFAULT 'str',
    description TEXT,
    last_modified DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 4. Bajarilgan vazifalar jurnali (log)
CREATE TABLE IF NOT EXISTS task_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_key TEXT NOT NULL,
    account_id BIGINT,
    run_at DATETIME NOT NULL,
    duration_ms REAL,
    status TEXT NOT NULL CHECK(status IN ('SUCCESS', 'FAILURE', 'TIMEOUT', 'SKIPPED')),
    details TEXT
);

CREATE INDEX IF NOT EXISTS idx_task_logs_task_key ON task_logs (task_key);
CREATE INDEX IF NOT EXISTS idx_task_logs_status ON task_logs (status);
