"""Sequential, resumable calls to an OpenAI-compatible chat endpoint."""
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .core import digest, judge_messages, read_json, validate_judgment, write_json


def now():
    return datetime.now(timezone.utc).isoformat()


class CallFailure(Exception):
    def __init__(self, code, retryable=False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class ChatClient:
    def __init__(self, config, judge=False):
        prefix = "JUDGE_" if judge else "LLM_"
        base = os.getenv(prefix + "BASE_URL", os.getenv("LLM_BASE_URL", "")).rstrip("/")
        model = os.getenv(prefix + "MODEL", os.getenv("LLM_MODEL", ""))
        if not base or not model or "REPLACE_" in model:
            raise ValueError("Set LLM_BASE_URL and LLM_MODEL (and optional JUDGE overrides) before live calls.")
        url = urllib.parse.urlsplit(base)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Use an http(s) API base URL without embedded credentials, query, or fragment.")
        if url.scheme == "http" and url.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("Remote endpoints require HTTPS.")
        self.base, self.model = base, model
        self.key = os.getenv(prefix + "API_KEY", os.getenv("LLM_API_KEY", ""))
        self.timeout = config["timeout_seconds"]

    @property
    def identity(self):
        return {"base_url": self.base, "model": self.model}

    def complete(self, messages, temperature, max_tokens):
        body = {"model": self.model, "messages": messages, "temperature": temperature}
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        payload = json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = "Bearer " + self.key
        request = urllib.request.Request(self.base + "/chat/completions", payload, headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read())
            content = result["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("No string output")
            return {"text": content, "usage": result.get("usage"),
                    "response_model": result.get("model"), "response_id": result.get("id"),
                    "finish_reason": result["choices"][0].get("finish_reason")}
        except urllib.error.HTTPError as error:
            # Never persist provider error bodies: they can echo a credential or private request.
            raise CallFailure("http_" + str(error.code), error.code in (408, 429, 500, 502, 503, 504)) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            raise CallFailure("connection_or_timeout", True) from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise CallFailure("invalid_provider_response") from None


def read_events(path):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as stream:
        for index, line in enumerate(stream, 1):
            try:
                rows.append(json.loads(line))
            except ValueError:
                raise ValueError(f"Corrupt events file at line {index}; restore it before resuming.") from None
    return rows


def append_event(path, row):
    # One writer per run directory. fsync ensures results survive a process interruption.
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


class RunLock:
    def __init__(self, directory):
        self.path = Path(directory) / ".run.lock"

    def __enter__(self):
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise ValueError("Run is locked. Do not run two writers. After a crashed process, remove .run.lock manually.") from None
        os.write(self.fd, str(os.getpid()).encode())
        return self

    def __exit__(self, *_):
        os.close(self.fd)
        self.path.unlink()


def schedule(inputs, limit=None):
    jobs = [{"case_id": c["id"], "version": v, "repeat": repeat,
             "job_id": digest([c["id"], v, repeat])[:24]}
            for c in inputs["cases"][:limit] for v in ("v1", "v2")
            for repeat in range(inputs["config"]["repeats"])]
    random.Random(inputs["config"]["schedule_seed"]).shuffle(jobs)
    return jobs


def prepare_run(directory, inputs, clients, limit=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    identity = {"inputs": inputs, "clients": {k: v.identity for k, v in clients.items()},
                "scope": "smoke" if limit else "full", "limit": limit}
    fingerprint = digest(identity)
    path = directory / "manifest.json"
    if path.exists():
        manifest = read_json(path)
        if manifest["fingerprint"] != fingerprint:
            raise ValueError("Run inputs/model/settings changed. Choose a new run directory.")
    else:
        manifest = {**identity, "fingerprint": fingerprint, "created_at": now(), "jobs": schedule(inputs, limit)}
        write_json(path, manifest)
    return manifest


def execute_job(directory, manifest, client, job, stage, messages):
    path = Path(directory) / "events.jsonl"
    previous = [x for x in read_events(path) if x["job_id"] == job["job_id"] and x["stage"] == stage]
    success = next((x for x in reversed(previous) if x["status"] == "ok"), None)
    if success:
        return success
    config = manifest["inputs"]["config"]
    attempts = config["max_attempts"]
    for number in range(len(previous) + 1, attempts + 1):
        start = time.monotonic()
        event = {**job, "stage": stage, "attempt": number, "started_at": now(),
                 "run_fingerprint": manifest["fingerprint"], "request_hash": digest(messages),
                 "client": client.identity, "cost_usd": None}
        event["settings"] = {"temperature": config["judge_temperature"] if stage == "judge" else config["temperature"],
                             "max_tokens": config["judge_max_tokens"] if stage == "judge" else config["max_tokens"] if config.get("send_generation_max_tokens", True) else None}
        retryable = False
        try:
            result = client.complete(messages, event["settings"]["temperature"], event["settings"]["max_tokens"])
            event.update(result)
            if stage == "judge":
                try:
                    event["judgment"] = validate_judgment(json.loads(result["text"]))
                except (ValueError, TypeError):
                    raise CallFailure("invalid_judge_schema", True) from None
            event["status"] = "ok"
        except CallFailure as error:
            event.update(status="error", error_code=error.code)
            retryable = error.retryable
        event.update(finished_at=now(), latency_seconds=round(time.monotonic() - start, 4))
        append_event(path, event)
        if event["status"] == "ok":
            return event
        if not retryable:
            break
        if number < attempts:
            time.sleep(min(2 ** (number - 1), 8))
    return None


def make_review(directory, manifest):
    """Select before judging; review file deliberately contains no version or judge labels."""
    directory = Path(directory)
    if (directory / "human_review.json").exists():
        return
    inputs = manifest["inputs"]
    successful = {e["job_id"]: e for e in read_events(directory / "events.jsonl")
                  if e["stage"] == "generate" and e["status"] == "ok"}
    by_version = {v: [job for job in manifest["jobs"] if job["version"] == v and job["job_id"] in successful]
                  for v in ("v1", "v2")}
    if len(successful) != len(manifest["jobs"]):
        # Wait for the planned generation pool; never freeze an accidentally incomplete sample.
        return
    rng = random.Random(inputs["config"]["schedule_seed"] + 1)
    for jobs in by_version.values():
        rng.shuffle(jobs)
    # Prefer different cases, then fill remaining slots from repeats.
    selected = []
    plan = inputs["config"].get("human_review_plan")
    if plan and manifest["scope"] == "full":
        for split in ("calibration", "validation"):
            for case_id in plan[split + "_case_ids"]:
                for version in ("v1", "v2"):
                    # Pool is already shuffled: select one reproducible repeat per case/version.
                    selected.append(next(j for j in by_version[version] if j["case_id"] == case_id))
    else:
        for version in ("v1", "v2"):
            pool, chosen, seen = by_version[version], [], set()
            for job in pool:
                if job["case_id"] not in seen and len(chosen) < 15:
                    chosen.append(job)
                    seen.add(job["case_id"])
            chosen += [j for j in pool if j not in chosen][:15 - len(chosen)]
            selected.extend(chosen)
    rng.shuffle(selected)
    cases = {c["id"]: c for c in inputs["cases"]}
    key, review = [], []
    # Allocate five calibration labels per version when the full 30-label sample is available.
    calibration_count = {"v1": 0, "v2": 0}
    for index, job in enumerate(selected):
        case = cases[job["case_id"]]
        review_id = f"review-{index + 1:03d}"
        if plan and manifest["scope"] == "full":
            split = "calibration" if job["case_id"] in plan["calibration_case_ids"] else "validation"
        else:
            split = "calibration" if calibration_count[job["version"]] < 5 else "validation"
        if split == "calibration":
            calibration_count[job["version"]] += 1
        key.append({"review_id": review_id, "job_id": job["job_id"], "split": split})
        review.append({"review_id": review_id, "review_phase": split, "conversation": case["conversation"],
                       "expectations": {k: case[k] for k in ("must_include", "must_not_include", "ambiguities", "final_status", "next_action", "owner")},
                       "summary": successful[job["job_id"]]["text"], "label": None})
    write_json(directory / "human_review_key.json", key)
    write_json(directory / "human_review.json", {"instructions": "Human only. Read HUMAN_REVIEW.md and the rubric; label calibration first. Leave validation untouched until the judge is frozen.",
               "rubric": inputs["judge_prompt"], "product_spec": inputs["spec"],
               "gap_policies": inputs["config"].get("judge_policy", ""), "items": review})


def run(directory, inputs, clients, limit=None, stage="all"):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with RunLock(directory):
        manifest = prepare_run(directory, inputs, clients, limit)
        cases = {c["id"]: c for c in inputs["cases"]}
        if stage in ("all", "generate"):
            for job in manifest["jobs"]:
                # Match starter.load_prompt().strip() and starter.render() input exactly.
                messages = [{"role": "system", "content": inputs["prompts"][job["version"]].strip()},
                            {"role": "user", "content": cases[job["case_id"]]["conversation"]}]
                execute_job(directory, manifest, clients["generate"], job, "generate", messages)
            make_review(directory, manifest)
        if stage in ("all", "judge"):
            make_review(directory, manifest)
            events = read_events(directory / "events.jsonl")
            summaries = {x["job_id"]: x for x in events if x["stage"] == "generate" and x["status"] == "ok"}
            for job in manifest["jobs"]:
                if job["job_id"] in summaries:
                    execute_job(directory, manifest, clients["judge"], job, "judge",
                                judge_messages(inputs, cases[job["case_id"]], summaries[job["job_id"]]["text"]))
        return manifest
