"""Offline metrics/reporting. Analysis makes no model requests."""
import random
import statistics
import html
from pathlib import Path

from .core import DIMENSIONS, check_summary, read_json, semantic_pass, write_json
from .runner import read_events


def agreement(pairs):
    """Pairs are (human_pass, judge_pass). Positive means a quality pass."""
    counts = {"both_pass": 0, "both_fail": 0, "false_pass": 0, "false_fail": 0}
    for human, judge in pairs:
        key = "both_pass" if human and judge else "both_fail" if not human and not judge else "false_pass" if judge else "false_fail"
        counts[key] += 1
    n = len(pairs)
    if not n:
        return {"n": 0, "confusion_matrix": counts, "exact_agreement": None, "kappa": None}
    observed = (counts["both_pass"] + counts["both_fail"]) / n
    human_positive = (counts["both_pass"] + counts["false_fail"]) / n
    judge_positive = (counts["both_pass"] + counts["false_pass"]) / n
    expected = human_positive * judge_positive + (1 - human_positive) * (1 - judge_positive)
    human_fails = counts["both_fail"] + counts["false_pass"]
    human_passes = counts["both_pass"] + counts["false_fail"]
    return {"n": n, "confusion_matrix": counts, "exact_agreement": observed,
            "false_pass_rate_among_human_fails": counts["false_pass"] / human_fails if human_fails else None,
            "false_fail_rate_among_human_passes": counts["false_fail"] / human_passes if human_passes else None,
            "kappa": (observed - expected) / (1 - expected) if expected < 1 else None}


def paired_interval(differences, seed=73, iterations=2000):
    if not differences:
        return None
    rng = random.Random(seed)
    means = sorted(statistics.mean(rng.choices(differences, k=len(differences))) for _ in range(iterations))
    return {"paired_cases": len(differences), "mean_v2_minus_v1": statistics.mean(differences),
            "ci95_low": means[int(iterations * .025)], "ci95_high": means[min(iterations - 1, int(iterations * .975))],
            "method": "paired conversation-level percentile bootstrap", "iterations": iterations, "seed": seed}


def validate_human_label(label):
    if not isinstance(label, dict):
        raise ValueError("Human label must be an object.")
    for key in ("reviewed_by", "reviewed_at", "notes"):
        if not isinstance(label.get(key), str) or not label[key].strip():
            raise ValueError(f"Human label needs {key}.")
    if label.get("human_attestation") is not True:
        raise ValueError("Human must attest that they personally reviewed the output.")
    for dim in DIMENSIONS:
        if type(label.get(dim)) is not int or not 1 <= label[dim] <= 5:
            raise ValueError("Human scores must be integers 1–5.")
    if not isinstance(label.get("critical_errors"), list) or any(not isinstance(x, str) for x in label["critical_errors"]):
        raise ValueError("Human critical_errors must be a list of descriptions.")
    return label


