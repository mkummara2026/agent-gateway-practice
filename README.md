# Multi-Agent Department Assistant — agentgateway Demo

Three departments (HR, Payroll, IT Support), each split into a FastAPI chat
agent and a FastMCP tool server, built to actually exercise
[agentgateway](https://agentgateway.dev)'s capabilities rather than just
generic HTTP routing — MCP-aware backend proxying, LLM-call proxying, rate
limiting, prompt guardrails, and Prometheus observability, all enforced at
the gateway instead of in application code.

## Architecture

Each department is **two services**:

- **`<dept>-agent`** — FastAPI, holds no LLM client config and no hardcoded
  tool schemas. On each request it discovers its available tools live from
  its MCP server (`tools/list`) and translates them into OpenAI's tool-calling
  shape, then calls the LLM via the OpenAI SDK pointed at the gateway.
- **`<dept>-mcp`** — a real MCP server (FastMCP, Streamable HTTP transport)
  that owns the department's data file and exposes it as callable tools.

**Every outbound call an agent makes goes back through the gateway** — not
just the inbound chat request from the browser:

```
you → gateway → /hr/chat, /payroll/chat, /it-support/chat   (plain Service backend)
                        │
                        │  each agent pod makes TWO kinds of outbound calls,
                        │  both routed back through the SAME gateway:
                        │
         ┌──────────────┴───────────────┐
         │ (1) LLM call                 │ (2) MCP tool call
         ▼                               ▼
gateway → /llm/gemini            gateway → /mcp/hr, /mcp/payroll, /mcp/it-support
  AgentgatewayBackend               AgentgatewayBackend (kind: mcp)
  (kind: ai, provider: gemini)      protocol-aware MCP proxying
         │                               │
         ▼                               ▼
   Gemini API                    <dept>-mcp pod (owns the real data)
```

The real Gemini API key lives in **exactly one place** —
`gemini-llm-secret` — referenced only by the `ai`-type backend's auth policy.
No agent holds a key anymore.

```
agents/
  hr-agent/          Chat agent (FastAPI + OpenAI SDK) → gateway → hr-mcp
  hr-mcp/            MCP server: get_employee, get_holiday_calendar, get_hr_policies
                      owns data/hr.json

  payroll-agent/     Chat agent → gateway → payroll-mcp
  payroll-mcp/       MCP server: get_pay_stub, get_next_pay_date, get_tax_withholding
                      owns data/payroll.json

  it-support-agent/  Chat agent → gateway → it-support-mcp
  it-support-mcp/    MCP server: create_ticket, list_tickets
                      owns data/tickets.json

client/              Vite + TypeScript chat UI — manual department picker
                      (no classifier in front of the gateway), talks to
                      /{department}/chat through the gateway.

k8s/                 Gateway, routes, one Deployment+Service per service
                      above, AgentgatewayBackends (mcp + ai), policies
                      (rate limit, prompt guard), and the Prometheus setup.
```

## `k8s/` reference

| File | What it is |
|---|---|
| `namespace.yaml` | `department-assistant` namespace |
| `gateway.yaml` | The `Gateway` resource (`agentgateway-proxy`) |
| `hr-agent.yaml` / `payroll-agent.yaml` / `it-support-agent.yaml` | Deployment + Service per chat agent |
| `hr-mcp.yaml` / `payroll-mcp.yaml` / `it-support-mcp.yaml` | Deployment + Service per MCP tool server |
| `hr-mcp-backend.yaml` / `payroll-mcp-backend.yaml` / `it-support-mcp-backend.yaml` | `AgentgatewayBackend` (kind: mcp) per tool server |
| `catalog-mcp-backend.yaml` | `AgentgatewayBackend` aggregating **all 3** tool servers into one endpoint (`/mcp/catalog`) — for external MCP clients only, nothing in the app calls it |
| `gemini-llm-backend.yaml` | `AgentgatewayBackend` (kind: ai) — the single Gemini backend every agent's LLM call routes through |
| `routes.yaml` | One `HTTPRoute` with all rules: 3 chat routes, 3 department MCP routes, 1 catalog route, 1 LLM route |
| `rate-limit-policy.yaml` | `AgentgatewayPolicy` — 5 req/min + burst 2 on the 3 chat routes only |
| `gemini-prompt-guard.yaml` | `AgentgatewayPolicy` — regex-based guardrail (rejects SSN/credit-card patterns) on the `ai` backend, protecting all 3 departments at once |
| `agentgateway-proxy-metrics.yaml` | `Service` exposing the proxy's metrics port (`15020`) — not exposed by default |
| `prometheus-values.yaml` | Helm values for a minimal Prometheus install scraping that metrics port |

## Running in Kubernetes (kind + agentgateway)

Assumes: a kind cluster, Gateway API CRDs installed, and the
`agentgateway-crds` + `agentgateway` Helm charts installed into
`agentgateway-system` (controller + `agentgateway-proxy` Gateway).

1. **Namespace + secret** — the real Gemini key lives in `gemini-llm-secret`:
   ```bash
   kubectl apply -f k8s/namespace.yaml
   kubectl create secret generic gemini-llm-secret \
     --from-literal=Authorization="<your-real-Gemini-API-key>" \
     --namespace department-assistant
   ```

2. **Build + load every image into kind** (kind can't pull these from
   anywhere — they're local-only):
   ```bash
   for svc in hr-agent hr-mcp payroll-agent payroll-mcp it-support-agent it-support-mcp; do
     docker build -t "${svc}:latest" "agents/${svc}"
   done
   kind load docker-image hr-agent:latest hr-mcp:latest payroll-agent:latest \
     payroll-mcp:latest it-support-agent:latest it-support-mcp:latest --name <your-cluster-name>
   ```

3. **Deploy the gateway plumbing, then backends, then routes/policies, then agents**
   (agents' env vars point at the gateway, so the backends need to exist first):
   ```bash
   kubectl apply -f k8s/gateway.yaml
   kubectl apply -f k8s/hr-mcp.yaml -f k8s/payroll-mcp.yaml -f k8s/it-support-mcp.yaml
   kubectl apply -f k8s/hr-mcp-backend.yaml -f k8s/payroll-mcp-backend.yaml -f k8s/it-support-mcp-backend.yaml
   kubectl apply -f k8s/catalog-mcp-backend.yaml
   kubectl apply -f k8s/gemini-llm-backend.yaml
   kubectl apply -f k8s/routes.yaml
   kubectl apply -f k8s/rate-limit-policy.yaml
   kubectl apply -f k8s/gemini-prompt-guard.yaml
   kubectl apply -f k8s/hr-agent.yaml -f k8s/payroll-agent.yaml -f k8s/it-support-agent.yaml
   ```

4. **(Optional) Observability** — expose the proxy's metrics and scrape them:
   ```bash
   kubectl apply -f k8s/agentgateway-proxy-metrics.yaml
   helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
   helm install prometheus prometheus-community/prometheus \
     --namespace monitoring --create-namespace \
     -f k8s/prometheus-values.yaml
   ```
   Then `kubectl port-forward -n monitoring svc/prometheus-server 9090:80` and
   query e.g. `sum by (gen_ai_token_type) (agentgateway_gen_ai_client_token_usage_sum)`
   at `localhost:9090`.

5. **Reach the app**:
   ```bash
   kubectl port-forward -n agentgateway-system svc/agentgateway-proxy 8080:80
   ```
   Then `POST http://localhost:8080/hr/chat` (or `/payroll/chat`,
   `/it-support/chat`) with `{"message": "...", "history": []}`.

## Running the client UI

```bash
cd client
npm install
npm run dev
```

Requires the port-forward above running on `:8080` (see `client/vite.config.ts`
for the proxy config). Pick a department from the dropdown — there's no
classifier in front of the gateway, so routing is manual by design; this repo
is about gateway/MCP/LLM-proxy mechanics, not intent classification.

## HTTP contract

**Chat** (`<dept>-agent`, via the gateway at `/{department}/chat`):
```json
// request
{"message": "...", "history": [{"role": "user"|"assistant", "content": "..."}]}
// response
{"reply": "...", "ticket": {...}}   // ticket only ever present on it-support-agent
```
If a prompt guard rejects the underlying LLM call, `reply` contains the
guard's message instead of an error — the agent catches `openai.BadRequestError`
and returns it as a normal chat response.

**MCP** (`<dept>-mcp`, via the gateway at `/mcp/{department}`, or all three
merged at `/mcp/catalog`): standard MCP Streamable HTTP — `initialize`,
`tools/list`, `tools/call`. Connect with any MCP client, e.g.:
```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async with streamablehttp_client("http://localhost:8080/mcp/hr") as (r, w, _):
    async with ClientSession(r, w) as session:
        await session.initialize()
        print(await session.list_tools())
```

**LLM** (`gemini-llm-backend`, via the gateway at `/llm/gemini`): OpenAI Chat
Completions shape, even though it's actually calling Gemini underneath —
agentgateway translates:
```bash
curl localhost:8080/llm/gemini/v1/chat/completions \
  -H content-type:application/json \
  -d '{"model": "", "messages": [{"role":"user","content":"hi"}]}'
```

## Why `AgentgatewayBackend` instead of a plain `Service` backend

- **`hr-agent`/`payroll-agent`/`it-support-agent`** are plain HTTP — the
  gateway just forwards bytes, no protocol awareness needed.
- **The `*-mcp` services** are `AgentgatewayBackend` (kind: `mcp`) so the
  gateway parses actual MCP semantics (`initialize`, session IDs,
  `tools/call` framing) instead of opaque bytes. That's what makes
  `catalog-mcp-backend.yaml` possible at all — merging 3 independent
  services into one logical MCP endpoint is structurally impossible with a
  plain `Service` backendRef, which can only ever point at one Service.
- **`gemini-llm-backend`** is `AgentgatewayBackend` (kind: `ai`) so the
  gateway understands the LLM request/response well enough to translate
  formats, inject the real API key server-side, enforce the prompt guard,
  and report real token-usage metrics — none of which is possible if agents
  call Gemini directly (which is what this repo did before this backend was
  added; nothing was measurable at the gateway level until the LLM call
  itself was routed through it).

## Observability

Once `agentgateway-proxy-metrics.yaml` + Prometheus are deployed, real,
per-request metrics are available with zero code in any agent:
- `agentgateway_gen_ai_client_token_usage_{count,sum}` — input/output token
  counts, by model and route
- `agentgateway_gen_ai_server_request_duration_seconds_*` — LLM call latency
- `agentgateway_requests_total` — request counts by route and status code
  (useful for watching the rate limiter or prompt guard actually fire —
  filter on `status="429"` or `status="400"`)
- `agentgateway_mcp_requests_total` — MCP tool calls by department and tool
  name (`server`/`resource` labels)

## Notes / things intentionally left simple

- No auth on any endpoint.
- Each service is stateless per request; the caller (agent or client UI)
  owns conversation history and resends it every turn.
- No intent classifier — routing is either manual (client UI dropdown) or
  by whichever path you hit directly. Building that classifier was
  explicitly left out of this repo on purpose.
- Token usage isn't broken down per-department in Prometheus — all 3 chat
  routes live in one `HTTPRoute` object, so the `route` label covers all of
  them together; `route_rule` (which would give per-rule granularity) isn't
  currently populated by agentgateway for this metric.
- All three agents depend on the gateway being up to do their job at all —
  their own LLM calls and tool calls both route through it. That's a
  deliberate tradeoff to make agentgateway's backends load-bearing rather
  than a disconnected demo.
- Prometheus here has no persistence and no Grafana — it's enough to query
  and graph directly, not a production observability stack.
