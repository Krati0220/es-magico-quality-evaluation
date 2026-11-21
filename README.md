# Es Magico — Support handoff regression evaluation

This repository evaluates the supplied `v1` (production) and `v2` (proposed) support-handoff prompts — plus a spec-compliant `v3` candidate — against the verbatim product spec. It includes:
1. **Zero-dependency Python evaluation CLI (`es_eval/`)** with deterministic format/length/PII/safety/tone checks, a blinded semantic LLM judge, paired conversation-level bootstrap analysis, and a case-disjoint blinded human-review workflow.
2. **Interactive Web Studio (`backend/` FastAPI + `frontend/` React/Vite)** ready for **Render + Vercel** deployment, providing a Golden Set Explorer, Live Playground, background Evaluation Run Dashboard, Blinded Human Review UI, and one-click deliverable export.

## Quick start (Web Studio)

See [DEPLOYMENT.md](DEPLOYMENT.md) for full Render + Vercel setup. Locally:

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example .env   # add your Groq / OpenAI-compatible API key
uvicorn backend.app:app --reload --port 8000
```

In a second terminal:

```sh
cd frontend && npm install && npm run dev
```

Open `http://localhost:5173`. Any saved runs in `results/` load automatically into the Studio.

## Quick start (CLI only)

Python 3.10+ and the standard library are sufficient for the core CLI. From this folder:

```sh
python3 -m es_eval validate
python3 -m es_eval estimate
python3 tools/audit_inputs.py
python3 -m unittest discover -s tests -v
```

These commands make no model calls. `estimate` plans 180 summary calls and 180 judge calls (30 × 2 × 3 repeats). A maximum of three attempts per operation caps the full run at 1,080 requests. Retry usage may cost more; provider pricing and dollar cost are unknown until a model is chosen.

The static audit already found a release blocker: v2 explicitly requests three labeled lines, while the product requires one plain paragraph with no headings. This does not measure model failure rates. Neither prompt explicitly includes all privacy/safety/tone safeguards; behavioral differences remain unmeasured.

## Configure a model locally

```sh
cp .env.example .env
```

Edit `.env` to set `LLM_BASE_URL`, `LLM_MODEL`, and `LLM_API_KEY` when required by the provider. Use an OpenAI-compatible chat endpoint; a compatible local server is also supported. No model credentials or local model runtime were available during this implementation. Do not paste secrets into chat, commit `.env`, or include it in the submission.

The CLI reads literal settings from `.env` (or `--env-file PATH`); existing environment variables win. It never evaluates shell syntax or expands values. Optional `JUDGE_BASE_URL`, `JUDGE_MODEL`, and `JUDGE_API_KEY` override summariser defaults. A shared model is permitted but has correlated-bias limitations.

```sh
python3 -m es_eval preflight
```

Preflight validates configuration without sending requests. It is not a connectivity, quota, or pricing check. With missing configuration it exits clearly before model calls. Review the chosen provider and cost before running the smoke/full commands.

## Smoke, generation, judge, and resume

```sh
python3 -m es_eval run --smoke --out runs/smoke --allow-model-calls
python3 -m es_eval analyze --out runs/smoke
python3 -m es_eval run --stage generate --out runs/main --allow-model-calls
python3 -m es_eval run --stage judge --out runs/main --allow-model-calls
python3 -m es_eval analyze --out runs/main
```

Smoke uses T23 (safety) and T03 (phone/email privacy), with three repeats per version: 12 generation and 12 judge calls before retries. Its results cannot authorize release.

Repeat the exact run command to resume. Matching successful results are reused; retries have a total cap across resumptions. Changed spec, cases, prompts, rubric/config, model, endpoint, or scope require a new run directory. One writer is allowed at a time. Following a crashed process, verify no writer remains before manually removing a stale `.run.lock`. Corrupt logs stop analysis rather than being silently skipped.

Both versions use the starter's exact prompt stripping, channel/role rendering and user-message prefix. The generation temperature is 0.7 for both. No generation token cap is sent, matching the starter request; the local `max_tokens` setting is inactive when `send_generation_max_tokens` is false. The judge uses temperature 0 and a 1,400-token cap. Confirm that the chosen endpoint supports these fields rather than silently dropping them.

## Human review and offline reporting

When all planned summaries are saved, the runner creates `human_review.json` and a separate analysis key. The full-run review plan is fixed before outputs: both versions of five calibration cases (10 labels), and both versions of ten different validation cases (20 labels). One repeat per case/version is selected reproducibly without inspecting judge ratings. The annotation file has no version or judge labels; stylistic differences may still make version inference possible.

Follow HUMAN_REVIEW.md. You must personally label the outputs. AI-generated test labels exist only inside temporary software tests and are not annotation evidence. If the judge/rubric changes after calibration, use a new run and genuinely untouched validation cases. Do not tune against a reused held-out set.

Offline `analyze` makes no model requests and regenerates:

- `checks_and_judgments.json`: per-output deterministic checks, semantic scores and pass states.
- `metrics.json`: valid-output denominators, operational failures, version/case/risk comparisons, variability, paired uncertainty, and human agreement/disagreements.
- `REPORT.md`: evidence-derived comparison report and qualified ship/hold decision.

After actual model execution and human validation, review the generated full-run report, explain important examples and disagreements, and copy it to the top-level REPORT.md together with the referenced run records. The current top-level report contains static findings and clearly marks missing evidence.

## Data and provenance

`starter/` preserves the original README, code, prompts and all 45 synthetic threads; `SOURCE_MANIFEST.json` records their byte hashes. `data/product_spec.md` copies the product-owner section verbatim. `data/golden.json` contains 30 source-grounded cases with selection rationale, risk tags, semantic expectations, uncertainties, final state and sensitive spans. The other 15 remain in `data/unselected.json`. Rebuild the same curated set with:

```sh
python3 tools/build_golden.py
```

This reconstructs the documented annotations; it does not generate reference summaries, model outputs, or human labels. Each source conversation matches the starter rendering, verified by tests. See GOLDEN_SET.md for coverage and gaps.

## Rules and audit trail

The actual spec governs checks. Evaluator assumptions are explicit: English summaries; at most 80 Unicode-whitespace words; no internal line breaks; no common heading/Markdown syntax; conservative omission of card suffixes, identifying address fragments and full customer names. Source-aware normalized sensitive spans supplement generic email/phone/card patterns. Safety-tagged cases require an electrical hazard/damage signal. These heuristics have false-positive/negative limits, so the judge also checks semantics.

`manifest.json` snapshots inputs, settings, prompts, models/endpoints, schedule and fingerprint. `events.jsonl` saves every attempt, raw output (including malformed judge output), request hash, settings, timestamps, latency, finish reason, and token usage if supplied. Secrets and provider error bodies are excluded. Valid generation text is retained before judging/checking. Missing calls or invalid judge schemas are operational failures, never silent passes or invented semantic scores.

The bootstrap resamples paired conversation-level deltas, keeping repeats together. A purposively selected 30-case set and a 20-output validation sample cannot establish population-wide safety. `NOTES.md` defines the predeclared release gates and omissions.

Keep everything private. The archive excludes `.env`, virtual environments and caches. Never present synthetic test success, static prompt inspection, or an unvalidated judge as a completed regression evaluation.
