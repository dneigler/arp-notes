"""Resolver pipeline: tokenise, candidates, duplicate collapse, judge, escalate (K§4, K§12.2).

Owner: C5a (ga-mxal.12).

`tokenise` is a lexicon-free scan: it recognises catalogue patterns (Op. / BWV / K. / Hob. / D. /
S.), ordinal movement phrases, existing [[wikilinks]] and capitalised name runs, and carries context
down a list branch. `propose` sends the spans to every `LinkSchemes.reconcile`, collapses duplicate
rows, asks the judge (when one is configured) and degrades to search-only when it is absent or
raises. It never writes: the cache is `review` (R1), Layer 2 is `extract` (C5b).

Surnames and generic name runs are recall-only: the core has no lexicon, so a name no scheme
recognises is dropped rather than reported as unresolved. Unresolved mentions come from structural
patterns only (catalogue numbers, ordinal movements, named musical forms, key-and-form titles,
WTC, and explicitly coordinated proper names).
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from arp_notes import extract, repo
from arp_notes.anchors import slug
from arp_notes.config import HostConfig
from arp_notes.judges import Candidate, Judgement, Mention
from arp_notes.models import (
    Proposal,
    ProposalCandidate,
    ProposedLink,
    UnresolvedMention,
)
from arp_notes.ports import LinkSchemes, SchemeDedupe, Span, SpanContext

__all__ = ["Span", "Thresholds", "propose", "tokenise"]

log = logging.getLogger(__name__)

PROPOSED_BY = "resolver"

KindHint = Literal["work", "composer", "movement", "technique", "person"]


@dataclass(frozen=True)
class Thresholds:
    """Knobs for `propose` (K§4). The defaults are the contract's numbers."""

    judge: float = 0.5  # judge confidence below this is emitted ambiguous (K§4 step 4)
    high: float = 0.8  # confidence bands, used for the `reason` text (the UI pre-ticks >= medium)
    medium: float = 0.5
    near: int = 3  # other near clusters listed beside an ambiguous cluster
    max_candidates: int = 8  # cap on candidates[] of one ambiguous item
    floor: float = 0.0  # candidates scoring below this are ignored


# ---------------------------------------------------------------------------------------------
# Tokeniser
# ---------------------------------------------------------------------------------------------

_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n.*?\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)", re.DOTALL)
_FENCE = re.compile(r"^\s*(?:```|~~~)")
_HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
_LIST = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])[ \t]+(?:\[[ xX]\][ \t]+)?(.*)$")
_BLOCK_ID = re.compile(r"[ \t]\^([A-Za-z0-9-]+)[ \t]*$")
_BLOCKQUOTE = re.compile(r"^(?:>[ \t]*)+")
# Inline-field lines naming a person: `Attendees:: [[Roy Howat]]`.
_PERSON_FIELD = re.compile(
    r"^(?:attendees?|presenters?|speakers?|authors?|teachers?|instructors?|with|by)[ \t]*::[ \t]*"
    r"(?P<rest>.*)$",
    re.IGNORECASE,
)

# Spans that must not be scanned: code, URLs, images/embeds, and chips that already carry a target.
_MASKS = (
    re.compile(r"`[^`\n]*`"),
    re.compile(r"!\[\[[^\]\n]*\]\]"),
    re.compile(r"!\[[^\]\n]*\]\([^)\n]*\)"),
    re.compile(r"\[@[^\]\n]*\]\([^)\n]*\)"),
    re.compile(r"\]\([^)\n]*\)"),
    re.compile(r"https?://\S+"),
)

_WIKILINK = re.compile(r"\[\[(?P<target>[^\]|#\n]+)(?:#[^\]|\n]*)?(?:\|[^\]\n]*)?\]\]")
_MEDIA_EXT = re.compile(
    r"\.(?:png|jpe?g|webp|gif|avif|svg|pdf|mp3|m4a|wav|mp4|mov)$", re.IGNORECASE
)

