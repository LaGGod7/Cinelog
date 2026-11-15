# CineLog

Film logging, reviews and clubs with a **Spoiler Shield**. React + FastAPI, SQLite on a laptop (PostgreSQL via Docker).

**Roles:** Viewer, Critic, Club Convener, Moderator, Admin. The first account you register becomes Admin.

## What is in the box

| Area | What it does |
|---|---|
| Search | Own Trie autocomplete, inverted index with min-heap top-K, LRU cache |
| Storage | 3NF schema, one vote per member enforced by a UNIQUE constraint inside a transaction |
| Job scheduler | Thread pool + bounded priority queue (user jobs before batch jobs), retries with backoff |
| Security | bcrypt, JWT in an HttpOnly cookie, CSRF double-submit, token-bucket rate limits, security headers, Google OAuth (optional) |
| Roles & workflow | Deny-by-default permission matrix, review and poll state machines (first actor wins, second gets 409), append-only audit log |
| Product | Diary, watchlist, aspect ratings, taste radar, clubs, live polls (WebSocket), moderation queue, feed, taste similarity, CSV/JSON export |

### Spoiler Shield (hybrid, no LLM)

Every review is scanned in the background and split into sentences. Each sentence is scored by:

1. **Writer tags**: `||hidden||` is always blurred.
2. **Aho–Corasick** over per-film word lists: character names are weak signals, plot terms are strong.
3. **RAG**: the sentence is matched (TF-IDF cosine) against that film's plot passages and against spoilers moderators confirmed earlier.
4. **Cue rule**: words like "twist / dies / all along" next to a character name or plot term.
5. **ML** (optional until you train it): TF-IDF + retrieval features → logistic regression, calibrated to a risk scale.
6. **DL** (optional): a retrieval-augmented cross-encoder exported to ONNX.

**With a trained model, the model decides whether a review is blurred; the rules decide which sentences.** On films the model had never seen, the plot-similarity / rare-word / cue rules added nothing at review level on top of the model (AUC 0.80 alone, 0.78 fused), so they now only break ties between sentences. Which sentences to hide was chosen on a hand-labelled set (`backend/ml/gold_sentences.json`, 118 spoiler sentences, draft labels): the model's sentence score ranks them best, so a blurred review hides its top-scoring sentences, at most 30% of it, at least one, never anything scoring under half of the best. `python -m ml.eval_sentences` (or `eval_sentences.bat`) re-measures this. Hard evidence (writer tags, plot-term list, moderator-confirmed spoilers) always blurs. Without a trained model the rules are fused by noisy-OR as before. Risk ≥ 0.7 blurs; 0.3–0.7 goes to the moderator queue; the cut-offs come from `models/shield_thresholds.json` (written by `ml.tune_shield` / `tune_shield.bat`: blur at 8% of clean reviews, moderators at 15%, measured on validation films). Blurred text is **never sent to readers**; it is fetched by the Reveal button. Moderator decisions feed back into the film's RAG context.

**Recurrent layer (BiGRU + attention).** On top of the trained model there is a small neural network that reads a review word by word (a bidirectional GRU with attention, starting from public-domain GloVe word vectors, plus the same plot-match numbers the main model sees). The idea is that it reads word order and similar meanings, which the word-counting model cannot. Its probability is averaged with the trained model's in log-odds space; the weight of the blend and the blend's own cut-offs are measured by `ml.tune_shield` against the model the site actually runs, and **if tuning finds no gain the weight is 0 and the site ignores the network**. It is trained with PyTorch (`train_rnn.bat`) but served with numpy only, so nothing extra is installed on the site. It is not used until `tune_shield` has measured it (the Admin tag says "installed, run tune_shield.bat"). It is a classifier, not a language model: it generates no text and explains nothing; the moderator note only lists the words it attended to most.

> **What the recurrent layer measured** (12,000 reviews, split by film, 1,254 test reviews of films never seen in training): AUC trained model 0.748, recurrent alone 0.722, blend 0.758; the paired-bootstrap 95% interval of the blend's gain is -0.002 to +0.021, so **on that much data the gain is small and not statistically established**. On the 268-review sentence gold set the blend finds 68% of real spoiler sentences versus 64% for the trained model alone, and hides a real spoiler in 86% versus 82% of the spoiler reviews (draft labels, small sample). The IMDB spoiler flag itself is noisy (reviewers tag inconsistently), which caps every model near AUC 0.8. The full-data run is the real test: `train_rnn.bat` prints the same numbers for your data.

