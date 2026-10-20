// Copy for ProposalReview. The defaults are the approved mockup strings verbatim (K§8); a host
// overrides any subset through the `strings` prop. `{name}` placeholders are filled by fmt().

export const DEFAULT_STRINGS = {
  title: 'Review links and actions',
  // {title} is only shown when the host passes `noteTitle`.
  subtitleWithTitle: 'From “{title}” · {n} suggestions found by searching your library',
  subtitle: '{n} suggestions found by searching your library',
  bannerStrong: 'Nothing is created until you confirm.',
  banner: 'Unticked items are skipped. Rejected ones won’t be suggested again for this note.',
  close: 'Close',

  sectionPieces: 'Pieces',
  sectionComposers: 'Composers',
  sectionTechniques: 'Techniques',
  sectionOther: 'Other links',
  sectionPick: 'Needs your pick',
  sectionUnresolved: 'Not in your library',
  sectionActions: 'Action items',
  bandHigh: 'high',
  bandMedium: 'medium',
  bandLow: 'low',
  badgeHigh: 'High',
  badgeMedium: 'Medium',
  badgeLow: 'Low',

  linkTo: 'Link to {target}',
  linkToRejected: 'Link to {target}, rejected',
  reject: 'Reject link to {target}',
  rejected: 'Rejected',
  undo: 'Undo',
  undoLabel: 'Undo reject of {target}',
  mentionCount: 'Mentioned {n} times',
  mentionOnce: 'Mentioned once',
  showMore: 'Show {n} more',
  showFewer: 'Show fewer',
  untickAll: 'Untick all',
  tickAll: 'Tick all',
  untickAllLabel: 'Untick all in {section}',
  tickAllLabel: 'Tick all in {section}',

  pickMatches: '{n} matches in your library',
  pickNone: 'None of these — skip',
  pickGroup: 'Which match for “{quote}”',
  // {Count} = "Three", {count} = "three" (digits above nine).
  duplicateHint: '{Count} look like the same book. You can merge them later in Repertoire.',

  unresolvedHelp: 'Nothing is added to your repertoire.',
  unresolvedHelpSomeday:
    'Switch on to keep one as a “someday” idea. Nothing is added to your repertoire otherwise.',
  someday: 'Someday',
  somedayLabel: 'Save {name} as someday',

  addAction: 'Add action: {text}',
  lane: 'Lane',
  lanePractice: 'Practice',
  laneLesson: 'Lesson',

  // Footer: "Creates N links · M backlog items." then the pick summary.
  creates: 'Creates {links} · {backlog}.',
  linksOne: '{n} link',
  linksMany: '{n} links',
  backlogOne: '{n} backlog item',
  backlogMany: '{n} backlog items',
  pickPicked: '{name} picked.',
  pickSkipped: '{name} skipped.',
  pickLater: '{name}: pick left for later.',
  somedaySummaryOne: '{n} someday idea.',
  somedaySummaryMany: '{n} someday ideas.',

  rejectAll: 'Reject all',
  decideLater: 'Decide later',
  confirm: 'Confirm {n}',
  confirmEmpty: 'Confirm',
}

export function fmt(template, values = {}) {
  return String(template).replace(/\{(\w+)\}/g, (whole, key) =>
    Object.hasOwn(values, key) ? String(values[key]) : whole,
  )
}

export function makeStrings(overrides) {
  return { ...DEFAULT_STRINGS, ...(overrides ?? {}) }
}

const WORDS = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten']

// "Three" for 3, "12" past ten. Used by the duplicate_group hint.
export function countWord(n) {
  const word = n >= 0 && n < WORDS.length ? WORDS[n] : String(n)
  return { count: word, Count: word.charAt(0).toUpperCase() + word.slice(1) }
}
