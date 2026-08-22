"""AG-UI Generative UI module for the Knowledge Agent.

Synthesizes rich, interactive, sandboxed Generative UI artifacts (embedded in
iframes via the AG-UI protocol) for HR policies, guidelines, calculators,
procedure checklists, and comparison matrices with progressive streaming and skeleton states.
"""

from __future__ import annotations

import html
import logging
import re
from typing import Any

from app.contracts.auth import UserContext
from app.model_gateway.interfaces import LLM

logger = logging.getLogger(__name__)

# Keywords signaling visual, comparative, procedural, or numeric knowledge topics
_COMPARISON_KEYWORDS = (
    "compare",
    "comparison",
    "difference",
    "versus",
    "vs",
    "between",
    "options",
    "types of",
)
_CALCULATOR_KEYWORDS = (
    "calculate",
    "calculator",
    "how many days",
    "estimate",
    "accrual",
    "carryover",
    "carry over",
    "overtime",
    "severance",
    "prorated",
    "formula",
    "pay rate",
    "accrual rate",
)
_PROCEDURE_KEYWORDS = (
    "step",
    "steps",
    "procedure",
    "process",
    "how to",
    "checklist",
    "workflow",
    "guide",
    "onboarding",
    "resignation",
    "claim",
    "clearance",
    "apply for",
)
_GENUI_TRIGGER_KEYWORDS = (
    "ui",
    "genui",
    "interactive",
    "widget",
    "visualize",
    "visual",
    "dashboard",
    "table",
    "chart",
    "matrix",
    "iframe",
)


def format_inline_markdown(text: str) -> str:
    """Converts inline markdown (bold, italic, code, citations) to clean HTML."""
    if not text:
        return ""
    # Strip citation markers like [1], [2, 3] from widget display
    cleaned = re.sub(r"\[\d+(?:,\s*\d+)*\]", "", text)
    # Remove leading markdown header marks, bullets with whitespace, numbering with dot
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned)
    cleaned = re.sub(r"^(\*|-|•|\d+\.|\d+\))\s+", "", cleaned)
    cleaned = cleaned.strip()

    # Escape HTML special characters
    escaped = html.escape(cleaned)

    # Convert bold: **text** or __text__ -> <strong>text</strong>
    escaped = re.sub(r"\*\*(.+?)\*\*", r'<strong class="font-semibold text-zinc-900">\1</strong>', escaped)
    escaped = re.sub(r"__(.+?)__", r'<strong class="font-semibold text-zinc-900">\1</strong>', escaped)

    # Convert italic: *text* or _text_ -> <em>text</em>
    escaped = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r'<em class="text-zinc-800">\1</em>', escaped)

    # Convert inline code: `text` -> <code>text</code>
    escaped = re.sub(
        r"`(.+?)`",
        r'<code class="rounded bg-zinc-100 px-1 py-0.5 font-mono text-[11px] text-zinc-800">\1</code>',
        escaped,
    )
    return escaped


_AG_UI_BRIDGE_SCRIPT = """
<script>
(function() {
  let lastReported = 0;

  function reportHeight() {
    const root = document.getElementById('genui-root') || document.body.firstElementChild || document.body;
    if (!root) return;

    const rect = root.getBoundingClientRect();
    const bodyStyle = window.getComputedStyle(document.body);
    const padTop = parseFloat(bodyStyle.paddingTop) || 0;
    const padBottom = parseFloat(bodyStyle.paddingBottom) || 0;
    const totalHeight = Math.ceil(rect.height + padTop + padBottom + 4);

    if (totalHeight > 40 && Math.abs(totalHeight - lastReported) >= 2) {
      lastReported = totalHeight;
      window.parent.postMessage({ type: 'ag_ui:resize', height: totalHeight }, '*');
    }
  }

  window.addEventListener('DOMContentLoaded', reportHeight);
  window.addEventListener('load', reportHeight);

  if (window.ResizeObserver) {
    const root = document.getElementById('genui-root') || document.body.firstElementChild || document.body;
    if (root) {
      const observer = new ResizeObserver(function() {
        reportHeight();
      });
      observer.observe(root);
    }
  }

  window.triggerChatAction = function(actionText) {
    if (!actionText) return;
    window.parent.postMessage({
      type: 'ag_ui:action',
      text: actionText
    }, '*');
  };

  setTimeout(reportHeight, 100);
  setTimeout(reportHeight, 400);
})();
</script>
"""

