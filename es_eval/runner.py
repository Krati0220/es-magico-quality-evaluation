"""Sequential, resumable calls to an OpenAI-compatible chat endpoint (Groq-ready)."""
import json
import os
import random
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .core import (
    digest,
    estimate_cost_usd,
    extract_json_object,
    judge_messages,
    read_json,
    validate_judgment,
    write_json,
)


def now():
    return datetime.now(timezone.utc).isoformat()


def _parse_duration_seconds(value):
    """Parse Retry-After or Groq x-ratelimit-reset-* values (e.g. '12', '4.5s', '1m3s', '500ms')."""
    if not value:
        return None
    raw = str(value).strip().lower()
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    total = 0.0
    matched = False
    for amount, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(ms|s|m|h)", raw):
        matched = True
        num = float(amount)
        if unit == "ms":
            total += num / 1000.0
        elif unit == "s":
            total += num
        elif unit == "m":
            total += num * 60.0
        elif unit == "h":
            total += num * 3600.0
    return total if matched else None


def _extract_retry_after(headers):
    if not headers:
        return None
    candidates = []
    for key in ("retry-after", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        val = headers.get(key)
        parsed = _parse_duration_seconds(val)
        if parsed is not None and parsed > 0:
            candidates.append(parsed)
    return min(max(candidates), 65.0) if candidates else None


def _safe_error_detail(http_error):
    """Extract only short safe error type/code tokens; never persist raw provider error bodies."""
    try:
        raw = http_error.read(2048)
        payload = json.loads(raw.decode("utf-8", errors="ignore"))
        err = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(err, dict):
            parts = []
            for k in ("type", "code", "param"):
                v = err.get(k)
                if isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", v):
                    parts.append(f"{k}={v}")
            if parts:
                return ",".join(parts)
    except Exception:
        pass
    return None


class CallFailure(Exception):
    def __init__(self, code, retryable=False, retry_after=None, detail=None):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after
        self.detail = detail


def _ssl_context():
    """Return a verified SSLContext that works on macOS python.org builds and Linux containers."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    for system_ca in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt"):
        if os.path.exists(system_ca):
            return ssl.create_default_context(cafile=system_ca)
    return ssl.create_default_context()


class ChatClient:
    supports_response_format = True

    def __init__(self, config, judge=False, base_url=None, model=None, api_key=None):
        prefix = "JUDGE_" if judge else "LLM_"
        base = (base_url if base_url is not None else os.getenv(prefix + "BASE_URL", os.getenv("LLM_BASE_URL", ""))).rstrip("/")
        chosen_model = model if model is not None else os.getenv(prefix + "MODEL", os.getenv("LLM_MODEL", ""))
        if not base or not chosen_model or "REPLACE_" in chosen_model:
            raise ValueError("Set LLM_BASE_URL and LLM_MODEL (and optional JUDGE overrides) before live calls.")
        url = urllib.parse.urlsplit(base)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Use an http(s) API base URL without embedded credentials, query, or fragment.")
        if url.scheme == "http" and url.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("Remote endpoints require HTTPS.")
        self.base, self.model = base, chosen_model
        self.key = api_key if api_key is not None else os.getenv(prefix + "API_KEY", os.getenv("LLM_API_KEY", ""))
        self.timeout = config["timeout_seconds"]

    @property
    def identity(self):
        return {"base_url": self.base, "model": self.model}

    def _send(self, body):
        payload = json.dumps(body).encode()
        headers = {"Content-Type": "application/json", "User-Agent": "es-magico-eval/1.0"}
        if self.key:
            headers["Authorization"] = "Bearer " + self.key
        request = urllib.request.Request(self.base + "/chat/completions", payload, headers)
        urlopen_kwargs = {"timeout": self.timeout}
        if self.base.startswith("https://"):
            urlopen_kwargs["context"] = _ssl_context()
        with urllib.request.urlopen(request, **urlopen_kwargs) as response:
            result = json.loads(response.read())
        content = result["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("No string output")
        usage = result.get("usage")
        resp_model = result.get("model")
        return {
            "text": content,
            "usage": usage,
            "response_model": resp_model,
            "response_id": result.get("id"),
            "finish_reason": result["choices"][0].get("finish_reason"),
            "cost_usd": estimate_cost_usd(resp_model or self.model, usage),
        }

    def complete(self, messages, temperature, max_tokens, response_format=None, reasoning_effort=None):
        body = {"model": self.model, "messages": messages, "temperature": temperature}
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if response_format is not None:
            body["response_format"] = response_format
        if reasoning_effort is not None and any(tok in self.model.lower() for tok in ("gpt-oss", "o1", "o3", "o4")):
            body["reasoning_effort"] = reasoning_effort
        try:
            return self._send(body)
        except urllib.error.HTTPError as error:
            # If provider rejects optional structured/reasoning params with HTTP 400, retry cleanly without them.
            if error.code == 400 and ("response_format" in body or "reasoning_effort" in body):
                body.pop("response_format", None)
                body.pop("reasoning_effort", None)
                try:
                    return self._send(body)
                except urllib.error.HTTPError as fallback_error:
                    error = fallback_error
                except (urllib.error.URLError, TimeoutError, ConnectionError) as fallback_net:
                    reason = getattr(fallback_net, "reason", fallback_net)
                    raise CallFailure("connection_or_timeout", True, detail=type(reason).__name__) from None
                except (ValueError, KeyError, IndexError, TypeError):
                    raise CallFailure("invalid_provider_response") from None
            retry_after = _extract_retry_after(error.headers) if error.code == 429 else None
            detail = _safe_error_detail(error)
            # Never persist provider error bodies: they can echo a credential or private request.
            raise CallFailure(
                "http_" + str(error.code),
                error.code in (408, 429, 500, 502, 503, 504),
                retry_after=retry_after,
                detail=detail,
            ) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as net_error:
            reason = getattr(net_error, "reason", net_error)
            raise CallFailure("connection_or_timeout", True, detail=type(reason).__name__) from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise CallFailure("invalid_provider_response") from None


class MockChatClient:
    """Explicit offline demo client for UI plumbing tests when no API key is configured.
    Never represents real LLM behavior."""

    supports_response_format = False

    def __init__(self, judge=False):
        self.judge = judge

    @property
    def identity(self):
        return {"base_url": "mock://demo", "model": "mock-demo-not-real-llm"}

    def complete(self, messages, temperature, max_tokens, response_format=None):
        if self.judge:
            payload = {
                "faithfulness": 4,
                "completeness": 4,
                "usefulness": 4,
                "critical_errors": [],
                "reasons": {
                    "faithfulness": "Mock demo judge score (configure LLM_API_KEY / GROQ_API_KEY for live evaluation).",
                    "completeness": "Mock demo judge score (configure LLM_API_KEY / GROQ_API_KEY for live evaluation).",
                    "usefulness": "Mock demo judge score (configure LLM_API_KEY / GROQ_API_KEY for live evaluation).",
                },
                "evidence": [{"source": "Mock demo mode", "summary": "Mock demo mode"}],
            }
            return {
                "text": json.dumps(payload),
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "response_model": "mock-demo-not-real-llm",
                "response_id": "mock-judge",
                "finish_reason": "stop",
                "cost_usd": 0.0,
            }
        system_prompt = messages[0]["content"] if messages else ""
        convo = messages[-1]["content"] if messages else ""
        lines = [ln.strip() for ln in convo.splitlines() if ln.strip() and not ln.startswith("Conversation:") and not ln.startswith("[")]
        snippet = " ".join(lines[:2])
        words = snippet.split()[:26]
        body = " ".join(words)
        if "Issue:" in system_prompt and "Status:" in system_prompt:
            text = f"Issue: {body}\nStatus: Pending follow-up (mock output).\nNext step: Review thread."
        else:
            text = f"Customer handoff (mock preview): {body}. Case remains open pending next agent review."
        return {
            "text": text,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "response_model": "mock-demo-not-real-llm",
            "response_id": "mock-gen",
            "finish_reason": "stop",
            "cost_usd": 0.0,
        }


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


def schedule(inputs, limit=None, versions=("v1", "v2")):
    jobs = [{"case_id": c["id"], "version": v, "repeat": repeat,
             "job_id": digest([c["id"], v, repeat])[:24]}
            for c in inputs["cases"][:limit] for v in versions
            for repeat in range(inputs["config"]["repeats"])]
    random.Random(inputs["config"]["schedule_seed"]).shuffle(jobs)
    return jobs


def prepare_run(directory, inputs, clients, limit=None, versions=("v1", "v2")):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    identity = {"inputs": inputs, "clients": {k: v.identity for k, v in clients.items()},
                "scope": "smoke" if limit else "full", "limit": limit}
    if tuple(versions) != ("v1", "v2"):
        identity["versions"] = list(versions)
    fingerprint = digest(identity)
    path = directory / "manifest.json"
    if path.exists():
        manifest = read_json(path)
        if manifest["fingerprint"] != fingerprint:
            raise ValueError("Run inputs/model/settings changed. Choose a new run directory.")
    else:
        manifest = {**identity, "fingerprint": fingerprint, "created_at": now(),
                    "jobs": schedule(inputs, limit, versions=versions)}
        write_json(path, manifest)
    return manifest


def execute_job(directory, manifest, client, job, stage, messages, event_cache=None, on_event=None):
    path = Path(directory) / "events.jsonl" if directory is not None else None
    all_events = event_cache if event_cache is not None else read_events(path)
    previous = [x for x in all_events if x["job_id"] == job["job_id"] and x["stage"] == stage]
    success = next((x for x in reversed(previous) if x["status"] == "ok"), None)
    if success:
        return success
    config = manifest["inputs"]["config"]
    attempts = config["max_attempts"]
    min_delay = float(config.get("rate_limit_min_delay_seconds") or 0.0)
    response_format = None
    reasoning_effort = None
    if stage == "judge" and getattr(client, "supports_response_format", False):
        rf_mode = config.get("judge_response_format")
        if rf_mode == "json_object":
            response_format = {"type": "json_object"}
        reasoning_effort = config.get("judge_reasoning_effort")

    for number in range(len(previous) + 1, attempts + 1):
        start = time.monotonic()
        event = {**job, "stage": stage, "attempt": number, "started_at": now(),
                 "run_fingerprint": manifest["fingerprint"], "request_hash": digest(messages),
                 "client": client.identity, "cost_usd": None}
        event["settings"] = {"temperature": config["judge_temperature"] if stage == "judge" else config["temperature"],
                             "max_tokens": config["judge_max_tokens"] if stage == "judge" else config["max_tokens"] if config.get("send_generation_max_tokens", True) else None}
        retryable = False
        retry_after = None
        try:
            if response_format is not None or reasoning_effort is not None:
                result = client.complete(messages, event["settings"]["temperature"], event["settings"]["max_tokens"],
                                         response_format=response_format, reasoning_effort=reasoning_effort)
            else:
                result = client.complete(messages, event["settings"]["temperature"], event["settings"]["max_tokens"])
            event.update(result)
            if event.get("cost_usd") is None and event.get("usage"):
                event["cost_usd"] = estimate_cost_usd(
                    event.get("response_model") or client.identity.get("model"),
                    event.get("usage"),
                )
            if stage == "judge":
                try:
                    event["judgment"] = validate_judgment(extract_json_object(result["text"]))
                except (ValueError, TypeError):
                    raise CallFailure("invalid_judge_schema", True) from None
            event["status"] = "ok"
        except CallFailure as error:
            event.update(status="error", error_code=error.code)
            if error.detail:
                event["error_detail"] = error.detail
            retryable = error.retryable
            retry_after = error.retry_after
        event.update(finished_at=now(), latency_seconds=round(time.monotonic() - start, 4))
        if path is not None:
            append_event(path, event)
        if event_cache is not None:
            event_cache.append(event)
        if on_event is not None:
            on_event(event)
        if event["status"] == "ok":
            if min_delay > 0:
                time.sleep(min_delay)
            return event
        if not retryable:
            break
        if number < attempts:
            wait = (retry_after + 1.0) if retry_after is not None else min(2 ** (number - 1), 8)
            time.sleep(wait)
    return None


def build_review_bundle(manifest, events):
    """Build blinded human review items + companion key in memory."""
    inputs = manifest["inputs"]
    versions = tuple(manifest.get("versions", ("v1", "v2")))
    successful = {e["job_id"]: e for e in events if e["stage"] == "generate" and e["status"] == "ok"}
    if len(successful) != len(manifest["jobs"]):
        return None, None
    by_version = {v: [job for job in manifest["jobs"] if job["version"] == v and job["job_id"] in successful]
                  for v in versions}
    rng = random.Random(inputs["config"]["schedule_seed"] + 1)
    for jobs in by_version.values():
        rng.shuffle(jobs)
    selected = []
    plan = inputs["config"].get("human_review_plan")
    if plan and manifest["scope"] == "full":
        for split in ("calibration", "validation"):
            for case_id in plan[split + "_case_ids"]:
                for version in versions:
                    selected.append(next(j for j in by_version[version] if j["case_id"] == case_id))
    else:
        for version in versions:
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
    calibration_count = {v: 0 for v in versions}
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
        review.append({
            "review_id": review_id,
            "review_phase": split,
            "conversation": case["conversation"],
            "expectations": {k: case[k] for k in ("must_include", "must_not_include", "ambiguities", "final_status", "next_action", "owner")},
            "summary": successful[job["job_id"]]["text"],
            "label": None,
        })
    review_doc = {
        "instructions": "Human only. Read HUMAN_REVIEW.md and the rubric; label calibration first. Leave validation untouched until the judge is frozen.",
        "rubric": inputs["judge_prompt"],
        "product_spec": inputs["spec"],
        "gap_policies": inputs["config"].get("judge_policy", ""),
        "items": review,
    }
    return review_doc, key


def make_review(directory, manifest, events=None):
    """Select before judging; review file deliberately contains no version or judge labels."""
    directory = Path(directory)
    if (directory / "human_review.json").exists():
        return
    all_events = events if events is not None else read_events(directory / "events.jsonl")
    review_doc, key = build_review_bundle(manifest, all_events)
    if review_doc is None:
        return
    write_json(directory / "human_review_key.json", key)
    write_json(directory / "human_review.json", review_doc)


def resolve_prompt(inputs, version):
    if version in inputs["prompts"]:
        return inputs["prompts"][version]
    if version in inputs.get("extra_prompts", {}):
        return inputs["extra_prompts"][version]
    raise ValueError(f"Unknown prompt version: {version}")


def run(directory, inputs, clients, limit=None, stage="all", versions=("v1", "v2"), on_event=None, cancel_check=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with RunLock(directory):
        manifest = prepare_run(directory, inputs, clients, limit, versions=versions)
        cases = {c["id"]: c for c in inputs["cases"]}
        event_cache = read_events(directory / "events.jsonl")
        if stage in ("all", "generate"):
            for job in manifest["jobs"]:
                if cancel_check and cancel_check():
                    return manifest
                # Match starter.load_prompt().strip() and starter.render() input exactly.
                messages = [{"role": "system", "content": resolve_prompt(inputs, job["version"]).strip()},
                            {"role": "user", "content": cases[job["case_id"]]["conversation"]}]
                execute_job(directory, manifest, clients["generate"], job, "generate", messages,
                            event_cache=event_cache, on_event=on_event)
            make_review(directory, manifest, events=event_cache)
        if stage in ("all", "judge"):
            make_review(directory, manifest, events=event_cache)
            summaries = {x["job_id"]: x for x in event_cache if x["stage"] == "generate" and x["status"] == "ok"}
            for job in manifest["jobs"]:
                if cancel_check and cancel_check():
                    return manifest
                if job["job_id"] in summaries:
                    execute_job(directory, manifest, clients["judge"], job, "judge",
                                judge_messages(inputs, cases[job["case_id"]], summaries[job["job_id"]]["text"]),
                                event_cache=event_cache, on_event=on_event)
        return manifest
