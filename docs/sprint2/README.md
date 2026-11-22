# Sprint 2 (Gate 3 / Review 4) — evidence

- **[SPRINT2_EVIDENCE.md](SPRINT2_EVIDENCE.md)**: the evidence pack, numbered like the Sprint 2 Student Handbook
  (team register, backlog, handoff, implementation, algorithms, API, database, concurrency/security, build/run/Git,
  test register, execution evidence, defects and retests, readiness, traceability, weekly record, checklist).
- **[traceability.csv](traceability.csv)**: requirement → engine → code → test → result → gap.
- **evidence/test_logs/**: every test run, kept in order: the first run with 3 test mistakes, the run before the fixes
  (6 failed), each retest, and the final full suite with coverage and JUnit XML.
- **evidence/api/api_exchanges.md**: 29 real HTTP exchanges with a running server.
- **evidence/algorithm_traces.txt**, **evidence/benchmarks.txt**, **evidence/db_state_after_api_run.txt**.
- **evidence/screenshots/**: the running site (01–09) and the test runs (10–12).
- **CineLog_Sprint2_Review.pptx**: the Sprint 2 Review deck.

## Reproduce everything

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest -v                                   # 188 passed, 1 skipped
python -m pytest -k tc_e1 -v                          # one engine at a time: tc_e1 / tc_e2 / tc_e3 / tc_e4
python -m scripts.sprint2_algorithm_trace
python -m scripts.sprint2_benchmarks

python -m scripts.seed_demo                           # demo database, logins *@cinelog.dev / cinelog123
(cd ../frontend && npm ci && npm run build)
SERVE_FRONTEND=1 uvicorn app.main:create_app --factory --port 8000      # site: http://localhost:8000
python -m scripts.sprint2_api_evidence http://localhost:8000/api ../docs/sprint2/evidence/api/api_exchanges.md
```

On Windows set the variable first: `$env:SERVE_FRONTEND="1"`.
