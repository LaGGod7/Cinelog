# CineLog: Algorithms, Data Structures, ML and DL

Oct 31, 2026

## Overview

CineLog (Team 15, guide Prof. Vijay B) is a role-based film logging, review and club platform: React front end, FastAPI back end, SQLite (PostgreSQL optional). This document explains every data structure and algorithm in the back end, and every machine-learning (ML) and deep-learning (DL) component, with the reason each one was chosen and where the code lives. All paths are under `backend/`.

One rule runs through the whole design: **nothing generates text.** The ML and DL parts are classifiers and encoders (they output a probability or a vector), never a language model that writes answers or explanations. Every recommendation or spoiler flag carries a reason built from rules and data, not from generated prose.

The code falls into four groups.

| Group | What is in it | Where |
| --- | --- | --- |
| Data structures | Trie, inverted index, LRU cache, Aho-Corasick automaton, heaps (top-K, k-way merge), bounded priority queue, token bucket | `app/dsa/`, `app/scheduler/pool.py`, `app/security.py` |
| Algorithms | Content-based recommender, cosine taste match, streaks, goal pace, persona rules, film of the day, state machines with compare-and-swap, deny-by-default RBAC, strike and mute policy | `app/services/`, `app/workflow.py`, `app/rbac.py`, `app/gamification.py` |
| Classical ML | Hashed TF-IDF retrieval (RAG without generation), TF-IDF + logistic regression, threshold calibration | `app/spoiler/retrieval.py`, `ml.py`, `ml/train_ml.py`, `ml/tune_shield.py` |
| Deep learning | BiGRU with attention (trained in PyTorch, served in NumPy), MiniLM sentence encoder (ONNX), optional DistilBERT cross-encoder (ONNX) | `app/spoiler/rnn.py`, `semantic.py`, `dl.py` |

The sections that follow go in that order: data structures, core algorithms, rules and workflow, the Spoiler Shield (where ML and DL meet), how the models are trained and evaluated, a complexity table, and finally what the numbers do and do not show.

## Data structures

These live in `app/dsa/` (plus the queue in `app/scheduler/pool.py` and the rate limiter in `app/security.py`). Each is written by hand rather than imported, so the behaviour is explicit and testable.

### Trie with top-K per node (title autocomplete)

`dsa/trie.py`. A prefix tree over normalised titles (lower-case, punctuation stripped). The twist is that **every node stores its own best K films**, a small sorted list of `(-popularity, film_id)` pairs maintained with `bisect`. A query walks the prefix and reads the list on the node it lands on, so it costs O(L + K) for a prefix of length L, whatever the size of the catalogue. There is no subtree walk and no sorting at query time.

Each title is inserted from every word boundary, so "the dark knight" is reachable by "dark kn" as well as "the d". `SearchService.autocomplete` ignores prefixes shorter than 2 characters and asks for 10 results.

### Inverted index with min-heap ranking (full-text search)

`dsa/inverted_index.py`. The classic search-engine structure: a dictionary from each term to a sorted list of film ids (a posting list), plus term frequencies and a popularity prior.

- **Indexing.** Text is lower-cased, split into `[a-z0-9]+` tokens and stripped of a small stop list. Fields are weighted when counting a term: title 3, keywords 2, cast 2, genres 2, overview 1.
- **Query.** All query terms must match (AND). The posting lists are sorted shortest first and merged with a two-pointer intersection, so a rare term shrinks the candidate set before the common ones are touched. Genre, cast and year filters are then applied to the survivors.
- **Score.** For each term, `(1 + ln tf) × ln(1 + N / (1 + df))`, summed, plus `0.05 × ln(1 + popularity)`. The first factor is sub-linear term frequency, the second is inverse document frequency (rare words count more).
- **Top-K.** A min-heap of size K holds the best candidates seen so far; a new candidate replaces the root only if it beats it. That is O(n log K) rather than sorting all n matches.

`SearchService` (`services/search.py`) owns one trie and one index. On a rebuild, new structures are built off to the side and swapped in under a lock, so searches never see a half-built index. A cheap fingerprint of the catalogue (row count, latest sync time, highest id) tells it when an import script in another process has changed the data.

### LRU cache (hash map + doubly linked list)

