#!/usr/bin/env python3
"""
LeadFlow Support: handoff summariser (starter).

Reads support conversations (data/threads.jsonl), asks an LLM for a handoff
summary using a chosen prompt version, and prints JSON lines.

  python summarise.py --prompt v1 --id T01
  python summarise.py --prompt v2 --all > outputs_v2.jsonl
  python summarise.py --prompt v1 --id T01 --runs 3        # repeat to see variation

Configuration (environment variables):
  LLM_BASE_URL   OpenAI-compatible endpoint, e.g. https://api.openai.com/v1
                 Set to "mock" to run without any API (see below).
  LLM_API_KEY    Your API key. Never commit it.
  LLM_MODEL      Model name.
  LLM_TEMPERATURE  Optional, default 0.7.

Mock mode (LLM_BASE_URL=mock) returns a crude extract of the conversation.
It exists so you can build and test your plumbing without an API key. It is
NOT a language model and says nothing about the real prompts.

You may import `summarise()` from your own code, or replace this file.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent


def load_threads(path=ROOT / "data" / "threads.jsonl"):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def render(thread):
    lines = [f"[{thread['channel']}]"]
    for m in thread["messages"]:
        lines.append(f"{m['role'].upper()}: {m['text']}")
    return "\n".join(lines)


def load_prompt(version):
    return (ROOT / "prompts" / f"{version}.txt").read_text(encoding="utf-8").strip()


def _mock(thread):
    words = " ".join(m["text"] for m in thread["messages"]).split()
    return " ".join(words[:30])


def summarise(thread, version="v1", temperature=None, timeout=60, retries=3):
    """Return the summary text for one thread."""
    base = os.environ.get("LLM_BASE_URL", "")
    if base == "mock":
        return _mock(thread)
    key, model = os.environ.get("LLM_API_KEY"), os.environ.get("LLM_MODEL")
    if not (base and key and model):
        sys.exit("Set LLM_BASE_URL, LLM_API_KEY and LLM_MODEL (or LLM_BASE_URL=mock).")
    if temperature is None:
        temperature = float(os.environ.get("LLM_TEMPERATURE", "0.7"))

    body = json.dumps({
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": load_prompt(version)},
            {"role": "user", "content": "Conversation:\n\n" + render(thread)},
        ],
    }).encode()
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            sys.exit(f"LLM request failed: HTTP {e.code}")
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            sys.exit("LLM request failed: network error")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="v1", help="prompt version: v1 or v2")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--id", help="one thread id, e.g. T01")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--runs", type=int, default=1, help="repeat each thread N times")
    ap.add_argument("--temperature", type=float)
    a = ap.parse_args()

    threads = load_threads()
    if a.id:
        threads = [t for t in threads if t["id"] == a.id]
        if not threads:
            sys.exit(f"no thread {a.id}")
    for t in threads:
        for run in range(a.runs):
            out = summarise(t, a.prompt, a.temperature)
            print(json.dumps({"id": t["id"], "prompt": a.prompt, "run": run, "summary": out},
                             ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
