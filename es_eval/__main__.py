import argparse
import json
from pathlib import Path

from .core import load_inputs, load_env_file


def main():
    parser = argparse.ArgumentParser(description="Private Es Magico summariser evaluation")
    parser.add_argument("command", choices=("validate", "estimate", "preflight", "run", "analyze"))
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--out", default="runs/main")
    parser.add_argument("--smoke", action="store_true", help="Use two cases in a separate run directory")
    parser.add_argument("--stage", choices=("all", "generate", "judge"), default="all")
    parser.add_argument("--candidate", default="v2", help="Candidate prompt version to compare against v1 (default: v2; e.g. v3)")
    parser.add_argument("--allow-model-calls", action="store_true", help="Explicitly enable external/local model calls")
    parser.add_argument("--env-file", default=".env", help="Literal provider settings file, default .env; existing environment wins")
    args = parser.parse_args()
    try:
        if args.command == "analyze":
            from .analysis import analyze
            metrics = analyze(args.out)
            print(json.dumps({"recommendation": metrics["recommendation"], "reasons": metrics["decision_reasons"]}, indent=2))
            return
        inputs = load_inputs(args.config)
        n = 2 if args.smoke else len(inputs["cases"])
        normal = n * 2 * inputs["config"]["repeats"]
        if args.command in ("validate", "estimate"):
            print(json.dumps({"status": "valid", "golden_cases": len(inputs["cases"]),
                              "planned_generation_calls": normal, "planned_judge_calls": normal,
                              "upper_bound_attempts_with_retries": normal * 2 * inputs["config"]["max_attempts"],
                              "cost_usd": None, "note": "Cost depends on chosen provider/model and tokens. No calls made."}, indent=2))
            return
        if args.command != "preflight" and not args.allow_model_calls:
            raise ValueError("No model calls made. Review provider/budget, then pass --allow-model-calls.")
        load_env_file(args.env_file)
        from .runner import ChatClient, run
        clients = {"generate": ChatClient(inputs["config"]), "judge": ChatClient(inputs["config"], judge=True)}
        if args.command == "preflight":
            print(json.dumps({"status": "configured_not_connectivity_tested", "clients": {k: c.identity for k, c in clients.items()},
                              "model_calls_made": 0, "note": "Check provider quota/pricing before a smoke run."}, indent=2))
            return
        run(Path(args.out), inputs, clients, limit=2 if args.smoke else None, stage=args.stage,
            versions=("v1", args.candidate))
        print("Run stage complete. Use analyze for offline evidence; human labels may remain pending.")
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, f"Evaluation stopped: {error}\n")


if __name__ == "__main__":
    main()
