"""Render-ready FastAPI backend wrapping the es_eval harness."""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select

from es_eval.analysis import analyze_data, validate_human_label
from es_eval.core import (
    check_summary,
    extract_json_object,
    judge_messages,
    load_env_file,
    load_inputs,
    read_json,
    semantic_pass,
    validate_judgment,
)
from es_eval.runner import CallFailure, resolve_prompt

from .db import EvalEvent, EvalRun, SessionLocal, db_backend_name, get_run_events, init_db, utcnow
from .worker import RUN_MANAGER, build_clients, provider_status

ROOT = Path(__file__).resolve().parents[1]

# Load local .env if present (host environment variables like Render always win).
# Re-reading on request lets local edits to .env apply without restarting uvicorn.
_HOST_ENV_KEYS = frozenset(os.environ.keys())


def refresh_local_env():
    allowed = {
        "LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY",
        "JUDGE_BASE_URL", "JUDGE_MODEL", "JUDGE_API_KEY",
        "DATABASE_URL", "APP_ACCESS_TOKEN", "CORS_ORIGINS",
        "RATE_LIMIT_MIN_DELAY_SECONDS",
    }
    parsed = {}
    for candidate_env in (ROOT / ".env", ROOT / "backend" / ".env"):
        if not candidate_env.exists():
            continue
        for line in candidate_env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            key, sep, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not sep or key not in allowed:
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if value and not value.startswith(("REPLACE_", "YOUR_", "gsk_YOUR_", "change-me-")):
                parsed[key] = value
    for key in allowed:
        if key in _HOST_ENV_KEYS:
            continue
        if key in parsed:
            os.environ[key] = parsed[key]
        else:
            os.environ.pop(key, None)


refresh_local_env()

init_db()


def _import_result_folders():
    """Auto-load tracked empirical runs from results/*/ into the DB if not already present."""
    results_dir = ROOT / "results"
    if not results_dir.exists():
        return
    with SessionLocal() as session:
        for folder in sorted(results_dir.iterdir()):
            manifest_path = folder / "manifest.json"
            events_path = folder / "events.jsonl"
            if not folder.is_dir() or not manifest_path.exists() or not events_path.exists():
                continue
            run_id = "repo-" + folder.name
            if session.get(EvalRun, run_id) is not None:
                continue
            try:
                manifest = read_json(manifest_path)
                from es_eval.runner import read_events
                events = read_events(events_path)
                review_doc = read_json(folder / "human_review.json") if (folder / "human_review.json").exists() else None
                review_key = read_json(folder / "human_review_key.json") if (folder / "human_review_key.json").exists() else None
                metrics, rows, report = analyze_data(manifest, events, review_doc, review_key)
                versions = tuple(manifest.get("versions", ("v1", "v2")))
                ok_pairs = {(e["job_id"], e["stage"]) for e in events if e.get("status") == "ok"}
                total_steps = len(manifest["jobs"]) * 2
                rec = EvalRun(
                    id=run_id,
                    name=f"Repo Evidence: {folder.name}",
                    scope=manifest.get("scope", "full"),
                    baseline_version=versions[0],
                    candidate_version=versions[1],
                    status="completed" if len(ok_pairs) == total_steps else "partial",
                    stage="all",
                    use_mock=0,
                    completed_steps=len(ok_pairs),
                    total_steps=total_steps,
                    manifest_json=json.dumps(manifest, ensure_ascii=False),
                    review_doc_json=json.dumps(review_doc, ensure_ascii=False) if review_doc else None,
                    review_key_json=json.dumps(review_key, ensure_ascii=False) if review_key else None,
                    metrics_json=json.dumps(metrics, ensure_ascii=False),
                    rows_json=json.dumps(rows, ensure_ascii=False),
                    report_md=report,
                )
                session.add(rec)
                for ev in events:
                    session.add(EvalEvent(
                        run_id=run_id,
                        job_id=ev["job_id"],
                        stage=ev["stage"],
                        attempt=int(ev["attempt"]),
                        status=ev["status"],
                        payload_json=json.dumps(ev, ensure_ascii=False),
                    ))
                session.commit()
            except Exception:
                session.rollback()


_import_result_folders()

app = FastAPI(
    title="Es Magico Quality Evaluation API",
    version="1.0.0",
    description="Support handoff prompt regression evaluation, live playground, and blinded human review API.",
)

cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins if "*" not in cors_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_auth(
    authorization: Optional[str] = Header(default=None),
    x_access_token: Optional[str] = Header(default=None),
):
    expected = os.getenv("APP_ACCESS_TOKEN", "").strip()
    if not expected:
        return
    token = x_access_token
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing access token. Set X-Access-Token or Authorization: Bearer <token>.",
        )


# --- Pydantic Schemas ---


class PlaygroundRequest(BaseModel):
    case_id: Optional[str] = None
    custom_conversation: Optional[str] = None
    versions: List[str] = Field(default_factory=lambda: ["v1", "v2", "v3"])
    custom_prompt: Optional[str] = None
    run_judge: bool = False
    use_mock: bool = False
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)


class CreateRunRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    scope: str = Field(default="smoke", pattern="^(smoke|full)$")
    candidate_version: str = Field(default="v2", pattern="^(v2|v3)$")
    use_mock: bool = False
    rate_limit_delay: Optional[float] = Field(default=None, ge=0.0, le=30.0)
    repeats: Optional[int] = Field(default=None, ge=1, le=3)


class HumanLabelRequest(BaseModel):
    reviewed_by: str = Field(min_length=1, max_length=120)
    human_attestation: bool
    faithfulness: int = Field(ge=1, le=5)
    completeness: int = Field(ge=1, le=5)
    usefulness: int = Field(ge=1, le=5)
    critical_errors: List[str] = Field(default_factory=list)
    notes: str = Field(min_length=1, max_length=2000)


# --- Helpers ---


def _all_prompts(inputs):
    merged = dict(inputs["prompts"])
    merged.update(inputs.get("extra_prompts", {}))
    return merged


def _run_summary_dict(rec: EvalRun):
    metrics = json.loads(rec.metrics_json) if rec.metrics_json else None
    return {
        "id": rec.id,
        "name": rec.name,
        "scope": rec.scope,
        "baseline_version": rec.baseline_version,
        "candidate_version": rec.candidate_version,
        "status": rec.status,
        "use_mock": bool(rec.use_mock),
        "is_active": RUN_MANAGER.is_active(rec.id),
        "completed_steps": rec.completed_steps,
        "total_steps": rec.total_steps,
        "error_message": rec.error_message,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
        "recommendation": metrics.get("recommendation") if metrics else None,
        "cost_usd": metrics.get("cost_usd") if metrics else None,
        "versions": metrics.get("versions") if metrics else None,
        "human_status": metrics.get("human", {}).get("status") if metrics else None,
        "models": metrics.get("models") if metrics else None,
    }


# --- Routes ---


@app.get("/api/health")
def health():
    refresh_local_env()
    inputs = load_inputs(ROOT / "config.json")
    return {
        "status": "ok",
        "database": db_backend_name(),
        "auth_required": bool(os.getenv("APP_ACCESS_TOKEN", "").strip()),
        "provider": provider_status(inputs["config"]),
    }


@app.get("/api/overview", dependencies=[Depends(require_auth)])
def overview():
    inputs = load_inputs(ROOT / "config.json")
    unselected = read_json(ROOT / "data/unselected.json") if (ROOT / "data/unselected.json").exists() else []
    static_audit = read_json(ROOT / "data/static_audit.json") if (ROOT / "data/static_audit.json").exists() else None
    coverage = read_json(ROOT / "data/coverage.json") if (ROOT / "data/coverage.json").exists() else None
    return {
        "spec": inputs["spec"],
        "config": {
            "case_count": inputs["config"]["case_count"],
            "repeats": inputs["config"]["repeats"],
            "temperature": inputs["config"]["temperature"],
            "judge_temperature": inputs["config"]["judge_temperature"],
            "checks": inputs["config"]["checks"],
            "rubric": inputs["config"]["rubric"],
            "release": inputs["config"]["release"],
            "judge_policy": inputs["config"].get("judge_policy", ""),
            "human_review_plan": inputs["config"].get("human_review_plan"),
        },
        "prompts": _all_prompts(inputs),
        "judge_prompt": inputs["judge_prompt"],
        "static_audit": static_audit,
        "coverage": coverage,
        "golden_cases": inputs["cases"],
        "unselected_cases": unselected,
        "provider": provider_status(inputs["config"]),
    }