**Giveaway word + plot restatement.** One extra hard rule: a sentence that contains a giveaway word ("dies", "twist", "turns out", ...) *and* closely restates the film's plot (similarity ≥ 0.35 with at least 2 rare plot terms) is blurred even if the model is calm. Found while testing with made-up reviews: sentences like "Jack dies of hypothermia ... Old Rose drops the diamond into the sea" were passing because the model-led design ignores soft plot matching. The pair was 3.9× more common in spoiler than in clean reviews of unseen films, which neither signal shows alone. **Be aware of the measurement:** on 3,000 held-out IMDB reviews the rule is a wash (spoilers blurred 44.7% → 45.4%, clean wrongly blurred 12.1% → 12.9%), because real reviewers rarely restate plots closely and the IMDB flag is noisy. It helps on reviews that do restate the plot (made-up test: 2 of 17 spoiler reviews blurred before, 7 of 17 after, no clean review affected). To switch it off set `CUE_PLOT_COS = 1.1` in `app/spoiler/shield.py`.

**Three tiers, and the price of recall.** Blur (confident), moderator queue (unsure) and, new, a reader-visible **"Possible spoilers"** label that hides nothing and does not reach moderators. `tune_shield.bat [blurFPR] [moderatorFPR] [recall]` sets the label's cut-off so that the chosen share (default 0.8) of validation spoiler reviews is flagged in one of the three ways, and prints what that costs. On films never seen in training, 80% needs about 42% of clean reviews flagged too (70% costs about 34%, 90% about 63%), because the models cannot separate more cleanly: the IMDB spoiler flag is noisy and caps AUC near 0.8, and adding semantic (GloVe) plot matching as extra features changed nothing (AUC 0.748 → 0.749). The recall on reviews written in a new style can be lower than on the IMDB data it was tuned on: on the 24 spoiler-containing made-up reviews, 58% were flagged (46% blurred), with none of the 16 clean ones touched, because reworded spoilers look like clean text to a word-based model.

**Stress test and the semantic layer.** `eval_adversarial.bat` runs 101 hand-written reviews (set A) and 63 more written afterwards (set B): spoilers hidden behind euphemism, slang and typos, Hinglish, questions, emotional reactions, hindsight ("on a rewatch, knowing he was dead..."), character fates, sarcasm, one sentence buried in a long review, plus clean reviews that sound spoilery ("no spoilers, but the ending is devastating"). It found that the trained models did not understand what a review discloses: they flagged 7 of 67 (set A) and 2 of 38 (set B) disguised spoilers, and the model's score on set A was no better than plain review length (AUC 0.73 vs 0.72). So the layer was added that actually compares meaning: **semantic plot match** (`app/spoiler/semantic.py`). Every review sentence and every plot sentence is embedded with a small public sentence encoder (all-MiniLM-L6-v2, Apache-2.0, int8 ONNX, 23 MB, a classifier of meaning, not a text generator) and a review sentence is hard evidence if it is close to something in the SECOND HALF of the plot (the first half, a premise recap, carried no signal: AUC 0.49). Cut-offs come from real clean IMDB reviews (`calibrate_semantic.bat`): 3% of short clean reviews would be blurred, 10% would get the label. Needs `pip install onnxruntime tokenizers`; without them the layer is off and nothing else changes.

| (full shield) | before | after | clean reviews wrongly flagged |
|---|---|---|---|
| Set A, disguised spoilers blurred / flagged | 2 / 7 of 67 | 16 / 27 of 67 | 1 blurred, 3 flagged of 34 |
| Set B (fresh), blurred / flagged | 1 / 2 of 38 | 7 / 10 of 38 | 0 blurred, 2 flagged of 25 |
| Real short clean IMDB reviews blurred / flagged | 2.4% / 12.2% | 5.4% / 22.4% | (this row is the cost) |

That is 3-4 times as many caught, not 8 in 10. A learned combiner of every signal (model, rules, semantic match) trained on set A and tested on set B reaches AUC 0.82-0.84 and, at the false-flag rate of real clean reviews, flags only about 10-25%: the zero-shot encoder is the ceiling until the matching is *trained* on real labelled examples. The two limits to know: (1) set A and B are written by me and share my style, so real reviews will behave differently; (2) the IMDB "clean" reviews used for the false-flag rate may contain unflagged spoilers, which makes the cost look higher than it is. Moderator decisions (blur / approve) are the labelled data that will fix this; they are stored with every review.

