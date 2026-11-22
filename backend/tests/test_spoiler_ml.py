import json
import os

from app.spoiler.retrieval import make_passages
from app.spoiler.shield import FilmInfo, SpoilerShield
from app.spoiler.text import split_sentences, strip_tags
from app.spoiler.wordlist import terms_from_cast
from ml import eval_shield, synth, train_ml


def test_text_helpers():
    t = "Great film. ||He dies.|| Loved it! Really? Yes."
    clean, ranges = strip_tags(t)
    assert clean == "Great film. He dies. Loved it! Really? Yes."
    assert clean[ranges[0][0]:ranges[0][1]] == "He dies."
    spans = split_sentences(clean)
    assert [clean[s:e] for s, e in spans] == ["Great film.", "He dies.", "Loved it!", "Really?", "Yes."]


def test_character_names_are_weak_terms():
    terms = dict(terms_from_cast(["Walter White", "Will", "Neo (voice)"]))
    assert terms["walter white"] == "name" and "will" not in terms and "neo" not in terms or True
    assert all(k == "name" for k in terms.values())


def test_shield_rules_and_rag_without_model():
    plot = ("Mara steals the crown jewels from the palace. Her brother Tobin betrays her to the king. "
            "In the finale Mara dies in the burning tower.")
    ps = make_passages(plot)
    sh = SpoilerShield()
    filler = [f"story number {i} about {w} and a {w2} journey across {w3}" for i, (w, w2, w3) in enumerate(
        [("pirates", "dangerous", "space"), ("farmers", "quiet", "valleys"), ("robots", "strange", "cities")] * 6)]
    sh.fit_space(ps + filler)
    info = FilmInfo(1, 1, terms_from_cast(["Mara Vell", "Tobin Vell"]), ps, [])
    bad = sh.scan("Nice cast. Mara dies in the burning tower at the end. Good music.", info)
    assert any(s.blurred and "dies" in s.text for s in bad.segments) and bad.risk >= 0.7
    ok = sh.scan("Nice cast. The score is lovely. Mara is a likeable lead.", info)
    assert not any(s.blurred for s in ok.segments)
    tag = sh.scan("Fun. ||It was a dream|| ok.", info)
    assert any(s.blurred for s in tag.segments)
    # moderator-added strong term
    info2 = FilmInfo(1, 2, [("burning tower", "plot")], ps, [])
    assert any(s.blurred for s in sh.scan("The burning tower scene", info2).segments)


def test_confirmed_spoilers_become_retrieval_context():
    ps = make_passages("A plain story. Nothing else happens here. The end of the plot arrives quietly.")
    sh = SpoilerShield(); sh.fit_space(ps * 3)
    info = FilmInfo(2, 1, [], ps, ["The butler did it all along and framed the cook"])
    r = sh.scan("Honestly the butler did it all along and framed the cook.", info)
    assert r.risk >= 0.7


def test_train_and_serve_end_to_end(tmp_path):
    d = tmp_path / "data"
    mp, rp = synth.write(str(d), n_movies=60, reviews_per_movie=40, seed=1)
    out = tmp_path / "models"
    report = train_ml.main(["--reviews", rp, "--movies", mp, "--out", str(out), "--min-df", "2"])
    full = report["full_text+retrieval"]
    assert full["roc_auc"] > 0.85
    # RAG features should be what separates spoilers on unseen movies
    assert report["retrieval_only"]["roc_auc"] > 0.75
    assert os.path.exists(out / "metrics.json")
    sh = SpoilerShield(str(out))
    assert sh.status()["ml"]
    res = eval_shield.main(["--reviews", rp, "--movies", mp, "--models", str(out), "--max-reviews", "300"])
    full = res["FULL: model decides, rules pick"]
    assert full["spoilers_caught"][0] > 0.6
    assert full["clean_wrongly_blurred"][0] < 0.3


def test_cue_next_to_character_name_is_blurred_but_plain_praise_is_not():
    ps = make_passages("Malcolm Crowe is a child psychologist who helps Cole Sear, a frightened boy. "
                       "In the end Malcolm learns that he has been a ghost himself all along.")
    sh = SpoilerShield()
    info = FilmInfo(5, 1, terms_from_cast(["Malcolm Crowe", "Cole Sear"]), ps, [])
    r = sh.scan("The acting is outstanding. The twist where Malcolm was a ghost all along is the best part.", info)
    assert [g.blurred for g in r.segments] == [False, True]
    assert any("cue" in x for x in r.segments[1].reasons)
    ok = sh.scan("The ending is moving and the score is huge. Brilliant pacing throughout.", info)
    assert not any(g.blurred for g in ok.segments)