@app.post("/api/playground/run", dependencies=[Depends(require_auth)])
def playground_run(req: PlaygroundRequest):
    refresh_local_env()
    inputs = load_inputs(ROOT / "config.json")
    cases_by_id = {c["id"]: c for c in inputs["cases"]}
    unselected = read_json(ROOT / "data/unselected.json") if (ROOT / "data/unselected.json").exists() else []
    unselected_by_id = {c["id"]: c for c in unselected}

    case = None
    if req.case_id:
        if req.case_id in cases_by_id:
            case = cases_by_id[req.case_id]
            conversation = case["conversation"]
        elif req.case_id in unselected_by_id:
            raw = unselected_by_id[req.case_id]
            conversation = raw["conversation"]
        else:
            raise HTTPException(status_code=404, detail=f"Case {req.case_id} not found.")
    elif req.custom_conversation and req.custom_conversation.strip():
        conversation = req.custom_conversation.strip()
        if not conversation.startswith("Conversation:"):
            conversation = "Conversation:\n\n[chat]\n" + conversation
    else:
        raise HTTPException(status_code=400, detail="Provide either case_id or custom_conversation.")

    try:
        clients = build_clients(inputs["config"], use_mock=req.use_mock)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))

    temperature = req.temperature if req.temperature is not None else inputs["config"]["temperature"]
    max_tokens = inputs["config"]["max_tokens"] if inputs["config"].get("send_generation_max_tokens", True) else None
    all_prompts = _all_prompts(inputs)
    targets = []
    for version in req.versions:
        if version == "custom":
            if not req.custom_prompt or not req.custom_prompt.strip():
                raise HTTPException(status_code=400, detail="custom_prompt is required when 'custom' is selected.")
            targets.append(("custom", req.custom_prompt.strip()))
        elif version in all_prompts:
            targets.append((version, all_prompts[version].strip()))
        else:
            raise HTTPException(status_code=400, detail=f"Unknown prompt version: {version}")

    outputs = []
    for version, system_prompt in targets:
        start = time.monotonic()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": conversation},
        ]
        try:
            gen = clients["generate"].complete(messages, temperature, max_tokens)
        except CallFailure as err:
            outputs.append({
                "version": version,
                "error": err.code,
                "error_detail": err.detail,
                "latency_seconds": round(time.monotonic() - start, 3),
            })
            continue

        gen_latency = round(time.monotonic() - start, 3)
        checks = check_summary(gen["text"], inputs["config"]["checks"], case)
        judgment = None
        sem_pass = None
        judge_error = None
        judge_latency = None
        judge_cost = None
        if req.run_judge:
            judge_case = case or {
                "conversation": conversation,
                "must_include": ["Customer request and current status"],
                "must_not_include": ["Invented facts or exposed personal data"],
                "ambiguities": [],
                "final_status": None,
                "actions_taken": None,
                "next_action": None,
                "owner": None,
            }
            j_start = time.monotonic()
            try:
                rf = {"type": "json_object"} if getattr(clients["judge"], "supports_response_format", False) else None
                re_effort = inputs["config"].get("judge_reasoning_effort") if getattr(clients["judge"], "supports_response_format", False) else None
                j_res = clients["judge"].complete(
                    judge_messages(inputs, judge_case, gen["text"]),
                    inputs["config"]["judge_temperature"],
                    inputs["config"]["judge_max_tokens"],
                    response_format=rf,
                    reasoning_effort=re_effort,
                ) if (rf or re_effort) else clients["judge"].complete(
                    judge_messages(inputs, judge_case, gen["text"]),
                    inputs["config"]["judge_temperature"],
                    inputs["config"]["judge_max_tokens"],
                )
                judgment = validate_judgment(extract_json_object(j_res["text"]))
                sem_pass = semantic_pass(judgment, inputs["config"]["rubric"])
                judge_cost = j_res.get("cost_usd")
            except (CallFailure, ValueError, TypeError) as j_err:
                judge_error = str(j_err)
            judge_latency = round(time.monotonic() - j_start, 3)

        outputs.append({
            "version": version,
            "summary": gen["text"],
            "word_count": len(gen["text"].strip().split()),
            "checks": checks,
            "judgment": judgment,
            "semantic_pass": sem_pass,
            "combined_pass": (checks["passed"] and sem_pass) if sem_pass is not None else checks["passed"],
            "judge_error": judge_error,
            "latency_seconds": gen_latency,
            "judge_latency_seconds": judge_latency,
            "usage": gen.get("usage"),
            "cost_usd": gen.get("cost_usd"),
            "judge_cost_usd": judge_cost,
            "model": gen.get("response_model") or clients["generate"].identity["model"],
        })

    return {
        "case_id": req.case_id,
        "conversation": conversation,
        "use_mock": req.use_mock,
        "models": {k: v.identity for k, v in clients.items()},
        "outputs": outputs,
    }


