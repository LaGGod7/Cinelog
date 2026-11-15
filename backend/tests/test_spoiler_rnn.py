"""The recurrent (BiGRU + attention) layer: numpy serving matches PyTorch, blending, tuned thresholds, safe loading, shield wiring."""
import json

import numpy as np
import pytest

from app.spoiler.retrieval import REVIEW_FEATS
from app.spoiler.rnn import META_FILE, VOCAB_FILE, WEIGHTS_FILE, RNNScorer, tokenize
from tests.test_spoiler_ml import REVIEW, SOFT, _stub_shield

ND = len(REVIEW_FEATS)


def _random_scorer(seed=0, V=40, D=8, H=6, **meta):
    r = np.random.RandomState(seed)
    g = lambda *s: (r.randn(*s) * 0.3).astype(np.float32)  # noqa: E731
    w = {"emb": g(V, D), "att_w": g(2 * H, 2 * H), "att_b": g(2 * H), "att_v": g(2 * H),
         "fc1_w": g(8, 4 * H + ND), "fc1_b": g(8), "fc2_w": g(1, 8), "fc2_b": g(1),
         "dense_mean": np.zeros(ND, np.float32), "dense_std": np.ones(ND, np.float32)}
    for d in ("f", "b"):
        w.update({f"w_ih_{d}": g(3 * H, D), f"w_hh_{d}": g(3 * H, H), f"b_ih_{d}": g(3 * H), f"b_hh_{d}": g(3 * H)})
    vocab = {"<pad>": 0, "<unk>": 1, **{w_: i + 2 for i, w_ in enumerate(["mara", "dies", "the", "tower", "twist", "ending", "great"])}}
    return RNNScorer(w, vocab, {"max_len": 30, **meta}), w, vocab


def test_tokenizer_keeps_contractions_and_exclamations():
    assert tokenize("It's a TWIST! Really?") == ["it's", "a", "twist", "!", "really", "?"]


def test_numpy_server_matches_pytorch():
    torch = pytest.importorskip("torch")
    from ml.train_rnn import make_net, pad
    V, H = 40, 6
    emb = np.random.RandomState(1).randn(V, 100).astype(np.float32)
    net = make_net(V, 100, H, ND, emb)
    net.eval()
    sd = {k: v.detach().numpy() for k, v in net.state_dict().items()}
    weights = {"emb": sd["emb.weight"],
               "w_ih_f": sd["gru.weight_ih_l0"], "w_hh_f": sd["gru.weight_hh_l0"], "b_ih_f": sd["gru.bias_ih_l0"], "b_hh_f": sd["gru.bias_hh_l0"],
               "w_ih_b": sd["gru.weight_ih_l0_reverse"], "w_hh_b": sd["gru.weight_hh_l0_reverse"],
               "b_ih_b": sd["gru.bias_ih_l0_reverse"], "b_hh_b": sd["gru.bias_hh_l0_reverse"],
               "att_w": sd["att.weight"], "att_b": sd["att.bias"], "att_v": sd["att_v.weight"].reshape(-1),
               "fc1_w": sd["fc1.weight"], "fc1_b": sd["fc1.bias"], "fc2_w": sd["fc2.weight"], "fc2_b": sd["fc2.bias"],
               "dense_mean": np.zeros(ND, np.float32), "dense_std": np.ones(ND, np.float32)}
    words = ["mara", "dies", "the", "tower", "twist", "ending", "great", "film", "plot"]
    vocab = {"<pad>": 0, "<unk>": 1, **{w: i + 2 for i, w in enumerate(words)}}
    scorer = RNNScorer(weights, vocab, {"max_len": 12})
    texts = ["mara dies", "the twist ending is great!", "great film the tower plot mara dies in the tower the twist ending",
             "unknown words only xyzzy"]
    dense = np.random.RandomState(2).randn(len(texts), ND).astype(np.float32)
    ids, _, _ = scorer.encode(texts)
    seqs = [[int(x) for x in row if x != 0] for row in ids]
    ids_t, lens = pad(seqs, list(range(len(texts))))
    with torch.no_grad():
        ref = torch.sigmoid(net(ids_t, lens, torch.from_numpy(dense))).numpy()
    got = scorer.predict(texts, dense)
    assert np.abs(got - ref).max() < 1e-4


