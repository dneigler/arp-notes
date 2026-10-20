// Markdown for the editor, built on @lezer/markdown directly (spike §2.5, "cm6-lean"): no
// @codemirror/lang-markdown, so the HTML/CSS/JS nested parsers stay out of the bundle. The parser only
// drives styling and tells the chip plugin where code is; it never rewrites the text, so the note
// body stays the string the writer typed.
import { Language, defineLanguageFacet, languageDataProp, syntaxTree } from '@codemirror/language'
import { RangeSetBuilder } from '@codemirror/state'
import { Decoration, ViewPlugin } from '@codemirror/view'
import { GFM, parser } from '@lezer/markdown'

const data = defineLanguageFacet({ commentTokens: { block: { open: '<!--', close: '-->' } } })

export const markdownLanguage = new Language(
  data,
  parser.configure([GFM, { props: [languageDataProp.add((type) => (type.isTop ? data : undefined))] }]),
  [],
  'markdown',
)

// Source-mode styling by node name: markers dimmed, headings and emphasis weighted, code monospaced.
// The live-preview layer (C6e) builds on the same tree.
const MARK = Decoration.mark({ class: 'arpn-md-mark' })
const BY_NAME = {
  ATXHeading1: Decoration.mark({ class: 'arpn-md-h arpn-md-h1' }),
  ATXHeading2: Decoration.mark({ class: 'arpn-md-h arpn-md-h2' }),
  ATXHeading3: Decoration.mark({ class: 'arpn-md-h arpn-md-h3' }),
  ATXHeading4: Decoration.mark({ class: 'arpn-md-h' }),
  ATXHeading5: Decoration.mark({ class: 'arpn-md-h' }),
  ATXHeading6: Decoration.mark({ class: 'arpn-md-h' }),
  SetextHeading1: Decoration.mark({ class: 'arpn-md-h arpn-md-h1' }),
  SetextHeading2: Decoration.mark({ class: 'arpn-md-h arpn-md-h2' }),
  StrongEmphasis: Decoration.mark({ class: 'arpn-md-strong' }),
  Emphasis: Decoration.mark({ class: 'arpn-md-em' }),
  Strikethrough: Decoration.mark({ class: 'arpn-md-strike' }),
  InlineCode: Decoration.mark({ class: 'arpn-md-code' }),
  CodeText: Decoration.mark({ class: 'arpn-md-code' }),
  URL: Decoration.mark({ class: 'arpn-md-url' }),
  Blockquote: Decoration.mark({ class: 'arpn-md-quote' }),
  HeaderMark: MARK,
  EmphasisMark: MARK,
  CodeMark: MARK,
  CodeInfo: MARK,
  LinkMark: MARK,
  QuoteMark: MARK,
  ListMark: MARK,
  TaskMarker: MARK,
  StrikethroughMark: MARK,
}

function build(view) {
  const tree = syntaxTree(view.state)
  const found = []
  for (const { from, to } of view.visibleRanges) {
    tree.iterate({
      from,
      to,
      enter(node) {
        const deco = BY_NAME[node.name]
        if (deco && node.to > node.from) found.push({ from: node.from, to: node.to, deco })
      },
    })
  }
  found.sort((a, b) => a.from - b.from || a.deco.startSide - b.deco.startSide)
  const builder = new RangeSetBuilder()
  for (const { from, to, deco } of found) builder.add(from, to, deco)
  return builder.finish()
}

export const markdownStyle = ViewPlugin.fromClass(
  class {
    constructor(view) {
      this.decorations = build(view)
    }

    update(update) {
      if (update.docChanged || update.viewportChanged || syntaxTree(update.state) !== syntaxTree(update.startState)) {
        this.decorations = build(update.view)
      }
    }
  },
  { decorations: (plugin) => plugin.decorations },
)
