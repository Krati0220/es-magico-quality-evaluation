# Human review instructions

The assignment requires your own labels to check the LLM judge. None has been supplied yet. Do not have an AI fill these labels or copy the synthetic unit-test objects.

After full generation completes, open `runs/main/human_review.json`. It contains the actual spec, rubric, gap policies, conversation, expectations, summary, review phase and a null label. Do not view the companion key or judge results while labeling. Calibration and validation use disjoint source cases. Both versions appear, without version IDs; stylistic differences may still make them recognizable.

1. Personally label the 10 calibration outputs first, using the 1–5 rubric anchors.
2. Inspect calibration disagreements and decide if the judge/rubric needs adjustment. Do not tune against validation.
3. Freeze the judge, then personally label the 20 validation outputs.
4. If changing inputs/rubric/judge after calibration, use a new run and genuinely unseen validation cases. The runner rejects mixed configurations but cannot enforce what a human has already seen. Do not reuse a seen held-out set and still call it untouched.

For each label, enter your actual name/timestamp, `human_attestation: true`, integer scores `faithfulness`, `completeness`, `usefulness`, a `critical_errors` array (empty if none), and concise source-grounded `notes`. Leave unknown labels null. Example structure only:

```json
{
  "human_attestation": true,
  "reviewed_by": "YOUR_NAME",
  "reviewed_at": "ACTUAL_ISO_TIMESTAMP",
  "faithfulness": 1,
  "completeness": 1,
  "usefulness": 1,
  "critical_errors": ["Actual error description and source/summary evidence, or an empty array"],
  "notes": "Your own source-grounded assessment; do not copy these example scores"
}
```

Review final status and unsupported promises carefully. T30's double-refund promise is actually in the source; T39's combined benefit is not confirmed. Explicit safety omission and PII leakage are critical. Format/length have separate deterministic checks; do not lower semantic faithfulness solely because a summary uses headings.

Run `python3 -m es_eval analyze --out runs/main` after saving. It derives pass/fail using the same thresholds for judge and human, and reports calibration and held-out agreement separately. False pass means judge passed/human failed; false fail means judge failed/human passed. Inspect score errors, kappa, critical misses and concrete disagreements. Small or imbalanced samples limit confidence; kappa can be undefined. Human attestation records your assertion, not independent proof of who wrote a label.