_HTML_SHELL_HEAD = """<!DOCTYPE html>
<html lang="en" style="height: auto; min-height: 0; margin: 0; padding: 0;">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    html, body {
      font-family: 'Inter', system-ui, -apple-system, sans-serif;
      margin: 0;
      padding: 6px;
      height: auto;
      min-height: 0;
      background: transparent;
      color: #18181b;
      -webkit-font-smoothing: antialiased;
      box-sizing: border-box;
      width: 100%;
    }
    *, *:before, *:after {
      box-sizing: inherit;
    }
    ::-webkit-scrollbar { width: 5px; height: 5px; }
    ::-webkit-scrollbar-track { background: #f4f4f5; border-radius: 4px; }
    ::-webkit-scrollbar-thumb { background: #d4d4d8; border-radius: 4px; }
    ::-webkit-scrollbar-thumb:hover { background: #a1a1aa; }
  </style>
</head>
<body style="height: auto; min-height: 0;">
"""

_HTML_SHELL_TAIL = f"""
{_AG_UI_BRIDGE_SCRIPT}
</body>
</html>
"""


def should_generate_genui(query: str, grounded_context: str | None = None) -> bool:
    """Determine if a knowledge query warrants an interactive GenUI component."""
    q = query.lower()
    if any(kw in q for kw in _GENUI_TRIGGER_KEYWORDS):
        return True
    if any(kw in q for kw in _COMPARISON_KEYWORDS):
        return True
    if any(kw in q for kw in _CALCULATOR_KEYWORDS):
        return True
    if any(kw in q for kw in _PROCEDURE_KEYWORDS):
        return True
    if grounded_context:
        ctx = grounded_context.lower()
        if "|" in grounded_context and "---" in grounded_context:
            return True
        if "1." in ctx and "2." in ctx and "3." in ctx:
            return True
    return False


def detect_genui_type(query: str, grounded_context: str | None = None) -> tuple[str, str]:
    """Determines the UI type and human-friendly title for early progressive skeleton generation."""
    q = query.lower()
    if any(kw in q for kw in _CALCULATOR_KEYWORDS):
        return ("calculator", "Interactive Policy Calculator")
    if any(kw in q for kw in _PROCEDURE_KEYWORDS):
        return ("procedure", "Procedure Guide & Checklist")
    if any(kw in q for kw in _COMPARISON_KEYWORDS):
        return ("comparison", "Policy Comparison Matrix")
    if any(kw in q for kw in _GENUI_TRIGGER_KEYWORDS):
        return ("custom", "Interactive Policy Overview")
    return ("comparison", "Policy Overview & Comparison")


