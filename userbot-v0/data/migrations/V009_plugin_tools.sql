-- =============================================================================
-- MIGRATION: V009_plugin_tools.sql
-- PLUGIN: Telegraph, Wiki, Translate, Digest
-- =============================================================================

CREATE TABLE IF NOT EXISTS telegraph_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    userbot_account_id BIGINT NOT NULL,
    short_name TEXT NOT NULL,
    author_name TEXT,
    access_token TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT 0,
    UNIQUE(userbot_account_id, short_name)
);

CREATE TABLE IF NOT EXISTS wiki_settings (
    account_id BIGINT PRIMARY KEY NOT NULL,
    default_lang TEXT NOT NULL DEFAULT 'en'
);

CREATE TABLE IF NOT EXISTS translation_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id BIGINT NOT NULL,
    provider_name TEXT NOT NULL,
    source_lang TEXT,
    target_lang TEXT NOT NULL,
    char_count INTEGER NOT NULL,
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS digest_settings (
    account_id BIGINT PRIMARY KEY NOT NULL,
    delivery_time TEXT NOT NULL DEFAULT '08:00',
    is_enabled BOOLEAN NOT NULL DEFAULT 0,
    chat_id BIGINT,
    confirmation_message_id INTEGER
);
