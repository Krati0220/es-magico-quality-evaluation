# Golden set — selection and record format

All 45 supplied conversations were read. Exactly 30 were selected; none was invented. The selected set includes 22 chats, 7 emails and the sole voice transcript. It deliberately emphasizes consequential failures over representative traffic frequency.

| Coverage | Selected examples | Why it matters |
|---|---|---|
| Safety and emotional tone | T23, T08 | Burning/hot plug or reported electrical damage must survive compression; profanity must not |
| PII and privacy workflows | T03, T04, T05, T26, T28, T34, T42 | Phones/email, address, card suffix, OTP, signatures, third-party refusal, deletion exception |
| Prompt injection | T09 | Embedded instructions must not replace the handoff with a poem |
| Changed or contested facts | T15, T16, T39 | Latest reversal, conflicting dates, and supervisor confirmation |
| Multiple/long threads | T14, T17, T35 | Preserve important subcases and final commitments amid noise |
| Sparse and non-English sources | T11, T12, T06, T07, T27 | No invented issue; Hindi/Hinglish and voice transcription |
| Conditional and unusual promises | T02, T29, T30, T37 | Do not complete conditional steps or silently correct source-agent promises |
| Money and lifecycle state | T01, T25, T38 | Initiated/approved versus paid; correct net partial refund |
| Missing attachment contents | T32 | Filenames do not mean logs/images were inspected |
| Internal-note policy gap | T10 versus T37 | Explicitly do-not-disclose allegation excluded; relevant conditional eligibility retained |

Every case has stable `id`, full rendered `conversation`, original `thread`, source provenance, `selection_reason`, risk `tags`, `must_include`, `must_not_include`, `ambiguities`, `final_status`, `actions_taken`, `next_action`, `owner`, and optional typed `sensitive_spans`. Unknown values are null. Expectations are semantic, not an exact reference paragraph. Annotation origin is explicitly AI-assisted; these are not human judge-validation labels.

The source contains an inconsistency in T17: the hub was reportedly mailed to the service centre, but a later old/new-unit exchange is booked. Expectations preserve the final booking without inventing a location explanation. In T30, the agent really promises double refund; attributing that promise is faithful even if the policy seems implausible. T39 still awaits a supervisor decision, so no refund-plus-replacement entitlement is established.

The separate 15 cases are T13, T18, T19, T20, T21, T22, T24, T31, T33, T36, T40, T41, T43, T44, T45. This omits a dedicated spam example, praise/basic FAQs, consumer-court threat, invoice-backdating refusal, GSTIN handling, express-delivery upgrade, and some simpler cancellation/tracking/repeat-contact cases. Several partially overlap selected risks; they remain useful for a later extension. Full card numbers, many address styles, multilingual abuse and additional attack variations are not well covered by the supplied data. These gaps limit any safety claim.

Machine-readable IDs, channel totals and overlapping tag counts are in `data/coverage.json`. `tools/build_golden.py` reproduces the curated records from unchanged source threads. Owner/next-action fields describe supported handoff context; summaries must not invent completed actions from implied workflow responsibilities.
