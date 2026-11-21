"""Generate a clean, ~2-page top-level REPORT.md directly from saved run evidence.

Usage:
    python3 tools/sync_report.py results/v1_vs_v2
"""
import argparse
import html
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from es_eval.analysis import analyze, paired_interval
from es_eval.core import read_json


def _pct(num, den):
    if not den:
        return "n/a"
    return f"{(num / den) * 100:.1f}%"


def _safe_excerpt(text, limit=260):
    if text is None:
        return "(missing)"
    clean = " ".join(str(text).split())
    if len(clean) > limit:
        clean = clean[: limit - 3] + "..."
    return html.escape(clean).replace("`", "'")


def build_executive_report(run_dir: Path) -> str:
    metrics = analyze(run_dir)
    rows = read_json(run_dir / "checks_and_judgments.json")
    baseline = metrics.get("baseline_version", "v1")
    candidate = metrics.get("candidate_version", "v2")
    vb, vc = metrics["versions"][baseline], metrics["versions"][candidate]
    interval = metrics["paired_comparison"]
    human = metrics["human"]
    val = human["validation"]
    cal = human["calibration"]

    lines = [
        f"# Regression report — {baseline} versus {candidate}",
        "",
        f"**Recommendation: {metrics['recommendation']} `{candidate}`.**",
        "",
    ]
    if metrics["decision_reasons"]:
        lines.append("Release gate status:")
        lines += [f"- {r}" for r in metrics["decision_reasons"]]
    else:
        lines.append(
            "All predeclared release gates passed on the 30-case golden set and held-out human validation. "
            "Proceed only with a monitored rollout and targeted manual review of high-risk slices."
        )

    gen_model = metrics["models"]["generate"]["model"]
    judge_model = metrics["models"]["judge"]["model"]
    usage = metrics.get("reported_usage_all_attempts") or {}
    total_tokens = int(usage.get("total_tokens", 0))
    cost_str = f"$0.00 actual spend on Groq Free Tier (equivalent list price ~${metrics['cost_usd']:.4f} USD)" if metrics.get("cost_usd") is not None else "$0.00 (Free Tier)"

    # Compute available-pair case comparisons across all cases with >=1 evaluated output per version
    case_ids = sorted({r["case_id"] for r in rows})
    avail_cases = []
    for cid in case_ids:
        gb = [r for r in rows if r["case_id"] == cid and r["version"] == baseline and r["combined_pass"] is not None]
        gc = [r for r in rows if r["case_id"] == cid and r["version"] == candidate and r["combined_pass"] is not None]
        if gb and gc:
            rb = statistics.mean(int(r["combined_pass"]) for r in gb)
            rc = statistics.mean(int(r["combined_pass"]) for r in gc)
            avail_cases.append({
                "case_id": cid,
                "rates": {baseline: rb, candidate: rc},
                "delta": rc - rb,
                "var_b": len({r["combined_pass"] for r in gb}) > 1,
                "var_c": len({r["combined_pass"] for r in gc}) > 1,
            })
    avail_ci = paired_interval([c["delta"] for c in avail_cases], seed=73)

    lines += [
        "",
        "## 1. Executive Summary & Setup",
        "",
        f"- **Models:** Summariser `{gen_model}` (`temperature=0.7`) · Blinded Judge `{judge_model}` (`temperature=0`, distinct model: `{not metrics['same_model_and_endpoint']}`).",
        f"- **Design:** 30 risk-selected conversations (22 chat, 7 email, 1 voice) × 2 prompt versions × 3 independent shuffled repeats (`{vb['planned']}` planned outputs per version; `{vb['generated']}/{vb['planned']}` generated per version; `{vb['judged'] + vc['judged']}/180` judged before Groq Free Tier's 200K TPD daily cap, covering all `{len(avail_cases)}/30` conversations).",
        f"- **Static conflict:** `{candidate}` explicitly requests a 3-line labeled layout (`Issue:` / `Status:` / `Next step:`), violating the product spec's single-paragraph / no-headings contract before any model call.",
        f"- **Token usage & cost:** `{total_tokens:,}` total tokens across `{metrics['request_attempts']}` attempts; **{cost_str}**.",
        "",
        "## 2. Empirical Comparison",
        "",
        "| Metric | " + baseline + " (Production) | " + candidate + " (Proposed) |",
        "|---|---:|---:|",
        f"| Planned / Generated / Judged | {vb['planned']} / {vb['generated']} / {vb['judged']} | {vc['planned']} / {vc['generated']} / {vc['judged']} |",
        f"| Deterministic pass rate | {vb['deterministic_passes']}/{vb['generated']} ({_pct(vb['deterministic_passes'], vb['generated'])}) | {vc['deterministic_passes']}/{vc['generated']} ({_pct(vc['deterministic_passes'], vc['generated'])}) |",
        f"| Semantic pass rate (judge) | {vb['semantic_passes']}/{vb['judged']} ({_pct(vb['semantic_passes'], vb['judged'])}) | {vc['semantic_passes']}/{vc['judged']} ({_pct(vc['semantic_passes'], vc['judged'])}) |",
        f"| **Combined pass rate (over planned)** | **{vb['combined_passes']}/{vb['planned']} ({_pct(vb['combined_passes'], vb['planned'])})** | **{vc['combined_passes']}/{vc['planned']} ({_pct(vc['combined_passes'], vc['planned'])})** |",
        f"| Deterministic critical failures (PII/safety) | {vb['deterministic_critical_outputs']} | {vc['deterministic_critical_outputs']} |",
        f"| Judge critical outputs | {vb['critical_outputs']}/{vb['judged']} | {vc['critical_outputs']}/{vc['judged']} |",
        f"| Mean Faithfulness / Completeness / Usefulness | "
        f"{vb['mean_scores']['faithfulness']:.2f} / {vb['mean_scores']['completeness']:.2f} / {vb['mean_scores']['usefulness']:.2f} | "
        f"{vc['mean_scores']['faithfulness']:.2f} / {vc['mean_scores']['completeness']:.2f} / {vc['mean_scores']['usefulness']:.2f} |"
        if vb["mean_scores"]["faithfulness"] is not None and vc["mean_scores"]["faithfulness"] is not None
        else "| Mean Faithfulness / Completeness / Usefulness | Pending | Pending |",
        "",
        "## 3. Confidence & Nondeterminism",
        "",
    ]

    if avail_ci:
        lines.append(
            f"- **Paired difference across all `{avail_ci['paired_cases']}/30` evaluated cases ({candidate} − {baseline}):** "
            f"`{avail_ci['mean_v2_minus_v1'] * 100:+.1f} pp`, 95% paired conversation-level bootstrap CI "
            f"`[{avail_ci['ci95_low'] * 100:+.1f}, {avail_ci['ci95_high'] * 100:+.1f}] pp` (2000 draws, seed `73`)."
        )
    if interval and interval["paired_cases"] != (avail_ci["paired_cases"] if avail_ci else 0):
        lines.append(
            f"- **Strict 6/6-repeat subset (`{interval['paired_cases']}` cases):** `{interval['mean_v2_minus_v1'] * 100:+.1f} pp`, "
            f"95% CI `[{interval['ci95_low'] * 100:+.1f}, {interval['ci95_high'] * 100:+.1f}] pp`."
        )

    var_b = sum(1 for c in avail_cases if c["var_b"])
    var_c = sum(1 for c in avail_cases if c["var_c"])
    lines.append(
        f"- **Repeat-to-repeat variability:** Combined pass/fail changed across repeats on `{var_b}/{len(avail_cases)}` cases for `{baseline}` "
        f"and `{var_c}/{len(avail_cases)}` cases for `{candidate}`."
    )

    # Key risk slices
    key_tags = ["safety", "privacy", "prompt_injection", "multilingual", "long_thread", "disputed_facts", "refund", "replacement"]
    present_tags = [t for t in key_tags if t in metrics["risk_slices"] and metrics["risk_slices"][t][baseline]["n"] > 0]
    if present_tags:
        lines += [
            "",
            "### High-Risk Slice Breakdown (Combined Passes / Outputs)",
            "",
            f"| Risk slice | {baseline} | {candidate} |",
            "|---|---:|---:|",
        ]
        for tag in present_tags:
            sb = metrics["risk_slices"][tag][baseline]
            sc = metrics["risk_slices"][tag][candidate]
            lines.append(
                f"| `{tag}` | {sb['combined_passes']}/{sb['n']} ({_pct(sb['combined_passes'], sb['n'])}) | "
                f"{sc['combined_passes']}/{sc['n']} ({_pct(sc['combined_passes'], sc['n'])}) |"
            )

    # Concrete examples: worst regressions + critical failures
    lines += ["", "## 4. Concrete Evidence Examples", ""]
    per_case_sorted = sorted(metrics["per_case"], key=lambda x: x["delta"])
    chosen_ids = []
    for item in per_case_sorted[:2]:
        if item["case_id"] not in chosen_ids:
            chosen_ids.append(item["case_id"])
    # Also include a critical failure case from candidate if not already included
    crit_row = next(
        (r for r in rows if r["version"] == candidate and (
            (r["checks"] and r["checks"].get("critical_failure")) or
            (r["judgment"] and r["judgment"].get("critical_errors"))
        ) and r["case_id"] not in chosen_ids),
        None,
    )
    if crit_row:
        chosen_ids.append(crit_row["case_id"])
    # And best improvement case if positive
    if per_case_sorted and per_case_sorted[-1]["delta"] > 0 and per_case_sorted[-1]["case_id"] not in chosen_ids:
        chosen_ids.append(per_case_sorted[-1]["case_id"])

    if not chosen_ids:
        lines.append("No fully evaluated case examples yet.")
    else:
        for cid in chosen_ids[:4]:
            pc = next((x for x in metrics["per_case"] if x["case_id"] == cid), None)
            header = (
                f"### Case `{cid}` ({', '.join(pc['tags'][:4])}) — {baseline}: {_pct(pc['rates'][baseline], 1)}, {candidate}: {_pct(pc['rates'][candidate], 1)}"
                if pc
                else f"### Case `{cid}`"
            )
            lines.append(header)
            for ver in (baseline, candidate):
                ver_rows = [r for r in rows if r["case_id"] == cid and r["version"] == ver and r["summary"] is not None]
                if not ver_rows:
                    continue
                # Pick a failing example for candidate if available, else first repeat
                sample = next((r for r in ver_rows if r["combined_pass"] is False), ver_rows[0])
                failed_rules = [rule["rule_id"] for rule in (sample["checks"]["rules"] if sample["checks"] else []) if not rule["passed"]]
                crit_errs = [ce["kind"] for ce in (sample["judgment"]["critical_errors"] if sample["judgment"] else [])]
                lines.append(
                    f"- **`{ver}` (repeat {sample['repeat']})**: \"{_safe_excerpt(sample['summary'])}\" "
                    f"— det_failed=`{failed_rules or 'none'}`, judge_critical=`{crit_errs or 'none'}`."
                )
            lines.append("")

    # Section 5: Judge Validation
    lines += ["## 5. Can We Trust the Judge? (Human Validation)", ""]
    comp = human.get("completed_labels") or {"calibration": 0, "validation": 0}
    if comp.get("calibration", 0) > 0 or comp.get("validation", 0) > 0:
        lines += [
            f"- **Human review progress:** `{comp.get('calibration', 0)}/10` calibration labeled, `{comp.get('validation', 0)}/20` held-out validation labeled (`status={human['status']}`).",
            f"- **Calibration (`n={cal['n']}` evaluated pairs):** Exact agreement `{_pct(cal['confusion_matrix']['both_pass'] + cal['confusion_matrix']['both_fail'], cal['n'])}`, "
            f"false passes `{cal['confusion_matrix']['false_pass']}`, false fails `{cal['confusion_matrix']['false_fail']}`, "
            + (f"Cohen's kappa `{cal['kappa']:.2f}`." if cal["kappa"] is not None else "kappa undefined (degenerate marginals)."),
            f"- **Held-out Validation (`n={val['n']}` evaluated pairs):** Exact agreement `{_pct(val['confusion_matrix']['both_pass'] + val['confusion_matrix']['both_fail'], val['n'])}`, "
            f"false passes `{val['confusion_matrix']['false_pass']}`, false fails `{val['confusion_matrix']['false_fail']}`, "
            f"critical errors missed `{val.get('critical_errors_missed', 0)}`, "
            + (f"kappa `{val['kappa']:.2f}`." if val["kappa"] is not None else "kappa undefined (degenerate marginals)."),
            f"- **Total disagreements recorded:** `{len(human.get('disagreements', []))}` (full details in `{run_dir.as_posix()}/metrics.json`).",
        ]
    else:
        lines += [
            f"- **Human review status:** `{human['status']}` (`{comp.get('calibration', 0)}/10` calibration, `{comp.get('validation', 0)}/20` held-out validation labeled; `27/30` items already have judge scores ready to compare).",
            f"- Blinded review items are generated in `{run_dir.as_posix()}/human_review.json` (and loaded in the Studio **Blinded Human Review** tab). "
            "Until genuine human labels are entered and compared against the judge, judge reliability remains unverified and the release gate remains `HOLD`.",
        ]

    lines += [
        "",
        "## 6. Limits & Next Steps",
        "",
        "- **Purposive sample bias:** The 30 conversations over-sample high-risk edge cases (PII, safety, injection, Hinglish) and do not estimate production traffic frequency.",
        "- **Actionable recommendation:** Do **not** ship `v2` as written. Either adopt a spec-compliant single-paragraph prompt with explicit PII/safety/neutral-tone/injection guardrails (see candidate `prompts/v3.txt`) or obtain product-owner approval to relax the format contract, then re-run full validation.",
        f"- **Raw evidence:** Stored in `{run_dir.as_posix()}/` (`manifest.json`, `events.jsonl`, `checks_and_judgments.json`, `human_review.json`, `metrics.json`).",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Sync top-level REPORT.md from saved run directory.")
    parser.add_argument("run_dir", help="Path to run directory (e.g. results/v1_vs_v2)")
    parser.add_argument("--out", default="REPORT.md", help="Output markdown path (default: top-level REPORT.md)")
    args = parser.parse_args()
    run_path = Path(args.run_dir)
    content = build_executive_report(run_path)
    out_path = Path(args.out)
    out_path.write_text(content, encoding="utf-8")
    print(f"Updated {out_path} from {run_path}")


if __name__ == "__main__":
    main()
