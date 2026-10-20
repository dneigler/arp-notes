-- arp-notes core migration 001: notes, content-addressed blobs, note attachments, note links,
-- upload tickets and hygiene dismissals (ADR notes-sync-adr.md A.1 + contract K§1).
-- Additive and idempotent (every statement guards itself; a host runner may skip the whole file
-- on error). user_id is plain TEXT NOT NULL with no FK to any users table (house rule): the core
-- never assumes a users table. Host-specific tables (for example a Postgres blob store) belong in
-- the host's own migration, not here.

CREATE TABLE IF NOT EXISTS notes (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'note',          -- masterclass|workshop|lecture|reading|video|reflection|meeting|note (open vocabulary)
    title TEXT NOT NULL,
    body_md TEXT NOT NULL DEFAULT '',           -- verbatim for origin='source'
    frontmatter JSONB DEFAULT '{}',             -- parsed YAML as given; keys preserved as-is
    person TEXT,                                -- presenter / author (free text, D6)
    note_date TEXT,                             -- YYYY-MM-DD (house TEXT-date convention)
    place TEXT,
    origin TEXT NOT NULL DEFAULT 'app',         -- 'app' (editable) | 'source' (read-only import)
    source_system TEXT,                         -- 'obsidian'|'notion'|'apple_notes'|'llm'|NULL
    source_workspace TEXT,                      -- vault name | Notion workspace id | Mac store id
    source_doc_id TEXT,                         -- arp_id | Notion page id | ZIDENTIFIER | client uuid
    source_path TEXT,                           -- current path at last sync (display + deep link only)
    source_url TEXT,                            -- obsidian://open?vault=..&file=.. | https://notion.so/.. | NULL
    source_modified_at TEXT,                    -- ISO-8601 as reported by the source
    content_hash TEXT,                          -- sha256 hex of the verbatim source bytes
    last_synced_at TIMESTAMP,
    deleted_at TIMESTAMP NULL,                  -- tombstone (source deletion); body and links retained
    created_via TEXT DEFAULT 'web',             -- 'web'|'mobile'|'mcp'|'cli'|'chat'|'ai'
    version INTEGER DEFAULT 1,                  -- autosave optimistic concurrency (app notes only)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    proposal JSONB,                             -- cached last Proposal (K§3); NULL = never proposed
    proposed_at TIMESTAMP,                      -- when `proposal` was computed
    review_pending INTEGER NOT NULL DEFAULT 0   -- K§3 count; drives the "N to review" badges
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_notes_source_identity
    ON notes(user_id, source_system, source_workspace, source_doc_id) WHERE source_doc_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_notes_user_date ON notes(user_id, note_date);
CREATE INDEX IF NOT EXISTS idx_notes_user_updated ON notes(user_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_notes_user_live ON notes(user_id) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS blobs (                -- content-addressed, per user
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    sha256 TEXT NOT NULL,                       -- 64 lowercase hex
    mime TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    storage_path TEXT NOT NULL,                 -- backend-specific locator returned by Storage.put (informational; the core never parses it)
    width INTEGER,
    height INTEGER,                             -- images only, best effort
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, sha256)
);

CREATE TABLE IF NOT EXISTS note_attachments (
    id SERIAL PRIMARY KEY,
    note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    blob_id INTEGER NOT NULL REFERENCES blobs(id) ON DELETE RESTRICT,
    filename TEXT NOT NULL,                     -- as named in the source
    ref_in_markdown TEXT NOT NULL,              -- exact embed/link text in body_md, e.g. '![[2026-10-18 Masterclass-1792329672740.webp]]'
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(note_id, ref_in_markdown)
);
CREATE INDEX IF NOT EXISTS idx_note_attachments_blob ON note_attachments(blob_id);

CREATE TABLE IF NOT EXISTS note_links (          -- app-owned enrichment, anchored
    id SERIAL PRIMARY KEY,
    note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,                  -- host vocabulary, e.g. 'repertoire'|'movement'|'section'|'composer'|'technique'|'instructor'
    entity_id INTEGER NOT NULL,
    anchor TEXT,                                -- heading slug or '^block-id'; NULL = whole note
    quote TEXT,                                 -- excerpt the link was made from
    comment TEXT,                               -- takeaway (app-owned)
    action_item TEXT,
    action_completed INTEGER DEFAULT 0,
    action_completed_at TIMESTAMP,
    backlog_id INTEGER,                         -- host backlog row created on confirm (no FK; host rows are user-deletable)
    status TEXT NOT NULL DEFAULT 'confirmed',   -- 'confirmed'|'rejected'|'orphaned'
    proposed_by TEXT,                           -- 'resolver'|'llm'|'user'
    confidence REAL,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_note_links_entity ON note_links(entity_type, entity_id, status);
CREATE INDEX IF NOT EXISTS idx_note_links_note ON note_links(note_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_note_links_dedupe
    ON note_links(note_id, entity_type, entity_id, COALESCE(anchor, ''));

CREATE TABLE IF NOT EXISTS upload_tickets (       -- one-time PUT URLs (A.4)
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,            -- sha256 of the url token; token itself never stored
    sha256 TEXT NOT NULL,
    mime TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    filename TEXT,
    expires_at TIMESTAMP NOT NULL,
    consumed_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS hygiene_dismissals (   -- K§6
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    issue_key TEXT NOT NULL,                    -- HygieneIssue.key (stable, K§6.1)
    reason TEXT,
    dismissed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, issue_key)
);
