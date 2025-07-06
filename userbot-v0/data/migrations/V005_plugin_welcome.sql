-- =============================================================================
-- MIGRATION: V005_plugin_welcome.sql
-- PLUGIN: Welcome
-- =============================================================================

CREATE TABLE IF NOT EXISTS group_settings (
    userbot_account_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    welcome_enabled BOOLEAN DEFAULT 0,
    welcome_message TEXT,
    welcome_timeout INTEGER DEFAULT 0,
    goodbye_enabled BOOLEAN DEFAULT 0,
    goodbye_message TEXT,
    clean_service_messages BOOLEAN DEFAULT 0,
    captcha_enabled BOOLEAN DEFAULT 0,
    captcha_timeout INTEGER DEFAULT 120,
    captcha_penalty TEXT DEFAULT 'mute',
    PRIMARY KEY (userbot_account_id, chat_id)
);

CREATE TABLE IF NOT EXISTS captcha_challenges (
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    correct_answer TEXT NOT NULL,
    captcha_message_id INTEGER NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, user_id)
);