_NO = r"(?i:n[º°o]\.?|no\.?|number|#)"
_OPUS = re.compile(
    r"(?i:\bOp(?:us)?\.?[ \t]*)(?P<opus>\d+[a-z]?)"
    rf"(?:[ \t]*[,;:–-]?[ \t]*{_NO}[ \t]*(?P<num>\d+))?"
)
# (label, pattern, formatter). Case-sensitive on purpose: `K`, `D` and `S` are single letters.
_CATALOGUES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("BWV", re.compile(r"\bBWV\.?[ \t]*(?P<n>\d+[a-z]?)"), "BWV {n}"),
    (
        "K",
        re.compile(r"\bK\.?[ \t]*(?P<n>\d{3}[a-z]?)\b|\bK\.[ \t]*(?P<n2>\d{1,3}[a-z]?)\b"),
        "K. {n}",
    ),
    ("Hob", re.compile(r"\bHob\.?[ \t]*(?P<n>[IVX]+[ \t]*[:/][ \t]*\d+[a-z]?)"), "Hob. {n}"),
    ("D", re.compile(r"\bD\.[ \t]*(?P<n>\d{1,3}[a-z]?)\b|\bD[ \t](?P<n2>\d{3}[a-z]?)\b"), "D. {n}"),
    ("S", re.compile(r"\bS\.[ \t]*(?P<n>\d{1,3}[a-z]?)\b"), "S. {n}"),
)
_BARE_NO = re.compile(r"(?<!\w)[Nn](?:[º°]|o\.)[ \t]*(?P<num>\d+)\b")
_ORDINAL = re.compile(
    r"\b(?i:first|second|third|fourth|fifth|sixth|seventh|last|final|slow|opening|closing"
    r"|\d+(?:st|nd|rd|th))[ \t]+(?i:movement)"
    r"(?:[ \t]+(?i:of)[ \t]+(?:(?i:the)[ \t]+)?"
    r"[A-ZÀ-ÖØ-Þ][\w'’-]*"
    r"(?:[ \t]+(?:[A-ZÀ-ÖØ-Þ][\w'’-]*|(?i:op)\.?[ \t]*\d+|(?i:no)\.?[ \t]*\d+))*)?"
)
_KEY_TITLE = re.compile(
    r"\b[A-G](?:[-\s]?(?i:flat|sharp)|[♭♯b#])?[ \t-](?i:major|minor)[ \t]+[A-ZÀ-ÖØ-Þ][\w'’-]*"
)
_WTC = re.compile(
    r"\b(?:WTC|Well[- ]Tempered[ \t]+Clavier)(?:,?[ \t]*Book[ \t]*(?:[12]|I{1,2}))?",
)
_QUOTED = re.compile(r"[\"“](?P<t>[^\"”\n]{4,80})[\"”]|(?<![*\w])\*(?P<i>[^*\n]{4,80})\*(?![*\w])")
_TECHNIQUE = re.compile(
    r"\b(?i:pedal(?:l?ing)?|legato|staccato|rubato|metronome|articulation|dynamics|phrasing"
    r"|fingering|voicing|trills?|arpeggios?|scales?|voice[ \t]+leading|hand[ \t]+position"
    r"|tone[ \t]+production|relaxation)\b"
)

_NAME_START = "A-ZÀ-ÖØ-Þ"
_NAME = rf"[{_NAME_START}][\w'’-]*"
_NAMED_FORM = re.compile(
    rf"\b{_NAME}[ \t]+(?i:préludes?|preludes?|études?|etudes?|nocturnes?|sonatas?"
    r"|ballades?|polonaises?|inventions?|suites?|concertos?|symphonies)\b"
)
_COMPOSER_PAIR = re.compile(rf"\b(?P<first>{_NAME})[ \t]+and[ \t]+(?P<second>{_NAME})\b")
_PRECEDING_NAME = re.compile(rf"(?P<name>{_NAME})(?:['’]s)?[,:]?[ \t]*$")
_CAT_START = (
    r"(?:(?i:op(?:us)?)\.?[ \t]*\d|BWV\.?[ \t]*\d|K\.?[ \t]*\d|Hob\.?[ \t]*[IVX]"
    r"|D\.[ \t]*\d|S\.[ \t]*\d)"
)
_NAME_BEFORE_CAT = re.compile(rf"(?P<name>{_NAME})(?:['’]s)?[,:]?[ \t]+{_CAT_START}")
_WORD = re.compile(r"[^\W\d_][\w'’-]*")
_POSSESSIVE = re.compile(r"['’]s$")
_PARTICLES = {"de", "du", "van", "von", "di", "da", "la", "le", "del", "der", "den", "ter", "el"}
_SENTENCE_END = '.!?:"“(*_>—–'

_STOP = {
    w.casefold()
    for w in (
        "The This That These Those Today Also And But Then When While If In On At For With From "
        "Next Last First Second Third Practice Remember Note Notes Try Use Keep Make Play Listen "
        "Think Work Focus Watch Let Do Dont Not No Yes How Why What Who Where Which It Its He She "
        "They We You My Our Your His Her Their There Here Some Many Most Each Every All Both One "
        "Two Three Op Opus Nr Monday Tuesday Wednesday Thursday Friday Saturday Sunday January "
        "February March April May June July August September October November December Also "
        "Because Since So As Or Is Are Was Were Be Been Can Could Should Would Will May Might "
        "Need Needs Want Wants Get Got Take Took Give Gave See Saw Look Tell Told Ask Asked Say "
        "Said Start Stop Good Great Nice Bad Better Best Very Really Just Only Even Still Always "
        "Never Sometimes Often Maybe Perhaps Again After Before During Until Over Under About "
        "Between Into Out Up Down Off Now Soon Later Once Another Other Such Same Different Next "
        "Lesson Class Session Masterclass Workshop Lecture Meeting Reading Video Reflection "
        "Action Items Item Summary Notes Todo Idea Ideas Question Questions Answer Example"
    ).split()
}


@dataclass
class _Tok:
    span: Span
    structural: bool  # eligible to be reported as unresolved
    start: int = 0


@dataclass
class _Frame:
    indent: int
    composer: str | None
    opus: str | None


def _mask(text: str) -> str:
    for pattern in _MASKS:
        text = pattern.sub(lambda m: " " * len(m.group(0)), text)
    return text


def _blank(work: str, start: int, end: int) -> str:
    return work[:start] + " " * (end - start) + work[end:]


