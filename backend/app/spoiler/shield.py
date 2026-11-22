"""Spoiler Shield: Aho-Corasick word lists + RAG retrieval + trained ML (+ optional DL), fused per sentence."""
from __future__ import annotations

import logging
import json
import math
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

from ..dsa.lru import LRUCache
from .dl import DLScorer
from .ml import MLBundle, calibrate
from .retrieval import FilmCtx, RetrievalSpace
from .rnn import RNNScorer
from .semantic import SemanticMatcher
from .text import normalize_text, split_sentences, strip_tags
from .wordlist import AutomatonCache, TermT

log = logging.getLogger("cinelog.shield")

BLUR, ASK = 0.7, 0.3
# Which sentences to hide once a review is blurred - chosen on 118 hand-labelled spoiler sentences (ml/gold_sentences.json):
# the model's sentence score ranks them best (AUC 0.87 vs 0.74 for the rules); the rules only break ties (weight 0.2).
MAX_BLUR_FRAC = 0.3   # a blurred review never hides more than this share of its sentences (at least one)
REL_TOP = 0.5         # ...and only sentences scoring at least this fraction of the review's best sentence
RULE_WEIGHT = 0.2

# Phrases reviewers use when they are about to give away what happens. Alone they mean little ("no twist here"), but a cue
# next to a character name or a plot-specific word is a strong signal - this works without any trained model.
CUES = re.compile(r"\b(twist|ending|turns? out|reveals?|revealed|dies|died|dead|killed|kills|murder(?:s|ed)?|all along|"
                  r"in the end|at the end|final scene|last scene|finale|betray(?:s|ed|al)?|sacrific(?:e|es|ed)|"
                  r"the culprit|real identity|it was all)\b", re.I)

# A character's fate or true identity stated outright ("X dies", "X was dead the whole time", "X is actually Y"). Narrower than
# CUES on purpose: "the ending is devastating" must not match. In a SHORT review (the kind written on this site) a sentence that
# pairs one of these with a character or actor name is sent to a moderator even when the trained model is calm: the model was
# trained on long IMDB reviews and scores one-line giveaways low. Measured on 2,272 real reviews of films the models never saw
# (short ones, not already flagged): it touched 1 clean review and no spoiler review, so it costs moderators almost nothing there;
# what it buys is on short written-for-the-site reviews (see logs/adversarial.txt). It never blurs on its own.
REVEAL = re.compile(r"\b(?:(?:dies|died(?! in (?:19|20)\d\d)|(?:is|was|are|were) dead|(?:is|was|gets|got|are|were) (?:killed|murdered)|(?:gets|got) shot|shot dead|"
                    r"kills(?! it\b)|killed(?! it\b)|murders|murdered|commits? suicide|(?:kills?|killed) (?:him|her|them)sel(?:f|ves)|"
                    r"turns? out|turned out|all along|the whole time|(?:is|was) revealed|reveals? that|"
                    r"(?:isn't|is not|wasn't|was not) (?:even )?real|the same person|"
                    r"(?:is|was) (?:the|a) (?:killer|murderer|traitor|villain|ghost|mole|culprit)|sacrific(?:es|ed) (?:him|her)self)\b|"
                    # "X is actually Y" / "X was really the ...": only before a name or "the/his/her", so "is really good" does not count
                    r"(?:is|was) (?:actually|really|secretly) (?:(?:the|his|her)\b|(?-i:[A-Z])))", re.I)
SHORT_REVIEW = 6      # sentences; same notion of "short" as ml.calibrate_semantic

# giveaway cue + plot restatement = hard evidence; measured on held-out IMDB films (see README, Spoiler Shield)
CUE_PLOT_COS = 0.35
CUE_PLOT_RARE = 2


@dataclass
class FilmInfo:
    film_id: int
    version: int
    terms: List[TermT] = field(default_factory=list)
    plot_passages: List[str] = field(default_factory=list)
    spoiler_passages: List[str] = field(default_factory=list)


@dataclass
class Segment:
    idx: int
    start: int
    end: int
    text: str
    blurred: bool
    risk: float
    reasons: List[str]

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class ScanResult:
    clean_text: str
    segments: List[Segment]
    risk: float
    uncertain: bool
    p_ml: Optional[float] = None
    model: str = "rules"
    warn: bool = False      # not blurred, not for moderators, but scored above the recall-targeted cut-off: readers see a 'possible spoilers' label


