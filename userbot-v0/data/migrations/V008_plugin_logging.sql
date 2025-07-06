-- =============================================================================
-- MIGRATION: V008_plugin_logging.sql
-- PLUGIN: Text Logger, Media Logger
-- =============================================================================

CREATE TABLE IF NOT EXISTS text_log_settings (
    account_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT 0,
    PRIMARY KEY (account_id, chat_id)
);

CREATE TABLE IF NOT EXISTS text_log_ignored_users (
    account_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    PRIMARY KEY (account_id, user_id)
);

CREATE TABLE IF NOT EXISTS media_logger_account_settings (
    account_id BIGINT PRIMARY KEY NOT NULL,
    log_channel_id BIGINT,
    log_all_private BOOLEAN NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS media_log_chat_settings (
    account_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT 0,
    PRIMARY KEY (account_id, chat_id)
);

CREATE TABLE IF NOT EXISTS logged_media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id BIGINT NOT NULL,
    source_chat_id BIGINT NOT NULL,
    sender_id BIGINT,
    media_type TEXT,
    file_name TEXT,
    file_size INTEGER,
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_logged_media_timestamp ON logged_media (timestamp);
