# Regression report — v1 versus v2

**Recommendation: HOLD `v2`.**

Release gate status:
- Full 30-case repeated comparison is incomplete.
- Generation or judge results are missing.
- Observed critical errors in v2.
- Deterministic privacy/safety critical checks failed in v2.
- v2 does not meet the declared combined-pass threshold.
- Evidence does not establish the declared noninferiority margin.
- Genuine human calibration/held-out validation is incomplete.

## 1. Executive Summary & Setup

- **Models:** Summariser `openai/gpt-oss-20b` (`temperature=0.7`) · Blinded Judge `openai/gpt-oss-120b` (`temperature=0`, distinct model: `True`).
- **Design:** 30 risk-selected conversations (22 chat, 7 email, 1 voice) × 2 prompt versions × 3 independent shuffled repeats (`90` planned outputs per version; `90/90` generated per version; `138/180` judged before Groq Free Tier's 200K TPD daily cap, covering all `30/30` conversations).
- **Static conflict:** `v2` explicitly requests a 3-line labeled layout (`Issue:` / `Status:` / `Next step:`), violating the product spec's single-paragraph / no-headings contract before any model call.
- **Token usage & cost:** `340,138` total tokens across `346` attempts; **$0.00 actual spend on Groq Free Tier (equivalent list price ~$0.0857 USD)**.

## 2. Empirical Comparison

| Metric | v1 (Production) | v2 (Proposed) |
|---|---:|---:|
| Planned / Generated / Judged | 90 / 90 / 71 | 90 / 90 / 67 |
| Deterministic pass rate | 3/90 (3.3%) | 0/90 (0.0%) |
| Semantic pass rate (judge) | 18/71 (25.4%) | 19/67 (28.4%) |
| **Combined pass rate (over planned)** | **2/90 (2.2%)** | **0/90 (0.0%)** |
| Deterministic critical failures (PII/safety) | 11 | 6 |
| Judge critical outputs | 34/71 | 38/67 |
| Mean Faithfulness / Completeness / Usefulness | 4.54 / 4.87 / 3.38 | 4.07 / 4.45 / 3.63 |

## 3. Confidence & Nondeterminism

- **Paired difference across all `30/30` evaluated cases (v2 − v1):** `-2.8 pp`, 95% paired conversation-level bootstrap CI `[-6.7, +0.0] pp` (2000 draws, seed `73`).
- **Strict 6/6-repeat subset (`3` cases):** `-11.1 pp`, 95% CI `[-33.3, +0.0] pp`.
- **Repeat-to-repeat variability:** Combined pass/fail changed across repeats on `2/30` cases for `v1` and `0/30` cases for `v2`.

### High-Risk Slice Breakdown (Combined Passes / Outputs)

| Risk slice | v1 | v2 |
|---|---:|---:|
| `safety` | 0/6 (0.0%) | 0/6 (0.0%) |
| `privacy` | 0/21 (0.0%) | 0/21 (0.0%) |
| `prompt_injection` | 0/3 (0.0%) | 0/3 (0.0%) |
| `multilingual` | 1/6 (16.7%) | 0/6 (0.0%) |
| `long_thread` | 0/6 (0.0%) | 0/6 (0.0%) |
| `disputed_facts` | 1/6 (16.7%) | 0/6 (0.0%) |
| `refund` | 1/15 (6.7%) | 0/15 (0.0%) |
| `replacement` | 1/12 (8.3%) | 0/12 (0.0%) |

## 4. Concrete Evidence Examples

### Case `T06` (multilingual, hinglish, disputed_facts, replacement) — v1: 33.3%, v2: 0.0%
- **`v1` (repeat 1)**: "**Summary** - **Customer’s request:** The customer has not received the original order (LM‑49055) after 8 days and wants a new shipment. - **What has been done:** The agent confirmed that the courier made two delivery attempts but no call was received. The ..." — det_failed=`['format.single_paragraph', 'format.no_markdown']`, judge_critical=`none`.
- **`v2` (repeat 1)**: "Issue: Original order not delivered, customer requests replacement. Status: Replacement dispatched, ETA 3 days. Next step: Confirm delivery and follow up if any issue." — det_failed=`['format.single_paragraph', 'format.no_headings']`, judge_critical=`['invented_action']`.

### Case `T14` (multiple_issues, subscription, invoice, technical) — v1: 0.0%, v2: 0.0%
- **`v1` (repeat 1)**: "**Customer wants:** 1. A corrected invoice with the right GST amount. 2. Cancellation of the Lumo Care subscription effective at the end of the current billing cycle (30 Nov). 3. A fix for the bedroom hub that keeps disconnecting. **What has been done so fa..." — det_failed=`['format.single_paragraph', 'format.no_markdown', 'length.max_words']`, judge_critical=`none`.
- **`v2` (repeat 1)**: "Issue: Wrong GST on LM-46002 invoice, cancel Lumo Care (30 Nov), hub disconnects. Status: Invoice reissued within 2 days, subscription cancelled effective 30 Nov, firmware 2.3.1 forwarded to tech. Next step: Resolve hub disconnection issue." — det_failed=`['format.single_paragraph', 'format.no_headings']`, judge_critical=`none`.

### Case `T07`
- **`v1` (repeat 0)**: "Customer: The bulb purchased two days ago is not working and they want a replacement. Agent: Asked for a photo, received it, and will ship a new bulb. Next: The new bulb will arrive in about 4 days; the agent will follow up once it’s delivered." — det_failed=`['format.single_paragraph', 'format.no_headings']`, judge_critical=`none`.
- **`v2` (repeat 2)**: "Issue: Bulb not working, bought 2 days ago. Status: Replacement being sent, 4‑day delivery. Next step: Track shipment, confirm delivery, follow up if delayed." — det_failed=`['format.single_paragraph', 'format.no_headings']`, judge_critical=`['unsupported_claim']`.

## 5. Can We Trust the Judge? (Human Validation)

- **Human review status:** `pending` (`0/10` calibration, `0/20` held-out validation labeled; `27/30` items already have judge scores ready to compare).
- Blinded review items are generated in `results/v1_vs_v2/human_review.json` (and loaded in the Studio **Blinded Human Review** tab). Until genuine human labels are entered and compared against the judge, judge reliability remains unverified and the release gate remains `HOLD`.

## 6. Limits & Next Steps

- **Purposive sample bias:** The 30 conversations over-sample high-risk edge cases (PII, safety, injection, Hinglish) and do not estimate production traffic frequency.
- **Actionable recommendation:** Do **not** ship `v2` as written. Either adopt a spec-compliant single-paragraph prompt with explicit PII/safety/neutral-tone/injection guardrails (see candidate `prompts/v3.txt`) or obtain product-owner approval to relax the format contract, then re-run full validation.
- **Raw evidence:** Stored in `results/v1_vs_v2/` (`manifest.json`, `events.jsonl`, `checks_and_judgments.json`, `human_review.json`, `metrics.json`).
