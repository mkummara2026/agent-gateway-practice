# Multi-Agent Department Assistant — agentgateway Demo

Implementation of [DEPARTMENT_ASSISTANT_PROMPT.md](./DEPARTMENT_ASSISTANT_PROMPT.md),
rebuilt to exercise [agentgateway](https://agentgateway.dev)'s MCP-aware
backend proxying rather than just generic HTTP routing.

## Architecture

Each department is **two services**, not one:

- **`<dept>-agent`** — FastAPI + Gemini chat loop. Holds no tools locally; on
  each request it discovers its available tools live from its MCP server
  (`tools/list`) and translates those schemas directly into Gemini
  `FunctionDeclaration`s — no hand-duplicated tool schemas in the agent.
- **`<dept>-mcp`** — a real MCP server (FastMCP, Streamable HTTP transport)
  that owns the department's data file and exposes it as callable tools.

```
you → gateway → /hr/chat, /payroll/chat, /it-support/chat  (plain Service backend)
                        │  each agent pod calls out to...
                        ▼
                gateway → /mcp/hr, /mcp/payroll, /mcp/it-support
                          (AgentgatewayBackend, kind: mcp — NOT a plain Service)
                        │
                        ▼
                <dept>-mcp pod (owns the data, exposes tools via MCP)
```

Both hops go through agentgateway — the chat request from you, *and* each
agent's own outbound tool calls. That second hop is the actual agentgateway
feature being demonstrated: MCP protocol-aware proxying (session handling,
tool-call semantics), not just byte-forwarding.

```
agents/
  hr-agent/         Gemini chat loop, MCP client → gateway → hr-mcp
  hr-mcp/           MCP server: get_employee, get_holiday_calendar, get_hr_policies
                     owns data/hr.json

  payroll-agent/    Gemini chat loop, MCP client → gateway → payroll-mcp
  payroll-mcp/      MCP server: get_pay_stub, get_next_pay_date, get_tax_withholding
                     owns data/payroll.json

  it-support-agent/ Gemini chat loop, MCP client → gateway → it-support-mcp
  it-support-mcp/   MCP server: create_ticket, list_tickets
                     owns data/tickets.json

client/             Vite + TypeScript chat UI — manual department picker
                     (no classifier in front of the gateway), talks to
                     /{department}/chat through the gateway.

k8s/                Gateway, GatewayClass route, one Deployment+Service per
                     service above, one AgentgatewayBackend (kind: mcp) per
                     *-mcp service, and the HTTPRoute wiring it all together.
```

## Running in Kubernetes (kind + agentgateway)

Assumes: a kind cluster, Gateway API CRDs installed, and the
`agentgateway-crds` + `agentgateway` Helm charts installed into
`agentgateway-system` (controller + `agentgateway-proxy` Gateway).

1. **Secret** — copy `k8s/secret.yaml.example` to `k8s/secret.yaml`, fill in
   a real `GEMINI_API_KEY`, then:
   ```bash
   kubectl apply -f k8s/namespace.yaml
   kubectl apply -f k8s/secret.yaml
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

3. **Deploy the gateway plumbing, then the MCP servers, then the agents**
   (agents' MCP_SERVER_URL points at the gateway, so the MCP backends need
   to exist first):
   ```bash
   kubectl apply -f k8s/gateway.yaml
   kubectl apply -f k8s/hr-mcp.yaml -f k8s/payroll-mcp.yaml -f k8s/it-support-mcp.yaml
   kubectl apply -f k8s/hr-mcp-backend.yaml -f k8s/payroll-mcp-backend.yaml -f k8s/it-support-mcp-backend.yaml
   kubectl apply -f k8s/routes.yaml
   kubectl apply -f k8s/hr-agent.yaml -f k8s/payroll-agent.yaml -f k8s/it-support-agent.yaml
   ```

4. **Reach it**:
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
is about the gateway/MCP mechanics, not intent classification.

## HTTP contract

**Chat** (`<dept>-agent`, via the gateway at `/{department}/chat`):
```json
// request
{"message": "...", "history": [{"role": "user"|"assistant", "content": "..."}]}
// response
{"reply": "...", "ticket": {...}}   // ticket only ever present on it-support-agent
```

**MCP** (`<dept>-mcp`, via the gateway at `/mcp/{department}`): standard MCP
Streamable HTTP — `initialize`, `tools/list`, `tools/call`. Connect with any
MCP client, e.g.:
```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async with streamablehttp_client("http://localhost:8080/mcp/hr") as (r, w, _):
    async with ClientSession(r, w) as session:
        await session.initialize()
        print(await session.list_tools())
```

## Why an `AgentgatewayBackend` instead of a plain `Service` backend

`hr-agent`/`payroll-agent`/`it-support-agent` are plain HTTP — the gateway
just forwards bytes, no protocol awareness needed. The `*-mcp` services are
registered as `AgentgatewayBackend` (`spec.mcp.targets`) instead, because
that's what makes the gateway actually parse MCP semantics — the
`initialize` handshake, session IDs, `tools/call` framing — rather than
treating the traffic as opaque bytes. That protocol awareness is also what
would let you add a second MCP server as another target on the same backend
(aggregating multiple tool servers behind one MCP endpoint) or apply MCP/tool
specific policies — neither is possible with a plain `Service` backend.

## Notes / things intentionally left simple

- No auth on any endpoint.
- Each service is stateless per request; the caller (agent or client UI)
  owns conversation history and resends it every turn.
- No intent classifier — routing is either manual (client UI dropdown) or
  by whichever path you hit directly. Building that classifier was
  explicitly left out of this repo on purpose.
- `hr-agent`/`payroll-agent`/`it-support-agent` depend on the gateway being
  up to do their job at all now (their own tool calls route through it) —
  that's a deliberate tradeoff to make agentgateway's MCP backend
  load-bearing rather than a disconnected demo.
