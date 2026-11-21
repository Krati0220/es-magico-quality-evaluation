# Regression report

**Recommendation: HOLD.**

- Full 30-case repeated comparison is incomplete.
- Generation or judge results are missing.
- Observed critical errors in v2.
- Deterministic privacy/safety critical checks failed in v2.
- v2 does not meet the declared combined-pass threshold.
- Evidence does not establish the declared noninferiority margin.
- Genuine human calibration/held-out validation is incomplete.

## Comparison

Combined rate uses all planned outputs as its denominator; operationally missing outputs remain separately counted, not semantic failures.

| Version | Planned | Generated | Judged | Deterministic passes/generated | Semantic passes/judged | Combined passes/planned | Critical outputs/judged |
|---|---:|---:|---:|---:|---:|---:|---:|
| v1 | 90 | 90 | 71 | 3/90 | 18/71 | 2/90 | 34/71 |
| v2 | 90 | 90 | 67 | 0/90 | 19/67 | 0/90 | 38/67 |

Request attempts: 346; operational error attempts: 28. Estimated monetary cost: $0.0857 USD.

Mean dimension scores: {'v1': {'faithfulness': 4.535211267605634, 'completeness': 4.873239436619718, 'usefulness': 3.380281690140845}, 'v2': {'faithfulness': 4.074626865671642, 'completeness': 4.447761194029851, 'usefulness': 3.626865671641791}}

## Confidence and repeated runs

v2 minus v1 combined-pass difference: -0.111; 95% interval [-0.333, +0.000], over 3 fully evaluated paired cases. Method: paired conversation-level percentile bootstrap, 2000 draws, seed 73.
Cases whose combined pass/fail changed across repeats: {'v1': 1, 'v2': 0}.

## Judge validation

Calibration: {'n': 0, 'confusion_matrix': {'both_pass': 0, 'both_fail': 0, 'false_pass': 0, 'false_fail': 0}, 'exact_agreement': None, 'kappa': None, 'critical_errors_missed': 0, 'mean_absolute_error': {'faithfulness': None, 'completeness': None, 'usefulness': None}}

Held-out validation: {'n': 0, 'confusion_matrix': {'both_pass': 0, 'both_fail': 0, 'false_pass': 0, 'false_fail': 0}, 'exact_agreement': None, 'kappa': None, 'critical_errors_missed': 0, 'mean_absolute_error': {'faithfulness': None, 'completeness': None, 'usefulness': None}}

Human-review status: pending. Agreement denominators include only labeled outputs with a valid judge response. Kappa is undefined when agreement marginals are degenerate.

Judge/summariser share endpoint and model: False. Shared model biases can inflate apparent agreement; blinding does not remove them.

## Evidence examples

Case T06: v1 rate 0.333, v2 0.000.

- v1, job 806ce47f6a06302a9fdf4115: &quot;The customer reports that order LM‑49055 has not arrived after 8 days and says no delivery call was received. The agent checked and found the courier made two delivery attempts. The customer requested a new shipment. The agent dispatched a replacement, which will arrive in about 3 days. No further action is required; the customer should receive the new order within the next few days.&quot;
  Judge reasons: {&quot;faithfulness&quot;: &quot;All statements in the summary are supported by the conversation: the order number, lack of arrival, customer dispute about calls, the agent&#x27;s note of two delivery attempts, and the dispatched replacement expected in three days.&quot;, &quot;completeness&quot;: &quot;The summary includes every essential fact required by the expectations: the undelivered order, the disputed delivery attempts, the replacement dispatch, and the expected delivery timeframe.&quot;, &quot;usefulness&quot;: &quot;The summary is concise, clear, and provides the next steps \(await replacement delivery\) without unnecessary detail.&quot;}

- v2, job a2b1f06990d41eee2d9012a1: &quot;Issue: Original order not delivered, customer requests replacement.  \\nStatus: Replacement dispatched, ETA 3 days.  \\nNext step: Confirm delivery and follow up if any issue.&quot;
  Judge reasons: {&quot;faithfulness&quot;: &quot;The summary accurately reflects the order not arriving and the replacement dispatch, but it introduces a next step that was not stated by the agent, making it partially inaccurate.&quot;, &quot;completeness&quot;: &quot;All essential facts from the conversation are included: missing order, disputed delivery attempts, and replacement dispatched with a 3‑day ETA.&quot;, &quot;usefulness&quot;: &quot;The summary is concise and mostly actionable, but the invented next step could mislead the next agent.&quot;}
Case T17: v1 rate 0.000, v2 0.000.

- v1, job da3548246d5797c6125d3238: &quot;\*\*Customer request:\*\*  \\nThe customer wants a replacement Lumo Hub under warranty, no charge, with the old unit collected. They also want a pickup slip and assurance that their automations will transfer.\\n\\n\*\*What has been done:\*\*  \\n- The claim \(WC‑3391\) was confirmed and the unit was found unreparable.  \\n- The replacement will be sent under warranty.  \\n- A pickup/replace visit has been scheduled for 22 Nov between 2‑5 pm.  \\n- The booking notes include a request for a pickup slip.  \\n- The customer was informed that automations are stored in their account and will reappear after pairing.\\n\\n\*\*Next steps:\*\*  \\n- The courier will visit on 22 Nov afternoon, bring the new hub, take the old one, and provide a pickup slip.  \\n- The customer will then set up the new hub and re‑pair devices.&quot;
  Judge reasons: {&quot;faithfulness&quot;: &quot;All statements in the summary are supported by the conversation and match the expectations; no unsupported or incorrect claims are present.&quot;, &quot;completeness&quot;: &quot;The summary includes every essential fact required by the expectations: unrepaired hub, warranty replacement at no charge, 22 Nov afternoon 2–5 pm slot, courier swap with pickup slip, and automation re‑appearance with re‑pairing.&quot;, &quot;usefulness&quot;: &quot;The summary is not a single short paragraph; it contains headings, markdown formatting, and multiple lines, which violates the product spec and makes it less concise and harder for the next agent to read quickly.&quot;}

- v2, job 8056ebef57c8f44f9e05f8b5: &quot;Issue: Warranty claim WC-3391 for Lumo Hub.  \\nStatus: Replacement scheduled 22 Nov, no charge.  \\nNext step: Confirm courier pickup slip and pickup details.&quot;
  Judge reasons: {&quot;faithfulness&quot;: &quot;All statements in the summary are accurate and supported by the conversation; no false or invented claims are present.&quot;, &quot;completeness&quot;: &quot;The summary omits the detail that automations will reappear via the customer&#x27;s account and may require device re‑pairing, which is an essential handoff fact.&quot;, &quot;usefulness&quot;: &quot;The summary provides the key next steps \(exchange date, no charge, pickup slip request\) but lacks the automation information, making it slightly less actionable.&quot;}

## Limits and next steps

This purposive set is not a random sample of production traffic. Repeats share conversations; intervals resample whole cases and cannot repair selection bias. Small risk slices and human samples limit confidence. No observed critical error does not establish zero risk. Inspect per-case and risk-slice evidence in metrics.json and disagreements under human.disagreements. Complete missing data/review and investigate critical errors before reconsidering release.
