"""Background evaluation run worker with DB-backed resumability and cancellation."""
import copy
import json
import os
import threading
import uuid
from pathlib import Path

from es_eval.analysis import analyze_data
from es_eval.core import digest, judge_messages, load_inputs
from es_eval.runner import (
    ChatClient,
    MockChatClient,
    build_review_bundle,
    execute_job,
    now,
    resolve_prompt,
    schedule,
)

from .db import EvalRun, SessionLocal, append_run_event, get_run_events, utcnow

ROOT = Path(__file__).resolve().parents[1]


def build_clients(config, use_mock=False):
    if use_mock:
        return {"generate": MockChatClient(judge=False), "judge": MockChatClient(judge=True)}
    return {
        "generate": ChatClient(config, judge=False),
        "judge": ChatClient(config, judge=True),
    }


def provider_status(config):
    """Non-sensitive provider configuration status."""
    gen_base = os.getenv("LLM_BASE_URL", "").strip()
    gen_model = os.getenv("LLM_MODEL", "").strip()
    gen_has_key = bool(os.getenv("LLM_API_KEY", "").strip())
    judge_base = os.getenv("JUDGE_BASE_URL", gen_base).strip()
    judge_model = os.getenv("JUDGE_MODEL", gen_model).strip()
    judge_has_key = bool(os.getenv("JUDGE_API_KEY", os.getenv("LLM_API_KEY", "")).strip())
    configured = bool(gen_base and gen_model and "REPLACE_" not in gen_model and "YOUR_" not in gen_model)
    return {
        "configured": configured,
        "generate": {
            "base_url": gen_base or None,
            "model": gen_model or None,
            "has_api_key": gen_has_key,
        },
        "judge": {
            "base_url": judge_base or None,
            "model": judge_model or None,
            "has_api_key": judge_has_key,
        },
        "same_model_and_endpoint": bool(configured and gen_base == judge_base and gen_model == judge_model),
        "default_rate_limit_delay": float(os.getenv("RATE_LIMIT_MIN_DELAY_SECONDS", config.get("rate_limit_min_delay_seconds", 0.0))),
    }


class RunManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._active = {}  # run_id -> threading.Event (cancel flag)

    def is_active(self, run_id):
        with self._lock:
            return run_id in self._active

    def cancel_run(self, run_id):
        with self._lock:
            flag = self._active.get(run_id)
            if flag:
                flag.set()
                return True
        return False

    def create_and_start(self, name, scope="smoke", candidate_version="v2", use_mock=False, rate_limit_delay=None, repeats=None):
        inputs = load_inputs(ROOT / "config.json")
        inputs = copy.deepcopy(inputs)
        if rate_limit_delay is not None:
            inputs["config"]["rate_limit_min_delay_seconds"] = max(0.0, min(float(rate_limit_delay), 30.0))
        else:
            env_delay = os.getenv("RATE_LIMIT_MIN_DELAY_SECONDS")
            if env_delay:
                inputs["config"]["rate_limit_min_delay_seconds"] = max(0.0, float(env_delay))
        if repeats is not None and scope == "smoke":
            inputs["config"]["repeats"] = max(1, min(int(repeats), 3))

        # Validate prompt availability
        versions = ("v1", candidate_version)
        for v in versions:
            resolve_prompt(inputs, v)

        clients = build_clients(inputs["config"], use_mock=use_mock)
        limit = 2 if scope == "smoke" else None
        identity = {
            "inputs": inputs,
            "clients": {k: v.identity for k, v in clients.items()},
            "scope": scope,
            "limit": limit,
        }
        if versions != ("v1", "v2"):
            identity["versions"] = list(versions)
        fingerprint = digest(identity)
        jobs = schedule(inputs, limit=limit, versions=versions)
        manifest = {
            **identity,
            "fingerprint": fingerprint,
            "created_at": now(),
            "jobs": jobs,
        }

        run_id = "run-" + uuid.uuid4().hex[:12]
        total_steps = len(jobs) * 2
        with SessionLocal() as session:
            record = EvalRun(
                id=run_id,
                name=name or f"{scope.title()} ({versions[0]} vs {versions[1]})",
                scope=scope,
                baseline_version=versions[0],
                candidate_version=versions[1],
                status="queued",
                stage="all",
                use_mock=1 if use_mock else 0,
                completed_steps=0,
                total_steps=total_steps,
                manifest_json=json.dumps(manifest, ensure_ascii=False),
            )
            session.add(record)
            session.commit()

        self._launch_thread(run_id, use_mock=use_mock)
        return run_id

    def resume_run(self, run_id):
        with SessionLocal() as session:
            record = session.get(EvalRun, run_id)
            if not record:
                raise ValueError("Run not found.")
            if self.is_active(run_id):
                raise ValueError("Run is already executing.")
            use_mock = bool(record.use_mock)
            manifest = json.loads(record.manifest_json)
            # Validate client configuration before launching
            build_clients(manifest["inputs"]["config"], use_mock=use_mock)
            record.status = "queued"
            record.error_message = None
            record.updated_at = utcnow()
            session.commit()
        self._launch_thread(run_id, use_mock=use_mock)

    def _launch_thread(self, run_id, use_mock=False):
        cancel_event = threading.Event()
        with self._lock:
            self._active[run_id] = cancel_event
        thread = threading.Thread(
            target=self._execute_run,
            args=(run_id, use_mock, cancel_event),
            daemon=True,
            name=f"eval-{run_id}",
        )
        thread.start()

    def _execute_run(self, run_id, use_mock, cancel_event):
        try:
            with SessionLocal() as session:
                record = session.get(EvalRun, run_id)
                if not record:
                    return
                manifest = json.loads(record.manifest_json)
                events = get_run_events(session, run_id)
                record.status = "running"
                record.error_message = None
                record.updated_at = utcnow()
                session.commit()

            inputs = manifest["inputs"]
            cases = {c["id"]: c for c in inputs["cases"]}
            clients = build_clients(inputs["config"], use_mock=use_mock)
            total_steps = len(manifest["jobs"]) * 2

            def count_completed():
                ok_pairs = {(e["job_id"], e["stage"]) for e in events if e["status"] == "ok"}
                return len(ok_pairs)

            def persist_event(event):
                with SessionLocal() as s:
                    append_run_event(s, run_id, event)
                    rec = s.get(EvalRun, run_id)
                    if rec:
                        rec.completed_steps = count_completed()
                        rec.updated_at = utcnow()
                        s.commit()

            # Stage 1: Generate
            for job in manifest["jobs"]:
                if cancel_event.is_set():
                    break
                messages = [
                    {"role": "system", "content": resolve_prompt(inputs, job["version"]).strip()},
                    {"role": "user", "content": cases[job["case_id"]]["conversation"]},
                ]
                execute_job(
                    None,
                    manifest,
                    clients["generate"],
                    job,
                    "generate",
                    messages,
                    event_cache=events,
                    on_event=persist_event,
                )

            # Create blinded human review bundle if all generations succeeded
            with SessionLocal() as session:
                record = session.get(EvalRun, run_id)
                if record and not record.review_doc_json:
                    review_doc, review_key = build_review_bundle(manifest, events)
                    if review_doc is not None:
                        record.review_doc_json = json.dumps(review_doc, ensure_ascii=False)
                        record.review_key_json = json.dumps(review_key, ensure_ascii=False)
                        session.commit()

            # Stage 2: Judge
            if not cancel_event.is_set():
                summaries = {x["job_id"]: x for x in events if x["stage"] == "generate" and x["status"] == "ok"}
                for job in manifest["jobs"]:
                    if cancel_event.is_set():
                        break
                    if job["job_id"] in summaries:
                        execute_job(
                            None,
                            manifest,
                            clients["judge"],
                            job,
                            "judge",
                            judge_messages(inputs, cases[job["case_id"]], summaries[job["job_id"]]["text"]),
                            event_cache=events,
                            on_event=persist_event,
                        )

            # Offline analysis & status update
            with SessionLocal() as session:
                record = session.get(EvalRun, run_id)
                if not record:
                    return
                review_doc = json.loads(record.review_doc_json) if record.review_doc_json else None
                review_key = json.loads(record.review_key_json) if record.review_key_json else None
                metrics, rows, report = analyze_data(manifest, events, review_doc, review_key)
                completed = count_completed()
                record.completed_steps = completed
                record.total_steps = total_steps
                record.metrics_json = json.dumps(metrics, ensure_ascii=False)
                record.rows_json = json.dumps(rows, ensure_ascii=False)
                record.report_md = report
                if cancel_event.is_set():
                    record.status = "cancelled"
                elif completed == total_steps:
                    record.status = "completed"
                else:
                    record.status = "partial"
                record.updated_at = utcnow()
                session.commit()
        except Exception as exc:
            with SessionLocal() as session:
                record = session.get(EvalRun, run_id)
                if record:
                    record.status = "failed"
                    record.error_message = str(exc)[:500]
                    record.updated_at = utcnow()
                    session.commit()
        finally:
            with self._lock:
                self._active.pop(run_id, None)


RUN_MANAGER = RunManager()
