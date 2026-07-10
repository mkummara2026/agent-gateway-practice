import json
import os
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

DATA_PATH = Path(__file__).parent / "data" / "tickets.json"

mcp = FastMCP(
    "it-support-tickets",
    host="0.0.0.0",
    port=int(os.environ.get("PORT", 8000)),
    stateless_http=True,
)


def load_tickets() -> list:
    return json.loads(DATA_PATH.read_text())


def save_tickets(tickets: list) -> None:
    DATA_PATH.write_text(json.dumps(tickets, indent=2))


@mcp.tool()
def create_ticket(summary: str, description: str, priority: str, category: str) -> dict:
    """Create a new IT support ticket and return the created record.

    priority must be one of: low, medium, high, urgent.
    """
    tickets = load_tickets()
    ticket = {
        "id": f"TCK-{len(tickets) + 1001}",
        "summary": summary,
        "description": description,
        "priority": priority,
        "category": category,
        "status": "open",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    tickets.append(ticket)
    save_tickets(tickets)
    return ticket


@mcp.tool()
def list_tickets() -> list:
    """List all IT support tickets."""
    return load_tickets()


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