def human_metrics(directory, rows, inputs):
    directory = Path(directory)
    if not (directory / "human_review.json").exists():
        return {"status": "pending", "validation": agreement([]), "calibration": agreement([]), "disagreements": []}
    key = {x["review_id"]: x for x in read_json(directory / "human_review_key.json")}
    items = read_json(directory / "human_review.json")["items"]
    if len({x["review_id"] for x in items}) != len(items) or {x["review_id"] for x in items} != set(key):
        raise ValueError("Human review IDs changed or duplicated.")
    rows_by_id = {x["job_id"]: x for x in rows}
    cases = {x["id"]: x for x in inputs["cases"]}
    pairs = {"calibration": [], "validation": []}
    errors = {split: {dim: [] for dim in DIMENSIONS} for split in pairs}
    disagreements, missed = [], {"calibration": 0, "validation": 0}
    completed = {"calibration": 0, "validation": 0}
    coverage = []
    for item in items:
        entry = key[item["review_id"]]
        row = rows_by_id[entry["job_id"]]
        case = cases[row["case_id"]]
        if item["summary"] != row["summary"] or item["conversation"] != case["conversation"]:
            raise ValueError("Human review source/summary differs from raw evidence.")
        if item["label"] is None:
            continue
        label = validate_human_label(item["label"])
        split = entry["split"]
        completed[split] += 1
        coverage.append({"review_id": item["review_id"], "split": split, "case_id": row["case_id"],
                         "version": row["version"], "tags": case["tags"]})
        if row["judgment"] is None:
            continue
        hp = semantic_pass(label, inputs["config"]["rubric"])
        jp = row["semantic_pass"]
        pairs[split].append((hp, jp))
        for dim in DIMENSIONS:
            errors[split][dim].append(abs(label[dim] - row["judgment"][dim]))
        if label["critical_errors"] and not row["judgment"]["critical_errors"]:
            missed[split] += 1
        if hp != jp or any(label[dim] != row["judgment"][dim] for dim in DIMENSIONS) or bool(label["critical_errors"]) != bool(row["judgment"]["critical_errors"]):
            disagreements.append({"review_id": item["review_id"], "job_id": row["job_id"], "split": split,
                                  "human": label, "judge": row["judgment"], "human_pass": hp, "judge_pass": jp})
    result = {"status": "complete" if sum(completed.values()) == len(items) and len(items) == 30 else "pending",
              "completed_labels": completed, "sample_coverage": coverage, "disagreements": disagreements}
    for split in pairs:
        result[split] = {**agreement(pairs[split]), "critical_errors_missed": missed[split],
                         "mean_absolute_error": {d: statistics.mean(errors[split][d]) if errors[split][d] else None for d in DIMENSIONS}}
    return result


