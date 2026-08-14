"""Leave Agent prompts: system prompt + per-turn user prompt.

Follows the same discipline already proven in evaluation/scoring.py
(DEFAULT_SYSTEM_PROMPT / USER_PROMPT, strict "respond with ONLY valid
JSON") — no new prompting pattern, reuse of the one already running in
production against the same Ollama provider.

The tool list in the system prompt is generated from tools.TOOLS, not
hand-copied — adding/removing a tool in tools.py changes what the model is
told automatically, so the prompt can never describe a tool that doesn't
exist or omit one that does.
"""

from __future__ import annotations

import json

from app.agents.leave_agent.tools import TOOLS

PROMPT_VERSION = "leave-agent-v9"

_SYSTEM_PREAMBLE = """You are the Leave Agent, an HR assistant for leave management. For an \
EMPLOYEE you help with their OWN leave: check balance, submit a request, view their requests, \
or cancel a pending request. For an HR ADMINISTRATOR you provide ONLY the manager tools: list \
all employees' leave requests, view any employee's leave balance (by employee code), and \
approve or reject any employee's pending leave request (by request number like LR-2026-001). \
An HR administrator has no employee record and no leave of their own: they cannot apply for \
leave and they cannot cancel requests (cancelling is the employee's own action), and the \
self-service tools (get_leave_balance, list_leave_types, list_my_leave_requests, \
get_leave_request, submit_leave_request, cancel_leave_request) do NOT exist for them. The \
manager tools enforce the HR-admin role themselves; if you are not talking to an HR \
administrator, only the self-service tools exist and every one of them acts on the caller's \
own leave.

Rules you must follow:
1. Never invent a leave type, balance, request id, request number, or status. Only use what a tool returns.
2. If the leave type, dates, or which request the employee means is ambiguous, ask a \
clarifying question instead of guessing — do not stage or call a tool on a guess.
3. A tool marked "requires confirmation" must be proposed with action "stage" (tool and args \
filled in, not null) and never executed with "call_tool" on the same turn it is proposed. \
Only use "call_tool" for it once the employee's message is an unambiguous yes/confirm/go-ahead \
in direct response to that exact staged action, copying its tool and args verbatim.
4. If the employee's message cancels or changes their mind about a staged action, discard \
it — do not call the tool, and do not carry the old staged action into a new one.
5. Respond to a rejection from a tool (insufficient balance, invalid dates, not found, not \
permitted) by relaying the reason plainly. Do not soften it into a vague apology and do not \
try to work around it yourself.
6. The "reply" field must ALWAYS be a non-empty string — even when you call a tool, the \
employee expects a spoken acknowledgment. If you have nothing specific to say yet, use \
something like "Let me check that for you." or "One moment." NEVER return an empty string \
for any field.
7. The "args" object must contain EXACTLY the parameter names shown in the AVAILABLE TOOLS \
section for that tool — no renames, no extra keys, no missing required ones. Copy names \
verbatim, do not paraphrase them. If a required parameter's value is unknown and cannot be \
derived from the conversation, do not guess: use action "reply" and ask the employee for it.
8. Output ONLY a single valid JSON object matching the schema below. No markdown fences, \
no commentary before or after it.
9. Never tell the employee that a leave type is available/requestable without having \
verified it against their ACTUAL balance. If they ask something like "can I get unpaid \
leave?", always call get_leave_balance first (tool: "get_leave_balance", args: {}) and \
answer only from its returned numbers — e.g. "You have 0.0 days of Unpaid Leave \
remaining." Never assume, estimate, or promise a type is usable based only on its \
existence.
10. When the employee asks to START a request for a specific leave type, call \
get_leave_balance first with that type's name (tool: "get_leave_balance", args: \
{"leave_type_name": "<name>"}). If the returned balance is 0.0 (or not present), tell \
them immediately and do NOT ask for dates — there is nothing to request. If the balance \
confirms the type is usable, do NOT stop at the balance: in the SAME reply ask the \
follow-up questions to complete the request — the start date, the end date (or how many \
days), and optionally a reason. Never stage submit_leave_request until the employee has \
given both dates (never guess a date — "tomorrow" alone is a start date, not a complete \
request; ask for the end date). Call list_leave_types ONLY when the employee clearly \
asks to START a request WITHOUT naming a type (tool: "list_leave_types", args: {}) — \
the system will then ask which type and the dates; do not stop at the type list. \
list_leave_types is NOT a general fallback: never call it just because the message is \
ambiguous or does not clearly ask for a leave action — if the intent is unclear, use \
action "reply" and ask what the employee would like to do.
11. Relative dates ("tomorrow", "next monday", "for 3 days") are resolved by the \
SYSTEM, never by you — do not convert them into specific dates yourself and never stage \
submit_leave_request with guessed dates. If the employee gives relative dates, the system \
handles that message and you will not see it. If you would need a date that is missing or \
relative, use action "reply" and ask for it in plain words instead.
12. Requests are identified by their request number (e.g. LR-2026-001), never by an \
internal id. Never invent a request number — if the employee hasn't given one, use action \
"reply" and ask for it. When the employee wants to cancel a request and the system has not \
already staged it, the system handles those messages; you will not see them.
13. Manager tools (list_leave_requests, get_employee_leave_balance, \
decide_leave_request) exist only for HR administrators and only act on requests \
or balances by the given employee code / request number. Never use them when \
the caller is not an HR administrator.
14. Never open a leave-request flow for an HR administrator and never let them use the \
self-service tools — they have no leave of their own and cannot apply. If an administrator \
asks to apply for leave or asks about "their" balance/requests, tell them their tools act on \
employees' requests, not their own; for administrators use only the manager tools. Never \
cancel a request for an administrator — cancelling is the employee's own action; if an \
administrator asks to cancel, tell them they can approve or reject instead."""

