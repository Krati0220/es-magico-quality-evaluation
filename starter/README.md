# Support handoff summariser (starter)

A small LLM feature for a customer-support team. When a case moves from one agent to another, the next agent sees a short summary at the top of the case instead of reading the whole conversation.

This folder has the feature as it is today, two versions of its prompt, and 45 synthetic conversations. Your job is to test it.

## What the product owner asked for

- A short summary the next agent can read in a few seconds.
- A single short paragraph. No lists, headings or markdown.
- It says what the customer wants and where the case stands now.
- It only says things that are in the conversation. No guessing.
- It must not expose personal data such as phone numbers, email addresses, full addresses, card numbers or one-time passwords. Order numbers, amounts and dates are fine and useful.
- Neutral tone. It does not repeat insults or profanity.
- If there is a safety problem, it says so clearly.

That is the whole spec. If something is not covered, that is a gap you will have to notice and decide about.

## The two prompt versions

`prompts/v1.txt` is what runs in production today. `prompts/v2.txt` is a proposed replacement from a teammate who says it is "tighter". The team wants to know whether it is safe to ship.

## Data

`data/threads.jsonl` has 45 synthetic conversations, one JSON object per line:

```json
{"id": "T01", "channel": "chat", "messages": [{"role": "customer", "text": "..."}, {"role": "agent", "text": "..."}]}
```

Roles are `customer`, `agent` and `bot`. Channels are `chat`, `email` and `voice` (a call transcript). The conversations are made up. Customers, numbers and addresses are not real.

## Run it

Python 3.9 or newer, no packages needed.

```bash
cp .env.example .env     # fill in a provider, key and model, then load them into your shell
python summarise.py --prompt v1 --id T01
python summarise.py --prompt v2 --all > outputs_v2.jsonl
python summarise.py --prompt v1 --id T01 --runs 3     # same input, repeated
```

Any OpenAI-compatible provider works, including free tiers and local models. For plumbing tests without a key, set `LLM_BASE_URL=mock`. Mock mode is not a language model and tells you nothing about the prompts.

You can use `summarise.py` as it is, import `summarise()` from your own code, or replace it.