def build_skeleton_genui(ui_type: str, query: str) -> str:
    """Generates an animated, shimmering Tailwind skeleton placeholder for early streaming."""
    escaped_query = html.escape(query)

    if ui_type == "calculator":
        content = f"""
        <div id="genui-root" class="w-full rounded-xl bg-gradient-to-br from-blue-50/40 via-white to-indigo-50/30 p-4 border border-blue-100 shadow-2xs animate-pulse">
          <!-- Top Bar -->
          <div class="flex items-center justify-between pb-3 border-b border-blue-100/60 mb-3.5">
            <div class="flex items-center gap-2.5">
              <div class="h-7 w-7 rounded-lg bg-indigo-200/80 animate-pulse"></div>
              <div class="space-y-1.5">
                <div class="h-3.5 w-40 bg-zinc-200 rounded"></div>
                <div class="h-2.5 w-24 bg-zinc-100 rounded"></div>
              </div>
            </div>
            <div class="flex items-center gap-1.5 rounded-full bg-indigo-50 px-2.5 py-1 border border-indigo-200/60">
              <span class="h-1.5 w-1.5 rounded-full bg-indigo-500 animate-ping"></span>
              <span class="text-[10px] font-semibold text-indigo-700">Calculating...</span>
            </div>
          </div>

          <!-- 2-Column Dashboard Skeleton -->
          <div class="grid grid-cols-1 md:grid-cols-12 gap-3.5 mb-3">
            <div class="md:col-span-7 space-y-2.5">
              <div class="bg-white/80 rounded-xl p-3.5 border border-zinc-200/70 space-y-2.5">
                <div class="flex justify-between">
                  <div class="h-3 w-32 bg-zinc-200 rounded"></div>
                  <div class="h-3 w-12 bg-blue-100 rounded"></div>
                </div>
                <div class="h-2 w-full bg-zinc-100 rounded-full"></div>
              </div>
              <div class="bg-white/80 rounded-xl p-3.5 border border-zinc-200/70 space-y-2.5">
                <div class="flex justify-between">
                  <div class="h-3 w-40 bg-zinc-200 rounded"></div>
                  <div class="h-3 w-12 bg-indigo-100 rounded"></div>
                </div>
                <div class="h-2 w-full bg-zinc-100 rounded-full"></div>
              </div>
            </div>

            <div class="md:col-span-5 rounded-xl bg-white/80 p-4 border border-indigo-100/80 flex flex-col justify-between space-y-3">
              <div class="space-y-2">
                <div class="h-2.5 w-24 bg-zinc-200 rounded"></div>
                <div class="h-6 w-36 bg-indigo-100 rounded"></div>
                <div class="h-2 w-full bg-zinc-100 rounded-full mt-2"></div>
              </div>
              <div class="h-7 w-full bg-indigo-200/60 rounded-lg"></div>
            </div>
          </div>
        </div>
        """
    elif ui_type == "procedure":
        content = f"""
        <div id="genui-root" class="w-full rounded-xl bg-gradient-to-br from-emerald-50/30 via-white to-zinc-50 p-4 border border-emerald-100 shadow-2xs animate-pulse">
          <!-- Top Bar -->
          <div class="flex items-center justify-between pb-3 border-b border-emerald-100/60 mb-3">
            <div class="flex items-center gap-2.5">
              <div class="h-7 w-7 rounded-lg bg-emerald-200/80 animate-pulse"></div>
              <div class="space-y-1.5">
                <div class="h-3.5 w-44 bg-zinc-200 rounded"></div>
                <div class="h-2.5 w-28 bg-zinc-100 rounded"></div>
              </div>
            </div>
            <div class="flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 border border-emerald-200/60">
              <span class="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-ping"></span>
              <span class="text-[10px] font-semibold text-emerald-700">Structuring steps...</span>
            </div>
          </div>

          <!-- Step Cards Grid Skeleton -->
          <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5 mb-3">
            <div class="p-3 bg-white/90 rounded-xl border border-zinc-200/70 space-y-2">
              <div class="h-3.5 w-12 bg-emerald-100 rounded"></div>
              <div class="h-3 w-full bg-zinc-100 rounded"></div>
              <div class="h-3 w-3/4 bg-zinc-100 rounded"></div>
            </div>
            <div class="p-3 bg-white/90 rounded-xl border border-zinc-200/70 space-y-2">
              <div class="h-3.5 w-12 bg-emerald-100 rounded"></div>
              <div class="h-3 w-full bg-zinc-100 rounded"></div>
              <div class="h-3 w-3/4 bg-zinc-100 rounded"></div>
            </div>
            <div class="p-3 bg-white/90 rounded-xl border border-zinc-200/70 space-y-2">
              <div class="h-3.5 w-12 bg-emerald-100 rounded"></div>
              <div class="h-3 w-full bg-zinc-100 rounded"></div>
              <div class="h-3 w-3/4 bg-zinc-100 rounded"></div>
            </div>
          </div>

          <div class="flex items-center justify-between pt-2.5 border-t border-zinc-100">
            <div class="h-3 w-32 bg-zinc-100 rounded"></div>
            <div class="h-6 w-24 bg-emerald-100 rounded"></div>
          </div>
        </div>
        """
    else:  # comparison & custom
        content = f"""
        <div id="genui-root" class="w-full rounded-xl bg-gradient-to-b from-zinc-50 to-white p-4 border border-zinc-200 shadow-2xs animate-pulse">
          <!-- Top Bar -->
          <div class="flex items-center justify-between pb-3 border-b border-zinc-200/70 mb-3">
            <div class="flex items-center gap-2.5">
              <div class="h-7 w-7 rounded-lg bg-blue-200/80 animate-pulse"></div>
              <div class="space-y-1.5">
                <div class="h-3.5 w-44 bg-zinc-200 rounded"></div>
                <div class="h-2.5 w-32 bg-zinc-100 rounded"></div>
              </div>
            </div>
            <div class="flex items-center gap-1.5 rounded-full bg-blue-50 px-2.5 py-1 border border-blue-200/60">
              <span class="h-1.5 w-1.5 rounded-full bg-blue-500 animate-ping"></span>
              <span class="text-[10px] font-semibold text-blue-700">Synthesizing matrix...</span>
            </div>
          </div>

          <!-- Comparison Grid Skeleton -->
          <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5 mb-3">
            <div class="p-3 bg-white/90 rounded-xl border border-zinc-200/70 space-y-2">
              <div class="flex items-center gap-2">
                <div class="h-5 w-5 rounded-full bg-blue-100"></div>
                <div class="h-3.5 w-24 bg-zinc-200 rounded"></div>
              </div>
              <div class="h-3 w-full bg-zinc-100 rounded"></div>
              <div class="h-3 w-4/5 bg-zinc-100 rounded"></div>
            </div>
            <div class="p-3 bg-white/90 rounded-xl border border-zinc-200/70 space-y-2">
              <div class="flex items-center gap-2">
                <div class="h-5 w-5 rounded-full bg-blue-100"></div>
                <div class="h-3.5 w-24 bg-zinc-200 rounded"></div>
              </div>
              <div class="h-3 w-full bg-zinc-100 rounded"></div>
              <div class="h-3 w-4/5 bg-zinc-100 rounded"></div>
            </div>
            <div class="p-3 bg-white/90 rounded-xl border border-zinc-200/70 space-y-2">
              <div class="flex items-center gap-2">
                <div class="h-5 w-5 rounded-full bg-blue-100"></div>
                <div class="h-3.5 w-24 bg-zinc-200 rounded"></div>
              </div>
              <div class="h-3 w-full bg-zinc-100 rounded"></div>
              <div class="h-3 w-4/5 bg-zinc-100 rounded"></div>
            </div>
          </div>

          <div class="flex items-center justify-between pt-2.5 border-t border-zinc-100">
            <div class="h-3 w-28 bg-zinc-100 rounded"></div>
            <div class="h-6 w-24 bg-zinc-200 rounded"></div>
          </div>
        </div>
        """

    return f"{_HTML_SHELL_HEAD}{content}{_HTML_SHELL_TAIL}"