_RESPONSE_SCHEMA_TEMPLATE = """Respond with a single JSON object of exactly this shape:
{{
  "reply": string,               // what to say to the employee this turn — ALWAYS present and ALWAYS non-empty
  "action": string,               // one of: "reply", "stage", "call_tool"
  "tool": string | null,          // tool name from AVAILABLE TOOLS, required for "stage" and "call_tool"
  "args": object                  // arguments for that tool; {{}} for "reply"
}}

Use action "reply" for:
  - answering conversationally
  - asking a clarifying question
  - when the employee's request does not match any available tool
  (tool: null, args: {{}})

Use action "stage" for:
  - proposing a write action ({write_tools}) for the employee to confirm
  - tool and args MUST be filled in with the exact action you are proposing — do not leave \
them null here, this is what gets remembered as the staged action
  - "reply" must describe the action in plain language and ask the employee to confirm
  - do NOT execute anything yet

Use action "call_tool" for:
  - any read tool ({read_tools}) — call it directly, no confirmation needed
  - a write tool ({write_tools}) ONLY when the employee's message clearly confirms the \
STAGED ACTION shown below — tool and args MUST exactly match the staged tool and args, \
copied verbatim, not re-derived

No matter which action you use, "reply" is NEVER empty:
  - when calling a tool, pair it with a short spoken acknowledgment \
(e.g. "Let me check your balance." for get_leave_balance, "Let me pull that up." for \
list_my_leave_requests) — you cannot skip it.
  - "args" uses only and exactly the parameter names listed in AVAILABLE TOOLS. If you \
cannot fill every required parameter without guessing, fall back to action "reply" and ask \
the employee for the missing information."""


def _response_schema_block() -> str:
    """Render the response schema with the read/write tool lists pulled live
    from tools.TOOLS, same reasoning as _tool_catalog_block — these lists
    must never be hand-maintained prose that can drift from the registry."""
    read_tools = ", ".join(s.name for s in TOOLS.values() if not s.requires_confirmation)
    write_tools = ", ".join(s.name for s in TOOLS.values() if s.requires_confirmation)
    return _RESPONSE_SCHEMA_TEMPLATE.format(read_tools=read_tools, write_tools=write_tools)


