-- -- =============================================================================
-- -- MIGRATION: V006_plugin_ai_core.sql
-- -- PLUGIN: AI Toolkit
-- -- =============================================================================

-- CREATE TABLE IF NOT EXISTS ai_knowledge_base (
--     id INTEGER PRIMARY KEY AUTOINCREMENT,
--     account_id BIGINT NOT NULL,
--     trigger_phrase TEXT NOT NULL,
--     response_text TEXT NOT NULL,
--     created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
--     UNIQUE (account_id, trigger_phrase)
-- );

-- -- Barcha AI plaginlari uchun umumiy statistika jadvali
-- CREATE TABLE IF NOT EXISTS ai_usage_stats (
--     userbot_account_id BIGINT NOT NULL,
--     stat_date DATE NOT NULL,
--     call_count INTEGER NOT NULL DEFAULT 0,
--     PRIMARY KEY (userbot_account_id, stat_date)
-- );


-- =============================================================================
-- MIGRATION: V006_plugin_ai_core.sql
-- PLUGIN: AI Toolkit
-- =============================================================================

CREATE TABLE IF NOT EXISTS ai_knowledge_base (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id BIGINT NOT NULL,
    trigger_phrase TEXT NOT NULL,
    response_text TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (account_id, trigger_phrase)
);

-- Barcha AI plaginlari uchun umumiy statistika jadvali
CREATE TABLE IF NOT EXISTS ai_usage_stats (
    userbot_account_id BIGINT NOT NULL,
    stat_date DATE NOT NULL,
    call_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (userbot_account_id, stat_date)
);
