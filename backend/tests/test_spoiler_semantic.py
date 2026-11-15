"""Semantic plot-match layer: plot sentences, late-plot scoring, shield wiring, safe loading."""
import os
import zlib

import numpy as np
import pytest

from app.spoiler.retrieval import make_passages
from app.spoiler.semantic import SemanticMatcher, plot_sentences
from app.spoiler.shield import FilmInfo, SpoilerShield
from app.spoiler.wordlist import terms_from_cast

PLOT = ("Mara steals the crown jewels from the palace. She hides in the old harbour town. A friendly baker teaches her to cook. "
        "Her brother Tobin betrays her to the king. The guards drag Mara to the burning tower. In the finale the tower collapses and Mara dies.")


class FakeEncoder(SemanticMatcher):
    """Hashed bag-of-words embeddings: enough to test the maths and the wiring without an ONNX file."""
    def __init__(self, thr_blur=0.45, thr_warn=0.30):
        self.meta, self.thr_blur, self.thr_warn, self.max_len = {}, thr_blur, thr_warn, 96

    def embed(self, texts, batch=32):
        out = np.zeros((len(texts), 1024), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in "".join(c.lower() if c.isalnum() else " " for c in t).split():
                out[i, zlib.crc32(w.encode()) % 1024] += 1.0
        return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)


def test_plot_sentences_undo_the_overlapping_windows():
    ps = make_passages(PLOT)
    s = plot_sentences(ps)
    assert len(s) == 6 and s[0].startswith("Mara steals") and s[-1].endswith("Mara dies.")


def test_late_plot_match_scores_higher_than_early_plot_match():
    m = FakeEncoder()
    pv = m.plot_matrix(make_passages(PLOT))
    late, early, none = m.scores(["Mara dies when the tower collapses.", "Mara steals the crown jewels from the palace.", "Lovely music and costumes."], pv)
    assert late > early and late > none
    assert late > 0.3 and none < 0.15


def test_scores_are_empty_safe():
    m = FakeEncoder()
    assert len(m.scores([], m.plot_matrix(make_passages(PLOT)))) == 0
    assert list(m.scores(["x"], m.plot_matrix([]))) == [0.0]


def test_a_one_sentence_plot_has_no_late_part_and_does_not_crash():
    m = FakeEncoder()
    assert list(m.scores(["The tower collapses and Mara dies.", "Nice music."], m.plot_matrix(["Mara steals the crown jewels."]))) == [0.0, 0.0]


def test_cut_off_rises_with_review_length_but_never_drops_below_the_short_review_value():
    m = FakeEncoder(thr_blur=0.37, thr_warn=0.31)
    assert m.blur_threshold(40) == 0.37                      # no tail table (old meta.json): flat cut-off, as before
    m._tail_p = np.array([0.1, 0.03, 0.01, 0.003, 0.001]); m._tail_s = np.array([0.25, 0.31, 0.37, 0.42, 0.46])
    m.blur_fpr, m.warn_fpr = 0.03, 0.10
    t = [m.blur_threshold(n) for n in (1, 3, 6, 12, 30)]
    assert t[0] == 0.37 and t == sorted(t) and t[-1] > 0.42   # more sentences = more chances to match by accident = stricter
    assert all(m.warn_threshold(n) <= m.blur_threshold(n) for n in (1, 6, 30)) and m.warn_threshold(30) > m.warn_threshold(3)


def test_a_long_review_needs_a_stronger_match_than_a_short_one():
    sh, info = _shield_with_semantic(thr_blur=0.45, thr_warn=0.30)
    hit = "The guards drag Mara toward the tower."            # a middling match with the late plot
    score = float(sh.sem.scores([hit], sh.sem.plot_matrix(info.plot_passages))[0])
    sh.sem.thr_blur = score - 0.01                            # just enough to blur in a short review
    sh.sem._tail_p = np.array([0.1, 0.01, 0.001]); sh.sem._tail_s = np.array([score - 0.2, score - 0.01, score + 0.3])
    sh.sem.blur_fpr, sh.sem.warn_fpr = 0.03, 0.10
    short = sh.scan("Great score. " + hit, info)
    assert any(s.blurred for s in short.segments)
    padding = " ".join(f"Point {i} about the lovely costumes and music." for i in range(30))
    long = sh.scan(padding + " " + hit, info)
    assert not any(s.blurred for s in long.segments)


