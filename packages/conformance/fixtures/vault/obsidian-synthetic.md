---
arp_id: 3f1c2a9e-7b4d-4c1e-9f0a-1b2c3d4e5f60
creation date: 2026-10-18 09:03
tags: [MeetingNote, piano/chopin]
aliases:
  - Howat masterclass
meeting-date: 2026-10-18
cssclasses: wide
---

# Synthetic Obsidian corpus

**Attendees**:: [[Roy Howat]]
**Links**:: [[Chopin Études Op. 10]], [[Op.10 nº 3|the E major étude]]
Inline field [key:: value] and a tag #practice/slow and #MeetingNote.

## Wikilinks and embeds

A plain [[Note Title]] link, an aliased [[Note Title|display text]], a heading link [[Note Title#Section]], a block link [[Note Title#^abc123]], and a nested path [[folder/sub/Note]].
Embeds: ![[image.png]] and sized ![[image.png|438x282]] and width-only ![[photo.webp|300]] and a note embed ![[Other Note#Heading]] and a PDF page ![[score.pdf#page=3]].
An external [markdown link](https://example.com/a?b=1&c=2 "title") and an autolink <https://example.com> and a bare URL https://example.org/x.
A house mention chip: [@Chopin Études Op.10](mention://repertoire/chopin-etudes-op-10) and a host chip pt://repertoire/42 inline.

## Callouts

> [!note] A note callout
> Body line one.
> Body line two with **bold** and *italic* and ==highlight==.

> [!warning]- Collapsed warning
> Hidden by default.

> [!quote]+ Expanded quote
> > nested blockquote
> > with two lines

> Plain blockquote without a type.

## Lists and tasks

- [ ] open task
- [x] done task
- [-] cancelled task (custom status)
- [>] forwarded task
	- tab-indented child
		- grandchild with a [[link]]
	- [ ] nested task
1. ordered
2. list
   1. with a space-indented child
10. ten

* star bullet
+ plus bullet

Term with a footnote.[^1] And an inline footnote.^[Inline footnote text.]

[^1]: The footnote body, with a [[link]].

## Table

| Piece | Measure | Note |
|:------|--------:|:----:|
| Op. 10 nº 1 | 27 | compare WTC I |
| Op. 25 nº 1 | 1–4 | notehead sizes \| escaped pipe |

## Code and math

```dataview
TABLE meeting-date AS "Meeting Date"
FROM [[Roy Howat]] AND -"Templates" AND #MeetingNote
SORT meeting-date DESC
```

```python
def f(x):
    return x  # four-space indent
```

~~~
tilde fence
~~~

Inline `code` and inline math $E = mc^2$ and display math:

$$
\int_0^1 x^2 \, dx = \frac{1}{3}
$$

Dataview inline: `=dateformat(this.file.mtime, "yyyy-MM-dd HH:mm:ss")`

## Formatting edge cases

Text with ==highlight==, ~~strike~~, **bold**, __also bold__, *italic*, _also italic_, ***both***.
A comment %%hidden from reader%% in the middle.
A hard break at the end of this line  
next line after two trailing spaces.
Line ending with backslash\
next line.
Escapes: \*not italic\*, \[not a link\], 1\. not a list, \#not-a-tag.
Setext heading
--------------

A paragraph with a block id. ^abc123

<div class="html-block">raw html block</div>
Inline <sup>html</sup> and <kbd>Cmd</kbd>+<kbd>B</kbd>.

***

---

- - -

Emoji :smile: and unicode — “quotes” nº ½ é.

Final line without trailing newline