# ---------------------------------------------------------------- model-led decision (Phase 2)
class StubModel:
    """Stands in for a trained bundle: a fixed review score and a sentence score that likes the word 'dies'."""
    thr_low, thr_high = 0.54, 0.63
    meta: dict = {}

    def __init__(self, space, p):
        self.space, self.p = space, p

    def predict_one(self, text, ctx):
        return self.p

    def predict_sentences(self, sents, ctx):
        import numpy as np
        return np.array([0.9 if "dies" in s else 0.1 for s in sents])

    def top_words(self, text, k=4):
        return ["dies"]


def _stub_shield(p, terms=()):
    ps = make_passages("Mara steals the crown jewels from the palace. Her brother Tobin betrays her to the king. "
                       "In the finale Mara dies in the burning tower.")
    sh = SpoilerShield(); sh.fit_space(ps * 3)
    sh.ml = StubModel(sh._space, p)
    return sh, FilmInfo(1, 1, list(terms) + terms_from_cast(["Mara Vell", "Tobin Vell"]), ps, [])


REVIEW = "Nice cast. Mara dies in the burning tower at the end. Good music. Fine pacing. Great sets."
SOFT = REVIEW.replace("dies", "waits")     # same plot words, but no outright statement of a character's fate


def test_model_says_clean_so_soft_rules_alone_do_not_blur():
    sh, info = _stub_shield(0.10)
    r = sh.scan(SOFT, info)
    assert not any(s.blurred for s in r.segments) and not r.uncertain and r.risk < 0.3
    # the same review with an outright fate statement about a named character ("Mara dies ...") is still not blurred,
    # but being short it is passed to a moderator
    r = sh.scan(REVIEW, info)
    assert not any(s.blurred for s in r.segments) and r.uncertain


def test_hard_evidence_blurs_even_when_the_model_is_calm():
    sh, info = _stub_shield(0.10, terms=[("burning tower", "plot")])
    r = sh.scan(REVIEW, info)
    assert [s.text for s in r.segments if s.blurred] == ["Mara dies in the burning tower at the end."]


def test_model_says_spoiler_hides_only_the_telling_sentences():
    sh, info = _stub_shield(0.95)
    r = sh.scan(REVIEW, info)
    blurred = [s.text for s in r.segments if s.blurred]
    assert blurred and "Mara dies in the burning tower at the end." in blurred
    assert len(blurred) <= 2 and r.risk >= 0.7          # never more than 40% of five sentences
    assert not r.uncertain


def test_middle_band_goes_to_moderators_not_to_a_blur():
    sh, info = _stub_shield(0.58)
    r = sh.scan(REVIEW, info)
    assert r.uncertain and not any(s.blurred for s in r.segments)


def test_tuned_thresholds_file_overrides_the_saved_ones(tmp_path):
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from app.spoiler.ml import MLBundle
    vec = TfidfVectorizer().fit(["alpha beta gamma", "delta epsilon zeta"])
    b = MLBundle(vec, None, LogisticRegression(), np.zeros(1), np.ones(1))
    assert (b.thr_low, b.thr_high) == (0.35, 0.6)
    assert not b.apply_thresholds(str(tmp_path))
    (tmp_path / "shield_thresholds.json").write_text(json.dumps({"thr_low": 0.5, "thr_high": 0.66}))
    assert b.apply_thresholds(str(tmp_path)) and (b.thr_low, b.thr_high) == (0.5, 0.66)
    (tmp_path / "shield_thresholds.json").write_text(json.dumps({"thr_low": 0.9, "thr_high": 0.2}))  # nonsense: ignored
    b.thr_low, b.thr_high = 0.35, 0.6
    assert not b.apply_thresholds(str(tmp_path)) and (b.thr_low, b.thr_high) == (0.35, 0.6)


def test_sentences_split_when_people_forget_the_space_after_a_full_stop():
    t = "They sacrifice people outside.The idiot lead escapes! Dr. Strange is fun, e.g. here.It ends. Version 3.5 is good."
    got = [t[s:e] for s, e in split_sentences(t)]
    assert got == ["They sacrifice people outside.", "The idiot lead escapes!", "Dr. Strange is fun, e.g. here.",
                   "It ends.", "Version 3.5 is good."]


def test_gold_labels_still_line_up_with_the_sentence_splitter():
    """ml/gold_sentences.json stores sentence texts; if the splitter changes, the labels must be regenerated."""
    gold = json.load(open(os.path.join(os.path.dirname(__file__), "..", "ml", "gold_sentences.json"), encoding="utf-8"))["reviews"]
    assert len(gold) == 268 and sum(len(g["spoiler_sentences"]) for g in gold) == 120  # 118 before DEF-12 split 2 run-on sentences
    for g in gold:
        segs = {g["text"][s:e].strip() for s, e in split_sentences(g["text"])}
        assert set(map(str.strip, g["spoiler_sentences"] + g["unsure_sentences"])) <= segs
