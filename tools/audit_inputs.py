"""Static evidence only: no model requests or generated-summary measurements."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from es_eval.core import digest, load_inputs, read_json, write_json


def main():
    inputs = load_inputs(ROOT / "config.json")
    source = read_json(ROOT / "starter/SOURCE_MANIFEST.json")
    for entry in source:
        observed = hashlib.sha256((ROOT / "starter" / entry["path"]).read_bytes()).hexdigest()
        if observed != entry["sha256"]:
            raise ValueError("Starter source changed: " + entry["path"])
    total = len(inputs["cases"]) * 2 * inputs["config"]["repeats"]
    finding = {"kind": "static_prompt_spec_conflict", "version": "v2",
               "product_spec": "A single short paragraph. No lists, headings or markdown.",
               "prompt_lines": [line for line in inputs["prompts"]["v2"].splitlines() if "layout" in line or line.strip().startswith(("Issue:", "Status:", "Next step:"))],
               "conclusion": "v2 explicitly instructs a layout contrary to the current product spec. This is a static blocker, not an observed LLM failure rate."}
    if len(finding["prompt_lines"]) != 4:
        raise ValueError("Reinspect static finding; expected v2 layout text changed.")
    out = {"evidence_type": "static_inspection_not_model_evaluation", "starter_hashes_verified": source,
           "golden_cases": len(inputs["cases"]), "other_cases": len(read_json(ROOT / "data/unselected.json")),
           "input_fingerprint": digest(inputs), "planned_generation_calls": total, "planned_judge_calls": total,
           "findings": [finding], "notes": ["Both v1 and v2 omit explicit product privacy/safety/tone safeguards; actual behavioral differences are unmeasured.",
             "v2 under-40-word aim is a prompt preference; evaluator limit is 80 words as a documented product-spec gap assumption."],
           "recommendation": "HOLD v2 as written; fix the prompt/spec conflict before release and complete empirical comparison and genuine judge validation."}
    write_json(ROOT / "data/static_audit.json", out)
    print(json.dumps({"starter_files_verified": len(source), "golden_cases": len(inputs["cases"]),
                      "static_blocker": finding["conclusion"], "model_calls_made_by_audit": 0}, indent=2))


if __name__ == "__main__":
    main()
