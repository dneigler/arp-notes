-- K§13.3: the lane an action item was confirmed under. NULL = the link has no action item.
-- Separate from 001 so a database that already applied 001 still gets the column.
ALTER TABLE note_links ADD COLUMN IF NOT EXISTS lane TEXT CHECK (lane IN ('practice', 'lesson'));
