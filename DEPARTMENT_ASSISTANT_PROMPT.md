# Multi-Agent Department Assistant — Build Spec

## Goal

Build a chatbot application where employees ask questions about **HR**,
**Payroll**, and **IT Support** in a single chat interface. IT Support
conversations can result in the assistant **creating a support ticket** on
the user's behalf.

## User-facing experience

- A single TypeScript web chat UI, one conversation thread.
- Users type free-form questions — **no department picker**. The system
  determines intent and routes to the right agent automatically. (Optional:
  allow a manual department override in the UI as a fallback/debug
  affordance.)
- In IT Support conversations, the assistant can collect the fields needed to
  open a ticket (summary, description, priority, category) and confirms
  creation back to the user with a ticket ID.

## Architecture

- **Frontend**: TypeScript chat UI (your framework choice). Talks to a single
  backend endpoint — it has no knowledge of HR/Payroll/IT as separate
  services.
- **Three specialized agents**:
  - **HR Agent** — answers HR policy/benefits questions.
  - **Payroll Agent** — answers payroll/pay-cycle/tax-withholding questions.
  - **IT Support Agent** — answers IT questions *and* can create support
    tickets via a tool call.
- Each agent has its own LLM backend (same provider for all three, or
  different — your call) and, where relevant, its own tools. At minimum, the
  IT Support Agent needs a `create_ticket` tool. HR/Payroll can start as
  pure LLM-only agents and grow tools (policy lookup, pay stub lookup) later.
- Something needs to decide which of the three agents handles each incoming
  message, since the user never explicitly picks a department — a simple
  intent classifier (even a cheap/fast LLM call that returns one of
  `{hr, payroll, it_support}`) in front of the three agents is enough for a
  first version.

## Mock database

Create a single JSON file (e.g. `db.json`) that acts as the shared "database"
for all three agents, seeded with dummy starter data:

- **IT tickets**: an initially-empty or small-seeded array of ticket records
  (`id`, `summary`, `description`, `priority`, `category`, `status`,
  `createdAt`). The `create_ticket` tool reads this file, appends a new
  record, and writes it back.
- **HR data**: a few dummy records the HR agent can look up — e.g. PTO
  balances, benefits enrollment status, holiday calendar.
- **Payroll data**: a few dummy records — e.g. pay stubs (date, gross, net,
  deductions), next pay date, tax withholding info.

Each agent reads/writes only its own section of the file (or its own file,
if you'd rather split it into `tickets.json`, `hr.json`, `payroll.json` —
your call). Keep it simple: a JSON file read into memory and rewritten on
change is enough for this project; don't reach for a real database.

## Deliverables

1. Three agents (HR, Payroll, IT Support), each independently callable.
2. A JSON-file mock database with dummy starter data, backing each agent's
   tools.
3. The IT Support agent's `create_ticket` tool, reading/writing that JSON
   file.
4. An intent classifier/router that directs each incoming message to the
   correct agent.
5. A minimal TypeScript chat UI that talks to the app's single backend
   endpoint (whatever that endpoint's implementation looks like is up to
   you).

## Suggested build order

1. Get **one** agent (start with IT Support — it has the most interesting
   behavior) working end-to-end with its tool and the mock DB.
2. Add the second and third agents.
3. Build the intent classifier/router in front of all three.
4. Build the TypeScript chat UI last, once the backend contract is stable.

## Explicitly your call (not prescribed here)

- Whether all three agents share one LLM backend/provider or use different
  ones.
- Exact classifier implementation (a real ML classifier vs. a cheap LLM call
  with a tight prompt — the latter is simpler to stand up first).
- How conversation continuity works across turns (sticky-route a whole
  session to one agent once classified, vs. reclassifying every message).
- Whether/how to add auth, guardrails, or observability at this layer — not
  needed for a first working version.
