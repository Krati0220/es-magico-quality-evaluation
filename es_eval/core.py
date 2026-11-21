"""Pure validation/checking functions. No network access."""
import hashlib
import json
import re
from pathlib import Path

DIMENSIONS = ("faithfulness", "completeness", "usefulness")

# Approximate self-serve USD pricing per 1M tokens (input, output) for common models.
# Unknown/local models return None rather than guessing.
MODEL_PRICING_USD_PER_1M = {
    "openai/gpt-oss-20b": (0.075, 0.30),
    "openai/gpt-oss-120b": (0.15, 0.60),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "qwen/qwen3-32b": (0.29, 0.59),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.5-pro": (1.25, 10.00),
}


def estimate_cost_usd(model, usage):
    """Estimate USD cost from provider token usage when model pricing is known."""
    if not model or not isinstance(usage, dict):
        return None
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    if not isinstance(prompt_tokens, (int, float)) or not isinstance(completion_tokens, (int, float)):
        return None
    normalized = model.lower().strip()
    rates = MODEL_PRICING_USD_PER_1M.get(normalized)
    if rates is None:
        for prefix, candidate in MODEL_PRICING_USD_PER_1M.items():
            if normalized.startswith(prefix):
                rates = candidate
                break
    if rates is None:
        return None
    in_rate, out_rate = rates
    return round((prompt_tokens * in_rate + completion_tokens * out_rate) / 1_000_000, 6)


def extract_json_object(text):
    """Parse JSON object from judge text, safely unwrapping <think> blocks or Markdown fences."""
    if not isinstance(text, str):
        raise ValueError("Judge output is not a string.")
    cleaned = text.strip()
    try:
        return json.loads(cleaned)
    except ValueError:
        pass
    # Strip reasoning blocks such as <think>...</think>
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.S | re.I).strip()
    # Unwrap fenced JSON blocks
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, flags=re.S | re.I)
    if fence:
        return json.loads(fence.group(1))
    # Fallback to outermost JSON object
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        return json.loads(cleaned[start:end + 1])
    raise ValueError("No valid JSON object found in judge output.")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_inputs(config_path):
    path = Path(config_path).resolve()
    config = read_json(path)
    if config.get("spec_reviewed") is not True:
        raise ValueError("Starter product spec has not been reviewed. Supply starter ZIP before live evaluation.")
    cases = read_json(path.parent / config["golden_path"])
    if len(cases) != config["case_count"] or config["case_count"] != 30:
        raise ValueError("The primary golden set must contain exactly 30 cases.")
    ids = []
    for case in cases:
        for key in ("id", "conversation", "provenance", "selection_reason"):
            if not isinstance(case.get(key), str) or not case[key].strip():
                raise ValueError(f"Every case needs a nonempty {key} string.")
        for key in ("tags", "must_include", "must_not_include", "ambiguities"):
            if not isinstance(case.get(key), list) or not all(isinstance(x, str) for x in case[key]):
                raise ValueError(f"Case {case['id']}: {key} must be a list of strings.")
        if not case["tags"] or not case["must_include"] or not case["must_not_include"]:
            raise ValueError("Each case needs risk tags and positive/negative semantic expectations.")
        for key in ("final_status", "actions_taken", "next_action", "owner"):
            if key not in case or (case[key] is not None and not isinstance(case[key], str)):
                raise ValueError(f"Case {case['id']}: {key} must be a string or explicit null.")
        ids.append(case["id"])
    if len(set(ids)) != len(ids):
        raise ValueError("Golden case IDs must be unique.")
    plan = config.get("human_review_plan")
    if plan:
        calibration, validation = plan["calibration_case_ids"], plan["validation_case_ids"]
        if len(calibration) != 5 or len(validation) != 10 or len(set(calibration + validation)) != 15 or not set(calibration + validation) <= set(ids):
            raise ValueError("Human review plan needs 5 calibration and 10 distinct validation cases from the golden set.")
    if set(config["prompt_paths"]) != {"v1", "v2"}:
        raise ValueError("Exactly v1 and v2 prompts are required.")
    prompts = {k: (path.parent / v).read_text(encoding="utf-8") for k, v in config["prompt_paths"].items()}
    extra_prompts = {k: (path.parent / v).read_text(encoding="utf-8")
                     for k, v in config.get("extra_prompt_paths", {}).items()
                     if (path.parent / v).exists()}
    spec = (path.parent / config["spec_path"]).read_text(encoding="utf-8")
    judge = (path.parent / config["judge_prompt_path"]).read_text(encoding="utf-8")
    if not spec.strip() or not judge.strip() or any(not p.strip() for p in prompts.values()):
        raise ValueError("Spec, prompts and judge must be nonempty.")
    rules = config["checks"]
    if rules.get("format") not in ("text", "json"):
        raise ValueError("Set the format policy after reviewing the spec.")
    if not any(isinstance(rules.get(k), int) and not isinstance(rules[k], bool) and rules[k] > 0 for k in ("max_words", "max_chars")):
        raise ValueError("At least one positive length limit is required.")
    for key in ("max_words", "max_chars"):
        if rules.get(key) is not None and (type(rules[key]) is not int or rules[key] < 1):
            raise ValueError(f"{key} must be a positive integer or null.")
    if not isinstance(rules.get("banned_patterns"), list) or not rules.get("rationale", "").strip():
        raise ValueError("Define banned-content checks and their rationale (an empty list requires an explicit reason).")
    pattern_ids = []
    for pattern in rules["banned_patterns"]:
        if not pattern.get("id") or not pattern.get("rationale"):
            raise ValueError("Every banned pattern needs an ID and rationale.")
        re.compile(pattern["regex"])
        pattern_ids.append(pattern["id"])
    if len(set(pattern_ids)) != len(pattern_ids):
        raise ValueError("Banned pattern IDs must be unique.")
    for key in ("repeats", "max_attempts", "max_tokens", "judge_max_tokens", "timeout_seconds"):
        if type(config.get(key)) is not int or config[key] < 1:
            raise ValueError(f"{key} must be a positive integer.")
    for dim in DIMENSIONS:
        threshold = config["rubric"][dim + "_min"]
        if type(threshold) is not int or not 1 <= threshold <= 5:
            raise ValueError("Rubric thresholds must be integers from 1 to 5.")
    release = config["release"]
    for key in ("minimum_combined_pass_rate", "noninferiority_margin"):
        if not 0 <= release[key] <= 1:
            raise ValueError(f"{key} must be between 0 and 1.")
    if not 1 <= release["minimum_human_validation_labels"] <= 20:
        raise ValueError("Human validation minimum must be between 1 and 20.")
    result = {"config": config, "cases": cases, "prompts": prompts, "spec": spec, "judge_prompt": judge}
    if extra_prompts:
        result["extra_prompts"] = extra_prompts
    return result


