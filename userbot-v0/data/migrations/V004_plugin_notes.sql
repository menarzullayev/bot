-- =============================================================================
-- MIGRATION: V004_plugin_notes.sql
-- PLUGIN: Notes
-- =============================================================================

CREATE TABLE IF NOT EXISTS notes (
    account_id BIGINT NOT NULL,
    name TEXT NOT NULL,
    content TEXT,
    source_chat_id BIGINT,
    source_message_id INTEGER,
    note_type TEXT NOT NULL DEFAULT 'text',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (account_id, name)
);