def build_comparison_genui(query: str, answer: str, context: str) -> str:
    """Synthesizes a horizontally-oriented Policy Comparison Matrix GenUI artifact."""
    escaped_query = html.escape(query)

    raw_lines = [l.strip() for l in answer.splitlines() if l.strip()]
    candidate_items: list[str] = []

    for line in raw_lines:
        if line.startswith("#") and len(candidate_items) > 0:
            continue
        cleaned = re.sub(r"^(\*|-|•|\d+\.|\d+\))\s+", "", line).strip()
        if cleaned and len(cleaned) > 5:
            candidate_items.append(cleaned)
        if len(candidate_items) >= 6:
            break

    items_html = ""
    for i, item in enumerate(candidate_items[:6]):
        formatted = format_inline_markdown(item)
        items_html += f"""
        <div class="flex flex-col justify-between p-3 bg-white rounded-xl border border-zinc-200 shadow-2xs hover:border-blue-300 hover:shadow-xs transition-all">
          <div class="flex items-start gap-2.5">
            <span class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-50 text-[10px] font-bold text-blue-600 border border-blue-200">
              {i + 1}
            </span>
            <div class="text-xs text-zinc-700 leading-relaxed space-y-0.5">
              {formatted}
            </div>
          </div>
        </div>
        """

    if not items_html:
        formatted_ans = format_inline_markdown(answer[:300])
        items_html = f"""
        <div class="p-3 bg-white rounded-xl border border-zinc-200 col-span-full">
          <div class="text-xs text-zinc-700 leading-relaxed">{formatted_ans}...</div>
        </div>
        """

    content = f"""
    <div id="genui-root" class="w-full rounded-xl bg-gradient-to-b from-zinc-50 to-white p-4 border border-zinc-200 shadow-2xs">
      <!-- Horizontal Top Header -->
      <div class="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-zinc-200/70 mb-3">
        <div class="flex items-center gap-2.5">
          <span class="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-600 text-white shadow-2xs">
            <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
          </span>
          <div>
            <h3 class="text-xs font-bold text-zinc-900">Policy Comparison Matrix</h3>
            <p class="text-[11px] text-zinc-500 max-w-md truncate">{escaped_query}</p>
          </div>
        </div>

        <div class="flex items-center gap-2">
          <input
            id="filterInput"
            type="text"
            placeholder="Filter policy terms..."
            oninput="filterItems(this.value)"
            class="w-48 sm:w-60 rounded-lg border border-zinc-300 bg-white px-2.5 py-1 text-xs text-zinc-800 placeholder-zinc-400 focus:border-blue-500 focus:outline-none"
          />
          <span class="rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-medium text-blue-700 border border-blue-200 shrink-0">
            Interactive AG-UI
          </span>
        </div>
      </div>

      <!-- Horizontal Multi-Column Cards -->
      <div id="itemsGrid" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5 mb-3">
        {items_html}
      </div>

      <!-- Horizontal Footer -->
      <div class="flex items-center justify-between pt-2.5 border-t border-zinc-100 text-[11px] text-zinc-500">
        <span>Click below for more details or clarifications</span>
        <button
          type="button"
          onclick="window.triggerChatAction('Can you provide more specific examples of these policies?')"
          class="rounded-lg bg-zinc-900 px-3 py-1 text-xs font-medium text-white hover:bg-zinc-800 transition-colors shadow-2xs"
        >
          Ask follow-up &rarr;
        </button>
      </div>
    </div>

    <script>
      function filterItems(term) {{
        const lower = (term || '').toLowerCase();
        const cards = document.querySelectorAll('#itemsGrid > div');
        cards.forEach(function(card) {{
          const text = card.textContent.toLowerCase();
          card.style.display = text.includes(lower) ? '' : 'none';
        }});
      }}
    </script>
    """
    return f"{_HTML_SHELL_HEAD}{content}{_HTML_SHELL_TAIL}"