def test_padding_does_not_change_a_score():
    s, _, _ = _random_scorer()
    d = np.random.RandomState(3).randn(2, ND).astype(np.float32)
    alone = s.predict(["mara dies in the tower"], d[:1])[0]
    together = s.predict(["mara dies in the tower", "great ending " * 12], d)[0]
    assert abs(alone - together) < 1e-5


def test_fuse_is_a_logit_average():
    s, _, _ = _random_scorer(fusion_weight=0.0)
    ml, rn = np.array([0.2, 0.9]), np.array([0.8, 0.4])
    assert np.allclose(s.fuse(ml, rn), ml, atol=1e-6)
    s.weight = 1.0
    assert np.allclose(s.fuse(ml, rn), rn, atol=1e-6)
    s.weight = 0.5
    f = s.fuse(ml, rn)
    assert (f > np.minimum(ml, rn) - 1e-9).all() and (f < np.maximum(ml, rn) + 1e-9).all()
    assert f[0] == pytest.approx(0.5, abs=1e-6)      # logit(0.2) = -logit(0.8)


def test_attention_words_skip_function_words():
    s, _, _ = _random_scorer()
    words = s.attention_words("the tower and the twist ending", np.zeros(ND), 3)
    assert 1 <= len(words) <= 3 and "the" not in words and "and" not in words


def test_files_round_trip_and_damage_is_tolerated(tmp_path):
    s, w, vocab = _random_scorer()
    assert RNNScorer.load(str(tmp_path)) is None                       # nothing there: inactive, not an error
    np.savez_compressed(tmp_path / WEIGHTS_FILE, **w)
    (tmp_path / VOCAB_FILE).write_text(json.dumps(vocab))
    (tmp_path / META_FILE).write_text(json.dumps({"max_len": 30, "fusion_weight": 0.4}))
    got = RNNScorer.load(str(tmp_path))
    d = np.zeros((1, ND), np.float32)
    assert got is not None and got.weight == 0.4
    assert got.predict(["mara dies"], d)[0] == pytest.approx(s.predict(["mara dies"], d)[0], abs=1e-6)
    (tmp_path / WEIGHTS_FILE).write_bytes(b"this is not an npz file")
    assert RNNScorer.load(str(tmp_path)) is None                       # damaged: the site still starts
    (tmp_path / WEIGHTS_FILE).write_bytes(b"")
    assert RNNScorer.load(str(tmp_path)) is None


def test_tuned_fused_thresholds_are_read_and_nonsense_is_ignored(tmp_path):
    s, _, _ = _random_scorer(fused_thr_low=0.4, fused_thr_high=0.6)
    assert not s.apply_thresholds(str(tmp_path))
    (tmp_path / "shield_thresholds.json").write_text(json.dumps({"thr_low": 0.5, "thr_high": 0.6}))   # ML-only file: no fused part
    assert not s.apply_thresholds(str(tmp_path))
    (tmp_path / "shield_thresholds.json").write_text(json.dumps({"fused": {"thr_low": 0.52, "thr_high": 0.59, "rnn_weight": 0.3}}))
    assert s.apply_thresholds(str(tmp_path)) and (s.thr_low, s.thr_high, s.weight) == (0.52, 0.59, 0.3)
    (tmp_path / "shield_thresholds.json").write_text(json.dumps({"fused": {"thr_low": 0.9, "thr_high": 0.2, "rnn_weight": 0.3}}))
    s.thr_low, s.thr_high, s.weight = 0.4, 0.6, 0.5
    assert not s.apply_thresholds(str(tmp_path)) and (s.thr_low, s.thr_high, s.weight) == (0.4, 0.6, 0.5)


def _with_rnn(p_ml, p_rnn, weight=0.5, thr=(0.4, 0.6)):
    sh, info = _stub_shield(p_ml)
    s, _, _ = _random_scorer(fusion_weight=weight, fused_thr_low=thr[0], fused_thr_high=thr[1])
    s.tuned = True
    s.predict = lambda texts, dense, batch=64: np.full(len(texts), p_rnn)       # a fixed opinion; the maths is tested above
    sh.rnn = s
    return sh, info