`dsa/lru.py`. The textbook O(1) cache: a dictionary maps a key to a node, and the nodes form a doubly linked list ordered by recency, with sentinel head and tail so there are no edge cases. `get` moves the node to the front; `put` evicts the node before the tail when full. A lock makes it safe across the worker threads, and it counts hits and misses. It is used three times in the Spoiler Shield: compiled Aho-Corasick automata (128 entries), per-film retrieval contexts (256) and per-film semantic plot vectors (64). All three are expensive to build and cheap to keep.

### Aho-Corasick automaton (many-word matching in one pass)

`dsa/aho_corasick.py`. Finds every occurrence of every word in a list while reading the text **once**.

1. **Trie.** All terms go into a trie stored as arrays (`goto`, `fail`, `out`).
2. **Failure links.** A breadth-first pass gives each state a link to the longest proper suffix that is also a prefix of some term, and copies the matches of that suffix into the state's output list.
3. **Search.** For each character, follow failure links until a transition exists, move, then report every term in the state's output list. Hits are optionally restricted to whole words by checking the characters on either side.

Build is linear in the total length of the terms; search is O(n + number of matches), independent of how many terms there are. Each film has its own list (character names, actor surnames, plot-specific words), so the automaton is built per film and cached by `(film_id, wordlist_version)` in the LRU above.

### Heaps for top-K and k-way merge

`dsa/inverted_index.py::top_k` is the generic min-heap used for similarity lists. `dsa/feed.py::merge_feeds` builds the home feed: each followed user's activity list is already newest-first, so a heap holding one cursor per list yields the newest `limit` items overall in O(limit × log F) for F followed users, without merging everything.

### Bounded priority queue and worker pool

`scheduler/pool.py`. A producer-consumer queue built from a heap, a mutex and **two counting semaphores** (free slots and available items), the classic bounded-buffer solution from operating systems.

- Two priorities: `USER` jobs (spoiler scans a person is waiting for) run before `BATCH` jobs (catalogue sync, e-mail). A sequence number keeps equal priorities first-in first-out.
- When the queue is full, a USER producer waits up to 2 seconds and then fails loudly; a BATCH job is postponed and retried a second later.
- A job that raises is retried up to 3 times with exponential back-off (0.5 s, 1 s, 2 s), then recorded as failed. The Admin page reads the pool's `stats` and `failed_jobs`.
- Four daemon worker threads by default, capacity 256.

### Token bucket (rate limiting)

`security.py::TokenBucket`. Each key (an IP address or a user id) has a bucket that refills at a fixed rate up to a capacity. A request spends one token; with none left it is refused. Tokens are computed lazily from elapsed time, so there is no timer thread. The table is capped at 50,000 keys and cleared if it grows past that, which bounds memory.

## Core algorithms

### Content-based recommender

`services/recommend.py`. It recommends from what the catalogue already knows about each film; there is no outside service and no model to train.

1. **Film as a bag of features.** Each genre counts 1.0, each of the first 12 keywords 0.5, each of the 3 top-billed actors 0.7, and the decade 0.4.
2. **How much you liked each film.** From your diary, using the latest rating per film: `(stars − 3) / 2`, so a 5 is +1 and a 0.5 is −1.25. A film logged without stars counts a mild +0.25.
3. **Rare features matter more.** Over the 1,500 most popular films, `idf(feature) = ln((N + 1) / (df + 1)) + 1`. Sharing "Documentary" says less than sharing a specific keyword.
4. **Profile.** The sum, over everything you logged, of `weight × feature value × idf`. Features of films you disliked push the profile negative.
5. **Score.** For each unseen candidate, the dot product of its idf-weighted features with your profile, divided by the length of the candidate's own feature vector so films with many features do not win by size alone.
6. **Re-rank the top 60** with small nudges: a log-scaled popularity bonus (up to 0.15), a bonus for a good average rating once a film has at least 3 ratings (up to 0.10), +0.25 for each followed user who rated it 4 stars or more (capped at 0.75) and +0.1 if it is on your watchlist.
7. **Reason.** If a friend rated it highly, the reason names them. Otherwise it finds the film you liked that overlaps most with the suggestion (a min-overlap of idf-weighted features) and names the two strongest shared features: "Because you liked X · Sci-Fi and 'heist'".

Until you have logged 3 films the page falls back to popular films and says so. Cost is roughly pool size × features per film (about 1,500 × 20), so it runs per request without caching.

### Taste match between two people

`services/insights.py::taste_match`. Two ingredients.

