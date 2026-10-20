"""C5a tokeniser (K§4 step 1, K§12.2). Synthetic text only."""

from __future__ import annotations

from typing import Any

from arp_notes.anchors import slug
from arp_notes.enrich import Span, tokenise
from enrich_support import BODY


def texts(spans: list[Span], hint: str | None = "*") -> list[str]:
    return [s["text"] for s in spans if hint == "*" or s["kind_hint"] == hint]


def one(body: str, text: str) -> Span:
    found = [s for s in tokenise(body) if s["text"] == text]
    assert len(found) == 1, (text, texts(tokenise(body)))
    return found[0]


def ctx(span: Span) -> dict[str, Any]:
    return {k: v for k, v in span["context"].items() if k not in ("note_title", "note_kind")}


# --- shape ------------------------------------------------------------------------------------


def test_span_shape_and_note_context() -> None:
    [span] = [s for s in tokenise("# Etudes\n\nOp. 10 nº 3 sings\n", title="T", kind="lesson")]
    assert span == {
        "text": "Op. 10 nº 3",
        "quote": "Op. 10 nº 3 sings",
        "anchor": "etudes",
        "kind_hint": "movement",
        "context": {"note_title": "T", "note_kind": "lesson", "opus": "Op. 10"},
    }


def test_frontmatter_is_not_scanned() -> None:
    body = "---\nsource: Op. 99 nº 1\n---\nOp. 10 nº 3\n"
    assert texts(tokenise(body)) == ["Op. 10 nº 3"]


def test_code_fences_and_inline_code_are_skipped() -> None:
    body = "```\nOp. 77\n```\n~~~\nBWV 1\n~~~\nUse `Op. 99` here and BWV 814.\n"
    assert texts(tokenise(body)) == ["BWV 814"]


def test_urls_images_embeds_and_resolved_chips_are_skipped() -> None:
    body = (
        "See https://example.com/Op.10 and ![[scan Op. 12.png]] and ![x](Op-5.png), "
        "plus [@Études, Op.10](pt://repertoire/35).\n"
    )
    assert texts(tokenise(body)) == []


# --- anchors ----------------------------------------------------------------------------------


def test_anchor_is_the_nearest_heading_slug() -> None:
    body = "Op. 1 nº 1 before any heading\n\n# Part One\nOp. 2 nº 2\n\n## Sub: Deep\nOp. 3 nº 3\n"
    anchors = {s["text"]: s["anchor"] for s in tokenise(body)}
    assert anchors == {
        "Op. 1 nº 1": None,
        "Op. 2 nº 2": slug("Part One"),
        "Op. 3 nº 3": slug("Sub: Deep"),
    }


def test_trailing_block_id_is_the_anchor() -> None:
    body = "# H\n- Op. 10 nº 3 sings ^b1\n- Op. 10 nº 4 runs\n"
    anchors = {s["text"]: s["anchor"] for s in tokenise(body)}
    assert anchors == {"Op. 10 nº 3": "^b1", "Op. 10 nº 4": "h"}


def test_a_mention_inside_a_heading_anchors_to_that_heading() -> None:
    [span] = tokenise("## Op. 10 nº 3\n")
    assert span["anchor"] == slug("Op. 10 nº 3")


# --- catalogue patterns -----------------------------------------------------------------------


def test_the_three_opus_numbering_styles() -> None:
    body = "- Op. 10 nº 3\n- Op.25 No 1\n- op. 25 nº 6\n"
    spans = tokenise(body)
    assert texts(spans) == ["Op. 10 nº 3", "Op.25 No 1", "op. 25 nº 6"]
    assert [s["context"].get("opus") for s in spans] == ["Op. 10", "Op. 25", "Op. 25"]
    assert {s["kind_hint"] for s in spans} == {"movement"}


def test_an_opus_without_a_number_is_a_work() -> None:
    assert one("Op. 110 is next\n", "Op. 110")["kind_hint"] == "work"


def test_other_catalogues_and_canonical_ids() -> None:
    body = "BWV 814, K.380, Hob.XVI:48, D. 960 and S. 141\n"
    spans = tokenise(body)
    assert texts(spans) == ["BWV 814", "K.380", "Hob.XVI:48", "D. 960", "S. 141"]
    assert [s["context"].get("opus") for s in spans] == [
        "BWV 814",
        "K. 380",
        "Hob. XVI:48",
        "D. 960",
        "S. 141",
    ]
    assert {s["kind_hint"] for s in spans} == {"work"}


def test_catalogue_letters_are_not_matched_inside_ordinary_words() -> None:
    assert tokenise("the dodo had 3 Ks and a D major chord, ok\n") == []


def test_ordinal_phrases() -> None:
    body = "- the second movement of the Moonlit Sonata drags\n- 3rd movement is quick\n"
    spans = tokenise(body)
    assert texts(spans, "movement") == [
        "second movement of the Moonlit Sonata",
        "3rd movement",
    ]


def test_key_and_form_titles_and_wtc() -> None:
    spans = tokenise("Try an E major Nocturne, an E-flat major Sonata and the WTC Book 1.\n")
    assert texts(spans, "work") == ["E major Nocturne", "E-flat major Sonata", "WTC Book 1"]


def test_wikilinks_use_the_target_and_skip_media() -> None:
    body = "See [[Other note]], [[Piece#Intro|the piece]] and [[scan.png]].\n"
    assert texts(tokenise(body)) == ["Other note", "Piece"]


def test_technique_cues_are_deduplicated_per_line() -> None:
    spans = tokenise("Half pedaling, then more pedaling and legato.\n")
    assert texts(spans, "technique") == ["pedaling", "legato"]


# --- carried context --------------------------------------------------------------------------