def load_env_file(path):
    """Read a small literal KEY=VALUE file without shell evaluation or interpolation."""
    import os
    path = Path(path)
    if not path.exists():
        return
    allowed = {prefix + suffix for prefix in ("LLM_", "JUDGE_") for suffix in ("BASE_URL", "MODEL", "API_KEY")}
    studio_keys = {"DATABASE_URL", "APP_ACCESS_TOKEN", "CORS_ORIGINS", "RATE_LIMIT_MIN_DELAY_SECONDS"}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or (key not in allowed and key not in studio_keys):
            raise ValueError(f"Invalid provider setting on env-file line {number}.")
        if key not in allowed:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value and not value.startswith(("REPLACE_", "YOUR_", "gsk_YOUR_")):
            os.environ.setdefault(key, value)


def check_summary(summary, rules, case=None):
    """Length is over stripped raw output; words are Unicode whitespace tokens."""
    stripped = summary.strip()
    results = []

    def add(rule, passed, observed, expected, severity="error"):
        results.append({"rule_id": rule, "passed": passed, "observed": observed,
                        "expected": expected, "severity": severity})

    add("nonempty", bool(stripped), len(stripped), ">0 characters")
    if rules["format"] == "json":
        try:
            parsed = json.loads(stripped)
            valid = isinstance(parsed, dict)
        except (ValueError, TypeError):
            parsed, valid = None, False
        add("format.json_object", valid, type(parsed).__name__, "JSON object without fences")
        if valid:
            for key in rules.get("required_keys", []):
                add("field." + key, key in parsed and isinstance(parsed[key], str) and bool(parsed[key].strip()),
                    parsed.get(key), "nonempty string")
            if rules.get("allow_extra_keys") is False:
                extra = sorted(set(parsed) - set(rules.get("required_keys", [])))
                add("fields.extra", not extra, extra, [])
    else:
        add("format.text", bool(stripped) and not stripped.startswith("```"),
            "fenced" if stripped.startswith("```") else "plain", "nonempty unfenced text")
        if rules.get("single_paragraph"):
            add("format.single_paragraph", not re.search(r"[\r\n\u2028\u2029]", stripped),
                len(stripped.splitlines()), "one paragraph without internal line breaks")
        if rules.get("no_markdown"):
            match = re.search(r"(?:^|\n)\s*(?:[-*+]\s|\d+[.)]\s|#{1,6}\s|>\s)|\*\*|__|`|\[[^\]]+\]\(", stripped)
            add("format.no_markdown", match is None, match.group(0) if match else None, "plain sentences")
        if rules.get("no_headings"):
            match = re.search(r"(?:^|[\r\n])\s*(?:issue|status|next[ -]step|summary|handoff(?: note)?|customer|resolution|action|overview)\s*:", stripped, re.I)
            add("format.no_headings", match is None, match.group(0) if match else None, "no heading labels")
    for name, observed in (("max_words", len(stripped.split())), ("max_chars", len(stripped))):
        limit = rules.get(name)
        if limit is not None:
            add("length." + name, observed <= limit, observed, limit)
    for pattern in rules.get("banned_patterns", []):
        match = re.search(pattern["regex"], summary, flags=re.IGNORECASE if pattern.get("ignore_case", True) else 0)
        add("banned." + pattern["id"], match is None,
            match.group(0) if match else None, "no match", pattern.get("severity", "error"))
    if rules.get("source_sensitive_spans") and case:
        for index, span in enumerate(case.get("sensitive_spans", [])):
            value = span["value"]
            if span["type"] in ("phone", "otp", "card_suffix"):
                digits = re.sub(r"\D", "", value)
                alternatives = [digits]
                if span["type"] == "phone" and digits.startswith("91") and len(digits) == 12:
                    alternatives.append(digits[2:])
                pattern = r"(?<![\w-])(?:" + "|".join(r"[\s().+-]*".join(re.escape(d) for d in variant) for variant in alternatives) + r")(?![\w-])"
            else:
                tokens = re.findall(r"\w+", value)
                pattern = r"(?<!\w)" + r"[\W_]*".join(re.escape(t) for t in tokens) + r"(?!\w)"
            match = re.search(pattern, summary, re.I)
            add(f"privacy.source.{span['type']}.{index}", match is None,
                match.group(0) if match else None, "sensitive value omitted/redacted", "critical")
    if case and "safety" in case.get("tags", []) and rules.get("safety_signal_pattern"):
        match = re.search(rules["safety_signal_pattern"], summary, re.I)
        add("safety.signal", match is not None, match.group(0) if match else None,
            "explicit source-supported electrical hazard/damage signal", "critical")
    return {"passed": all(x["passed"] for x in results),
            "critical_failure": any(not x["passed"] and x["severity"] == "critical" for x in results), "rules": results}


