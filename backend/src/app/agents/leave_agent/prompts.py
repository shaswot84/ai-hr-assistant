"""Leave Agent prompts: system prompt + per-turn user prompt.

Follows the same discipline already proven in evaluation/scoring.py
(DEFAULT_SYSTEM_PROMPT / USER_PROMPT, strict "respond with ONLY valid
JSON") -- no new prompting pattern, reuse of the one already running in
production against the same Ollama provider.

The tool list in the system prompt is generated from tools.TOOLS, not
hand-copied -- adding/removing a tool in tools.py changes what the model is
told automatically, so the prompt can never describe a tool that doesn't
exist or omit one that does.

AMENDMENT vs. the first draft of this file: the response schema originally
had two actions, "reply" and "call_tool", with staging done via action
"reply" and tool/args forced to null/{}. That breaks the round trip
build_turn_prompt's pending_confirmation depends on -- agent.py needs a
concrete {tool, args} to persist across turns when a write action is
staged, and a free-text "reply" string can't be reconstructed back into
that reliably. Fixed here by adding a third action, "stage", which still
carries a real tool/args pair (the proposed call) alongside the
human-readable summary in "reply". "reply" is now reserved for pure
conversation/clarifying questions with no action attached.
"""

from __future__ import annotations

import json

from app.agents.leave_agent.tools import TOOLS

PROMPT_VERSION = "leave-agent-v2"

_SYSTEM_PREAMBLE = """You are the Leave Agent, a focused assistant that helps an employee \
check their leave balance, submit a leave request, view their past requests, or cancel a \
pending request. You are talking to the employee themselves — never another employee's \
leave, never a manager reviewing someone else's request. Approving or rejecting leave \
requests is not something you do, regardless of who is asking or how the request is phrased.

Rules you must follow:
1. Never invent a leave type, balance, request id, or status. Only use what a tool returns.
2. If the leave type, dates, or which request the employee means is ambiguous, ask a \
clarifying question instead of guessing — do not stage or call a tool on a guess.
3. A tool marked "requires confirmation" must never be called on the same turn it is \
proposed. Use action "stage" to propose it and summarize it in plain language. Only use \
action "call_tool" for that tool once the employee's message is an unambiguous \
yes/confirm/go-ahead in direct response to that exact staged summary.
4. If the employee's message cancels or changes their mind about a staged action, discard \
it — do not call the tool, and do not carry the old staged action into a new one.
5. Respond to a rejection from a tool (insufficient balance, invalid dates, not found, not \
permitted) by relaying the reason plainly. Do not soften it into a vague apology and do not \
try to work around it yourself.
6. Output ONLY a single valid JSON object matching the schema below. No markdown fences, \
no commentary before or after it."""

_RESPONSE_SCHEMA_TEMPLATE = """Respond with a single JSON object of exactly this shape:
{{
  "reply": string,               // what to say to the employee this turn — always present
  "action": string,               // one of: "reply", "stage", "call_tool"
  "tool": string | null,          // tool name from AVAILABLE TOOLS, required for "stage" and "call_tool"
  "args": object                  // arguments for that tool (see its schema); {{}} if action == "reply"
}}

Use action "call_tool" for:
  - any read tool ({read_tools}) — call it directly, no confirmation needed
  - a write tool ({write_tools}) ONLY when the employee has just \
confirmed a staged action from the previous turn — copy the previously staged args exactly

Use action "stage" for:
  - proposing a write tool ({write_tools}) that has not yet been confirmed — fill in "tool" \
and "args" with the exact call you are proposing, and describe it fully in "reply" so the \
employee can confirm or decline it

Use action "reply" for:
  - answering conversationally, with no tool call attached
  - asking a clarifying question
  - relaying a tool rejection or the result of a prior tool call in plain language
  - declining a staged action the employee just backed out of"""


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
) -> str:
    """Build the user-role prompt for one turn.

    `history` is a list of {"role": "employee"|"agent", "content": ...} pairs
    from earlier in this session — kept short (state.py is responsible for
    trimming it) since this is a single-shot completion, not a native
    multi-turn chat call.

    `pending_confirmation` is set by agent.py when a write tool was staged
    (action "stage") on the previous turn and is awaiting a yes/no this
    turn — the model is told exactly what's staged so it can recognize
    "yes" as "confirm THIS" rather than inferring it, and so it can copy
    the args back verbatim instead of re-deriving them (which risks
    drifting from what was actually summarized to the employee).
    """
    parts: list[str] = []

    if history:
        parts.append("CONVERSATION SO FAR:")
        for turn in history:
            speaker = "Employee" if turn["role"] == "employee" else "Agent"
            parts.append(f"{speaker}: {turn['content']}")
        parts.append("")

    if pending_confirmation:
        parts.append(
            "STAGED ACTION AWAITING CONFIRMATION:\n"
            f"tool: {pending_confirmation['tool']}\n"
            f"args: {json.dumps(pending_confirmation['args'])}\n"
            "If the employee's new message below clearly confirms this, respond with "
            "action \"call_tool\" using this exact tool and these exact args. If they "
            "decline or change the subject, drop this staged action and respond with "
            "action \"reply\"."
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
        return f"Cancel leave request {args['leave_request_id']}?"
    return f"Proceed with {tool_name}({json.dumps(args)})?"