**Testing with made-up reviews.** `spoiler_test.bat` (or `python -m scripts.seed_spoiler_test`) adds 44 hand-labelled reviews from `garbage01@cinelog.dev` onwards (clean, spoilers, paraphrased spoilers, mixed, writer-tagged, vague) on the demo films, scans them with the real shield and prints which were blurred, sent to moderators or missed, plus a check that blurred text never reaches a stranger. `spoiler_test.bat --clean` removes them. It is a smoke test with my own wording, not an accuracy measurement.

> **Status of the models.** Out of the box the shield runs layers 1–4 (rules + RAG). Layers 5–6 need you to train them on the Kaggle data (below). The training code was only run on synthetic data in the build environment, so **real accuracy is unknown until you run it**; `ml.train_ml` writes `metrics.json` with ablations and `ml.eval_shield` reports held-out results.


**November update: what was checked and changed in the shield.** The whole shield was re-run, exactly as the site runs it, on 1,254 real
IMDB reviews of films the models never saw (`python -m ml.eval_real_reviews`, output in `backend/logs/eval_real_reviews.txt`).
Three things came out of it.

1. *The semantic layer was blurring long clean reviews at chance level.* Its cut-off was set on short reviews (6 sentences or fewer,
   3% of clean ones over it) but applied to reviews of any length. A 20-sentence review has 20 tries at matching the late plot, so
   12% of long clean reviews crossed it, and the reviews it blurred on its own were spoilers no more often than average. The cut-off
   now rises with the number of sentences (the calibration script stores the tail of the per-sentence score on clean reviews and the
   shield reads the matching value), which keeps the share of clean reviews over it near 3% at every length: 2.3% of long clean
   reviews of unseen films, down from 12.0%.
2. *A plot with a single sentence made the layer fail on every scan of that film* (caught and logged, so the scan continued without
   it). A one-sentence plot is a premise and has no late part; the layer now returns zero for it.
3. *One-line giveaways such as "Bruce Willis was dead the whole time" were shown untouched*, because the trained model scores short
   reviews low and the word rules are gated by it. A short review (6 sentences or fewer) in which one sentence pairs an outright
   fate or identity statement with a character or actor name now goes to a moderator. It never blurs by itself.

| Real reviews of unseen films (test split, 1,254 reviews) | Before | After |
|---|---|---|
| Clean reviews wrongly blurred | 17.0% | **12.0%** |
| IMDB-flagged spoiler reviews blurred | 59.1% | 53.7% |
| Share of blurred reviews that are flagged spoilers | 54% | **60%** |
| Clean reviews sent to moderators | 6.9% | 8.3% |

So the change trades about five points of catches for five points fewer wrong blurs, and the blurs that remain are right more often.
On the hand-written stress sets the full shield now blurs 14 of 67 disguised spoilers on set A (was 16) and 7 of 38 on set B (same),
flags 27 and 10 (was 24 and 10; the stress test now also passes actor names to the shield, as the site does), and still blurs none of the 34 spoiler-looking clean reviews of set A and 2 of 25 on set B (same).
The targets of NFR-02 (85% or more caught, 10% or fewer wrongly blurred) are still not met: wrong blurs are close on short and
medium reviews (3.9% and 9.2%) but 29.5% on reviews of 18 sentences or more, and that part comes from the trained model itself.
IMDB's spoiler flag is set by each review's author and is noisy, so these numbers compare versions of the shield; they are not exact accuracy.

## Roles in action, and what makes it worth coming back to

Access control is the theme, so every new feature is tied to a role (Admin > Permissions shows the live table the server enforces).

