# MCP Shield: demo script (about 3 minutes)

## Before you start (5 minutes earlier)

```bash
cd ~/Desktop/mcp_gateway
rm -f logs/audit.db          # empty dashboard (also clears the description cache)
uv run python dashboard/server.py
```

1. Open http://127.0.0.1:8000 and zoom the browser to 110–125% so the room can read it.
2. Do one warm-up run: **Normal request → Through MCP Shield**. This fills the description cache, so the real runs start fast. It also confirms the API keys work.
3. Check the warm-up run's steps for `model: openai/gpt-oss-20b`. If you see `gemini-…`, Groq is rate limited. The demo still runs, but Gemini may refuse the attack even without the shield. Say so honestly if it happens.
4. Close other tabs. Turn on Do Not Disturb.

## The script

### 1. The problem (20 s, Live flow page, nothing running)

> "Agents with MCP tools trust text they didn't write: tool descriptions, emails, web pages. That gives an attacker three ways in: poison a tool's description, hide instructions in data the agent reads, or make the agent send secrets out. I built MCP Shield, a proxy that sits between the agent and its tools and checks all three."

Point at the request path: **User → Agent → MCP Shield → Tool server**.

### 2. The attack works (30 s)

Click **Indirect prompt injection → Without shield**.

> "The user just asks the agent to handle their latest email. The email secretly tells it to read the credentials file and email it to an outside address."

Point out the steps as they arrive: the agent reads the email, lists files, reads `credentials.txt`, calls `send_email`. A red banner appears: **"The secret reached the attacker."**

> "About 13 seconds, no warning to the user."

### 3. Same request through the shield (60–90 s)

Click **Indirect prompt injection → Through MCP Shield**. While it runs, narrate the lit-up stages:

- **Regex scan** on the email result: *"Score 1.0. That's an obvious attack, decided in under a millisecond without any LLM."*
- **Sanitize:** *"It doesn't throw the email away. It removes only the two injected sentences, so the user still gets their email."* Click a cleaned value to expand it.
- **LLM judge** on other steps: *"Anything that isn't obviously bad goes to an LLM judge with a structured verdict. That's the 1–2 second pauses."*
- If the agent still tries to read the credentials file, a **Decision needed** box appears. Click **Deny**.

> "This is LangGraph's `interrupt()`. The graph pauses, its state is checkpointed in SQLite, and it resumes with my answer. If nobody answers in 60 seconds, it denies. It fails closed."

The green banner appears: **"Attack stopped: no secret leaked."**

### 4. Optional: tool poisoning (20 s)

Click **Tool poisoning → Through MCP Shield**. In the steps: **"Hid the tool add_numbers: its description is poisoned."**

> "The poisoned tool is never even shown to the agent."

### 5. The numbers (30 s, Evaluation page)

> "I measured it on 200 labelled cases, plus 32 holdout cases I wrote after tuning. Regex alone catches 26%. My first version caught 48%. Then I added keyword rules and hit 95%. But on the holdout set that version scored 7%: the rules had memorised my own phrasing. So I threw them out and let the judge see everything that isn't obviously an attack. That's 98% on the main set and 93% on the holdout, at about 4% false positives, costing 1–2 seconds per check."

### 6. Close (10 s)

> "So: a proxy that works with any MCP client, a fast regex path plus an LLM judge, policy in YAML, human approval with LangGraph interrupts, a full audit trail, and an evaluation that's honest about its own weak spots."

## Likely questions

**Why a proxy and not a check inside the agent?**
It works with any MCP client unchanged, and it sees all three attack surfaces in one place. The cost is one extra hop and one more component that has to be trusted.

**Why regex at all if you have an LLM?**
Cost and speed. Obvious cases are decided in microseconds for free. The LLM handles what regex can't judge. It is also a backstop when the LLM is down: obvious attacks are still blocked.

**Can the judge be prompt-injected?**
Yes, in principle. Mitigations: the content is marked as data, the judge has no tools, its output is a schema-checked Pydantic object, a high regex score blocks without asking it, and judge failures fail closed. I would measure its robustness with a dedicated adversarial set next.

**What's your false-positive rate and what causes it?**
About 4% on benign cases, all of them deliberate lookalikes, for example a benign "your request is pre-approved" message. The judge reads those phrases as manipulation. The next step would be benign examples in the judge prompt, measured on the holdout set.

**What happens when the LLM API is down or rate limited?**
The judge falls back from Groq to Gemini. If every model fails, the item is "unsure" and waits for a human, and no answer means deny. I hit this for real during testing, which is why the fallback exists.

**What would you do with more time?**
- An independent attack set written by someone else.
- An embeddings retriever instead of word overlap.
- Cached or parallel judge calls to cut latency.
- Proxying MCP resources and prompts, not just tools.
- Encrypting the audit log.