def test_shield_uses_the_blend_and_its_own_thresholds():
    sh, info = _with_rnn(0.66, 0.66, thr=(0.5, 0.75))     # 0.66 is above the ML-only blur line (0.63) but inside the blend's band
    ml_only = sh.scan(REVIEW, info, use_rnn=False)
    assert any(s.blurred for s in ml_only.segments) and ml_only.model == "rules+rag+ml"
    blended = sh.scan(REVIEW, info)
    assert blended.model == "rules+rag+ml+rnn"
    assert blended.uncertain and not any(s.blurred for s in blended.segments)


def test_rnn_can_raise_a_borderline_review_to_a_blur():
    sh, info = _with_rnn(0.50, 0.95)
    assert not any(s.blurred for s in sh.scan(REVIEW, info, use_rnn=False).segments)
    r = sh.scan(REVIEW, info)
    assert any(s.blurred for s in r.segments) and r.risk >= 0.7


def test_rnn_cannot_blur_a_review_when_both_models_are_calm():
    sh, info = _with_rnn(0.10, 0.10)
    r = sh.scan(SOFT, info)
    assert not any(s.blurred for s in r.segments) and not r.uncertain
    assert not any(s.blurred for s in sh.scan(REVIEW, info).segments)


def test_weight_zero_means_ml_only():
    sh, info = _with_rnn(0.50, 0.99, weight=0.0)
    r = sh.scan(REVIEW, info)
    assert not any(s.blurred for s in r.segments)


def test_a_failing_rnn_falls_back_to_ml():
    sh, info = _with_rnn(0.95, 0.5)
    sh.rnn.predict = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    r = sh.scan(REVIEW, info)
    assert any(s.blurred for s in r.segments)          # the ML verdict (0.95) still stands


def test_status_reports_the_rnn(tmp_path):
    sh, _ = _stub_shield(0.5)
    assert sh.status()["rnn"] is False
    s, _, _ = _random_scorer(test={"rnn": {"roc_auc": 0.72}, "tfidf_ml": {"roc_auc": 0.75}, "blend": {"roc_auc": 0.76}})
    sh.rnn = s
    st = sh.status()
    assert st["rnn"] is True and st["rnn_meta"]["auc"]["blend"] == 0.76 and st["rnn_meta"]["weight"] == 0.5


def test_an_untuned_rnn_is_loaded_but_not_used():
    sh, info = _with_rnn(0.50, 0.95)
    sh.rnn.tuned = False                       # trained, but tune_shield has not measured it with the deployed ML yet
    assert not any(s.blurred for s in sh.scan(REVIEW, info).segments)
    st = sh.status()
    assert st["rnn"] is True and st["rnn_meta"]["tuned"] is False and st["rnn_meta"]["active"] is False


# ---- giveaway cue + plot restatement (hard evidence) and the made-up-review test script
def _calm_shield_with_rare_plot_words():
    """A film whose plot has words that are rare in the corpus (so 'rare overlap' can count), and a model that is calm (p = 0.05)."""
    from app.spoiler.retrieval import make_passages
    from app.spoiler.shield import FilmInfo, SpoilerShield
    from app.spoiler.wordlist import terms_from_cast
    from tests.test_spoiler_ml import StubModel
    ps = make_passages("Mara steals the crown jewels from the palace. Her brother Tobin betrays her to the king. "
                       "In the finale Mara dies in the burning tower.")
    filler = [f"story number {i} about {w} and a {w2} journey across {w3}" for i, (w, w2, w3) in enumerate(
        [("pirates", "dangerous", "space"), ("farmers", "quiet", "valleys"), ("robots", "strange", "cities")] * 6)]
    sh = SpoilerShield()
    sh.fit_space(ps + filler)
    sh.ml = StubModel(sh._space, 0.05)
    return sh, FilmInfo(1, 1, terms_from_cast(["Mara Vell", "Tobin Vell"]), ps, [])


def test_cue_in_a_plot_restating_sentence_blurs_even_when_the_model_is_calm():
    sh, info = _calm_shield_with_rare_plot_words()
    r = sh.scan("Great cast. In the finale Mara dies in the burning tower. Lovely score.", info)
    hit = [s for s in r.segments if s.blurred]
    assert hit and "dies" in hit[0].text and any("restates the film's plot" in x for x in hit[0].reasons)