def _or(*ps: float) -> float:
    q = 1.0
    for p in ps:
        q *= 1 - min(max(p, 0.0), 1.0)
    return 1 - q


class SpoilerShield:
    def __init__(self, model_dir: Optional[str] = None, use_dl: bool = False) -> None:
        self.use_dl = use_dl
        self.ml: Optional[MLBundle] = None
        self.dl: Optional[DLScorer] = None
        self.rnn: Optional[RNNScorer] = None
        self.sem: Optional[SemanticMatcher] = None
        self.sem_cache: LRUCache = LRUCache(64)
        self.warn_thr: Dict[str, Optional[float]] = {"ml": None, "fused": None}
        self._space = RetrievalSpace()
        self._space_lock = threading.Lock()
        self.automata = AutomatonCache(128)
        self.ctx_cache: LRUCache = LRUCache(256)
        self.model_dir = model_dir
        if model_dir:
            self.reload(model_dir)

    # ---------------------------------------------------------------- model management
    def reload(self, model_dir: Optional[str] = None) -> Dict[str, bool]:
        d = model_dir or self.model_dir
        self.ml = MLBundle.load(d) if d else None
        self.dl = DLScorer.load(d) if (d and self.use_dl) else None
        self.rnn = RNNScorer.load(d) if (d and self.ml is not None) else None  # the RNN adds to the ML model, never replaces it
        self.sem = SemanticMatcher.load(d) if d else None
        self.sem_cache = LRUCache(64)
        self.warn_thr = self._read_warn_thresholds(d)
        self.ctx_cache = LRUCache(256)
        return self.status()

    @staticmethod
    def _read_warn_thresholds(d: Optional[str]) -> Dict[str, Optional[float]]:
        """'thr_warn' (from ml.tune_shield --recall): reviews scoring above it get a reader-visible label, never a blur."""
        out: Dict[str, Optional[float]] = {"ml": None, "fused": None}
        try:
            with open(os.path.join(d or "", "shield_thresholds.json"), encoding="utf-8") as fh:
                t = json.load(fh)
            for k, src in (("ml", t), ("fused", t.get("fused") or {})):
                v = src.get("thr_warn")
                if v is not None and 0 < float(v) < 1:
                    out[k] = float(v)
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return out

    def status(self) -> Dict[str, object]:
        rnn_test = (self.rnn.meta.get("test") or {}) if self.rnn else {}
        dep = (self.rnn.meta.get("deployed") or {}) if self.rnn else {}
        return {"ml": self.ml is not None, "dl": self.dl is not None, "rnn": self.rnn is not None, "semantic": self.sem is not None, "warn_thresholds": self.warn_thr,
                "caches": {"automata": self.automata.cache.stats(), "plot_tfidf": self.ctx_cache.stats(), "plot_embeddings": self.sem_cache.stats()},
                "ml_meta": (self.ml.meta if self.ml else {}), "space_fitted": self.space.fitted,
                "rnn_meta": ({"weight": self.rnn.weight, "tuned": self.rnn.tuned, "active": self.rnn.tuned and self.rnn.weight > 0,
                              "auc": dep.get("auc") or {"ml_only": (rnn_test.get("tfidf_ml") or {}).get("roc_auc"),
                                                        "rnn_only": (rnn_test.get("rnn") or {}).get("roc_auc"),
                                                        "blend": (rnn_test.get("blend") or {}).get("roc_auc")},
                              "auc_gain_95ci": dep.get("gain_95ci")} if self.rnn else {})}

    @property
    def space(self) -> RetrievalSpace:
        return self.ml.space if self.ml else self._space

    def fit_space(self, passages: Sequence[str]) -> None:
        """Fit the hashed idf table on our own plot corpus (used when no trained bundle is shipped)."""
        with self._space_lock:
            self._space = RetrievalSpace().fit(passages)
            self.ctx_cache = LRUCache(256)

    # ---------------------------------------------------------------- scanning
    def _ctx(self, info: FilmInfo) -> FilmCtx:
        sp = self.space
        if not sp.fitted:
            self.fit_space(info.plot_passages or ["placeholder context"])
            sp = self.space
        key = (info.film_id, info.version, id(sp))
        ctx = self.ctx_cache.get(key)
        if ctx is None:
            ctx = sp.film_ctx(info.plot_passages, info.spoiler_passages)
            self.ctx_cache.put(key, ctx)
        return ctx

    def scan(self, raw_text: str, info: FilmInfo, use_ml: bool = True, *, rag: bool = True, cue: bool = True,
             gate: bool = True, force_blur: bool = False, use_rnn: bool = True, use_sem: bool = True) -> ScanResult:
        """rag/cue switch the plot-matching and cue layers off (used by the ablation study). With gate=True and a trained
        model, soft rule hits (plot similarity, rare words, cues) only count when the model also finds the review risky;
        hard hits (writer tags, plot-term list, moderator-confirmed spoilers) always count.
        force_blur=True skips the review-level decision (pretends the model said 'spoiler') so that sentence selection
        can be evaluated on its own."""
        ml_model = self.ml if use_ml else None
        dl_model = self.dl if use_ml else None
        rnn_model = self.rnn if (use_ml and use_rnn and self.ml is not None and self.rnn is not None and self.rnn.tuned and self.rnn.weight > 0) else None  # untuned = not measured with the deployed ML yet; weight 0 = tuning found no gain
        text, tagged = strip_tags(normalize_text(raw_text))
        spans = split_sentences(text)
        sents = [text[s:e] for s, e in spans]
        n = len(sents)
        if n == 0:
            return ScanResult(text, [], 0.0, False)
        ctx = self._ctx(info)
        sp = self.space

        # --- rules: writer tags + Aho-Corasick word list (one pass over the review)
        rule = [0.0] * n
        reasons: List[List[str]] = [[] for _ in range(n)]
        strong = [False] * n
        hard = [False] * n
        ac = self.automata.get(info.film_id, info.version, info.terms)
        hits = ac.search(text)
        names_seen: List[set] = [set() for _ in range(n)]
        for (hs, _he, term, kind) in hits:
            i = next((j for j, (s, e) in enumerate(spans) if s <= hs < e), None)
            if i is None:
                continue
            if kind == "plot":
                rule[i] = _or(rule[i], 0.9); strong[i] = True; hard[i] = True
                reasons[i].append(f"spoiler term '{term}'")
            else:
                if term not in names_seen[i]:
                    names_seen[i].add(term)
                    rule[i] = min(0.4, _or(rule[i], 0.12))
        for i in range(n):
            if names_seen[i]:
                reasons[i].append("mentions character name(s): " + ", ".join(sorted(names_seen[i])[:3]))
        for (ts, te) in tagged:
            for i, (s, e) in enumerate(spans):
                if s < te and ts < e:
                    rule[i] = 1.0; strong[i] = True; hard[i] = True
                    if "writer spoiler tag" not in reasons[i]:
                        reasons[i].append("writer spoiler tag")

        # --- RAG: closeness to this film's plot / previously confirmed spoilers
        feats = sp.sentence_features(sents, ctx)
        for i in range(n):
            max_plot, _t3, max_sp, rare, _rf = feats[i]
            cos_c = min(max(((max_plot - 0.2) / 0.3), 0.0), 1.0) * 0.85 if rag else 0.0
            rare_c = min(0.45, 0.15 * rare) if rag else 0.0
            sp_c = min(max(((max_sp - 0.3) / 0.3), 0.0), 1.0) * 0.95
            if cos_c > 0.05:
                reasons[i].append(f"closely matches the film's plot (similarity {max_plot:.2f})")
            if sp_c > 0.05:
                reasons[i].append("similar to a moderator-confirmed spoiler")
            if rare >= 2:
                reasons[i].append(f"shares {int(rare)} rare plot terms")
            cue_m = CUES.search(sents[i]) if cue else None
            if cue_m and (names_seen[i] or rare >= 1 or cos_c > 0.05):
                rule[i] = _or(rule[i], 0.75)
                strong[i] = True
                reasons[i].append(f"spoiler cue '{cue_m.group(0).lower()}' next to plot details")
            if cue_m and rag and max_plot >= CUE_PLOT_COS and rare >= CUE_PLOT_RARE:
                # A giveaway word ("dies", "twist", "turns out") in a sentence that also restates the film's plot. On films the
                # models never saw, this pair was 3.9x more common in spoiler reviews than in clean ones (1.2% of clean reviews
                # versus 4.8% of spoilers), which neither the word counts nor the plot match shows alone, so it counts as hard evidence.
                rule[i] = _or(rule[i], 0.8)
                strong[i] = hard[i] = True
                reasons[i].append(f"'{cue_m.group(0).lower()}' in a sentence that restates the film's plot")
            rule[i] = _or(rule[i], cos_c, rare_c, sp_c)
            if cos_c >= BLUR or sp_c >= BLUR:
                strong[i] = True
            if sp_c >= BLUR:
                hard[i] = True
        # --- semantic plot match: a sentence that says what happens late in the film, in any words, is hard evidence
        sem_warn = False
        sem_model = self.sem if (use_sem and rag and info.plot_passages) else None
        if sem_model is not None:
            try:
                key = (info.film_id, info.version)
                plot_vec = self.sem_cache.get(key)
                if plot_vec is None:
                    plot_vec = sem_model.plot_matrix(info.plot_passages)
                    self.sem_cache.put(key, plot_vec)
                m = sem_model.scores(sents, plot_vec)
                # cut-offs rise with the number of sentences, so a long review is not blurred just for having more tries
                sem_blur_thr, sem_warn_thr = sem_model.blur_threshold(n), sem_model.warn_threshold(n)
                for i in range(n):
                    if m[i] >= sem_blur_thr:
                        rule[i] = _or(rule[i], 0.8)
                        strong[i] = hard[i] = True
                        reasons[i].append(f"means the same as something that happens late in the film's plot (semantic match {m[i]:.2f})")
                sem_warn = bool(len(m) and float(m.max()) >= sem_warn_thr)
            except Exception as exc:  # noqa: BLE001 - an add-on layer: never break the scan
                log.warning("semantic layer failed, continuing without it: %s", exc)
        rule_review = max(rule)
        # outright fate / identity statement about a named character (only consulted for short reviews, see REVEAL)
        reveal_hit = [bool(cue and names_seen[i] and REVEAL.search(sents[i])) for i in range(n)]

        # --- ML (+ optional DL), calibrated onto the same 0..1 risk scale
        p_ml = None
        p_warn: Optional[float] = None
        warn_thr: Optional[float] = None
        model_name = "rules+rag"
        ml_review = 0.0
        sent_ml = np.zeros(n)
        if ml_model is not None:
            lo, hi = ml_model.thr_low, ml_model.thr_high
            p = ml_model.predict_one(text, ctx)
            sent_p = ml_model.predict_sentences(sents, ctx)
            model_name = "rules+rag+ml"
            dense_r = None
            if rnn_model is not None:
                # the recurrent layer reads the words in order (GloVe-based, so paraphrases count too); both models vote
                # in log-odds space and the blend has its own thresholds, tuned with the ML model that is deployed
                try:
                    dense_r = self.space.review_features(text, ctx).reshape(1, -1)
                    dense_s = np.vstack([self.space.review_features(x, ctx) for x in sents])
                    p_f = float(rnn_model.fuse(np.array([p]), rnn_model.predict([text], dense_r))[0])
                    sent_f = rnn_model.fuse(np.asarray(sent_p), rnn_model.predict(sents, dense_s))
                    p, sent_p, (lo, hi) = p_f, sent_f, (rnn_model.thr_low, rnn_model.thr_high)
                    model_name = "rules+rag+ml+rnn"
                except Exception as exc:  # noqa: BLE001  - the RNN is an add-on; never break the scan
                    log.warning("RNN scorer failed, using ML only: %s", exc)
                    rnn_model = None
            p_ml = p
            p_warn, warn_thr = p, self.warn_thr["fused" if model_name.startswith("rules+rag+ml+rnn") else "ml"]
            ml_review = calibrate(p, lo, hi)
            sent_ml = np.array([calibrate(float(x), lo, hi) for x in sent_p])
            if dl_model is not None and info.plot_passages:
                try:
                    best = self._best_passages(sents, ctx, info)
                    p_dl = dl_model.score(sents, best)
                    d_sent = np.array([calibrate(float(x), dl_model.thr_low, dl_model.thr_high) for x in p_dl])
                    sent_ml = (sent_ml + d_sent) / 2
                    ml_review = (ml_review + float(d_sent.max())) / 2
                    model_name += "+dl"
                except Exception as exc:  # noqa: BLE001  - DL is optional; never break the scan
                    log.warning("DL scorer failed, using ML only: %s", exc)
            words = ml_model.top_words(text, 4)
            if rnn_model is not None and ml_review >= ASK:
                try:
                    words = list(dict.fromkeys(words[:2] + rnn_model.attention_words(text, dense_r, 3)))[:4]
                except Exception:  # noqa: BLE001  - explanation only
                    pass
            if words and ml_review >= ASK:
                note = f"model risk {p:.2f}; telling words: {', '.join(words)}"
                top_i = int(np.argmax(sent_ml)) if n else 0
                reasons[top_i].append(note)

        if ml_model is not None and gate:
            # --- model-led decision. Measured on films the model never saw: the plot-similarity / rare-word / cue rules
            # add no review-level information on top of the trained model (AUC 0.80 alone, 0.78 when fused), so they only
            # help choose WHICH sentences to hide. Hard evidence (writer tags, plot-term list, confirmed spoilers) still
            # forces a blur on its own.
            hard_review = max([rule[i] for i in range(n) if hard[i]] or [0.0])
            final = max(ml_review, hard_review)
            soft = [0.0 if hard[i] else rule[i] for i in range(n)]
            cand = [float(sent_ml[i]) + RULE_WEIGHT * soft[i] for i in range(n)]
            risk_i = [rule[i] if hard[i] else (min(cand[i], 1.0) if (final >= ASK or force_blur) else soft[i] * 0.3) for i in range(n)]
            blurred = [bool(hard[i] and rule[i] >= BLUR) for i in range(n)]
            if final >= BLUR or force_blur:
                room = max(1, math.ceil(MAX_BLUR_FRAC * n)) - sum(blurred)
                top = max(cand) if cand else 0.0
                for i in sorted((j for j in range(n) if not blurred[j]), key=lambda j: -cand[j]):
                    if room <= 0 or cand[i] < REL_TOP * top:
                        break
                    blurred[i] = True; room -= 1
                if not any(blurred):
                    blurred[int(np.argmax(cand))] = True
            if n <= SHORT_REVIEW and any(reveal_hit) and final < ASK and not any(blurred) and not force_blur:
                final = ASK + 0.1     # a moderator looks at it; nothing is hidden
                for i in range(n):
                    if reveal_hit[i]:
                        m_ = REVEAL.search(sents[i])
                        reasons[i].append(f"states a named character's fate or identity outright ('{m_.group(0).lower()}')")
                        risk_i[i] = max(risk_i[i], final)
            uncertain = ASK <= final < BLUR and not any(blurred) and not force_blur
        else:
            # --- no trained model (or ablation with gate=False): rules fused by noisy-OR
            final = _or(ml_review, rule_review) if ml_model is not None else rule_review
            on = 1.0 if final >= ASK else 0.0
            risk_i = [_or(rule[i], 0.9 * sent_ml[i] * on) for i in range(n)]
            blurred = [False] * n
            for i in range(n):
                if strong[i] and rule[i] >= BLUR:
                    blurred[i] = True
            if final >= BLUR:
                for i in range(n):
                    if risk_i[i] >= 0.5:
                        blurred[i] = True
                if not any(blurred):
                    blurred[int(np.argmax(risk_i))] = True
            uncertain = ASK <= final < BLUR and not any(blurred)

        segs = [Segment(i, s, e, text[s:e], blurred[i], round(float(risk_i[i]), 3), reasons[i])
                for i, (s, e) in enumerate(spans)]
        warn = bool(((warn_thr is not None and p_warn is not None and p_warn >= warn_thr) or sem_warn) and not uncertain and not any(blurred) and not force_blur)
        return ScanResult(text, segs, round(float(final), 3), uncertain, p_ml, model_name, warn)

    def _best_passages(self, sents: Sequence[str], ctx: FilmCtx, info: FilmInfo) -> List[str]:
        S = self.space.vec(sents)
        cos = (S @ ctx.plot.T).toarray()
        return [info.plot_passages[int(cos[i].argmax())] for i in range(len(sents))]
