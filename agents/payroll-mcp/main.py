import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

DATA_PATH = Path(__file__).parent / "data" / "payroll.json"

mcp = FastMCP(
    "payroll-data",
    host="0.0.0.0",
    port=int(os.environ.get("PORT", 8000)),
    stateless_http=True,
)


def load_payroll_data() -> dict:
    return json.loads(DATA_PATH.read_text())


@mcp.tool()
def get_pay_stub(employee_id: str) -> dict:
    """Get the most recent pay stub (gross, net, deductions) for an employee by employee ID."""
    stubs = [s for s in load_payroll_data()["payStubs"] if s["employeeId"] == employee_id]
    if not stubs:
        return {"error": f"No pay stubs found for employee {employee_id}"}
    return stubs[-1]


@mcp.tool()
def get_next_pay_date() -> str:
    """Get the next company-wide pay date."""
    return load_payroll_data()["nextPayDate"]


@mcp.tool()
def get_tax_withholding(employee_id: str) -> dict:
    """Get tax withholding filing status and allowances for an employee by employee ID."""
    withholding = load_payroll_data()["taxWithholding"].get(employee_id)
    if not withholding:
        return {"error": f"No tax withholding info for employee {employee_id}"}
    return withholding


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