@app.get("/api/runs", dependencies=[Depends(require_auth)])
def list_runs():
    _import_result_folders()
    with SessionLocal() as session:
        records = session.execute(select(EvalRun).order_by(EvalRun.created_at.desc())).scalars().all()
        return {"runs": [_run_summary_dict(r) for r in records]}


@app.post("/api/runs", status_code=202, dependencies=[Depends(require_auth)])
def create_run(req: CreateRunRequest):
    refresh_local_env()
    try:
        run_id = RUN_MANAGER.create_and_start(
            name=req.name,
            scope=req.scope,
            candidate_version=req.candidate_version,
            use_mock=req.use_mock,
            rate_limit_delay=req.rate_limit_delay,
            repeats=req.repeats,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
    return {"run_id": run_id, "status": "queued"}


@app.get("/api/runs/{run_id}", dependencies=[Depends(require_auth)])
def get_run(run_id: str):
    with SessionLocal() as session:
        rec = session.get(EvalRun, run_id)
        if not rec:
            raise HTTPException(status_code=404, detail="Run not found.")
        events = get_run_events(session, run_id)
        recent_errors = [
            {
                "job_id": e["job_id"],
                "case_id": e["case_id"],
                "version": e["version"],
                "stage": e["stage"],
                "attempt": e["attempt"],
                "error_code": e.get("error_code"),
                "error_detail": e.get("error_detail"),
                "finished_at": e.get("finished_at"),
            }
            for e in events
            if e.get("status") == "error"
        ][-25:]
        return {
            **_run_summary_dict(rec),
            "metrics": json.loads(rec.metrics_json) if rec.metrics_json else None,
            "rows": json.loads(rec.rows_json) if rec.rows_json else [],
            "report_md": rec.report_md,
            "has_review": bool(rec.review_doc_json),
            "recent_errors": recent_errors,
        }


@app.post("/api/runs/{run_id}/resume", status_code=202, dependencies=[Depends(require_auth)])
def resume_run(run_id: str):
    refresh_local_env()
    try:
        RUN_MANAGER.resume_run(run_id)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
    return {"run_id": run_id, "status": "queued"}


@app.post("/api/runs/{run_id}/cancel", dependencies=[Depends(require_auth)])
def cancel_run(run_id: str):
    cancelled = RUN_MANAGER.cancel_run(run_id)
    return {"run_id": run_id, "cancel_requested": cancelled}


@app.get("/api/runs/{run_id}/review", dependencies=[Depends(require_auth)])
def get_review(run_id: str):
    """Return strictly blinded human review items (no prompt version or judge ratings leaked)."""
    with SessionLocal() as session:
        rec = session.get(EvalRun, run_id)
        if not rec:
            raise HTTPException(status_code=404, detail="Run not found.")
        if not rec.review_doc_json:
            return {
                "available": False,
                "reason": "Human review set is generated once all planned summaries succeed.",
                "items": [],
            }
        doc = json.loads(rec.review_doc_json)
        metrics = json.loads(rec.metrics_json) if rec.metrics_json else None
        cal_items = [i for i in doc["items"] if i["review_phase"] == "calibration"]
        val_items = [i for i in doc["items"] if i["review_phase"] == "validation"]
        cal_done = sum(1 for i in cal_items if i["label"] is not None)
        val_done = sum(1 for i in val_items if i["label"] is not None)
        return {
            "available": True,
            "instructions": doc["instructions"],
            "rubric": doc["rubric"],
            "product_spec": doc["product_spec"],
            "gap_policies": doc["gap_policies"],
            "progress": {
                "calibration_done": cal_done,
                "calibration_total": len(cal_items),
                "validation_done": val_done,
                "validation_total": len(val_items),
            },
            # Only expose agreement summary; individual blinded items never include judge scores or version IDs.
            "human_metrics": metrics.get("human") if metrics else None,
            "items": doc["items"],
        }


@app.post("/api/runs/{run_id}/review/{review_id}", dependencies=[Depends(require_auth)])
def submit_review_label(run_id: str, review_id: str, req: HumanLabelRequest):
    with SessionLocal() as session:
        rec = session.get(EvalRun, run_id)
        if not rec or not rec.review_doc_json or not rec.review_key_json:
            raise HTTPException(status_code=404, detail="Review set not available for this run.")
        doc = json.loads(rec.review_doc_json)
        key = json.loads(rec.review_key_json)
        target = next((item for item in doc["items"] if item["review_id"] == review_id), None)
        if not target:
            raise HTTPException(status_code=404, detail=f"Review item {review_id} not found.")

        label = {
            "human_attestation": req.human_attestation,
            "reviewed_by": req.reviewed_by.strip(),
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "faithfulness": req.faithfulness,
            "completeness": req.completeness,
            "usefulness": req.usefulness,
            "critical_errors": [e.strip() for e in req.critical_errors if e.strip()],
            "notes": req.notes.strip(),
        }
        try:
            validate_human_label(label)
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err))

        target["label"] = label
        rec.review_doc_json = json.dumps(doc, ensure_ascii=False)

        # Recompute offline metrics & report immediately
        manifest = json.loads(rec.manifest_json)
        events = get_run_events(session, run_id)
        metrics, rows, report = analyze_data(manifest, events, doc, key)
        rec.metrics_json = json.dumps(metrics, ensure_ascii=False)
        rec.rows_json = json.dumps(rows, ensure_ascii=False)
        rec.report_md = report
        rec.updated_at = utcnow()
        session.commit()

        return {
            "saved": True,
            "review_id": review_id,
            "human_metrics": metrics["human"],
            "recommendation": metrics["recommendation"],
        }


