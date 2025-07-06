-- =============================================================================
-- MIGRATION: V003_plugin_profile.sql
-- PLUGIN: Profile, Animator
-- =============================================================================

CREATE TABLE IF NOT EXISTS profile_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id BIGINT NOT NULL,
    snapshot_name TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    bio TEXT,
    photo_blob BLOB,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (account_id, snapshot_name)
);

CREATE TABLE IF NOT EXISTS animator_elements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id BIGINT NOT NULL,
    element_type TEXT NOT NULL CHECK(element_type IN ('name', 'bio', 'pfp')),
    content TEXT NOT NULL
);
