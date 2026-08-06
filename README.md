# Data_agent_
# AI Data Analytics Agent — Payments Ops Investigation

## Motive
A support or ops person shouldn't need to know SQL or the schema to
answer "why did this transaction fail" or "which merchants have
unsettled payouts." This agent investigates that on its own.

## What it actually does
Point it at a database it has never seen — in this repo, an 11-table
payments schema (merchants, customers, transactions, refunds,
disputes, settlements, subscriptions, invoices, webhook events,
support tickets) — and ask it a real ops question in plain language:

- *"Which customers have open support tickets tied to failed transactions?"*
- *"Which merchants have pending settlements?"*
- *"Show me disputes that are still open, with the original transaction amount."*

It has no schema given upfront. It discovers the tables, inspects
foreign keys, resolves multi-hop joins, writes the SQL itself, and
answers — with the full trace (tables explored, SQL generated, raw
rows returned) visible for verification, not hidden behind a black box.

## Why this matters for a payments company specifically
The example schema is deliberately not generic e-commerce — it mirrors
the actual entities a payments support/ops team lives in: failed vs.
successful transactions, refund status, open disputes, merchant
settlement status, subscription/invoice state, webhook delivery
failures. The same architecture generalizes to any of Razorpay's own
domains named in the AI Builders posting — support, ops, revenue —
without changing a line of the agent logic, only the schema underneath.

## What makes it more than a wrapper around an LLM
Three concrete safeguards, implemented as real logic (not prompting):
- **Repeat-call detection** — the agent can't loop on an identical query; it's told to reuse the earlier result.
- **Malformed-response filtering** — every tool call is validated (real table? real column? read-only SQL?) before it touches the database; bad calls get a structured error back so the agent self-corrects instead of crashing.
- **Grounded-answer verification** — a dedicated graph node checks that the final answer's cited numbers actually appeared in the tool output before letting the agent stop, with one bounded retry if not.

## Also: works on your own data, live
The same agent runs against any uploaded Excel file — upload a
workbook, each sheet becomes a table, ask questions immediately. Good
for a live demo: hand it a real (anonymized) spreadsheet on the spot.

## Architecture
`Python, LangGraph (StateGraph), Groq (Llama 3.3 / GPT-OSS), SQLAlchemy, Streamlit`

```
user question
     |
   [agent] --tool call--> [tools] --result--> back to [agent]   (loop until no more tool calls)
     |
  [verify]  -- grounded? --> END
     |
  not grounded (max 1 retry) --> back to [agent]
```