def build_calculator_genui(query: str, answer: str, context: str) -> str:
    """Synthesizes a horizontally-oriented interactive HR Calculator GenUI artifact."""
    escaped_query = html.escape(query)

    found_days = re.findall(r"(\d+)\s*(?:days|day)", answer.lower() + " " + context.lower())
    default_entitlement = int(found_days[0]) if found_days else 20
    default_carryover = int(found_days[1]) if len(found_days) > 1 else 5

    content = f"""
    <div id="genui-root" class="w-full rounded-xl bg-gradient-to-br from-blue-50/50 via-white to-indigo-50/40 p-4 border border-blue-200/80 shadow-2xs">
      <!-- Top Bar -->
      <div class="flex items-center justify-between pb-3 border-b border-blue-100 mb-3.5">
        <div class="flex items-center gap-2.5">
          <span class="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-600 text-white shadow-2xs">
            <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 14h.01M12 14h.01M15 11h.01M12 11h.01M9 11h.01M7 21h10a2 2 0 002-2V5a2 2 0 00-2-2H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
            </svg>
          </span>
          <div>
            <h3 class="text-xs font-bold text-zinc-900">Interactive HR Policy Calculator</h3>
            <p class="text-[11px] text-zinc-500 truncate max-w-sm">{escaped_query}</p>
          </div>
        </div>
        <span class="rounded-full bg-indigo-50 px-2.5 py-0.5 text-[10px] font-semibold text-indigo-700 border border-indigo-200">
          Live Estimator
        </span>
      </div>

      <!-- Horizontal 2-Column Dashboard (Left: Inputs, Right: Live Result Card) -->
      <div class="grid grid-cols-1 md:grid-cols-12 gap-3.5 mb-3">
        <!-- Left Column: Controls (Span 7) -->
        <div class="md:col-span-7 space-y-2.5">
          <div class="bg-white rounded-xl p-3 border border-zinc-200/90 shadow-2xs">
            <div class="flex items-center justify-between mb-1.5">
              <label class="text-[11px] font-semibold text-zinc-700">
                Current Leave Balance
              </label>
              <span id="daysVal" class="text-xs font-bold text-blue-700 bg-blue-50 px-2 py-0.5 rounded-md border border-blue-200">{default_entitlement} Days</span>
            </div>
            <input
              id="daysInput"
              type="range"
              min="0"
              max="30"
              value="{default_entitlement}"
              oninput="updateCalc()"
              class="w-full accent-blue-600 cursor-pointer"
            />
          </div>

          <div class="bg-white rounded-xl p-3 border border-zinc-200/90 shadow-2xs">
            <div class="flex items-center justify-between mb-1.5">
              <label class="text-[11px] font-semibold text-zinc-700">
                Months in Service / Accrual Period
              </label>
              <span id="monthsVal" class="text-xs font-bold text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded-md border border-indigo-200">{12} Months</span>
            </div>
            <input
              id="monthsInput"
              type="range"
              min="1"
              max="12"
              value="12"
              oninput="updateCalc()"
              class="w-full accent-indigo-600 cursor-pointer"
            />
          </div>
        </div>

        <!-- Right Column: Live Result & Actions (Span 5) -->
        <div class="md:col-span-5 flex flex-col justify-between rounded-xl bg-white p-3.5 border border-indigo-200 shadow-2xs">
          <div>
            <span class="text-[11px] font-medium text-zinc-500 uppercase tracking-wider">Estimated Carryover</span>
            <div id="calcTotal" class="text-base font-bold text-indigo-700 mt-1">
              {default_carryover} Days Max Carryover
            </div>
            <div class="w-full bg-zinc-100 rounded-full h-2 mt-2.5 overflow-hidden">
              <div id="calcProgress" class="bg-indigo-600 h-2 rounded-full transition-all duration-300" style="width: 50%"></div>
            </div>
            <p class="text-[10px] text-zinc-400 mt-2">Maximum allowable carryover under policy rules</p>
          </div>

          <div class="pt-2 mt-2 border-t border-zinc-100">
            <button
              type="button"
              onclick="window.triggerChatAction('How do I submit a leave carryover request?')"
              class="w-full rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white shadow-2xs hover:bg-indigo-700 transition-colors text-center"
            >
              Submit Carryover Request &rarr;
            </button>
          </div>
        </div>
      </div>
    </div>

    <script>
      const MAX_CARRYOVER = {default_carryover};
      function updateCalc() {{
        const days = parseInt(document.getElementById('daysInput').value, 10);
        const months = parseInt(document.getElementById('monthsInput').value, 10);
        document.getElementById('daysVal').innerText = days + ' Days';
        document.getElementById('monthsVal').innerText = months + ' Months';

        const carryover = Math.min(days, MAX_CARRYOVER);
        const pct = Math.min(100, Math.round((carryover / Math.max(1, MAX_CARRYOVER)) * 100));

        document.getElementById('calcTotal').innerText = carryover + ' Days (from ' + days + ' available)';
        document.getElementById('calcProgress').style.width = pct + '%';
      }}
      updateCalc();
    </script>
    """
    return f"{_HTML_SHELL_HEAD}{content}{_HTML_SHELL_TAIL}"


