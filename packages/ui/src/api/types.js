// JSDoc typedefs mirroring the A.2 wire shapes plus the K§2/K§6 deltas, one to one. The JSON Schemas
// in ./schemas (vendored from packages/core) are the authority and are what ajv checks; these are for
// editors. Clients must tolerate unknown fields.

/**
 * @typedef {Object} Attachment
 * @property {number} id
 * @property {number} blob_id
 * @property {string} filename
 * @property {string} ref_in_markdown  The exact embed text in body_md, e.g. '![[a.png|300]]'.
 * @property {string} mime
 * @property {number} size_bytes
 * @property {string} sha256
 * @property {number|null} [width]
 * @property {number|null} [height]
 * @property {string} content_url  Signed; expires within 1 hour.
 */

/**
 * @typedef {Object} NoteLink
 * @property {number} id
 * @property {string} entity_type
 * @property {number} entity_id
 * @property {string} entity_label
 * @property {string|null} [entity_slug]
 * @property {string|null} [anchor]  Heading slug or '^block-id'; null = whole note.
 * @property {string|null} [quote]
 * @property {string|null} [comment]
 * @property {string|null} [action_item]
 * @property {number} action_completed
 * @property {number|null} [backlog_id]
 * @property {'practice'|'lesson'|null} [lane]  K§13.3: lane the action item was confirmed under; null without an action item.
 * @property {'confirmed'|'rejected'|'orphaned'} status
 * @property {string|null} [proposed_by]
 * @property {number|null} [confidence]
 * @property {number} sort_order
 * @property {{entity_type: string, entity_id: number}|null} [via]
 */

/**
 * @typedef {Object} NoteSummary
 * @property {number} id
 * @property {string} kind
 * @property {string} title
 * @property {string|null} [person]
 * @property {string|null} [note_date]
 * @property {'source'|'app'} origin
 * @property {string|null} [source_system]
 * @property {string|null} [source_workspace]
 * @property {string|null} [source_path]
 * @property {string|null} [last_synced_at]
 * @property {string|null} [deleted_at]
 * @property {number} link_count
 * @property {number} attachment_count
 * @property {string} updated_at
 * @property {string|null} [thumbnail_url]
 * @property {Array<{entity_type: string, entity_id: number, entity_label: string}>} [top_links]
 * @property {number} [action_count]
 * @property {number} [review_pending]
 * @property {number|null} [duration_min]
 */

/**
 * @typedef {Object} Note
 * @property {number} id
 * @property {string} kind
 * @property {string} title
 * @property {string} body_md
 * @property {Object<string, unknown>} frontmatter
 * @property {'source'|'app'} origin
 * @property {string|null} [source_system]
 * @property {string|null} [source_workspace]
 * @property {string|null} [source_path]
 * @property {string|null} [source_url]
 * @property {string|null} [deleted_at]
 * @property {number} version
 * @property {Attachment[]} attachments
 * @property {NoteLink[]} links
 * @property {number} [review_pending]
 */

/**
 * @typedef {Object} NoteList
 * @property {NoteSummary[]} items
 * @property {string|null} next_cursor
 * @property {Array<{source_system: string, source_workspace: string, last_synced_at: string|null, note_count: number}>} sync_sources
 */

/**
 * @typedef {Object} ConfirmBody
 * @property {Array<Object>} links
 * @property {Array<Object>} rejected
 * @property {Array<Object>} action_items
 * @property {Array<Object>} [takeaways]
 * @property {Array<Object>} [deferred]
 * @property {Array<Object>} [someday]
 */

/**
 * @typedef {Object} UploadProgress
 * @property {number} loaded  Bytes sent so far.
 * @property {number} total   Bytes to send (0 when the browser cannot tell).
 * @property {number} fraction  0..1
 */

export {}