- **Rating agreement**, from films both people rated (latest rating each): `agree = max(0, 1 − mean|difference| / 4.5)`, where 4.5 is the largest possible gap on a 0.5 to 5 scale.
- **Genre similarity**: cosine between the two genre-count vectors, `dot / (|a| |b|)`.

With 3 or more co-rated films the score is `100 × (0.7 × agree + 0.3 × genre cosine)`. With fewer, only genres are used and the score is multiplied by 0.85, because genres alone are weaker evidence. With neither, no score is shown rather than a made-up one. The number maps to a label: 85+ Kindred spirits, 70+ Same wavelength, 50+ Some common ground, 30+ Different tastes, below that Opposites attract. The response also lists films both loved (both ≥ 4 stars) and the biggest disagreements (gap ≥ 1.5).

### Streaks, yearly goal, badges

- **Streaks** (`gamification.py::streaks`). Sort the distinct viewing dates and scan once, extending a run when the next date is exactly one day later; the longest run is tracked along the way. The current streak counts backwards from today, or from yesterday if nothing is logged yet today, so it does not reset in the morning.
- **Goal pace** (`insights.py::goal_progress`). `expected = target × days elapsed / days in year` (leap years handled), `ahead_by = done − expected`, and `per_week_needed = remaining / days left × 7`. Past and future years are handled as fully elapsed or not started.
- **Badges.** Data-driven: a registry maps a metric name to a function (added with a decorator), and each badge is a row of (key, metric, target). Progress is `min(99, 100 × value / target)` until earned, and awarding is idempotent because earned keys are stored. Adding a badge means adding one row.

### Year-in-review persona

`insights.py::persona`. An ordered rule list in which **the first rule that fits wins**, from the most distinctive habit to the most general: fewer than 5 films gives "Newcomer"; 40% or more of viewings in a cinema gives "Big-Screen Believer"; 25% or more rewatches gives "Comfort Rewatcher"; a low or high average rating (with at least 10 rated films) gives "Tough Critic" or "Easy Believer"; 8 or more genres gives "Wanderer"; otherwise the top genre picks a persona, with "Cinephile" as the default. It is a transparent decision list, not a learned model.

### Film of the day

`routers/insights.py`. The date string is hashed with SHA-1, read as an integer, and taken modulo the number of candidate films (the most popular ones that have posters). Everyone sees the same film on the same day, it changes at midnight, and nothing needs to be stored or scheduled.

### Online search with memoisation and a cool-off

`services/online.py`. When a local search finds nothing, TMDB is asked and missing films are imported. Results are memoised in an LRU (256 entries, 10-minute freshness). After a TMDB failure the function returns "no online results" immediately for 45 seconds instead of making every keystroke wait on a dead network, which is a small circuit breaker. It never raises; the error is kept for the Admin status page.

### Poll result

`services/polls.py::finalize_poll`. Votes are counted per option; options are sorted by (votes descending, option id ascending), so a tie goes to the option added first, and a poll with no votes has no winner. The tally is frozen as JSON when the poll closes, so history does not change if votes or films are edited later.

### Calendar export

`routers/club_insights.py`. Club events are written as an iCalendar (`.ics`) file. RFC 5545 limits lines to 75 octets, so longer lines are cut and continued on the next line after a space ("line folding").

### Passwords, sessions and reset tokens

`security.py`. Passwords are hashed with bcrypt at cost 12 (the 72-byte limit of bcrypt is respected explicitly). A session is a signed JWT (HS256, with the algorithm pinned so a token claiming `alg: none` is rejected); any token issued before the user's `password_changed_at` is treated as void. A reset token is 32 random bytes; only its SHA-256 is stored, so a leaked database does not leak usable tokens. The client address is read from `X-Forwarded-For` only when the request came through a trusted proxy.

## Rules, roles and workflow

This group is the access-control theme of the project expressed as algorithms. None of it is learned; all of it is checkable.

### Deny-by-default permission matrix

`rbac.py`. `MATRIX` maps each permission to the set of roles that hold it, for example `review.moderate` → {moderator, admin}. Anything not listed is denied. A user may hold several roles and their rights are the **union** of the roles' permission sets, so granting a role can only add rights. Routes do not test roles directly; they declare the permission they need with a FastAPI dependency (`require_perm("role.manage")`), which returns 401 if nobody is signed in and 403 if the permission is missing. Because the matrix is one table, the Admin > Permissions page can display exactly what the server enforces.