def build_procedure_genui(query: str, answer: str, context: str) -> str:
    """Synthesizes a horizontally-oriented Procedure Checklist & Guide GenUI artifact."""
    escaped_query = html.escape(query)

    raw_lines = [l.strip() for l in answer.splitlines() if l.strip()]
    step_items: list[str] = []
    for line in raw_lines:
        if line.startswith("#") and len(step_items) > 0:
            continue
        cleaned = re.sub(r"^(\*|-|•|\d+\.|\d+\))\s+", "", line).strip()
        if cleaned and len(cleaned) > 5:
            step_items.append(cleaned)
        if len(step_items) >= 6:
            break

    if not step_items:
        step_items = [
            "Review company policy requirements and eligibility",
            "Prepare necessary supporting documentation and forms",
            "Submit request to your direct reporting manager",
            "Receive formal HR approval and acknowledgement",
        ]

    steps_html = ""
    for i, st in enumerate(step_items):
        formatted = format_inline_markdown(st)
        steps_html += f"""
        <label class="flex items-start gap-2.5 p-3 rounded-xl border border-zinc-200 bg-white hover:border-emerald-300 hover:shadow-2xs cursor-pointer transition-all">
          <input
            type="checkbox"
            onchange="updateChecklist()"
            class="step-check mt-0.5 h-4 w-4 rounded border-zinc-300 text-emerald-600 focus:ring-emerald-500 cursor-pointer shrink-0"
          />
          <div class="space-y-0.5">
            <span class="inline-block rounded-md bg-emerald-50 px-1.5 py-0.5 text-[10px] font-bold text-emerald-700 border border-emerald-200 mb-0.5">
              Step {i + 1}
            </span>
            <div class="text-xs text-zinc-700 leading-relaxed">{formatted}</div>
          </div>
        </label>
        """

    content = f"""
    <div id="genui-root" class="w-full rounded-xl bg-gradient-to-br from-emerald-50/40 via-white to-zinc-50 p-4 border border-emerald-200/80 shadow-2xs">
      <!-- Horizontal Top Header -->
      <div class="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-emerald-100 mb-3">
        <div class="flex items-center gap-2.5">
          <span class="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-600 text-white shadow-2xs">
            <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </span>
          <div>
            <h3 class="text-xs font-bold text-zinc-900">Procedure Checklist & Guide</h3>
            <p class="text-[11px] text-zinc-500 truncate max-w-sm">{escaped_query}</p>
          </div>
        </div>

        <div class="flex items-center gap-3">
          <div class="w-32 bg-zinc-100 rounded-full h-2 overflow-hidden border border-zinc-200">
            <div id="checklistProgressBar" class="bg-emerald-600 h-2 rounded-full transition-all duration-300" style="width: 0%"></div>
          </div>
          <span id="progressPill" class="rounded-full bg-emerald-50 px-2.5 py-0.5 text-[10px] font-semibold text-emerald-700 border border-emerald-200 shrink-0">
            0 / {len(step_items)} Done
          </span>
        </div>
      </div>

      <!-- Horizontal Multi-Column Step Cards -->
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5 mb-3">
        {steps_html}
      </div>

      <!-- Horizontal Footer -->
      <div class="flex items-center justify-between pt-2.5 border-t border-zinc-100 text-[11px] text-zinc-500">
        <span>Track your progress step-by-step</span>
        <button
          type="button"
          onclick="window.triggerChatAction('What forms do I need to attach for this procedure?')"
          class="rounded-lg bg-emerald-600 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-700 transition-colors shadow-2xs"
        >
          Get required forms &rarr;
        </button>
      </div>
    </div>

    <script>
      function updateChecklist() {{
        const checkboxes = document.querySelectorAll('.step-check');
        let checked = 0;
        checkboxes.forEach(function(cb) {{ if (cb.checked) checked++; }});
        const total = checkboxes.length;
        const pct = total > 0 ? Math.round((checked / total) * 100) : 0;

        document.getElementById('checklistProgressBar').style.width = pct + '%';
        document.getElementById('progressPill').innerText = checked + ' / ' + total + ' Done';
      }}
    </script>
    """
    return f"{_HTML_SHELL_HEAD}{content}{_HTML_SHELL_TAIL}"