def validate_judgment(value):
    expected = set(DIMENSIONS) | {"critical_errors", "reasons", "evidence"}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("Judge response has missing/extra keys.")
    for dim in DIMENSIONS:
        if type(value[dim]) is not int or not 1 <= value[dim] <= 5:
            raise ValueError(f"{dim} must be an integer from 1 to 5.")
    if not isinstance(value["reasons"], dict) or set(value["reasons"]) != set(DIMENSIONS):
        raise ValueError("Reasons must cover all score dimensions.")
    if any(not isinstance(x, str) or not x.strip() for x in value["reasons"].values()):
        raise ValueError("Reasons must be nonempty strings.")
    for key, fields in (("critical_errors", {"kind", "explanation", "source_evidence", "summary_evidence"}),
                        ("evidence", {"source", "summary"})):
        if not isinstance(value[key], list):
            raise ValueError(f"{key} must be an array.")
        for item in value[key]:
            if not isinstance(item, dict) or set(item) != fields or any(not isinstance(v, str) or not v.strip() for v in item.values()):
                raise ValueError(f"Invalid {key} evidence object.")
    return value


def semantic_pass(judgment, rubric):
    return not judgment["critical_errors"] and all(judgment[d] >= rubric[d + "_min"] for d in DIMENSIONS)


def judge_messages(inputs, case, summary):
    # Version/run IDs intentionally omitted. Instructions are kept outside the data envelope.
    expectations = {k: case[k] for k in ("must_include", "must_not_include", "ambiguities", "final_status", "actions_taken", "next_action", "owner")}
    policy = inputs["config"].get("judge_policy", "")
    return [{"role": "system", "content": inputs["judge_prompt"] + "\n\nPRODUCT SPEC:\n" + inputs["spec"] + "\n\nDECLARED GAP POLICIES:\n" + policy},
            {"role": "user", "content": json.dumps({"conversation": case["conversation"],
             "expectations": expectations, "candidate_summary": summary}, ensure_ascii=False)}]