Club roles are a **second, independent matrix** (`CLUB_MATRIX`): convener, co-convener and member apply only inside one club. A site admin is not automatically a convener, and a convener has no site power.

### Rank and separation of duties

Roles are ordered viewer < critic < convener < moderator < admin. Sanctions use `rank_of(roles)`, the highest rank a person holds, and require the target's rank to be **strictly lower** than the actor's. So a moderator cannot sanction another moderator or an admin, an admin can sanction a moderator but not another admin, and nobody can sanction themselves. Critic applications are decided by a moderator or admin, never self-approved: a viewer cannot grant themselves the critic role.

### Strikes and automatic mute

`routers/moderation.py`. A strike is a stored warning with a reason. After each new strike the code counts strikes **in a rolling 30-day window**; at 3 or more the account is muted for 3 days (a later mute never shortens an existing one: the longer date wins). `ensure_can_post` checks the mute before a review or club post is accepted. A mute blocks writing only; reading, rating and logging stay open. Every strike, mute and role change is written to the append-only audit log, which the application refuses to update or delete.

### Workflow state machines with compare-and-swap

`workflow.py`. Reviews, polls and critic applications each have a **finite state machine** written as a transition table: for each state, the set of states it may move to. A move not in the table raises an error that the API reports as HTTP 409.

| Machine | Allowed transitions |
| --- | --- |
| Review | pending\_scan → published, removed · published → hidden, pending\_scan (author edited), removed · hidden → published, removed · removed → nothing |
| Poll | draft → open, cancelled · open → closed · closed, cancelled → nothing |
| Critic application | pending → approved, rejected, withdrawn · the rest are final |

Checking the table is not enough when two people act at once (two moderators clicking Approve on the same review). So the move is performed as **compare-and-swap** in one SQL statement: `UPDATE ... SET state = :new WHERE id = :id AND state = :old`. If the row count is not 1, someone else changed the state first, and the second actor gets a 409 that names the state they actually found. First wins, second sees the new state, and no lock is held between reading and writing.

### Review lifecycle in practice

A new or edited review is saved as `pending_scan` and handed to the worker pool as a USER-priority job. The Spoiler Shield scans it, the result (risk, uncertain flag, warn flag, per-sentence segments, scan version) is cached on the row, and the review moves to `published`. A startup job re-queues any review left in `pending_scan` by a crash. Blurred sentences are never sent to other readers: the server returns the text only when someone presses Reveal.

## The Spoiler Shield: ML and DL in detail

The shield (`app/spoiler/`) decides which parts of a review give away the film. It is the one place where machine learning and deep learning are used, and it is deliberately a **stack of layers**: cheap exact rules first, then retrieval against the film's plot, then trained models. Each layer can be switched off without breaking the others, and a missing model file simply deactivates that layer.

Every review is split into sentences (`text.py::split_sentences`, a regex that also handles abbreviations such as "Dr." and text typed without a space after a full stop). Each sentence gets a risk between 0 and 1, and the review gets one too.

```text
Review text, split into sentences  (each sentence gets a risk 0..1, then the review does)
        |                         |                           |
        v                         v                           v
Rules: hard evidence      Retrieval: plot match       Models: soft score
- writer tags, word lists - hashed TF-IDF vs plot     - TF-IDF + logistic regression
  (Aho-Corasick)            passages                  - BiGRU + attention, blended
- cue + plot restatement  - cosine to plot / to       - DistilBERT (optional)
- semantic match (MiniLM)   confirmed spoilers        - calibrated to a 0..1 risk
                          - shared rare words
        |                         |                           |
        +-------------------------+---------------------------+
                                  v
 Decision: the model decides WHETHER, the rules decide WHICH sentences
 - risk >= 0.7 or any hard evidence: blur top sentences (max 30% of review)
 - 0.3 to 0.7: moderator queue
 - label only: "possible spoilers", nothing hidden
```

The layers below are listed in the order a review meets them. The first three groups run independently on every sentence and the decision step combines them.

### Layer 1: writer tags and word lists (rules)

A writer can mark text with `||hidden||`; tagged sentences are always blurred. Then the Aho-Corasick automaton for that film (see Data structures) scans the review once. Words come from the cast and plot data and have two strengths: **plot terms** are strong (rule score 0.9, treated as hard evidence), **character and actor names** are weak (capped at 0.4), because naming a character is not a spoiler. Common words that happen to be names ("will", "rose", "mark") are filtered out first.