_OPEN_GENUI_SYSTEM = """You are a Generative UI designer creating a modern, self-contained HTML component for an AI HR Assistant.
Given a user query, grounded HR policy context, and text answer, generate ONLY the HTML body content (no markdown code fences, no ```html, no <html>/<body> tags).
Follow these guidelines:
1. Wrap everything inside a top-level `<div id="genui-root" class="w-full rounded-xl bg-white p-4 border border-zinc-200">...</div>`.
2. Use horizontal, responsive multi-column layouts (`grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3`).
3. Do NOT output raw markdown symbols like `**`, `*`, `###`, or `[1]` citations inside the HTML; convert all formatting into proper HTML tags like `<strong>`, `<em>`, `<span>`, `<div>`, `<p>`, `<button>`.
4. Use modern Tailwind CSS classes for styling (cards, gradients, badges, buttons, sliders, tabs, or checklists).
5. Use a cohesive palette matching standard zinc/blue/emerald/indigo.
6. Make it interactive (e.g. tabs, filter inputs, calculate buttons, or interactive toggles with vanilla JavaScript).
7. If there are action buttons, wire them to `window.triggerChatAction('your chat prompt here')`.
8. Keep it expansive horizontally to fit the full width of the chat container.
Output ONLY the raw HTML/JS block.
"""


