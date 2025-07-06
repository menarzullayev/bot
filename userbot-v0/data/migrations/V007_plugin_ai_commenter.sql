-- -- =================================================================
-- --  USERBOT: V008 - AI IZOHLOVCHI PLAGINI
-- -- =================================================================

-- -- AI Izohlovchi (AI Commenter) shaxsiyatlari
-- CREATE TABLE IF NOT EXISTS ai_personalities (
--     id INTEGER PRIMARY KEY AUTOINCREMENT,
--     userbot_account_id INTEGER NOT NULL,
--     name TEXT NOT NULL,
--     prompt TEXT NOT NULL,
--     cooldown_seconds INTEGER NOT NULL DEFAULT 600,
--     FOREIGN KEY (userbot_account_id) REFERENCES accounts (id) ON DELETE CASCADE,
--     UNIQUE(userbot_account_id, name)
-- );

-- -- AI Izohlovchi uchun kanallar
-- CREATE TABLE IF NOT EXISTS ai_commenter_channels (
--     id INTEGER PRIMARY KEY AUTOINCREMENT,
--     userbot_account_id INTEGER NOT NULL,
--     channel_id INTEGER NOT NULL,
--     personality_name TEXT NOT NULL,
--     is_active BOOLEAN DEFAULT 1,
--     delay_min_seconds INTEGER DEFAULT 10,
--     delay_max_seconds INTEGER DEFAULT 30,
--     include_keywords TEXT,
--     exclude_keywords TEXT,
--     FOREIGN KEY (userbot_account_id) REFERENCES accounts (id) ON DELETE CASCADE,
--     UNIQUE(userbot_account_id, channel_id)
-- );

-- -- AI API chaqiruvlari statistikasi
-- CREATE TABLE IF NOT EXISTS ai_usage_stats (
--     id INTEGER PRIMARY KEY AUTOINCREMENT,
--     userbot_account_id INTEGER NOT NULL,
--     stat_date DATE NOT NULL,
--     call_count INTEGER NOT NULL DEFAULT 0,
--     FOREIGN KEY (userbot_account_id) REFERENCES accounts (id) ON DELETE CASCADE,
--     UNIQUE(userbot_account_id, stat_date)
-- );


-- =============================================================================
-- MIGRATION: V007_plugin_ai_commenter.sql
-- PLUGIN: AI Commenter
-- =============================================================================

CREATE TABLE IF NOT EXISTS ai_personalities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    userbot_account_id BIGINT NOT NULL,
    name TEXT NOT NULL,
    prompt TEXT NOT NULL,
    cooldown_seconds INTEGER NOT NULL DEFAULT 600,
    UNIQUE(userbot_account_id, name)
);

CREATE TABLE IF NOT EXISTS ai_commenter_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    userbot_account_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    personality_name TEXT NOT NULL,
    is_active BOOLEAN DEFAULT 1,
    delay_min_seconds INTEGER DEFAULT 10,
    delay_max_seconds INTEGER DEFAULT 30,
    include_keywords TEXT,
    exclude_keywords TEXT,
    UNIQUE(userbot_account_id, channel_id)
);
