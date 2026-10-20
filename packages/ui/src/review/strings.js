// Copy for ProposalReview, verbatim from the ReviewDesk / ReviewPhone / ReviewTablet artboards (K§8).
// Hosts override any entry through the `strings` prop; entries that carry numbers or names are
// functions.

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`
const WORDS = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten']

export const REVIEW_STRINGS = {
  title: 'Review links and actions',
  // Dialog: the long form. Sheet and form sheet: the short one.
  subtitle: (count, title) =>
    title
      ? `From “${title}” · ${plural(count, 'suggestion', 'suggestions')} found by searching your library`
      : `${plural(count, 'suggestion', 'suggestions')} found by searching your library`,
  subtitleShort: (count, title) =>
    title ? `${plural(count, 'suggestion', 'suggestions')} from “${title}”` : plural(count, 'suggestion', 'suggestions'),
  close: 'Close',
  bannerLead: 'Nothing is created until you confirm.',
  bannerDetail: 'Unticked items are skipped. Rejected ones won’t be suggested again for this note.',
  bannerDetailCompact: 'Unticked items are skipped; rejected ones won’t come back.',

  pieces: 'Pieces',
  composers: 'Composers',
  techniques: 'Techniques',
  pick: 'Needs your pick',
  unresolved: 'Not in your library',
  actions: 'Action items',
  bands: { high: 'High', medium: 'Medium', low: 'Low' },
  // Heading suffix: "Pieces · high".
  sectionBand: (bands) => bands.join(', '),
  tickedOf: (ticked, total) => `${ticked} of ${total} ticked`,
  untickAll: 'Untick all',
  tickAll: 'Tick all',
  showMore: (n) => `Show ${n} more`,
  showFewer: 'Show fewer',

  linkTo: (label) => `Link to ${label}`,
  linkToRejected: (label) => `Link to ${label}, rejected`,
  reject: (label) => `Reject link to ${label}`,
  rejected: 'Rejected',
  undo: 'Undo',
  undoReject: (label) => `Undo reject link to ${label}`,
  mentioned: (n) => `Mentioned ${n} times`,

  pickGroup: (label) => `Which ${label}`,
  matches: (n) => `${plural(n, 'match', 'matches')} in your library`,
  skipOption: 'None of these — skip',
  // Shared duplicate_group hint (K§2). Repertoire is the verbatim artboard line.
  duplicateHint: (count, entityType) => {
    const n = WORDS[count] ?? String(count)
    if (entityType === 'repertoire') return `${n} look like the same book. You can merge them later in Repertoire.`
    if (entityType === 'composer') return `${n} look like the same composer. You can merge them later.`
    return `${n} look like the same one. You can merge them later.`
  },

  somedayBlurb: 'Switch on to keep one as a “someday” idea. Nothing is added to your repertoire otherwise.',
  someday: 'Someday',
  somedayFor: (name) => `Save ${name} as someday`,
  kinds: { work: 'work', composer: 'composer', movement: 'movement', technique: 'technique', person: 'person' },

  lane: 'Lane',
  practice: 'Practice',
  lesson: 'Lesson',
  addAction: (text) => `Add action: ${text}`,
  noPiece: 'No piece linked',

  creates: (links, backlog) =>
    `Creates ${plural(links, 'link', 'links')} · ${plural(backlog, 'backlog item', 'backlog items')}.`,
  somedayCount: (n) => `${plural(n, 'someday idea', 'someday ideas')}.`,
  pickSummary: ({ picked, skipped, later }) =>
    [
      picked && `${picked} picked`,
      skipped && `${skipped} skipped`,
      later && `${later} left for later`,
    ]
      .filter(Boolean)
      .join(', ') + (picked || skipped || later ? '.' : ''),

  rejectAll: 'Reject all',
  decideLater: 'Decide later',
  confirm: (n) => `Confirm ${n}`,
}