def _quote(content: str, start: int, end: int, limit: int = 240) -> str:
    text = content.strip()
    if len(text) <= limit:
        return text
    lo = max(0, start - limit // 2)
    hi = min(len(content), end + limit // 2)
    head = "…" if lo > 0 else ""
    tail = "…" if hi < len(content) else ""
    return f"{head}{content[lo:hi].strip()}{tail}"


def _is_name_word(word: str) -> bool:
    core = _POSSESSIVE.sub("", word).strip("'’-")
    return (
        len(core) >= 3
        and core[0].isupper()
        and not (core.isupper() and len(core) > 1)
        and core.casefold() not in _STOP
    )


def _dominant_composer(body: str) -> str | None:
    """The name most often written directly before a catalogue number (the spike's rule)."""
    counts: Counter[str] = Counter()
    first: dict[str, int] = {}
    for m in _NAME_BEFORE_CAT.finditer(_mask(body)):
        name = _POSSESSIVE.sub("", m.group("name"))
        if name.casefold() in _STOP:
            continue
        counts[name] += 1
        first.setdefault(name, m.start())
    if not counts:
        return None
    return min(counts, key=lambda n: (-counts[n], first[n]))


def _span(
    text: str,
    quote: str,
    anchor: str | None,
    hint: KindHint | None,
    title: str,
    kind: str,
    composer: str | None = None,
    opus: str | None = None,
) -> Span:
    ctx: SpanContext = {"note_title": title, "note_kind": kind}
    if composer:
        ctx["composer"] = composer
    if opus:
        ctx["opus"] = opus
    return {"text": text, "quote": quote, "anchor": anchor, "kind_hint": hint, "context": ctx}


def _wikilink_targets(text: str) -> list[str]:
    return [
        m.group("target").strip()
        for m in _WIKILINK.finditer(text)
        if not _MEDIA_EXT.search(m.group("target").strip())
    ]


def _person_names(rest: str) -> list[str]:
    linked = _wikilink_targets(rest)
    if linked:
        return linked
    parts = re.split(r"\s*(?:,|;|&|\band\b)\s*", rest)
    return [p.strip(" \t.*_") for p in parts if p.strip(" \t.*_")]


def _line_tokens(
    content: str,
    anchor: str | None,
    title: str,
    kind: str,
    inherited: _Frame,
    dominant: str | None,
) -> tuple[list[_Tok], str | None, str | None]:
    """Spans of one line, plus the (composer, opus) the line itself established."""
    field_match = _PERSON_FIELD.match(content.strip())
    if field_match:
        rest = field_match.group("rest")
        return (
            [
                _Tok(_span(n, content.strip(), None, "person", title, kind), False)
                for n in _person_names(rest)
            ],
            None,
            None,
        )

    masked = work = _mask(content)
    toks: list[_Tok] = []
    found_comp: str | None = None
    found_opus: str | None = None
    adjacent: set[int] = set()

    def add(m_start: int, m_end: int, span: Span, structural: bool) -> None:
        toks.append(_Tok(span, structural, m_start))

    # Existing [[wikilinks]]
    for m in _WIKILINK.finditer(work):
        target = m.group("target").strip()
        if _MEDIA_EXT.search(target):
            continue
        add(
            m.start(),
            m.end(),
            _span(target, _quote(content, m.start(), m.end()), anchor, None, title, kind),
            False,
        )
        work = _blank(work, m.start(), m.end())

    # Catalogue numbers and bare "Nº 12", in reading order so a bare number inherits the opus
    # written earlier on the same line.
    hits: list[tuple[int, int, str, re.Match[str]]] = []
    for m in _OPUS.finditer(work):
        hits.append((m.start(), m.end(), "opus", m))
    for label, pattern, _fmt in _CATALOGUES:
        for m in pattern.finditer(work):
            hits.append((m.start(), m.end(), label, m))
    taken: list[tuple[int, int]] = []
    ordered = sorted(hits, key=lambda h: (h[0], -(h[1] - h[0])))
    kept: list[tuple[int, int, str, re.Match[str]]] = []
    for h in ordered:
        if any(h[0] < e and s < h[1] for s, e in taken):
            continue
        taken.append((h[0], h[1]))
        kept.append(h)
    for m in _BARE_NO.finditer(work):
        if not any(m.start() < e and s < m.end() for s, e in taken):
            kept.append((m.start(), m.end(), "bare", m))
    kept.sort(key=lambda h: h[0])

    running_comp = inherited.composer
    running_opus = inherited.opus
    for start, end, label, m in kept:
        before = _PRECEDING_NAME.search(work[:start])
        adj = None
        if before and before.group("name").casefold() not in _STOP and label != "bare":
            adj = _POSSESSIVE.sub("", before.group("name"))
            adjacent.add(before.start("name"))
            running_comp = adj
            found_comp = adj
        quote = _quote(content, start, end)
        text = content[start:end].strip()
        if label == "opus":
            opus = f"Op. {m.group('opus')}"
            running_opus = found_opus = opus
            comp = running_comp or dominant
            hint: KindHint = "movement" if m.group("num") else "work"
            add(start, end, _span(text, quote, anchor, hint, title, kind, comp, opus), True)
        elif label == "bare":
            if running_opus is None:
                continue
            comp = running_comp or dominant
            add(
                start,
                end,
                _span(text, quote, anchor, "movement", title, kind, comp, running_opus),
                True,
            )
        else:
            fmt = next(f for lab, _p, f in _CATALOGUES if lab == label)
            number = m.group("n") or m.groupdict().get("n2")
            canon = fmt.format(n=re.sub(r"\s+", "", number or ""))
            # The catalogue itself names the composer; a branch composer would often be wrong.
            add(start, end, _span(text, quote, anchor, "work", title, kind, adj, canon), True)
        work = _blank(work, start, end)

    # Ordinal movement phrases, key-and-form titles, WTC.
    line_comp = found_comp or inherited.composer
    for m in _ORDINAL.finditer(work):
        text = content[m.start() : m.end()].strip()
        # "second movement of the Hammerklavier" names its work; a bare one takes the branch's.
        named = re.search(r"(?i)\bof\b", text) is not None
        comp, opus = (None, None) if named else (line_comp, running_opus)
        quote = _quote(content, m.start(), m.end())
        add(
            m.start(),
            m.end(),
            _span(text, quote, anchor, "movement", title, kind, comp, opus),
            True,
        )
        work = _blank(work, m.start(), m.end())
    for pattern in (_KEY_TITLE, _WTC):
        for m in pattern.finditer(work):
            text = content[m.start() : m.end()].strip()
            add(
                m.start(),
                m.end(),
                _span(
                    text,
                    _quote(content, m.start(), m.end()),
                    anchor,
                    "work",
                    title,
                    kind,
                    line_comp,
                ),
                True,
            )
            work = _blank(work, m.start(), m.end())

    # A named musical form carries work evidence even when the title is lowercase.
    # Coordinated proper names are explicit mentions, including names absent from the host.
    for m in _NAMED_FORM.finditer(work):
        text = content[m.start() : m.end()].strip()
        add(
            m.start(),
            m.end(),
            _span(text, _quote(content, m.start(), m.end()), anchor, "work", title, kind),
            True,
        )
        work = _blank(work, m.start(), m.end())
    for m in _COMPOSER_PAIR.finditer(masked):
        if work[m.start() : m.end()] != m.group(0):
            continue  # a work phrase already consumed one of these words
        if not all(_is_name_word(m.group(k)) for k in ("first", "second")):
            continue
        for key in ("first", "second"):
            add(
                m.start(key),
                m.end(key),
                _span(
                    m.group(key),
                    _quote(content, m.start(), m.end()),
                    anchor,
                    "composer",
                    title,
                    kind,
                ),
                True,
            )
        work = _blank(work, m.start(), m.end())

    # Quoted and italic titles (recall only).
    for m in _QUOTED.finditer(work):
        text = (m.group("t") or m.group("i")).strip()
        if len(text.split()) < 2 and not text[:1].isupper():
            continue
        add(
            m.start(),
            m.end(),
            _span(text, _quote(content, m.start(), m.end()), anchor, "work", title, kind),
            False,
        )
        work = _blank(work, m.start(), m.end())

    # Name runs. A single capitalised word at the start of a sentence is skipped (it is usually
    # just a capital) unless it sits right before a catalogue number.
    words = list(_WORD.finditer(work))
    i = 0
    while i < len(words):
        w = words[i]
        if not _is_name_word(w.group(0)):
            i += 1
            continue
        j = i
        while j + 1 < len(words) and not _POSSESSIVE.search(words[j].group(0)):
            nxt = words[j + 1]
            gap = work[words[j].end() : nxt.start()]
            if gap.strip(" \t") != "" or gap == "":
                break
            if _is_name_word(nxt.group(0)):
                j += 1
            elif (
                nxt.group(0).casefold() in _PARTICLES
                and j + 2 < len(words)
                and work[nxt.end() : words[j + 2].start()].strip(" \t") == ""
                and _is_name_word(words[j + 2].group(0))
            ):
                j += 2
            else:
                break
        start, end = w.start(), words[j].end()
        run_words = [x.group(0) for x in words[i : j + 1]]
        i = j + 1
        prefix = work[:start].rstrip()
        initial = prefix == "" or prefix[-1] in _SENTENCE_END
        if initial and len(run_words) == 1 and start not in adjacent:
            continue
        if initial and run_words[0].casefold() in _STOP:
            continue
        text = _POSSESSIVE.sub("", content[start:end]).strip()
        name_hint: KindHint | None = "composer" if len(text.split()) == 1 else None
        quote = _quote(content, start, end)
        add(start, end, _span(text, quote, anchor, name_hint, title, kind), False)

    # Technique cues (recall only).
    seen_cues: set[str] = set()
    for m in _TECHNIQUE.finditer(work):
        cue = re.sub(r"\s+", " ", m.group(0).lower())
        if cue in seen_cues:
            continue
        seen_cues.add(cue)
        add(
            m.start(),
            m.end(),
            _span(cue, _quote(content, m.start(), m.end()), anchor, "technique", title, kind),
            False,
        )

    toks.sort(key=lambda t: t.start)
    return toks, found_comp, found_opus


def _scan(body_md: str, title: str = "", kind: str = "note") -> list[_Tok]:
    body = _FRONTMATTER.sub("", body_md, count=1)
    dominant = _dominant_composer(body)
    toks: list[_Tok] = []
    heading_anchor: str | None = None
    frames: list[_Frame] = []
    in_fence = False
    for raw in body.splitlines():
        if _FENCE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence or not raw.strip():
            continue
        heading = _HEADING.match(raw)
        if heading:
            content = heading.group(1)
            heading_anchor = slug(content.strip())
            frames.clear()
            indent = -1
        else:
            listed = _LIST.match(raw)
            if listed:
                indent = len(listed.group(1).expandtabs(4))
                content = listed.group(2)
            else:
                indent = 0
                content = raw.strip()
            content = _BLOCKQUOTE.sub("", content)
            while frames and frames[-1].indent > indent:
                frames.pop()
        anchor = heading_anchor
        block = _BLOCK_ID.search(content)
        if block and not heading:
            anchor = f"^{block.group(1)}"
            content = content[: block.start()]
        inherited = _Frame(
            indent,
            next((f.composer for f in reversed(frames) if f.composer), None),
            next((f.opus for f in reversed(frames) if f.opus), None),
        )
        found, comp, opus = _line_tokens(content, anchor, title, kind, inherited, dominant)
        toks.extend(found)
        if comp or opus:
            frames[:] = [f for f in frames if f.indent != indent]
            frames.append(_Frame(indent, comp or inherited.composer, opus or inherited.opus))
    return toks


def tokenise(body_md: str, *, title: str = "", kind: str = "note") -> list[Span]:
    """Spans of a Markdown body with carried context (K§4 step 1, K§12.2).

    Strips frontmatter, skips code, walks headings and list items (anchor = `anchors.slug` of the
    nearest heading, or `^block-id` when the line ends with one) and recognises catalogue numbers,
    ordinal movement phrases, existing [[wikilinks]], name runs and technique cues. An opus line
    with no composer inherits one from its list branch, else the note's dominant composer. A bare
    "Nº 12" inherits the last opus in its list branch and is skipped when there is none.
    """
    return [t.span for t in _scan(body_md, title, kind)]


# ---------------------------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------------------------


def _scheme_name(scheme: LinkSchemes) -> str:
    return str(getattr(scheme, "prefix", type(scheme).__name__))


def _entity_id(scheme: LinkSchemes, value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(f"scheme {_scheme_name(scheme)!r}: entity_id {value!r} is not an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"\s*-?\d+\s*", value):
        return int(value)
    raise ValueError(f"scheme {_scheme_name(scheme)!r}: entity_id {value!r} is not an integer")


def _candidate(scheme: LinkSchemes, raw: Candidate | dict[str, Any]) -> Candidate:
    """A host candidate (dataclass or plain dict, extra keys ignored) as a fresh Candidate."""

    def get(key: str, default: Any = None) -> Any:
        return getattr(raw, key, default) if not isinstance(raw, dict) else raw.get(key, default)

    for key in ("entity_type", "entity_id", "entity_label"):
        if get(key) is None:
            raise ValueError(f"scheme {_scheme_name(scheme)!r}: candidate lacks {key}")
    try:
        score = float(get("score", 0.0) or 0.0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"scheme {_scheme_name(scheme)!r}: bad candidate score") from exc
    children = get("children")
    duplicates = get("duplicates")
    return Candidate(
        entity_type=str(get("entity_type")),
        entity_id=_entity_id(scheme, get("entity_id")),
        entity_label=str(get("entity_label")),
        score=score,
        duplicate_group=get("duplicate_group"),
        children=[_candidate(scheme, c) for c in children] if children else None,
        composer_label=get("composer_label"),
        duplicates=[_candidate(scheme, c) for c in duplicates] if duplicates else None,
    )


@dataclass
class _Cluster:
    rep: Candidate
    members: list[Candidate]
    group: str | None = None
    key: str | None = None  # the dedupe_key that formed it, when no host group did


def _ident(c: Candidate) -> tuple[str, int]:
    return (c.entity_type, c.entity_id)


def _clusters(items: list[tuple[LinkSchemes, Candidate, Any]]) -> list[_Cluster]:
    """Duplicate collapse (K§4 step 3, K§12.2), keeping rank order of the best member.

    A candidate that arrives with `duplicate_group` (or `duplicates`) is a cluster the host already
    collapsed: it is `[it, *duplicates]` and `dedupe_key` is not called on it. Every other
    candidate collapses with the ones sharing its scheme's `dedupe_key`, which is handed the host's
    own object (a dict or a Candidate, whatever its reconcile returned).
    """
    clusters: list[_Cluster] = []
    by_group: dict[str, _Cluster] = {}
    by_key: dict[tuple[str, str], _Cluster] = {}

    def add(cluster: _Cluster, cand: Candidate) -> None:
        if all(_ident(m) != _ident(cand) for m in cluster.members):
            cluster.members.append(cand)

    for scheme, cand, raw in items:
        group = cand.duplicate_group
        if cand.duplicates and not group:
            group = f"dup:{cand.entity_type}:{cand.entity_id}"
        if group:
            cluster = by_group.get(group)
            if cluster is None:
                cluster = _Cluster(cand, [cand], group)
                by_group[group] = cluster
                clusters.append(cluster)
            else:
                add(cluster, cand)
            for dup in cand.duplicates or []:
                add(cluster, dup)
            continue
        key = scheme.dedupe_key(raw) if isinstance(scheme, SchemeDedupe) else None
        if key is not None:
            cluster = by_key.get((_scheme_name(scheme), key))
            if cluster is None:
                cluster = _Cluster(cand, [cand], key=key)
                by_key[(_scheme_name(scheme), key)] = cluster
                clusters.append(cluster)
            else:
                add(cluster, cand)
            continue
        clusters.append(_Cluster(cand, [cand]))
    for cluster in clusters:
        rest = sorted(cluster.members[1:], key=lambda m: -m.score)
        cluster.members = [cluster.rep, *rest]
        if len(cluster.members) > 1 and cluster.group is None:
            cluster.group = f"dup:{cluster.key}" if cluster.key else f"dup:{cluster.rep.entity_id}"
    return clusters


# ---------------------------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------------------------

_Outcome = Literal["link", "ambiguous", "unresolved", "none"]


@dataclass
class _Decision:
    outcome: _Outcome
    top: Candidate | None = None
    confidence: float = 0.0
    reason: str = ""
    candidates: list[ProposalCandidate] = field(default_factory=list)
    near: list[Candidate] = field(default_factory=list)  # judge said none: what it rejected


def _clamp(x: float) -> float:
    return min(1.0, max(0.0, x))


def _band(conf: float, t: Thresholds) -> str:
    return "high" if conf >= t.high else "medium" if conf >= t.medium else "low"


def _proposal_candidate(c: Candidate, group: str | None = None) -> ProposalCandidate:
    return ProposalCandidate(
        entity_type=c.entity_type,
        entity_id=c.entity_id,
        entity_label=c.entity_label,
        confidence=_clamp(c.score),
        duplicate_group=group if group is not None else c.duplicate_group,
    )


def _pickable(
    head: _Cluster, clusters: list[_Cluster], t: Thresholds, extra: list[Candidate] | None = None
) -> list[ProposalCandidate]:
    """candidates[] of an ambiguous item: the head cluster's members, then near clusters."""
    out: list[ProposalCandidate] = [_proposal_candidate(m, head.group) for m in head.members]
    for cand in extra or []:
        out.append(_proposal_candidate(cand))
    near = [c for c in clusters if c is not head][: t.near]
    for cluster in near:
        out.extend(_proposal_candidate(m, cluster.group) for m in cluster.members)
    seen: set[tuple[str, int]] = set()
    unique: list[ProposalCandidate] = []
    for c in out:
        key = (c.entity_type, c.entity_id)
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique[: t.max_candidates]


def _locate(
    choice: Candidate, clusters: list[_Cluster]
) -> tuple[_Cluster, Candidate, Candidate | None] | None:
    """Find the judge's choice among clusters, members and children -> (cluster, choice, parent)."""
    for cluster in clusters:
        for member in cluster.members:
            if _ident(member) == _ident(choice):
                return cluster, member, None
    for cluster in clusters:
        for member in cluster.members:
            for child in member.children or []:
                if _ident(child) == _ident(choice):
                    return cluster, child, member
    return None


def _decide(
    span: Span,
    clusters: list[_Cluster],
    judge: Any | None,
    t: Thresholds,
) -> tuple[_Decision, bool]:
    """-> (decision, judge_failed). K§4 steps 4-6."""
    text = span["text"]
    if not clusters:
        return _Decision("none"), False
    failed = False
    if judge is not None:
        mention = Mention(
            text=text,
            quote=span["quote"],
            anchor=span["anchor"],
            context=dict(span["context"]),
        )
        try:
            judgement: Judgement | None = judge.judge(mention, [c.rep for c in clusters])
        except Exception as exc:  # JevUnavailableError, timeouts, a host's own bug: degrade
            log.warning("enrich: judge failed on %r, degrading to search-only: %r", text, exc)
            judgement = None
            failed = True
        if judgement is not None:
            decided = _from_judgement(text, clusters, judgement, t)
            if decided is not None:
                return decided, False
            log.warning("enrich: judge chose an entity it was not offered on %r", text)
    return _search_only(text, clusters, t), failed


def _from_judgement(
    text: str, clusters: list[_Cluster], judgement: Judgement, t: Thresholds
) -> _Decision | None:
    conf = _clamp(judgement.confidence)
    if judgement.choice is None:
        near = [c.rep for c in clusters[: t.near]]
        return _Decision(
            "unresolved",
            confidence=conf,
            reason=f"{judgement.judge} found no match for {text!r}",
            near=near,
        )
    located = _locate(judgement.choice, clusters)
    if located is None:
        return None
    cluster, chosen, parent = located
    how = f"{text!r} matched by search and {judgement.judge} ({_band(conf, t)}, {conf:.2f})"
    if conf < t.judge:
        extra = [c for c in (parent.children if parent else []) or [] if c is not chosen]
        head = cluster if parent is None else _Cluster(chosen, [chosen])
        return _Decision(
            "ambiguous",
            chosen if parent else cluster.rep,
            conf,
            f"{how}; not sure enough to link, pick one",
            _pickable(head, clusters, t, extra if parent else None),
        )
    if parent is None and len(cluster.members) > 1 and judgement.stage == "work":
        return _Decision(
            "ambiguous",
            cluster.rep,
            conf,
            f"{how}; {len(cluster.members)} entries look like the same thing, pick one",
            _pickable(cluster, clusters, t),
        )
    return _Decision("link", chosen, conf, how)


def _search_only(text: str, clusters: list[_Cluster], t: Thresholds) -> _Decision:
    if len(clusters) == 1:
        cluster = clusters[0]
        score = _clamp(cluster.rep.score)
        if len(cluster.members) > 1:
            return _Decision(
                "ambiguous",
                cluster.rep,
                score,
                f"{text!r} matched {len(cluster.members)} entries that look like the same thing, "
                "pick one",
                _pickable(cluster, clusters, t),
            )
        return _Decision(
            "link",
            cluster.rep,
            score,
            f"{text!r} matched by search ({_band(score, t)}, {score:.2f})",
        )
    head = clusters[0]
    return _Decision(
        "ambiguous",
        head.rep,
        _clamp(head.rep.score),
        f"{text!r} matched {len(clusters)} different entries by search, pick one",
        _pickable(head, clusters, t),
    )


# ---------------------------------------------------------------------------------------------
# propose
# ---------------------------------------------------------------------------------------------

_PERSON_KEYS = ("presenter", "speaker", "author", "person", "teacher", "instructor", "attendees")
_TITLE_PERSON = re.compile(
    rf"(?:\b(?:with|by)\b|[-–—:])[ \t]*(?P<name>{_NAME}(?:[ \t]+{_NAME}){{1,2}})[ \t]*$"
)


def _as_text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def _clean_person(text: str) -> str:
    text = re.sub(r"\[\[([^\]|#]*)(?:[#|][^\]]*)?\]\]", r"\1", text)
    return text.strip(" \t*_\"'")


def _persons(row: dict[str, Any], title: str, kind: str) -> list[Span]:
    """Person spans from note.person, frontmatter, then the title (Attendees:: is in the body)."""
    found: list[tuple[str, str]] = []
    if row.get("person"):
        found.append((str(row["person"]), f"Person: {row['person']}"))
    fm = repo.as_json(row.get("frontmatter"), {}) or {}
    if isinstance(fm, dict):
        lowered = {str(k).casefold(): v for k, v in fm.items()}
        for key in _PERSON_KEYS:
            for value in _as_text_list(lowered.get(key)):
                found.append((value, f"{key.capitalize()}: {value}"))
    m = _TITLE_PERSON.search(title)
    if m:
        found.append((m.group("name"), title))
    spans: list[Span] = []
    seen: set[str] = set()
    for raw, quote in found:
        name = _clean_person(raw)
        if len(name) < 3 or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        spans.append(_span(name, quote, None, "person", title, kind))
    return spans


def _span_key(span: Span) -> tuple[str, str | None, str | None, str | None]:
    ctx = span["context"]
    return (span["text"].casefold(), span["kind_hint"], ctx.get("composer"), ctx.get("opus"))


def _norm_anchor(anchor: str | None) -> str:
    return anchor or ""


def _existing(cfg: HostConfig, user_id: str, note_id: int) -> dict[tuple[str, int, str], str]:
    rows = cfg.db.run(
        "SELECT entity_type, entity_id, anchor, status FROM note_links"
        " WHERE note_id = %s AND user_id = %s AND status IN ('confirmed', 'rejected')",
        [note_id, user_id],
    )
    out: dict[tuple[str, int, str], str] = {}
    for r in rows:
        key = (r["entity_type"], int(r["entity_id"]), _norm_anchor(r["anchor"]))
        if out.get(key) != "confirmed":
            out[key] = r["status"]
    return out


class _Suppress:
    """The diff rule: nothing re-proposes an (entity, anchor) already confirmed or rejected."""

    def __init__(self, existing: dict[tuple[str, int, str], str]) -> None:
        self.existing = existing

    def status(
        self, c: ProposalCandidate | ProposedLink, anchor: str | None, any_anchor: bool
    ) -> str | None:
        found: str | None = None
        for (etype, eid, a), status in self.existing.items():
            if etype != c.entity_type or eid != c.entity_id:
                continue
            if any_anchor or a == _norm_anchor(anchor):
                if status == "confirmed":
                    return "confirmed"
                found = status
        return found

    def link(self, link: ProposedLink, any_anchor: bool) -> ProposedLink | None:
        if not link.candidates:
            return None if self.status(link, link.anchor, any_anchor) else link
        kept: list[ProposalCandidate] = []
        for cand in link.candidates:
            status = self.status(cand, link.anchor, any_anchor)
            if status == "confirmed":
                return None  # the user already picked one of these here
            if status is None:
                kept.append(cand)
        if not kept:
            return None
        top = next(
            (c for c in kept if (c.entity_type, c.entity_id) == (link.entity_type, link.entity_id)),
            kept[0],
        )
        return link.model_copy(
            update={
                "candidates": kept,
                "entity_type": top.entity_type,
                "entity_id": top.entity_id,
                "entity_label": top.entity_label,
            }
        )


def propose(
    cfg: HostConfig,
    user_id: str,
    note_id: int,
    *,
    llm: bool = False,
    refresh: bool = False,
    use_judge: bool = True,
    thresholds: Thresholds | None = None,
) -> Proposal:
    """The Layer 1 proposal for a note (K§4, ADR §3.4). Computes every time and never writes.

    `refresh` is accepted for call-site symmetry only: the cache and its refresh rule are
    `review`'s (K§3), which calls this on a miss. `use_judge=False` is search-only, which is what
    `propose_on_sync='search'` needs so a sync never waits on AI. With `llm=True` the Layer 2
    extraction (`extract`, C5b) is folded in; it raises `extract.LlmDisabled` when the host has
    not enabled it.
    """
    t = thresholds or Thresholds()
    rows = cfg.db.run(
        "SELECT id, title, kind, body_md, frontmatter, person FROM notes"
        " WHERE id = %s AND user_id = %s",
        [note_id, user_id],
    )
    if not rows:
        raise repo.NoteNotFound(f"note {note_id} not found")
    row = rows[0]
    title, kind = row["title"] or "", row["kind"] or "note"

    toks = _scan(row["body_md"] or "", title, kind)
    toks += [_Tok(s, False) for s in _persons(row, title, kind)]

    # One host call per distinct span; every occurrence keeps its own anchor and quote.
    unique: dict[tuple[str, str | None, str | None, str | None], list[_Tok]] = {}
    for tok in toks:
        unique.setdefault(_span_key(tok.span), []).append(tok)
    keys = list(unique)
    spans = [unique[k][0].span for k in keys]

    gathered: list[list[tuple[LinkSchemes, Candidate, Any]]] = [[] for _ in spans]
    if spans:
        for scheme in cfg.schemes:
            result = scheme.reconcile(user_id, spans)
            if len(result) != len(spans):
                raise ValueError(
                    f"scheme {_scheme_name(scheme)!r}: reconcile returned {len(result)} lists "
                    f"for {len(spans)} spans"
                )
            for i, per_span in enumerate(result):
                for raw in per_span:
                    cand = _candidate(scheme, raw)
                    if cand.score >= t.floor:
                        gathered[i].append((scheme, cand, raw))

    judge = cfg.judge if use_judge else None
    decisions: dict[tuple[str, str | None, str | None, str | None], _Decision] = {}
    for key, span, items in zip(keys, spans, gathered, strict=True):
        items.sort(key=lambda it: -it[1].score)
        decision, failed = _decide(span, _clusters(items), judge, t)
        decisions[key] = decision
        if failed:
            judge = None  # one failure ends judging for this call; no N timeouts in a row

    links: list[ProposedLink] = []
    unresolved: list[UnresolvedMention] = []
    for key, occurrences in unique.items():
        decision = decisions[key]
        for tok in occurrences:
            span = tok.span
            if decision.outcome in ("link", "ambiguous") and decision.top is not None:
                links.append(
                    ProposedLink(
                        entity_type=decision.top.entity_type,
                        entity_id=decision.top.entity_id,
                        entity_label=decision.top.entity_label,
                        anchor=span["anchor"],
                        quote=span["quote"],
                        confidence=decision.confidence,
                        proposed_by=PROPOSED_BY,
                        reason=decision.reason,
                        candidates=decision.candidates if decision.outcome == "ambiguous" else None,
                    )
                )
            elif tok.structural and span["kind_hint"] != "person":
                label = next((c.composer_label for c in decision.near if c.composer_label), None)
                unresolved.append(
                    UnresolvedMention(
                        mention=span["text"],
                        anchor=span["anchor"],
                        quote=span["quote"],
                        candidates=[_proposal_candidate(c) for c in decision.near],
                        kind_hint=span["kind_hint"],
                        composer_label=label or span["context"].get("composer"),
                    )
                )

    note_level = _note_level(unique, decisions)
    suppress = _Suppress(_existing(cfg, user_id, note_id))
    kept: list[ProposedLink] = []
    for link in _collapse(links, note_level):
        out = suppress.link(link, (link.entity_type, link.entity_id) in note_level)
        if out is not None:
            kept.append(out)

    seen_un: set[tuple[str, str]] = set()
    uniq_un: list[UnresolvedMention] = []
    for u in unresolved:
        k = (u.mention.casefold(), _norm_anchor(u.anchor))
        if k not in seen_un:
            seen_un.add(k)
            uniq_un.append(u)

    proposal = Proposal(
        note_id=note_id,
        links=kept,
        action_items=[],
        takeaways=[],
        unresolved=uniq_un,
        generated_by=["resolver"],
        cached=False,
        proposed_at=datetime.now(UTC).replace(microsecond=0, tzinfo=None).isoformat(),
    )
    if llm:
        proposal = extract.merge(
            proposal, extract.extract(cfg, repo.get_note(cfg, user_id, note_id), proposal)
        )
    return proposal


def _note_level(
    unique: dict[tuple[str, str | None, str | None, str | None], list[_Tok]],
    decisions: dict[tuple[str, str | None, str | None, str | None], _Decision],
) -> dict[tuple[str, int], int | None]:
    """Entities a composer or person span resolved to: one note-level link each.

    The value is the occurrence count for a composer (`mention_count`, K§2) and None for a person.
    """
    found: dict[tuple[str, int], int | None] = {}
    for key, occurrences in unique.items():
        top = decisions[key].top
        hint = occurrences[0].span["kind_hint"]
        if top is None or hint not in ("composer", "person"):
            continue
        ident = (top.entity_type, top.entity_id)
        if hint == "composer":
            found[ident] = (found.get(ident) or 0) + len(occurrences)
        else:
            found.setdefault(ident, None)
    return found


def _collapse(
    links: list[ProposedLink], note_level: dict[tuple[str, int], int | None]
) -> list[ProposedLink]:
    """One link per (entity, anchor); composers and people get one per note."""
    out: list[ProposedLink] = []
    index: dict[tuple[Any, ...], int] = {}
    for link in links:
        ident = (link.entity_type, link.entity_id)
        if ident in note_level:
            key: tuple[Any, ...] = ("note", *ident)
            count = note_level[ident]
            update: dict[str, Any] = {"mention_count": count} if count is not None else {}
            if count is None:
                update["anchor"] = None  # a person is about the whole note
            link = link.model_copy(update=update)
        else:
            picks = tuple(sorted((c.entity_type, c.entity_id) for c in link.candidates or []))
            key = ("link", *ident, picks, _norm_anchor(link.anchor))
        if key in index:
            if link.confidence > out[index[key]].confidence:
                out[index[key]] = out[index[key]].model_copy(update={"confidence": link.confidence})
            continue
        index[key] = len(out)
        out.append(link)
    return out