def test_a_bare_number_inherits_the_opus_of_its_list_parent() -> None:
    body = "- Chopin Op. 10\n  - Nº 12 drop the hand\n  - Nº 4 is fast\n"
    spans = tokenise(body)
    bare = [s for s in spans if s["text"].startswith("Nº")]
    assert [ctx(s) for s in bare] == [{"composer": "Chopin", "opus": "Op. 10"}] * 2
    assert {s["kind_hint"] for s in bare} == {"movement"}


def test_a_bare_number_inherits_the_opus_earlier_on_the_same_line() -> None:
    body = "Op. 25 nº 1, then Nº 2 and Nº 3\n"
    assert [ctx(s) for s in tokenise(body)] == [{"opus": "Op. 25"}] * 3


def test_a_bare_number_inherits_the_last_opus_in_its_branch() -> None:
    body = "- Op. 10 nº 3\n- Nº 12\n"
    assert ctx(one(body, "Nº 12")) == {"opus": "Op. 10"}


def test_a_bare_number_with_no_opus_in_scope_is_dropped() -> None:
    assert tokenise("Nº 12 on its own\n") == []


def test_a_new_heading_resets_the_inherited_opus() -> None:
    body = "# A\n- Op. 10\n\n# B\n- Nº 3\n"
    assert texts(tokenise(body), "movement") == []


def test_a_composer_less_opus_takes_the_notes_dominant_composer() -> None:
    body = "Chopin Op. 10 nº 3 and Chopin's Op. 25 nº 1.\n\n# Later\nOp. 28 nº 4 is short\n"
    assert ctx(one(body, "Op. 28 nº 4")) == {"composer": "Chopin", "opus": "Op. 28"}


def test_a_named_composer_beats_the_dominant_one() -> None:
    body = "Chopin Op. 10 nº 3, Chopin Op. 25 nº 1, Beethoven Op. 110\n"
    assert ctx(one(body, "Op. 110"))["composer"] == "Beethoven"


def test_a_misspelt_composer_is_carried_as_written() -> None:
    assert ctx(one("Beethovan's Op. 110 is next\n", "Op. 110"))["composer"] == "Beethovan"


def test_non_opus_catalogues_do_not_borrow_a_composer() -> None:
    body = "- Chopin Op. 10 nº 3\n- K.380 is next\n"
    assert "composer" not in ctx(one(body, "K.380"))


def test_an_ordinal_that_names_its_work_carries_no_context() -> None:
    body = "- Chopin Op. 10 nº 3\n- the second movement of the Moonlit Sonata\n"
    assert ctx(one(body, "second movement of the Moonlit Sonata")) == {}


def test_a_bare_ordinal_takes_the_branch_context() -> None:
    body = "- Chopin Op. 28\n  - the third movement is quick\n"
    assert ctx(one(body, "third movement")) == {"composer": "Chopin", "opus": "Op. 28"}


# --- names and people -------------------------------------------------------------------------


def test_names_and_possessives() -> None:
    body = "We heard Roy Howat talk about Debussy's Préludes and Ludwig van Beethoven.\n"
    assert texts(tokenise(body)) == ["Roy Howat", "Debussy", "Préludes", "Ludwig van Beethoven"]
    hints = {s["text"]: s["kind_hint"] for s in tokenise(body)}
    assert hints["Debussy"] == "composer"
    assert hints["Roy Howat"] is None


def test_a_lone_sentence_initial_word_is_not_a_name_but_a_composer_before_a_catalogue_is() -> None:
    body = "Today we start. Pedal early.\n- Chopin Op. 10\n"
    assert texts(tokenise(body), "composer") == ["Chopin"]


def test_acronyms_and_stopwords_are_not_names() -> None:
    assert texts(tokenise("Then the PDF and OK list came on Monday in March.\n")) == []


def test_person_fields_become_person_spans_with_no_anchor() -> None:
    body = "# Talk\nAttendees:: [[Roy Howat]], [[Ada Quill|Ada]]\nPresenter:: Mo Lee and Jo Ng\n"
    persons = [s for s in tokenise(body) if s["kind_hint"] == "person"]
    assert [s["text"] for s in persons] == ["Roy Howat", "Ada Quill", "Mo Lee", "Jo Ng"]
    assert {s["anchor"] for s in persons} == {None}


# --- quotes -----------------------------------------------------------------------------------


def test_a_long_line_is_quoted_around_the_match() -> None:
    body = "x " * 300 + "Op. 10 nº 3 " + "y " * 300 + "\n"
    quote = one(body, "Op. 10 nº 3")["quote"]
    assert len(quote) < 300
    assert "Op. 10 nº 3" in quote
    assert quote.startswith("…") and quote.endswith("…")


def test_list_markers_are_not_part_of_the_quote() -> None:
    assert one("  - [ ] Op. 10 nº 3 sings\n", "Op. 10 nº 3")["quote"] == "Op. 10 nº 3 sings"


# --- the fixture ------------------------------------------------------------------------------


def test_fixture_note_spans() -> None:
    spans = tokenise(BODY, title="Synthetic masterclass", kind="masterclass")
    structural = [s["text"] for s in spans if s["kind_hint"] in ("work", "movement")]
    assert structural == [
        "Op. 10 nº 3",
        "Nº 12",
        "Op.25 No 1",
        "op. 25 nº 6",
        "BWV 814",
        "K.380",
        "Hob.XVI:48",
        "D. 960",
        "S. 141",
        "second movement of the Moonlit Sonata",
        "E major Nocturne",
        "WTC Book 1",
        "Op. 110",
    ]
    assert {s["context"].get("note_kind") for s in spans} == {"masterclass"}
    assert ctx(one(BODY, "Nº 12")) == {"composer": "Chopin", "opus": "Op. 10"}
    assert one(BODY, "Op. 10 nº 3")["anchor"] == "^e3"
