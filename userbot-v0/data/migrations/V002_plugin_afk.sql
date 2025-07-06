-- =============================================================================
-- MIGRATION: V002_plugin_afk.sql
-- PLUGIN: AFK
-- DESCRIPTION: Adds tables for AFK settings, mentions, and ignored users.
-- =============================================================================

CREATE TABLE IF NOT EXISTS afk_settings (
    account_id BIGINT PRIMARY KEY NOT NULL,
    is_afk BOOLEAN NOT NULL DEFAULT 0,
    reason TEXT,
    afk_since DATETIME,
    groups_enabled BOOLEAN NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS afk_ignored_users (
    owner_account_id BIGINT NOT NULL,
    ignored_user_id BIGINT NOT NULL,
    PRIMARY KEY (owner_account_id, ignored_user_id)
);

-- YECHIM: `afk_mentions` jadvalini yaratish uchun SQL buyrug'i qo'shildi
CREATE TABLE IF NOT EXISTS afk_mentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    afk_account_id BIGINT NOT NULL,
    chatter_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    message_text TEXT,
    mention_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_afk_mentions_time ON afk_mentions (mention_time);