### Layer 2: retrieval against the plot (RAG without generation)

`retrieval.py`. "Retrieval-augmented" here means only the retrieval half: the film's own plot text is fetched and compared with the sentence; nothing is generated.

- **Passages.** The plot (Wikipedia or Kaggle synopsis) is cut into overlapping windows of 2 sentences.
- **Vector space.** Words are hashed into 2^18 buckets (`HashingVectorizer`) and weighted by TF-IDF with sub-linear term frequency. Hashing means a word never seen in training, such as a brand-new character name, still lands in a bucket, and it counts as rare. Idf is fitted on the training films' plots only.
- **Rare buckets.** Buckets whose document frequency is at most about 1% of passages (never fewer than 2) are marked rare. Sharing rare words with the plot is much stronger evidence than sharing "police" or "city".
- **Per-sentence features.** Cosine similarity to the best plot passage, the mean of the best 3, similarity to moderator-confirmed spoiler sentences, the number of rare plot words shared, and the fraction of the sentence's rare words that are in the plot. A review gets 10 features from these (the max, the mean, the share of sentences above a threshold, log length, whether a plot exists).

The rule scores from this layer are small ramps: plot similarity ramps from 0 at 0.2 to 0.85 at 0.5; shared rare words add 0.15 each up to 0.45; similarity to a confirmed spoiler ramps from 0.3 to 0.6 and reaches 0.95. Scores from different rules combine as a **noisy-OR**, `1 − ∏(1 − p)`, so two weak signals add up but can never exceed 1.

### Layer 3: cue words

A regular expression for phrases reviewers use when giving something away ("turns out", "dies", "all along", "the twist", "in the end" and similar). A cue alone is weak, because "no twist here" is harmless, so it scores 0.75 only when the same sentence also names a character, shares a rare plot word or resembles the plot. A cue together with a close plot restatement (similarity at least 0.35 and at least 2 rare terms) is hard evidence at 0.8.

### Layer 4: semantic plot match (encoder, ONNX)

`semantic.py`. Words fail when the spoiler is reworded ("the guy on the poster does not make it to the credits"). This layer compares **meaning**.

1. Every plot sentence and every review sentence is embedded by **all-MiniLM-L6-v2**, a small public sentence encoder (int8 ONNX, 23 MB) run with `onnxruntime`. Token vectors are mean-pooled and L2-normalised, so cosine similarity is a dot product.
2. Only the **second half of the plot** counts as spoiler territory. The first half is a premise recap that any review may restate; measured on its own it carried no signal (AUC 0.49), while the second half scored 0.77 to 0.80 on the stress set.
3. Score = best similarity to the late plot − 0.5 × best similarity to the early plot. A sentence that matches the premise as well as the ending is probably just recapping.
4. Above the blur cut-off it is hard evidence (0.8); above a lower cut-off the review only gets the reader-visible "possible spoilers" label.

The cut-offs are not trained. `ml/calibrate_semantic.py` picks them from real clean reviews so that only about 3% of short clean reviews would be blurred and 10% labelled. The encoder is used as-is, so this layer is a fixed measuring instrument, not a model trained on this project's data.

### Layer 5: TF-IDF + logistic regression (classical ML)

`ml.py`, trained by `ml/train_ml.py`. Features: word and two-word TF-IDF (up to 300,000 terms, minimum document frequency 3, sub-linear tf) concatenated with the 10 standardised retrieval features from Layer 2. Classifier: logistic regression (C = 2, balanced class weights, liblinear solver). It is a linear model, so its decision is inspectable: the words that pushed the score up most are shown to moderators.

The raw probability is mapped onto the shield's common risk scale by a piecewise-linear **calibration**: below the low threshold it maps into 0 to 0.3, between the thresholds into 0.3 to 0.7, above into 0.7 to 1. After that, a risk of 0.7 or more means blur, 0.3 to 0.7 means send to the moderator queue, and below 0.3 means show. The two thresholds are not fixed numbers; they are measured (see the training section).

### Layer 6: BiGRU with attention (deep learning, recurrent)

`rnn.py`, trained by `ml/train_rnn.py` with PyTorch. TF-IDF sees isolated words and word pairs; a recurrent network reads the sentence **in order**, and starting from GloVe word vectors lets "the murderer is revealed to be her" land near "she turns out to be the killer" although they share almost no words.