def _shield_with_semantic(**kw):
    sh = SpoilerShield()
    sh.fit_space(make_passages(PLOT) * 2)
    sh.sem = FakeEncoder(**kw)
    from tests.test_spoiler_ml import StubModel
    sh.ml = StubModel(sh._space, 0.05)               # a calm trained model: soft word rules are then ignored, only hard evidence counts
    return sh, FilmInfo(1, 1, terms_from_cast(["Mara Vell"]), make_passages(PLOT), [])


def test_shield_blurs_a_sentence_that_matches_the_late_plot_and_warns_on_a_weaker_match():
    sh, info = _shield_with_semantic(thr_blur=0.45, thr_warn=0.30)
    r = sh.scan("Great score. The tower collapses and Mara dies. Lovely sets.", info)
    hit = [s for s in r.segments if s.blurred]
    assert hit and "dies" in hit[0].text and any("late in the film" in x for x in hit[0].reasons)
    sh2, info2 = _shield_with_semantic(thr_blur=0.99, thr_warn=0.30)           # blur cut-off out of reach: label only
    text = "Great score. The guards drag her toward the burning tower. Lovely sets."
    r2 = sh2.scan(text, info2)
    assert not any(s.blurred for s in r2.segments) and r2.warn
    assert not sh2.scan(text, info2, use_sem=False).warn            # the label comes from this layer


def test_clean_review_is_untouched_and_the_layer_can_be_switched_off():
    sh, info = _shield_with_semantic()
    r = sh.scan("Lovely music and warm costumes. Great pacing overall.", info)
    assert not any(s.blurred for s in r.segments) and not r.warn
    off = sh.scan("The tower collapses and Mara dies.", info, use_sem=False)
    assert not any("late in the film" in x for s in off.segments for x in s.reasons)


def test_a_failing_semantic_layer_never_breaks_the_scan():
    sh, info = _shield_with_semantic()
    sh.sem.embed = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    r = sh.scan("Great score. Tobin betrays her and Mara dies in the tower.", info)
    assert r.segments and sh.status()["semantic"] is True


def test_missing_or_damaged_files_mean_the_layer_is_off(tmp_path):
    assert SemanticMatcher.load(str(tmp_path)) is None
    d = tmp_path / "semantic"; d.mkdir()
    (d / "model.onnx").write_bytes(b"not a model"); (d / "tokenizer.json").write_text("{}")
    assert SemanticMatcher.load(str(tmp_path)) is None


MODEL_DIR = os.environ.get("MODEL_DIR", "models")


@pytest.mark.skipif(not os.path.exists(os.path.join(MODEL_DIR, "semantic", "model.onnx")), reason="semantic encoder not installed")
def test_the_real_encoder_understands_paraphrases():
    m = SemanticMatcher.load(MODEL_DIR)
    assert m is not None and m.thr_warn < m.thr_blur
    v = m.embed(["Jack dies of hypothermia in the freezing water", "the guy on the poster does not survive the cold sea", "the pizza was cheap and tasty"])
    assert np.allclose(np.linalg.norm(v, axis=1), 1, atol=1e-3)
    assert v[0] @ v[1] > v[0] @ v[2] + 0.2


def test_an_outright_fate_statement_in_a_short_review_goes_to_a_moderator_even_when_the_model_is_calm():
    sh, info = _shield_with_semantic(thr_blur=0.99, thr_warn=0.99)          # semantic layer out of reach: only the new rule can act
    r = sh.scan("Mara was dead the whole time.", info)
    assert r.uncertain and not any(s.blurred for s in r.segments)            # a moderator looks; nothing is hidden
    assert any("outright" in x for s in r.segments for x in s.reasons)
    for clean in ("Mara is really good in this.", "The actor playing Mara killed it.", "The ending is devastating, Mara is great."):
        assert not sh.scan(clean, info).uncertain, clean
    assert not sh.scan("The cook dies.", info).uncertain                     # no character or actor name: not enough
    padding = " ".join(f"Point {i} about the lovely costumes and music." for i in range(8))
    assert not sh.scan(padding + " Mara was dead the whole time.", info).uncertain   # long reviews are left to the trained model