async def generate_knowledge_genui(
    llm: LLM | None,
    query: str,
    answer: str,
    grounded_context: str | None = None,
    actor: UserContext | None = None,
) -> dict[str, Any] | None:
    """Generate an AG-UI GenUI widget for the knowledge agent response."""
    if not should_generate_genui(query, grounded_context):
        return None

    q = query.lower()

    # 1. Specialized fast high-quality template routing
    if any(kw in q for kw in _CALCULATOR_KEYWORDS):
        html_doc = build_calculator_genui(query, answer, grounded_context or "")
        return {
            "type": "genui_iframe",
            "spec": "ag-ui/v1",
            "ui_type": "calculator",
            "title": "Interactive Policy Calculator",
            "status": "ready",
            "html": html_doc,
        }

    if any(kw in q for kw in _PROCEDURE_KEYWORDS):
        html_doc = build_procedure_genui(query, answer, grounded_context or "")
        return {
            "type": "genui_iframe",
            "spec": "ag-ui/v1",
            "ui_type": "procedure",
            "title": "Procedure Guide & Checklist",
            "status": "ready",
            "html": html_doc,
        }

    if any(kw in q for kw in _COMPARISON_KEYWORDS):
        html_doc = build_comparison_genui(query, answer, grounded_context or "")
        return {
            "type": "genui_iframe",
            "spec": "ag-ui/v1",
            "ui_type": "comparison",
            "title": "Policy Comparison Matrix",
            "status": "ready",
            "html": html_doc,
        }

    # 2. Dynamic LLM-driven synthesis when LLM is available
    if llm is not None and any(kw in q for kw in _GENUI_TRIGGER_KEYWORDS):
        try:
            prompt = (
                f"QUESTION: {query}\n\n"
                f"GROUNDED CONTEXT:\n{grounded_context or ''}\n\n"
                f"ANSWER:\n{answer}\n\n"
                "Generate an interactive HTML/Tailwind visual component for this answer:"
            )
            raw_html = await llm.complete(_OPEN_GENUI_SYSTEM, prompt)
            cleaned_html = raw_html.strip()
            if cleaned_html.startswith("```"):
                cleaned_html = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned_html)
                cleaned_html = re.sub(r"\n?```$", "", cleaned_html)
            if cleaned_html:
                cleaned_html = re.sub(r"\[\d+(?:,\s*\d+)*\]", "", cleaned_html)
                cleaned_html = re.sub(r"\*\*(.+?)\*\*", r'<strong class="font-semibold text-zinc-900">\1</strong>', cleaned_html)
                if 'id="genui-root"' not in cleaned_html:
                    cleaned_html = f'<div id="genui-root" class="w-full rounded-xl bg-white p-4 border border-zinc-200">{cleaned_html}</div>'
                full_doc = f"{_HTML_SHELL_HEAD}\n{cleaned_html}\n{_HTML_SHELL_TAIL}"
                return {
                    "type": "genui_iframe",
                    "spec": "ag-ui/v1",
                    "ui_type": "custom",
                    "title": "Interactive Policy Overview",
                    "status": "ready",
                    "html": full_doc,
                }
        except Exception as e:
            logger.warning("LLM GenUI generation failed, falling back to comparison template: %s", e)

    # Default fallback template
    html_doc = build_comparison_genui(query, answer, grounded_context or "")
    return {
        "type": "genui_iframe",
        "spec": "ag-ui/v1",
        "ui_type": "comparison",
        "title": "Policy Overview & Comparison",
        "status": "ready",
        "html": html_doc,
    }
