# Verification record

Runtime: Python 3.14.6, standard library only. No live LLM endpoint called and no paid model usage initiated.

| Command | Observed result |
|---|---|
| `python3 -m unittest discover -s tests -v` | 29 offline tests passed |
| `python3 -m es_eval validate` | Valid 30-case inputs and configured evaluation rules |
| `python3 -m es_eval estimate` | 180 planned generations + 180 judge calls; 1,080 maximum attempts with retries |
| `python3 tools/audit_inputs.py` | 5 original files hash-verified; static v2 format conflict recorded; zero model requests |
| `python3 -m es_eval preflight` | Expected exit 2: LLM_BASE_URL/LLM_MODEL not configured; no model request |

The suite covers generic boundaries and persistence; exact 30/15 source partition; unchanged starter prompt/rendering parity; actual paragraph/heading/Markdown rules; allowed order/reference numbers and amounts; formatted/unformatted/spaced source phones, email, address fragments, OTP and card suffix; explicit safety signals; profanity false alarms; case-disjoint blinded review; literal env parsing; malformed judge schemas; operational failures; and offline full-flow metrics with synthetic annotation objects.

All artificial summaries/judgments/labels are test fixtures in temporary directories, not empirical assignment evidence. The real golden set uses actual supplied conversations and source-grounded AI-assisted expectations. Live model/provider compatibility, sampled v1/v2 behavior, model resistance to injection, and judge accuracy remain unverified. The injection software test verifies instruction/data separation only.