| Role | What it unlocks |
|---|---|
| Viewer | Year in review (`/me/year`: persona, charts, top films, shareable text, print to PDF), yearly goal with pace, recommendations with reasons, taste match on other people's profiles, friends who watched on each film, film of the day, spoiler-safe reading |
| Critic | Applied for, never self-assigned: a viewer with 5 films and 1 review applies, a moderator decides. Gets a Critic badge, a separate critic score beside the viewer score on each film, and can publish a pick (shown on the film page and on Home) |
| Convener | Club Insights tab (turnout, RSVPs, weekly posts, how members rated the club's films) and a Calendar tab with an `.ics` export for phone calendars |
| Moderator | Notes on every decision (sent to the author, kept in the audit log), warnings and mutes, critic applications, a desk-stats tab, and `/moderation/labels`, which exports every decision as a labelled training example |
| Admin | Permission matrix page, role changes with a reason (logged and sent to the person), role history |

Rules the code enforces, all covered by tests: nobody can decide their own critic application; a moderator cannot sanction an equal or higher role; three warnings in 30 days mute the account for three days; a mute blocks new reviews and club posts but not logging or rating; club roles are separate from site roles (a site moderator gets no analytics in someone else's club).

Recommendations are content-based (genres, keywords, top cast, decade, weighted by your ratings, nudged by friends' ratings), with no language model. They need a catalogue with more films than you have seen: run Admin > Sync from TMDB. `python -m scripts.seed_demo` now also seeds a year of viewing, critic picks, a pending critic application (`pat@cinelog.dev`) and a closed poll with a past watch-along, so every screen has something to show.

## Frontend design

The interface follows the supplied CineLog design: cream paper, ink outlines with hard drop shadows, pill controls, rotated
stickers, Cormorant Garamond + Lora (self-hosted in `frontend/public/fonts`), and generated colour-block posters when a film has
no TMDB poster. Screens: Home, Discover, Film, Your CineLog (dashboard), Profile, Feed, Clubs, Club, plus Moderation and Admin.

Lists, likes, badges, streaks, club discussion threads and watch-along RSVPs are all backed by real tables and endpoints.

## Adding to it later

- **A new badge:** add one `Badge(...)` line to `BADGES` in `backend/app/gamification.py` (name, description, metric, target, colour).
  Progress bars, the profile shelf, the feed and the "Badge earned" toast pick it up without other changes.
- **A new thing to count:** write a function with `@metric("name")` in the same file and point a badge at it.
- **A new likeable thing:** add its kind to `LIKE_KINDS` in `backend/app/models.py` and one branch in `_like_target`
  (`backend/app/routers/community.py`); the frontend `LikeBtn` already takes any kind.
- **A new feed activity:** append the item in `feed()` (`backend/app/routers/social.py`) and add a case to `describe()` in
  `frontend/src/pages/Feed.jsx`.
- New tables are created automatically on start. Changing an existing table's columns needs a migration (not set up).

## Run on your laptop (no Docker)

Needs Python 3.11+ and Node 20+.

```powershell
# 1. backend
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env            # optional; set TMDB_API_KEY here
python -m scripts.seed_demo       # optional demo data (11 films, 5 users, a club, a poll)
uvicorn app.main:create_app --factory --port 8000
# (or double-click backend\start_site.bat, which starts the API and the website together)

# 2. frontend (second terminal)
cd frontend
npm install
npm run dev                       # http://localhost:5173
```

Demo logins (after `seed_demo`, password `cinelog123`): `admin@`, `mod@`, `convener@`, `critic@`, `viewer@` + `cinelog.dev`.
Without the seed, just register: the first account is the admin.

Environment variables are read from the process environment (`.env.example` lists them). On Windows set them with `$env:TMDB_API_KEY="..."` before starting uvicorn.

## Speed

- `start_site.bat` runs the **pre-built** website and the API together on one port (http://localhost:8000). That is the fast way to use the site. `start_dev.bat` is the slower development mode (separate dev server on 5173); `rebuild_site.bat` rebuilds `frontend\dist` after front-end source changes.
- Page views use lock-free read transactions, so they never wait for background jobs (catalogue sync, review scans) that write; SQLite connections are pooled; responses are gzip-compressed.
- Searching for a film we don't have asks TMDB once, fetches the matches in parallel outside any database transaction, remembers the answer for 10 minutes, and backs off for 45 seconds if TMDB is unreachable, so a blocked network can't make every keystroke wait.
- `tests/test_speed.py` guards these properties (reads don't queue behind a writer, TMDB calls run in parallel and never freeze other pages, one-port serving).

## Real catalogue (TMDB + Wikipedia)

1. Get a free TMDB API key and set `TMDB_API_KEY`.
2. Sign in as admin → **Admin → System → Sync catalogue**. Popular films are imported; for each, the plot section is fetched from Wikipedia as spoiler context and character names become word-list terms.
3. Wikipedia text is CC BY-SA. It is used only as internal matching context and is never displayed.
4. For films without a Wikipedia plot, moderators/conveners can paste one (Admin → Spoiler word lists).

## Train the spoiler model

1. Download the **IMDB Spoiler Dataset** from Kaggle (`IMDB_reviews.json`, `IMDB_movie_details.json`).
2. In `backend`:
   ```powershell
   pip install pandas
   python -m ml.train_ml --reviews IMDB_reviews.json --movies IMDB_movie_details.json --out models
   python -m ml.eval_shield --reviews IMDB_reviews.json --movies IMDB_movie_details.json --models models
   ```
   Add `--max-reviews 100000` for a quicker first run. The split is **by movie** (80/10/10), so the test score reflects unseen films.
3. Restart the API (or Admin → System → Reload spoiler model). The System tab shows `ml: true`.
4. Optional: `python -m scripts.import_kaggle --movies IMDB_movie_details.json --limit 500` loads the Kaggle plot synopses as richer RAG context (needs the TMDB key to map IMDb ids to titles).
   After training, run `tune_shield.bat` (or `python -m ml.tune_shield ...`) to set the blur / moderator thresholds from the validation films. Its two arguments are the share of clean reviews you accept blurring and sending to moderators (default 0.08 and 0.15).
5. Recurrent layer: run `train_rnn.bat` (optionally with a review count, default 100000). It installs PyTorch if missing (training only), uses the GPU if it can, trains, then runs `ml.tune_shield` to measure and activate the blend. It writes `spoiler_rnn.npz`, `spoiler_rnn_vocab.json`, `spoiler_rnn_meta.json` into `models/` and prints the test numbers. Restart the site afterwards. Re-run `tune_shield.bat` after every retraining of the main model.
6. Optional deep model (off unless `USE_DL=true`; on the held-out films it scored lower than the ML model, so it is not used): `pip install torch transformers onnx onnxruntime tokenizers`, then `python -m ml.train_dl ...` (a free Colab GPU is enough). Copy the three `spoiler_dl*` files into `models/`.

## Docker (PostgreSQL)

```powershell
copy .env.example .env
docker compose up --build        # http://localhost:8080
```
Put trained model files in `backend/models/`. **PostgreSQL has not been tested in the build environment** (everything was tested on SQLite); expect to fix small things on first run.

## Accounts, notifications and upgrades

- **Forgot password:** Sign in → "Forgot your password?". A single-use link (valid 60 minutes, only its hash is stored) is e-mailed; with no `SMTP_*` set nothing leaves the machine, so the admin copies it from **Admin → Mailbox**. A reset or a password change signs out every other device. The form answers identically for unknown addresses and allows one e-mail per account per minute.
- **Notifications (bell):** likes, follows, thread replies, moderator decisions on your reviews, new badges and password changes. Read and unread, 60-day clean-up of read items.
- **Profile:** a short bio (300 characters) and a picture chosen from a fixed icon set. There are no file uploads on purpose: nothing to scan, store or moderate.
- **Database upgrades:** `backend/app/migrations.py` adds new columns to an existing `cinelog.db` on start-up and records them in `schema_version`, so updating the code never needs a database reset. To change the schema later, add the column to the model and append a numbered step to `MIGRATIONS`.

## Tests

```powershell
cd backend
pip install -r requirements-dev.txt
python -m pytest tests -q
```
98 tests cover speed guarantees, password reset, notifications, migrations, TMDB search fallback, the data structures, scheduler, security (rate limit, CSRF, forged tokens), RBAC, state machines, 100 concurrent votes with zero duplicates, WebSocket live results, the review/scan/blur/Reveal lifecycle, moderation, and the ML training/serving pipeline (on synthetic data).

## Known limits

- Hosting assumes one process (in-memory rate limits, WebSocket hub, job queue). Fine for a laptop; use a shared store and a real queue to scale out.
- Email is logged unless `SMTP_*` is set (the reset flow was tested with the dev mailbox, not a real SMTP server).
- Spoiler detection is a safety net, not a guarantee: paraphrased spoilers can slip through, and plain praise near a name can be over-blurred. The moderator queue and the report button exist for that reason.