def analyze(directory):
    directory = Path(directory)
    manifest = read_json(directory / "manifest.json")
    inputs, config = manifest["inputs"], manifest["inputs"]["config"]
    events = read_events(directory / "events.jsonl")
    if any(e["run_fingerprint"] != manifest["fingerprint"] for e in events):
        raise ValueError("Mixed run fingerprints detected.")
    latest = {(x["job_id"], x["stage"]): x for x in events if x["status"] == "ok"}
    cases_by_id = {case["id"]: case for case in inputs["cases"]}
    rows = []
    for job in manifest["jobs"]:
        generation, judge = latest.get((job["job_id"], "generate")), latest.get((job["job_id"], "judge"))
        checks = check_summary(generation["text"], config["checks"], cases_by_id[job["case_id"]]) if generation else None
        judgment = judge["judgment"] if judge else None
        sp = semantic_pass(judgment, config["rubric"]) if judgment else None
        rows.append({**job, "summary": generation["text"] if generation else None,
                     "checks": checks, "judgment": judgment, "semantic_pass": sp,
                     "combined_pass": checks["passed"] and sp if checks is not None and sp is not None else None})
    versions = {}
    for version in ("v1", "v2"):
        selected = [x for x in rows if x["version"] == version]
        generated = [x for x in selected if x["checks"] is not None]
        judged = [x for x in selected if x["judgment"] is not None]
        passes = sum(x["combined_pass"] is True for x in selected)
        versions[version] = {"planned": len(selected), "generated": len(generated), "judged": len(judged),
                             "deterministic_passes": sum(x["checks"]["passed"] for x in generated),
                             "semantic_passes": sum(x["semantic_pass"] for x in judged),
                             "combined_passes": passes, "combined_rate_over_planned": passes / len(selected) if selected else None,
                             "critical_outputs": sum(bool(x["judgment"]["critical_errors"]) for x in judged),
                             "deterministic_critical_outputs": sum(x["checks"].get("critical_failure", False) for x in generated),
                             "mean_scores": {d: statistics.mean(x["judgment"][d] for x in judged) if judged else None for d in DIMENSIONS}}
    case_comparisons = []
    for case in inputs["cases"]:
        groups = {v: [x for x in rows if x["case_id"] == case["id"] and x["version"] == v] for v in ("v1", "v2")}
        if not all(len(g) == config["repeats"] and all(x["combined_pass"] is not None for x in g) for g in groups.values()):
            continue
        rates = {v: statistics.mean(int(x["combined_pass"]) for x in g) for v, g in groups.items()}
        case_comparisons.append({"case_id": case["id"], "tags": case["tags"], "rates": rates,
                                 "delta": rates["v2"] - rates["v1"],
                                 "variable_across_repeats": {v: len({x["combined_pass"] for x in g}) > 1 for v, g in groups.items()}})
    interval = paired_interval([x["delta"] for x in case_comparisons], config["schedule_seed"])
    human = human_metrics(directory, rows, inputs)
    release = config["release"]
    reasons = []
    if manifest["scope"] != "full" or len(case_comparisons) != 30:
        reasons.append("Full 30-case repeated comparison is incomplete.")
    if any(v["generated"] != v["planned"] or v["judged"] != v["planned"] for v in versions.values()):
        reasons.append("Generation or judge results are missing.")
    if versions["v2"]["critical_outputs"]:
        reasons.append("Observed critical errors in v2.")
    if versions["v2"]["deterministic_critical_outputs"]:
        reasons.append("Deterministic privacy/safety critical checks failed in v2.")
    if (versions["v2"]["combined_rate_over_planned"] or 0) < release["minimum_combined_pass_rate"]:
        reasons.append("v2 does not meet the declared combined-pass threshold.")
    if interval is None or interval["ci95_low"] < -release["noninferiority_margin"]:
        reasons.append("Evidence does not establish the declared noninferiority margin.")
    validation = human["validation"]
    if human["status"] != "complete" or validation["n"] < release["minimum_human_validation_labels"]:
        reasons.append("Genuine human calibration/held-out validation is incomplete.")
    if validation.get("critical_errors_missed", 0):
        reasons.append("Judge missed human-identified critical errors in validation.")
    for metric, maximum in (("false_pass", release["maximum_human_false_passes"]), ("false_fail", release["maximum_human_false_fails"])):
        if validation["confusion_matrix"][metric] > maximum:
            reasons.append(f"Judge {metric} count exceeds the declared validation tolerance.")
    if any(x is not None and x > release["maximum_human_mean_absolute_error"] for x in validation.get("mean_absolute_error", {}).values()):
        reasons.append("Judge dimension error exceeds the declared validation tolerance.")
    tags = sorted({tag for c in inputs["cases"] for tag in c["tags"]})
    slices = {tag: {v: {"n": len(g := [x for x in rows if x["version"] == v and x["case_id"] in {c["id"] for c in inputs["cases"] if tag in c["tags"]}]),
                          "combined_passes": sum(x["combined_pass"] is True for x in g)} for v in ("v1", "v2")} for tag in tags}
    usage = {}
    for e in events:
        for key, val in (e.get("usage") or {}).items():
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                usage[key] = usage.get(key, 0) + val
    metrics = {"run_fingerprint": manifest["fingerprint"], "scope": manifest["scope"], "versions": versions,
               "paired_comparison": interval, "per_case": case_comparisons, "risk_slices": slices,
               "human": human, "operational_error_attempts": sum(x["status"] == "error" for x in events),
               "request_attempts": len(events), "reported_usage_all_attempts": usage, "cost_usd": None,
               "recommendation": "HOLD" if reasons else "CONDITIONAL SHIP", "decision_reasons": reasons,
               "models": manifest["clients"], "same_model_and_endpoint": manifest["clients"]["generate"] == manifest["clients"]["judge"]}
    write_json(directory / "checks_and_judgments.json", rows)
    write_json(directory / "metrics.json", metrics)
    write_report(directory / "REPORT.md", metrics, rows)
    return metrics


