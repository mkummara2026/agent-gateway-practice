type Department = "hr" | "payroll" | "it-support";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface ChatResponse {
  reply: string;
  ticket?: {
    id: string;
    summary: string;
    priority: string;
    category: string;
    status: string;
  };
  detail?: string; // FastAPI's HTTPException error shape
}

const messagesEl = document.getElementById("messages") as HTMLDivElement;
const formEl = document.getElementById("form") as HTMLFormElement;
const inputEl = document.getElementById("input") as HTMLInputElement;
const badgeEl = document.getElementById("badge") as HTMLSpanElement;
const departmentEl = document.getElementById("department") as HTMLSelectElement;

// Each agent service is stateless per request, so the client owns conversation
// history and resends it every turn. There's no classifier in front of the
// gateway, so the department has to be picked manually.
let department: Department | "" = "";
let conversationHistory: ChatMessage[] = [];

const DEPARTMENT_LABELS: Record<Department, string> = {
  hr: "HR",
  payroll: "Payroll",
  "it-support": "IT Support",
};

function appendMessage(role: "user" | "assistant" | "ticket", text: string) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = text;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function setBadge() {
  badgeEl.textContent = department ? DEPARTMENT_LABELS[department] : "select a department";
}

departmentEl.addEventListener("change", () => {
  department = departmentEl.value as Department | "";
  conversationHistory = [];
  messagesEl.innerHTML = "";
  setBadge();
  inputEl.disabled = !department;
  inputEl.placeholder = department
    ? `Ask ${DEPARTMENT_LABELS[department]} something...`
    : "Choose a department first";
});

inputEl.disabled = true;

formEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = inputEl.value.trim();
  if (!message || !department) return;

  appendMessage("user", message);
  inputEl.value = "";
  inputEl.disabled = true;

  try {
    const res = await fetch(`/${department}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history: conversationHistory }),
    });
    const rawBody = await res.text();
    let data: ChatResponse;
    try {
      data = JSON.parse(rawBody) as ChatResponse;
    } catch {
      // Not every error path returns JSON (e.g. an unhandled 500 from FastAPI
      // is plain text "Internal Server Error").
      data = { reply: "", detail: rawBody || `HTTP ${res.status}` };
    }

    if (!res.ok) {
      appendMessage("assistant", `Error: ${data.detail ?? "something went wrong"}`);
      return;
    }

    conversationHistory.push({ role: "user", content: message });
    conversationHistory.push({ role: "assistant", content: data.reply });

    appendMessage("assistant", data.reply);
    if (data.ticket) {
      appendMessage(
        "ticket",
        `Ticket ${data.ticket.id} created (priority: ${data.ticket.priority}, category: ${data.ticket.category})`
      );
    }
  } catch (err) {
    appendMessage("assistant", `Error: ${err instanceof Error ? err.message : "network error"}`);
  } finally {
    inputEl.disabled = false;
    inputEl.focus();
  }
});