@app.get("/api/runs/{run_id}/export", dependencies=[Depends(require_auth)])
def export_run_bundle(run_id: str):
    """Export all artifacts needed for the assignment deliverables (manifest, events, review, metrics, REPORT.md)."""
    with SessionLocal() as session:
        rec = session.get(EvalRun, run_id)
        if not rec:
            raise HTTPException(status_code=404, detail="Run not found.")
        return {
            "run_id": rec.id,
            "manifest": json.loads(rec.manifest_json),
            "events": get_run_events(session, run_id),
            "human_review": json.loads(rec.review_doc_json) if rec.review_doc_json else None,
            "human_review_key": json.loads(rec.review_key_json) if rec.review_key_json else None,
            "metrics": json.loads(rec.metrics_json) if rec.metrics_json else None,
            "checks_and_judgments": json.loads(rec.rows_json) if rec.rows_json else None,
            "report_md": rec.report_md,
        }


@app.post("/api/runs/{run_id}/save-deliverables", dependencies=[Depends(require_auth)])
def save_deliverables_to_repo(run_id: str):
    """Persist run evidence (manifest, events, human review, metrics, REPORT.md) into results/<pair>/."""
    from es_eval.core import write_json
    with SessionLocal() as session:
        rec = session.get(EvalRun, run_id)
        if not rec:
            raise HTTPException(status_code=404, detail="Run not found.")
        if rec.use_mock:
            raise HTTPException(status_code=400, detail="Refusing to save mock-mode output as assignment deliverables.")
        folder_name = f"{rec.baseline_version}_vs_{rec.candidate_version}" if rec.scope == "full" else f"smoke_{rec.baseline_version}_vs_{rec.candidate_version}"
        out_dir = ROOT / "results" / folder_name
        out_dir.mkdir(parents=True, exist_ok=True)
        write_json(out_dir / "manifest.json", json.loads(rec.manifest_json))
        events = get_run_events(session, run_id)
        (out_dir / "events.jsonl").write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events),
            encoding="utf-8",
        )
        if rec.review_doc_json:
            write_json(out_dir / "human_review.json", json.loads(rec.review_doc_json))
        if rec.review_key_json:
            write_json(out_dir / "human_review_key.json", json.loads(rec.review_key_json))
        if rec.metrics_json:
            write_json(out_dir / "metrics.json", json.loads(rec.metrics_json))
        if rec.rows_json:
            write_json(out_dir / "checks_and_judgments.json", json.loads(rec.rows_json))
        if rec.report_md:
            (out_dir / "REPORT.md").write_text(rec.report_md, encoding="utf-8")
        if rec.scope == "full" and rec.baseline_version == "v1" and rec.candidate_version == "v2":
            try:
                from tools.sync_report import build_executive_report
                (ROOT / "REPORT.md").write_text(build_executive_report(out_dir), encoding="utf-8")
            except Exception:
                pass
        return {"saved": True, "directory": f"results/{folder_name}", "files_written": sorted(p.name for p in out_dir.iterdir())}