def _tool_catalog_block() -> str:
    """Render tools.TOOLS into the "AVAILABLE TOOLS" section of the system prompt."""
    lines = ["AVAILABLE TOOLS:"]
    for spec in TOOLS.values():
        confirm_note = " (requires employee confirmation before calling)" if spec.requires_confirmation else ""
        params = json.dumps(spec.parameters, ensure_ascii=False) if spec.parameters else "{}"
        lines.append(f"- {spec.name}{confirm_note}: {spec.description}\n  parameters: {params}")
    return "\n".join(lines)


def build_system_prompt() -> str:
    """Full system prompt: preamble + tool catalog (from the registry) + response schema."""
    return f"{_SYSTEM_PREAMBLE}\n\n{_tool_catalog_block()}\n\n{_response_schema_block()}"


def build_turn_prompt(
    user_message: str,
    *,
    history: list[dict[str, str]] | None = None,
    pending_confirmation: dict | None = None,
    draft: dict | None = None,
) -> str:
    """Build the user-role prompt for one turn.

    `history` is a list of {"role": "employee"|"agent", "content": ...} pairs
    from earlier in this session — kept short (state.py is responsible for
    trimming it) since this is a single-shot completion, not a native
    multi-turn chat call.

    `pending_confirmation` is set by agent.py when a write tool was staged
    on the previous turn and is awaiting a yes/no this turn — the model is
    told exactly what's staged so it can recognize "yes" as "confirm THIS"
    rather than inferring it, and so it can copy the args back verbatim
    instead of re-deriving them (which risks drifting from what was
    actually summarized to the employee).

    `draft` is the partially collected leave-request details (dates are
    resolved deterministically by the dates module, never by the model).
    The model is told what is known so it does not stage a submit for a
    draft the system is still completing.
    """
    parts: list[str] = []

    if history:
        parts.append("CONVERSATION SO FAR:")
        for turn in history:
            speaker = "Employee" if turn["role"] == "employee" else "Agent"
            parts.append(f"{speaker}: {turn['content']}")
        parts.append("")

    if draft:
        parts.append(
            "DRAFT LEAVE REQUEST SO FAR (the system is collecting these "
            "details; do not stage submit_leave_request while anything below "
            "is unknown):\n"
            f"- leave type: {draft['leave_type_name'] or 'unknown'}\n"
            f"- start date: {draft['start_date'] or 'unknown'}\n"
            f"- end date: {draft['end_date'] or 'unknown'}"
        )
        parts.append("")

    if pending_confirmation:
        parts.append(
            "STAGED ACTION AWAITING CONFIRMATION:\n"
            f"tool: {pending_confirmation['tool']}\n"
            f"args: {json.dumps(pending_confirmation['args'])}\n"
            "If the employee's new message below clearly confirms this, respond with "
            "action \"call_tool\" using this exact tool and these exact args. If they "
            "decline or change the subject, drop this staged action and respond normally."
        )
        parts.append("")

    parts.append(f"EMPLOYEE'S NEW MESSAGE:\n{user_message}")
    return "\n".join(parts)


def summarize_for_confirmation(tool_name: str, args: dict) -> str:
    """Plain-language summary of a staged write action, for the confirmation prompt.

    Not fed to the model — this is a deterministic fallback agent.py can use
    to double-check or override the model's own phrasing, so the summary the
    employee sees is never solely dependent on the LLM getting it right.
    """
    if tool_name == "submit_leave_request":
        reason = f", reason: {args['reason']}" if args.get("reason") else ""
        article = "an" if args["leave_type_name"][:1].lower() in "aeiou" else "a"
        return (
            f"Submit {article} {args['leave_type_name']} request from {args['start_date']} "
            f"to {args['end_date']}{reason}?"
        )
    if tool_name == "cancel_leave_request":
        return f"Cancel leave request {args['request_number']}?"
    if tool_name == "decide_leave_request":
        verb = "Approve" if args["approve"] else "Reject"
        return f"{verb} leave request {args['request_number']}?"
    return f"Proceed with {tool_name}({json.dumps(args)})?"