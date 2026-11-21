# Requirements and readiness

| Assignment requirement | Artifact | Status |
|---|---|---|
| Read starter/spec/prompts/45 threads | Unchanged `starter/`, source hashes, copied product spec | Complete; byte/rendering parity tested |
| 30 golden cases with expectations | `data/golden.json`, GOLDEN_SET.md, builder | Complete; AI-assisted source annotations, not human labels |
| Format, length, banned-content checks | `es_eval/core.py`, config | Implemented and boundary/false-alarm tested |
| Semantic LLM judge | Versioned judge prompt, schema validation, runner | Implemented; no live judgments yet |
| Handle nondeterminism | Repeated shuffled runs, per-case analysis/bootstrap | Implemented; real variability unmeasured |
| Check judge against own labels | Case-disjoint blinded review plan and agreement analysis | Ready; genuine labels pending |
| Compare v1/v2 and recommend | Offline metrics/report; current static conflict finding | Static HOLD supported; empirical comparison pending |
| Raw outputs/labels and re-runnable repo | Manifest, event log, README, CLI | Code ready; real outputs/labels absent until run/review |
| REPORT.md / NOTES.md | Included | Honest static/status report and predeclared decisions |
| Secrets/confidentiality/cost | Environment-only credentials, private package, usage logging | No public sharing, embedded credentials or paid calls |

The detailed implementation prompt adds optional choices such as three repeats and bootstrap analysis. Those remain subordinate to the original product spec. The live model and genuine human review are essential pending steps, not optional polish.