def write_report(path, metrics, rows):
    interval = metrics["paired_comparison"]
    lines = ["# Regression report", "", f"**Recommendation: {metrics['recommendation']}.**", ""]
    lines += ["- " + r for r in metrics["decision_reasons"]]
    if not metrics["decision_reasons"]:
        lines.append("Declared gates passed on this small selected sample. Confirm the critical examples manually and use a monitored rollout; this is not proof of production-wide safety.")
    lines += ["", "## Comparison", "", "Combined rate uses all planned outputs as its denominator; operationally missing outputs remain separately counted, not semantic failures.", "",
              "| Version | Planned | Generated | Judged | Deterministic passes/generated | Semantic passes/judged | Combined passes/planned | Critical outputs/judged |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for v, m in metrics["versions"].items():
        lines.append(f"| {v} | {m['planned']} | {m['generated']} | {m['judged']} | {m['deterministic_passes']}/{m['generated']} | {m['semantic_passes']}/{m['judged']} | {m['combined_passes']}/{m['planned']} | {m['critical_outputs']}/{m['judged']} |")
    lines += ["", f"Request attempts: {metrics['request_attempts']}; operational error attempts: {metrics['operational_error_attempts']}. Monetary cost is unknown; token usage, when supplied by the provider, is in metrics.json.", "",
              "Mean dimension scores: " + str({v: m["mean_scores"] for v, m in metrics["versions"].items()}), "", "## Confidence and repeated runs", ""]
    if interval:
        lines.append(f"v2 minus v1 combined-pass difference: {interval['mean_v2_minus_v1']:+.3f}; 95% interval [{interval['ci95_low']:+.3f}, {interval['ci95_high']:+.3f}], over {interval['paired_cases']} fully evaluated paired cases. Method: {interval['method']}, {interval['iterations']} draws, seed {interval['seed']}.")
    else:
        lines.append("No complete paired cases; no comparison interval is available.")
    variable = {v: sum(x["variable_across_repeats"][v] for x in metrics["per_case"]) for v in ("v1", "v2")}
    lines += [f"Cases whose combined pass/fail changed across repeats: {variable}.", "", "## Judge validation", "",
              "Calibration: " + str(metrics["human"]["calibration"]), "", "Held-out validation: " + str(metrics["human"]["validation"]), "",
              f"Human-review status: {metrics['human']['status']}. Agreement denominators include only labeled outputs with a valid judge response. Kappa is undefined when agreement marginals are degenerate.", "",
              f"Judge/summariser share endpoint and model: {metrics['same_model_and_endpoint']}. Shared model biases can inflate apparent agreement; blinding does not remove them.", "", "## Evidence examples", ""]
    examples = sorted(metrics["per_case"], key=lambda x: x["delta"])
    selected = (examples[:1] + examples[-1:]) if examples else []
    seen = set()
    for case in selected:
        if case["case_id"] in seen:
            continue
        seen.add(case["case_id"])
        lines.append(f"Case {case['case_id']}: v1 rate {case['rates']['v1']:.3f}, v2 {case['rates']['v2']:.3f}.")
        for v in ("v1", "v2"):
            row = next(x for x in rows if x["case_id"] == case["case_id"] and x["version"] == v)
            # Escape syntax so source-controlled strings render as evidence, not active Markdown.
            import json
            def escaped(value):
                value = html.escape(json.dumps(value, ensure_ascii=False))
                for char in "\\`*_[]()":
                    value = value.replace(char, "\\" + char)
                return value
            lines += ["", f"- {v}, job {row['job_id']}: " + escaped(row["summary"]),
                      "  Judge reasons: " + escaped(row["judgment"]["reasons"])]
    if not selected:
        lines.append("No evaluated examples available. Do not substitute fixture summaries.")
    lines += ["", "## Limits and next steps", "", "This purposive set is not a random sample of production traffic. Repeats share conversations; intervals resample whole cases and cannot repair selection bias. Small risk slices and human samples limit confidence. No observed critical error does not establish zero risk. Inspect per-case and risk-slice evidence in metrics.json and disagreements under human.disagreements. Complete missing data/review and investigate critical errors before reconsidering release.", ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")