Architecture, left to right:

1. **Embedding.** 100-dimensional GloVe vectors (6B, public domain), fine-tuned at a quarter of the main learning rate.
2. **Bidirectional GRU**, hidden size 96 per direction. A GRU is a recurrent cell with an update gate and a reset gate that decide how much of the past to keep; one pass reads left to right, one right to left, and their outputs are concatenated per word.
3. **Attention.** Each word's state is scored by a small network, the scores are softmaxed into weights, and the weighted sum becomes a review vector. The weights say which words mattered; the moderator note lists the top few.
4. **Max-pooling** over time gives a second summary.
5. **Head.** The attention vector, the max-pool vector and the same 10 plot-match features go through a 64-unit ReLU layer to one output, a spoiler probability.

Training uses dropout 0.35, random word dropout (10% of words blanked, which also teaches robustness to unseen vocabulary), AdamW with weight decay, a one-cycle learning-rate schedule, a positive-class weight for the imbalance, and 4 epochs by default.

**Served with NumPy only.** `rnn.py` re-implements the GRU forward pass (reset, update and candidate gates, with padded steps leaving the state untouched so the backward pass starts at each review's real last word), the attention and the head directly from saved weight arrays. The site never imports PyTorch, so nothing extra has to be installed to run it.

**Fusion.** The ML and RNN probabilities are combined as a weighted average of their log-odds, `sigmoid((1 − w) · logit(p_ml) + w · logit(p_rnn))`. The weight w and the blend's own thresholds are chosen by `ml/tune_shield.py` against the ML model actually deployed. If tuning finds no gain, w is 0 and the site ignores the network. It is also ignored until tuning has run.

### Layer 7: transformer cross-encoder (optional, deep learning)

`dl.py`, trained by `ml/train_dl.py`. A DistilBERT model fine-tuned on pairs, `[review sentence] [SEP] [most similar plot passage]`, so the model reads the claim and the evidence together. It is exported to int8 ONNX and served with `onnxruntime`. It needs a GPU to train in reasonable time and is off by default (`use_dl`); when on, its calibrated score is averaged with the ML score.

### Putting the layers together

The decision logic in `shield.py::scan` has two modes.

**With a trained model (normal mode): the model decides whether, the rules decide which.** The review-level risk is the larger of the model's calibrated score and the strongest *hard* evidence (writer tag, plot-term hit, moderator-confirmed spoiler, cue plus plot restatement, semantic match). Soft rule evidence is deliberately not allowed to blur a review by itself, because on films the models had never seen it added nothing at review level. If the risk reaches 0.7 the review is blurred, and which sentences are hidden is chosen by `sentence model score + 0.2 × soft rule score`: the highest-scoring sentences, at most 30% of the review (at least one), and never one scoring under half of the best. If the risk is between 0.3 and 0.7 and nothing was blurred, the review is marked uncertain and goes to a moderator.

**Without a trained model:** rule scores are combined by noisy-OR and the same 0.7 and 0.3 bands apply.

There is also a third, softer tier: a reader-visible **"Possible spoilers" label** that hides nothing and does not reach moderators. It is set when the model score passes a separate recall-targeted threshold, or when the semantic layer's warn cut-off is crossed.

Every decision carries reasons ("closely matches the film's plot (similarity 0.41)", "spoiler cue 'dies' next to plot details", "model risk 0.74; telling words: ..."), and moderator decisions flow back into the film's context as confirmed spoilers, which Layer 2 then retrieves against. Blurred text is never sent to readers; the server returns it only when Reveal is pressed.

## How the models are trained and measured

Scripts are in `backend/ml/`. The main ones (training the recurrent model, tuning, the stress test, the semantic calibration) have a `.bat` wrapper in `backend/` for the Windows laptop.

### Data and the split

Training data is the Kaggle **IMDB Spoiler Dataset**: reviews with a spoiler flag, and a plot synopsis per film. The split is **by film**, 80% train, 10% validation, 10% test, using a seeded shuffle of all film ids. That matters: if reviews of one film appeared in both training and test, a model could score well by memorising that film's character names. Splitting by film means the test score is for films the model has never seen, which is the real situation when a new film arrives from TMDB. The retrieval space's idf table is fitted on the training films' plots only, for the same reason.

### Scripts and what each produces

| Script | What it does | Output |
| --- | --- | --- |
| `train_ml.py` | Fits TF-IDF + logistic regression, runs ablations (text only, retrieval only, both) | `spoiler_ml.joblib`, `metrics.json` |
| `train_rnn.py` | Trains the BiGRU in PyTorch on the same split, also trains the TF-IDF baseline and reports both and their blend | `spoiler_rnn.npz`, vocab, meta |
| `train_dl.py` | Fine-tunes DistilBERT as a cross-encoder, keeps the best epoch by validation AUC, exports int8 ONNX and checks it against PyTorch | `spoiler_dl.onnx`, tokenizer, meta |
| `tune_shield.py` | Chooses the thresholds and the RNN blend weight against the model that is actually deployed | `shield_thresholds.json` |
| `calibrate_semantic.py` | Sets the semantic layer's cut-offs from clean reviews (no spoiler labels needed) | `semantic/meta.json` |
| `eval_shield.py`, `eval_sentences.py`, `eval_adversarial.py` | Held-out, sentence-level and stress-test evaluation | printed reports |
| `synth.py`, `make_sample.py`, `make_adversarial.py` | Tiny synthetic data for tests, sampling helpers, and the hand-written stress sets | test fixtures, gold JSON |

### Choosing thresholds from data, not by hand

A probability alone does not say where to blur. `tune_shield.py` scores the validation films and sets the thresholds from a false-positive budget on **clean** reviews: the blur cut-off is the probability at which 8% of clean reviews would be blurred, and the moderator cut-off the one at which 15% would reach a moderator. Cost is stated before it is incurred. A third cut-off for the reader label can be set from a recall target (for example, flag 80% of validation spoiler reviews) and the tool prints what that costs in clean reviews flagged. For the RNN it searches the blend weight from 0 to 1 in steps of 0.05 by validation AUC, and uses a **paired bootstrap** (500 resamples) to put a 95% interval on the blend's AUC gain over the ML model alone.

### What was measured

All figures below are the ones recorded in the project README. "AUC" is the area under the ROC curve: 0.5 is guessing, 1.0 is perfect.

| Question | Result |
| --- | --- |
| Linear model on 1,254 test reviews of unseen films (from a 12,000-review run) | AUC 0.748 |
| BiGRU alone, same test set | AUC 0.722 |
| Blend of the two | AUC 0.758; the 95% interval of the gain over the linear model is −0.002 to +0.021, so **the gain is not statistically established** |
| Sentence selection, 268-review hand-labelled set (draft labels) | Blend finds 68% of real spoiler sentences versus 64% for the linear model; hides a real spoiler in 86% versus 82% of spoiler reviews |
| Reader label: price of recall on unseen films | Flagging 70% of spoiler reviews flags about 34% of clean ones; 80% costs about 42%; 90% about 63% |
| Giveaway-word-plus-plot-restatement rule on 3,000 held-out IMDB reviews | A wash: spoilers blurred 44.7% to 45.4%, clean blurred 12.1% to 12.9% |
| Same rule on made-up reviews that restate the plot | 2 of 17 spoiler reviews blurred before, 7 of 17 after, no clean review affected |
| Semantic layer, first half of plot versus second half | AUC 0.49 versus 0.77 to 0.80 on the stress set |

### The stress test

The IMDB spoiler flag is noisy and caps every model near AUC 0.8, so a second test was written by hand: 101 reviews (set A) and 63 more written afterwards (set B). They hide spoilers behind euphemism, slang, typos, Hinglish, questions, hindsight, character fates and sarcasm, and include clean reviews that *sound* spoilery ("no spoilers, but the ending is devastating").

This exposed a real weakness: the trained word-based models flagged only 7 of 67 disguised spoilers in set A and 2 of 38 in set B, and their score on set A was no better than plain review length (AUC 0.73 versus 0.72). That is why the semantic layer was added. With it:

| Full shield | Before | After | Clean reviews wrongly flagged |
| --- | --- | --- | --- |
| Set A: disguised spoilers blurred / flagged | 2 / 7 of 67 | 16 / 27 of 67 | 1 blurred, 3 flagged of 34 |
| Set B (fresh): blurred / flagged | 1 / 2 of 38 | 7 / 10 of 38 | 0 blurred, 2 flagged of 25 |
| Real short clean IMDB reviews: blurred / flagged | 2.4% / 12.2% | 5.4% / 22.4% | this row is the cost |

That is three to four times as many disguised spoilers caught, at a visible cost in false flags, and still far from catching most of them.

## Complexity at a glance

n is the size of the input at hand, K the result size, L a prefix length, P the candidate pool, z the number of matches, T a review's length in words, H the GRU hidden size.

| Component | Operation | Cost |
| --- | --- | --- |
| Trie (top-K per node) | Prefix query | O(L + K), independent of catalogue size |
| Trie | Insert a title | Proportional to the characters of all its word-suffixes, times a small K for the sorted insert |
| Inverted index | Query | Sum of the shortest posting lists in the merge, then O(c log K) over c survivors |
| LRU cache | get, put, evict | O(1) |
| Aho-Corasick | Build | O(total length of all terms) |
| Aho-Corasick | Search | O(n + z), independent of the number of terms |
| Min-heap top-K | Select K best of n | O(n log K) |
| K-way merge (feed) | Newest `limit` of F feeds | O(F + limit · log F) |
| Bounded priority queue | put, get | O(log n) plus semaphore waits |
| Token bucket | allow | O(1), lazily refilled |
| Recommender | One request | About P · f for scoring plus P log P to sort, P = 1,500, f ≈ 20 features |
| Taste match | One pair | Linear in co-rated films and genres |
| Streaks | One user | O(n log n) for the sort, one pass after |
| State transition | Review, poll, application | O(1): one table lookup and one UPDATE |
| Permission check | `has_perm` | O(M) over the 20 matrix entries |
| Retrieval features | One review | Sparse sentence × passage products |
| Semantic match | One review | One encoder pass per sentence, plus a sentences × plot-sentences dot product (plot vectors cached) |
| TF-IDF + logistic regression | Predict | Linear in the non-zero features |
| BiGRU | Predict | O(T · H²) per direction, sequential over T (T at most 256, H = 96) |

## Limitations and what to do next

**What the numbers say.** On films the models have never seen, the best review-level AUC is about 0.75 to 0.80. The IMDB spoiler flag is applied inconsistently by reviewers, which limits every model trained on it. The BiGRU's gain over the linear model (0.748 to 0.758) is within noise on the data measured so far, so it should be described as promising, not proven. That is why the code only uses it after `tune_shield` has measured it and sets its weight to 0 when there is no gain.

**The stress sets are mine.** Sets A and B were written by hand by the project author, share one writing style and carry unverified labels. Real reviews will behave differently. In the other direction, the "clean" IMDB reviews used to measure false flags may contain unflagged spoilers, which makes the cost of the semantic layer look higher than it is.

**The semantic layer is zero-shot.** It uses a public encoder as it is and only its cut-offs are calibrated. A learned combiner of every signal, trained on set A and tested on set B, reached AUC 0.82 to 0.84 but still flagged only about 10% to 25% of disguised spoilers at the false-flag rate of real clean reviews. Moderator decisions (blur or approve) are stored with every review; they are the labelled data that would let the matching be trained, and are the most valuable next step.

**The risk score is a scale, not a probability.** The piecewise-linear calibration puts model output on a 0 to 1 scale with agreed bands (0.3 and 0.7). It was not fitted as Platt or isotonic calibration, so "0.7" means "over the blur cut-off", not "70% likely".

**Explanations are hints.** The words shown to moderators come from the linear model's weights and the GRU's attention. They show what the model leaned on; they do not prove why a review is a spoiler.

**Operational notes.**

- The recurrent layer does nothing until `tune_shield.bat` has run, and the semantic layer needs `onnxruntime` and `tokenizers` installed (`pip install onnxruntime tokenizers`); without them the layer is off and the rest still works.
- The linear model is a pickle (`joblib`) file. Load only files you trained yourself.
- The README's "Status of the models" note says the training code was first run only on synthetic data in the build environment. The real-data figures in this document are those recorded elsewhere in the same README; re-running `train_rnn.bat`, `tune_shield.bat` and `eval_adversarial.bat` on the laptop reproduces them for your own data, and is the right check before quoting any number in a report.

**Smaller design limits.** Search is AND-only with no stemming or typo tolerance. The recommender is content-based, so it has no collaborative signal and a cold start below 3 logged films. The trie and inverted index live in memory and are rebuilt when the catalogue changes. Rate-limit buckets are per process.
