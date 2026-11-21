# Regression report — v1 versus v2

**Recommendation: HOLD v2 as written.** Its explicit three-line, labeled layout conflicts with the product spec. This is a directly observable prompt/spec conflict, not an estimated model failure rate. Actual quality comparisons and judge validation are pending model access and genuine human labels.

## Evidence available

The starter's product-owner section requires “A single short paragraph. No lists, headings or markdown.” In `starter/prompts/v2.txt`, the proposed prompt asks for a one-line-each layout: `Issue:`, `Status:`, `Next step:`. Following v2 literally would violate the current format contract. V1 asks for brief plain sentences and does not prescribe this incompatible layout. The automated format checks reject a fixture using v2's requested structure; that fixture is a software test, not a sampled model response.

Both prompts omit explicit instructions covering all product privacy, safety and neutral-tone requirements. This motivates risk testing, but omission alone does not establish that either prompt leaks PII or that v2 is worse. V2's under-40-word goal may compress useful details in complex cases; whether it actually does remains a hypothesis.

## Evaluation design

Exactly 30 of the 45 supplied conversations were selected: 22 chats, 7 emails and 1 voice transcript. Each has a source-grounded selection reason, must/must-not expectations, final-state context and uncertainties. The other 15 remain separate. Key cases cover phone/email/address/card-suffix/OTP leakage, explicit and reported electrical hazards, prompt injection, reversals, disputed dates, long/multi-issue threads, Hindi/Hinglish, sparse context, conditional replacements, and implausible source-agent promises. Original code, data and prompts are preserved and hashed; tests verify matching message construction.

Plan: three independent generations for each case and version, interleaved in a seeded shuffle, using the same model and 0.7 temperature. This gives 180 summaries plus 180 semantic judge calls before retries. Deterministic checks enforce the actual format contract, an assumed 80-word ceiling, source-sensitive PII rules, a limited profanity lexicon and safety signals. The blinded judge checks faithfulness, essential completeness, usefulness, and material safety/privacy/status errors. Golden expectations permit paraphrase and do not invent missing facts.

The judge will be checked against 10 human calibration outputs and 20 validation outputs on disjoint source cases, balanced between versions. Pass/fail confusion matrices, false passes/fails, score error, kappa and critical misses will be reported. Case-level paired bootstrap analysis will keep repeats together; the risk-selected sample cannot establish production-wide safety.

## Empirical results: not yet available

| Evidence | v1 | v2 |
|---|---:|---:|
| Planned summary generations | 90 | 90 |
| Real summary outputs saved | 0 | 0 |
| Real judge outputs saved | 0 | 0 |
| Measured deterministic/semantic pass rates | Not available | Not available |
| Repeated-run variability or paired confidence interval | Not available | Not available |

Genuine human labels: 0; judge agreement and trust are unmeasured. There is no configured model endpoint/key or installed local runtime in the session. No paid calls occurred; future dollar cost is unknown. The software suite's synthetic outputs/labels do not enter these totals. Static findings are machine-readable in `data/static_audit.json`; coverage is in `data/coverage.json`.

## Release decision and next steps

Do not ship the current proposal against the current spec. Clarify whether the product owner intends a paragraph or changes the contract; keep original v1/v2 unchanged during their evaluation. If v2 is repaired, treat that as a new candidate rather than silently replacing the tested version. Configure a model, smoke-test T23/T03, run the repeated comparison, obtain genuine labels, and replace this pending-results section with evidence-derived metrics and concrete regressions/improvements.

Predeclared gates in NOTES.md require full evidence, zero observed v2 critical errors, at least 95% combined pass, a case-level lower confidence bound no worse than -5 points, and acceptable human validation. Passing supports only a qualified, monitored rollout. No claim is made that the current harness tests or static audit establish LLM reliability.
