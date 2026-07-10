import json
import os
from typing import List, Literal, Optional

from fastapi import FastAPI, HTTPException
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from openai import AsyncOpenAI, BadRequestError
from pydantic import BaseModel

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:8080/llm/gemini")
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8000/mcp")

# Auth for the real LLM provider lives in the gateway's AgentgatewayBackend
# (gemini-llm-secret), not here - "anything" is just a placeholder the OpenAI
# SDK requires a non-empty api_key to be set.
llm_client = AsyncOpenAI(base_url=LLM_BASE_URL, api_key="anything")

app = FastAPI(title="IT Support Agent")

SYSTEM_PROMPT = """You are the IT Support Agent for an internal employee assistant. Help employees
troubleshoot IT issues (network, hardware, software, account access, email). If a question needs
a human to fix (something you can't resolve via chat, or the employee asks for a ticket), collect:
summary, description, priority (low/medium/high/urgent), and category, confirm the details back to
the employee, and once confirmed call the create_ticket tool. After the tool returns, tell the
employee their ticket ID and that the IT team will follow up. If a question is outside IT (HR,
payroll), say so plainly so the caller can re-route it."""


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []


class Ticket(BaseModel):
    id: str
    summary: str
    description: str
    priority: str
    category: str
    status: str
    createdAt: str


class ChatResponse(BaseModel):
    reply: str
    ticket: Optional[Ticket] = None


_cached_tools: list | None = None


async def get_mcp_tools() -> list:
    """Discover this agent's tools from its MCP server, caching for the process lifetime.

    Declarations are derived directly from the MCP server's schemas, so there's
    one source of truth instead of hand-duplicated tool schemas.
    """
    global _cached_tools
    if _cached_tools is not None:
        return _cached_tools

    async with streamablehttp_client(MCP_SERVER_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listing = await session.list_tools()
            _cached_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description or "",
                        "parameters": t.inputSchema,
                    },
                }
                for t in listing.tools
            ]
    return _cached_tools


def _parse_mcp_text(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


async def call_mcp_tool(name: str, arguments: dict) -> dict:
    async with streamablehttp_client(MCP_SERVER_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
            # FastMCP emits one TextContent block per list element (not one block with a
            # JSON array), so a single-item list and a scalar are indistinguishable here.
            # Scalar str returns come back as raw text, not JSON-quoted, so fall back to
            # the raw string when a part isn't valid JSON.
            parsed = [_parse_mcp_text(part.text) for part in result.content if hasattr(part, "text")]
            return parsed[0] if len(parsed) == 1 else parsed


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    try:
        tools = await get_mcp_tools()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach MCP server: {exc}") from exc

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend({"role": m.role, "content": m.content} for m in req.history)
    messages.append({"role": "user", "content": req.message})

    reply = ""
    created_ticket: Optional[dict] = None

    for _ in range(4):
        try:
            completion = await llm_client.chat.completions.create(model="", messages=messages, tools=tools)
        except BadRequestError as exc:
            # A prompt guard (e.g. gemini-prompt-guard) rejected this request
            # at the gateway before it ever reached the LLM.
            return ChatResponse(reply=str(exc), ticket=None)
        msg = completion.choices[0].message

        if not msg.tool_calls:
            reply = msg.content or ""
            break

        messages.append(
            {
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
            }
        )
        for tc in msg.tool_calls:
            try:
                tool_response = await call_mcp_tool(tc.function.name, json.loads(tc.function.arguments))
                tool_result = {"ok": True, "result": tool_response}
                if tc.function.name == "create_ticket":
                    created_ticket = tool_response
            except Exception as exc:
                tool_result = {"ok": False, "error": str(exc)}
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(tool_result)})

    return ChatResponse(reply=reply, ticket=created_ticket)
