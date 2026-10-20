// Demo + test fixture: the Roy Howat masterclass note (ADR §5) as a 26-suggestion Proposal, shaped
// like the ReviewDesk mockup: 11 pieces (high), 3 composers (medium), 2 techniques (low), 1 pick
// (Debussy), 6 not in the library, 3 action items (K§3: 11 + 3 + 2 + 1 + 6 + 3).

const link = (entity_type, entity_id, entity_label, anchor, confidence, quote, extra = {}) => ({
  entity_type,
  entity_id,
  entity_label,
  anchor,
  quote,
  confidence,
  proposed_by: 'resolver',
  reason: 'Matched in your library.',
  ...extra,
})

export const NOTE_TITLE = '2026-10-18 Roy Howat'

export const howatProposal = {
  note_id: 7,
  cached: false,
  proposed_at: '2026-10-18T14:30:00',
  generated_by: ['resolver'],
  takeaways: [],
  links: [
    link('movement', 1003, 'Études, Op.10 · Nº 3', 'op-10-no-3', 0.95, 'So Op. 10 nº 3 is meant to be an operatic piece'),
    link('movement', 1012, 'Études, Op.10 · Nº 12', 'op-10-no-12', 0.94, 'If you practice Nº 12 the wrong way, it will teach you the wrong thing'),
    link('movement', 1005, 'Études, Op.10 · Nº 5', 'op-10-no-5', 0.93, 'Op. 10 nº 5 - why the differences? Leggieriss.'),
    link('movement', 2001, 'Etudes Op.25 · Nº 1', 'op-25-no-1', 0.92, 'Op.25 No 1 — Decided to use different note size heads'),
    link('movement', 3002, 'In the Mists · II', 'in-the-mists-2', 0.9, "And second movement of Janacek's In The Mists has a notehead diff"),
    link('movement', 1001, 'Études, Op.10 · Nº 1', 'op-10-no-1', 0.89, 'Nº 1 as a study in the span of the hand'),
    link('movement', 1008, 'Études, Op.10 · Nº 8', 'op-10-no-8', 0.88, 'Nº 8 is a little Bach-like perpetual motion'),
    link('movement', 1010, 'Études, Op.10 · Nº 10', 'op-10-no-10', 0.86, 'Nº 10 — a test of how loosely you can hold the wrist'),
    link('movement', 2006, 'Études, Op.25 · Nº 6', 'op-25-no-6', 0.85, 'Op.25 Nº 6, the thirds, never rush them'),
    link('repertoire', 35, 'Études, Op.10', 'op-10', 0.97, 'the Op.10 work as a whole'),
    link('repertoire', 33, 'Études, Op.25', 'op-25', 0.84, 'and Op.25 after it'),
    link('composer', 13, 'Chopin', null, 0.78, 'Chopin always asked for singing', { mention_count: 14 }),
    link('composer', 9, 'Beethoven', null, 0.7, 'He must have been listening to Beethoven, not just early Beethoven'),
    link('composer', 7, 'Bach', null, 0.66, 'Bach — Your library has two Bach entries'),
    link('technique', 302, 'Pedaling', 'pedaling', 0.42, "Pedaling - Chopin didn't always pedal the same way in the same piece"),
    link('technique', 308, 'Metronome practice', 'metronome', 0.38, 'said to practice with a metronome to get rhythmic steadiness'),
    link('repertoire', 18, 'Préludes, Livre 1', 'debussy', 0.55, 'Debussy preludes - one of them has this', {
      mention: 'Debussy',
      candidates: [
        { entity_type: 'repertoire', entity_id: 18, entity_label: 'Préludes, Livre 1', composer_label: 'Debussy', confidence: 0.55, duplicate_group: 'repertoire:preludes-1' },
        { entity_type: 'repertoire', entity_id: 26, entity_label: 'Préludes (Book 1)', composer_label: 'Debussy', confidence: 0.54, duplicate_group: 'repertoire:preludes-1' },
        { entity_type: 'repertoire', entity_id: 19, entity_label: 'Preludes (Book 1)', composer_label: 'Debussy', confidence: 0.53, duplicate_group: 'repertoire:preludes-1' },
        { entity_type: 'repertoire', entity_id: 20, entity_label: 'Preludes, Book 2', composer_label: 'Debussy', confidence: 0.31 },
      ],
    }),
  ],
  unresolved: [
    { mention: 'WTC Book 1', quote: 'try the WTC book 1 fugues', anchor: null, kind_hint: 'work', composer_label: 'Bach', candidates: [] },
    { mention: 'E Major Nocturne', quote: 'the E major nocturne for pedaling', anchor: null, kind_hint: 'work', composer_label: 'Chopin', candidates: [] },
    { mention: 'Op 27 Nº 2', quote: 'Op 27 nº 2 as a model', anchor: null, kind_hint: 'work', composer_label: 'Chopin', candidates: [] },
    { mention: 'Op. 55 nº 2', quote: 'Op. 55 nº 2 for the clock', anchor: null, kind_hint: 'work', composer_label: 'Chopin', candidates: [] },
    { mention: 'Fauré', quote: 'listen to Fauré songs', anchor: null, kind_hint: 'composer', composer_label: 'composer, not in PT', candidates: [] },
    { mention: 'Duparc', quote: 'Dupac songs, same idea', anchor: null, kind_hint: 'composer', composer_label: '“Dupac” in the note · not in PT', candidates: [] },
  ],
  action_items: [
    { text: 'Practice Nº 12 slowly — drop the hand', lane: 'practice', anchor: 'op-10-no-12', entity_type: 'movement', entity_id: 1012, proposed_by: 'resolver' },
    { text: "Always try Chopin's pedalings first", lane: 'practice', anchor: 'op-10', entity_type: 'repertoire', entity_id: 35, proposed_by: 'resolver' },
    { text: 'Reference Op. 55 nº 2 for the clock', lane: 'lesson', anchor: null, entity_type: null, entity_id: null, proposed_by: 'resolver' },
  ],
}

export const HOST_NOTE = 'Roy Howat is kept as text — he isn’t one of your teachers in PT.'
