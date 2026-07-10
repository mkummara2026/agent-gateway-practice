import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

DATA_PATH = Path(__file__).parent / "data" / "hr.json"

mcp = FastMCP(
    "hr-data",
    host="0.0.0.0",
    port=int(os.environ.get("PORT", 8000)),
    stateless_http=True,
)


def load_hr_data() -> dict:
    return json.loads(DATA_PATH.read_text())


@mcp.tool()
def get_employee(employee_id: str) -> dict:
    """Look up an employee's PTO balance and benefits enrollment by employee ID."""
    for employee in load_hr_data()["employees"]:
        if employee["employeeId"] == employee_id:
            return employee
    return {"error": f"No employee found with ID {employee_id}"}


@mcp.tool()
def get_holiday_calendar() -> list:
    """List upcoming company holidays."""
    return load_hr_data()["holidayCalendar"]


@mcp.tool()
def get_hr_policies() -> dict:
    """Get HR policies: PTO accrual rate, parental leave weeks, remote work policy."""
    return load_hr_data()["policies"]


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