def test_plot_recap_without_a_giveaway_word_or_a_giveaway_word_without_plot_is_left_alone():
    sh, info = _calm_shield_with_rare_plot_words()
    recap = sh.scan("Great cast. Mara steals the crown jewels from the palace in the first act. Lovely score.", info)
    assert not any(s.blurred for s in recap.segments)
    unrelated = sh.scan("Great cast. The hero dies of laughter during the second act jokes. Lovely score.", info)
    assert not any(s.blurred for s in unrelated.segments)


def test_seed_spoiler_test_script_runs_and_leaks_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'demo.db'}")
    monkeypatch.setenv("MODEL_DIR", str(tmp_path / "no_models"))
    from scripts import seed_spoiler_test as t
    assert t.main([]) == 0
    out = capsys.readouterr().out
    assert "blurred text visible to a stranger: 0" in out and "clean reviews left alone" in out
    assert t.main(["--clean"]) == 0


# ---- the 'possible spoilers' label (recall-targeted cut-off)
def test_warn_label_is_given_between_the_recall_cutoff_and_the_moderator_band():
    sh, info = _stub_shield(0.45)                    # ML band is 0.54 .. 0.63; 0.45 is below it
    assert not sh.scan(SOFT, info).warn            # no cut-off configured: nothing happens
    sh.warn_thr = {"ml": 0.40, "fused": None}
    r = sh.scan(SOFT, info)
    assert r.warn and not r.uncertain and not any(s.blurred for s in r.segments)
    sh.warn_thr = {"ml": 0.50, "fused": None}
    assert not sh.scan(SOFT, info).warn            # review scores below this cut-off
    sh2, info2 = _stub_shield(0.95)
    sh2.warn_thr = {"ml": 0.40, "fused": None}
    r2 = sh2.scan(REVIEW, info2)
    assert any(s.blurred for s in r2.segments) and not r2.warn     # blurred reviews carry no extra label


def test_warn_thresholds_are_read_from_the_tuned_file_and_garbage_is_ignored(tmp_path):
    from app.spoiler.shield import SpoilerShield
    assert SpoilerShield._read_warn_thresholds(str(tmp_path)) == {"ml": None, "fused": None}
    (tmp_path / "shield_thresholds.json").write_text(json.dumps({"thr_warn": 0.39, "fused": {"thr_warn": 0.41}}))
    assert SpoilerShield._read_warn_thresholds(str(tmp_path)) == {"ml": 0.39, "fused": 0.41}
    (tmp_path / "shield_thresholds.json").write_text(json.dumps({"thr_warn": 7, "fused": "oops"}))
    assert SpoilerShield._read_warn_thresholds(str(tmp_path)) == {"ml": None, "fused": None}
    (tmp_path / "shield_thresholds.json").write_text("not json")
    assert SpoilerShield._read_warn_thresholds(str(tmp_path)) == {"ml": None, "fused": None}


def test_warn_label_reaches_readers_and_old_databases_are_migrated(tmp_path):
    import datetime as dt
    from sqlalchemy import create_engine, inspect, text
    from app.migrations import migrate
    eng = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.begin() as c:                          # a database from before this release: reviews without the column
        c.execute(text("CREATE TABLE reviews (id INTEGER PRIMARY KEY, uncertain BOOLEAN)"))
        c.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
    migrate(eng)
    assert "warn" in {col["name"] for col in inspect(eng).get_columns("reviews")}
    assert migrate(eng) == []                       # idempotent
    from app.models import Review, User
    from app.services.reviews import review_view
    u = User(id=1, email="a@b.c", display_name="A", password_hash="x")
    r = Review(id=1, user_id=1, film_id=1, text="t", state="published", warn=True, segments_json='[{"idx":0,"text":"fine.","blurred":false,"risk":0.1,"reasons":[]}]',
               created_at=dt.datetime(2026, 1, 1))
    r.author = u
    assert review_view(r, None)["warn"] is True
    r.segments_json = '[{"idx":0,"text":"secret.","blurred":true,"risk":0.9,"reasons":[]}]'
    assert review_view(r, None)["warn"] is False     # a blurred review already warns by blurring
