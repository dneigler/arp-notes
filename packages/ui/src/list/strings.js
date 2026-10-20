// Copy for the list and detail chrome. Strings come from the approved mockups verbatim (K§8) and the
// host can override any of them through a `strings` prop. Functions take the dynamic parts.

import { plural } from './format.js'

export const STRINGS = {
  // NotesList
  title: 'Notes',
  subtitle: 'Masterclasses, lectures and your own writing — synced from Obsidian or written here.',
  newNote: 'New note',
  filterLabel: 'Filter notes',
  search: 'Search',
  searchPlaceholder: 'Title, person, text…',
  searchPhone: 'Search notes',
  origin: 'Origin',
  originAll: 'All',
  originSource: 'Imported',
  originApp: 'Written here',
  kind: 'Kind',
  allKinds: 'All kinds',
  source: 'Source',
  allSources: 'All sources',
  sourceObsidian: 'Obsidian',
  sourceLlm: 'Claude (MCP)',
  showDeleted: 'Show deleted',
  lastSync: (system, workspace, ago) => `Last sync · ${system}${workspace ? ` “${workspace}”` : ''}${ago ? ` · ${ago}` : ''}`,
  monthHeader: (month, count) => `${month} · ${plural(count, 'note')}`,
  loading: 'Loading notes…',
  loadMore: 'Load more',
  errorPrefix: 'Could not load notes',
  noMatches: 'No notes match these filters',
  noMatchesHint: 'Try a different search, or clear the filters.',
  clearFilters: 'Clear filters',
  emptyTitle: 'No notes yet',
  emptyBody: 'Keep masterclass, lecture and reading notes next to the pieces they mention.',
  emptyWrite: 'Write a note',
  emptySyncTitle: 'Already write in Obsidian?',
  emptySyncBody: 'Ask Claude to “sync my Roy Howat note”. Your notes arrive word-for-word with their images, and stay owned by Obsidian.',
  emptySyncLink: 'How syncing works',
  emptyTile: 'Empty',
  rowSourceDeleted: 'Source deleted',
  llmProvenance: 'written by Claude at your request',

  // Origin badges
  importedFrom: (system) => `Imported · ${system}`,
  importedFromShort: (system) => system,
  writtenHere: 'Written here',
  claudeMcp: 'Claude · via MCP',
  claudeMcpShort: 'Claude · MCP',
  readOnly: 'read-only',
  toReview: (n) => `${n} to review`,
  suggestionsToReview: (n) => `${plural(n, 'suggestion')} to review`,

  // Row meta / time
  synced: (ago) => `Synced ${ago}`,
  edited: (ago) => `Edited ${ago}`,
  created: (ago) => `Created ${ago}`,
  vaultRoot: 'vault root',
  minutes: (n) => `${n} min`,
  moreLinks: (n) => `+${plural(n, 'link')}`,
  moreCount: (n) => `+${n} more`,
  actions: (n) => plural(n, 'action'),
  images: (n) => plural(n, 'image'),
  moreImages: (n) => `+${plural(n, 'image')}`,
  thumbnailAlt: (filename) => `Thumbnail: ${filename}`,

  // NoteCard
  openNote: 'Open note',
  openShort: 'Open',
  dayFooter: (when, actions) =>
    `${when}${actions ? ` · ${plural(actions, 'action item')} added to backlog` : ''}`,
  withPerson: (person) => `with ${person}`,
  noteKindSuffix: (kind) => `${kind} note`,

  // NoteDetailHeader
  importedReadOnly: (system) => `Imported · ${system} · read-only`,
  readOnlyShort: (system) => `${system} · read-only`,
  openIn: (system) => `Open in ${system}`,
  editThere: 'Edit it there — the next sync updates this copy.',
  reviewPicks: (n) => `Review ${plural(n, 'pick')}`,
  needsPick: (n) => (n === 1 ? '1 link needs your pick' : `${n} links need your pick`),
  reviewShort: 'Review',
  export: 'Export',
  sourceDeleted: 'Source deleted',
  deletedIn: (system, when) => `Deleted in ${system} on ${when}`,
  deletedBody: (where, label, person) =>
    `The file is gone from ${where}, so this note is hidden from the feed and Day page. ${
      label
        ? `The copy and its links stay here, so ${label} still shows${person ? ` what ${person} said` : ' what it said'}.`
        : 'The copy and its links stay here.'
    }`,
  yourVault: 'your vault',
  deletedRestore: 'If the file comes back, the next sync restores it.',
  keepCopy: 'Keep copy',
  deleteFromHost: (host) => `Delete from ${host}…`,
  lastSyncedKept: (when, n) => `Last synced ${when} · ${plural(n, 'link')} kept, marked “source deleted”`,
  defaultHostName: 'this app',
  confirmDeleteTitle: (host) => `Delete this note from ${host}?`,
  confirmDeleteBody: (host, n) =>
    `This removes the copy${n ? ` and its ${plural(n, 'link')}` : ''} from ${host}. The file is already gone from the source. This can’t be undone.`,
  confirmDelete: (host) => `Delete from ${host}`,
  cancel: 'Cancel',
  deleteFailed: 'Could not delete the note. Try again.',
  keepFailed: 'Could not keep the copy. Try again.',
  working: 'Working…',

  // NoteRail
  railLabel: 'Links and attachments',
  linkedPieces: (n) => `Linked pieces · ${n}`,
  composers: (n) => `Composers · ${n}`,
  otherLinks: (n) => `Other links · ${n}`,
  actionItems: (n) => `Action items · ${n}`,
  imagesHeading: (n) => `Images · ${n}`,
  properties: 'Properties',
  imagesNote: (size) => `${size} · links expire after 1 h and refresh automatically`,
  showMoreImages: (n) => `Show ${plural(n, 'more image')}`,
  laneLabels: { practice: 'Practice', lesson: 'Lesson' },
  partPrefix: 'Nº',
  done: 'Done',
  noValue: '—',
  imageAlt: (filename) => `Image ${filename}`,
  openImage: (filename) => `Open ${filename}`,
}

export function withStrings(overrides) {
  return overrides ? { ...STRINGS, ...overrides } : STRINGS
}
