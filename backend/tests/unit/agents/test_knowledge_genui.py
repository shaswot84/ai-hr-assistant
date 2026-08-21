"""Unit tests for AG-UI GenUI generator."""

from __future__ import annotations

import pytest

from app.agents.knowledge_agent.genui import (
    build_calculator_genui,
    build_comparison_genui,
    build_procedure_genui,
    format_inline_markdown,
    generate_knowledge_genui,
    should_generate_genui,
)
from app.model_gateway.interfaces import LLM


class FakeLLM(LLM):
    def __init__(self, reply: str = "<div>Fake GenUI</div>"):
        self.reply = reply

    async def complete(self, system: str, user: str) -> str:
        return self.reply


def test_format_inline_markdown():
    # Bold conversion
    res = format_inline_markdown("**Annual Leave:** 20 days per year [1].")
    assert "<strong" in res
    assert "Annual Leave:" in res
    assert "[1]" not in res
    assert "**" not in res

    # Italic and code
    res = format_inline_markdown("Submit *two weeks* in advance with `Form A` [2, 3].")
    assert "<em" in res
    assert "<code" in res
    assert "[2, 3]" not in res
    assert "*" not in res


def test_should_generate_genui_keywords():
    assert should_generate_genui("compare sick leave and casual leave")
    assert should_generate_genui("calculate my overtime pay")
    assert should_generate_genui("how to apply for resignation checklist")
    assert should_generate_genui("visualize this as a genui widget")
    assert should_generate_genui("what is the policy?", "| Col 1 | Col 2 |\n|---|---|")
    assert not should_generate_genui("hello who are you?")


def test_build_comparison_genui():
    html_doc = build_comparison_genui(
        "compare sick and casual leave",
        "- **Sick Leave:** 10 days [1]\n- **Casual Leave:** 5 days [2]",
        "Context evidence",
    )
    assert "<!DOCTYPE html>" in html_doc
    assert "Policy Comparison Matrix" in html_doc
    assert "<strong" in html_doc
    assert "**" not in html_doc
    assert "ag_ui:resize" in html_doc
    assert "triggerChatAction" in html_doc


def test_build_calculator_genui():
    html_doc = build_calculator_genui(
        "calculate my leave carryover",
        "You can carry over up to 10 days of annual leave.",
        "Context evidence",
    )
    assert "<!DOCTYPE html>" in html_doc
    assert "Interactive HR Policy Calculator" in html_doc
    assert "updateCalc" in html_doc


def test_build_procedure_genui():
    html_doc = build_procedure_genui(
        "steps to claim medical expenses",
        "1. **Fill out** claim form [1].\n2. **Attach** medical receipts.\n3. Submit to HR.",
        "Context evidence",
    )
    assert "<!DOCTYPE html>" in html_doc
    assert "Procedure Checklist & Guide" in html_doc
    assert "<strong" in html_doc
    assert "**" not in html_doc
    assert "updateChecklist" in html_doc


@pytest.mark.asyncio
async def test_generate_knowledge_genui_calculator():
    widget = await generate_knowledge_genui(
        llm=None,
        query="calculate my carryover days",
        answer="You can carry over 10 days.",
        grounded_context="Policy doc",
    )
    assert widget is not None
    assert widget["type"] == "genui_iframe"
    assert widget["spec"] == "ag-ui/v1"
    assert widget["ui_type"] == "calculator"
    assert "html" in widget
    assert "<!DOCTYPE html>" in widget["html"]


@pytest.mark.asyncio
async def test_generate_knowledge_genui_llm_custom():
    fake_llm = FakeLLM("<div class='custom-card'>Custom GenUI</div>")
    widget = await generate_knowledge_genui(
        llm=fake_llm,
        query="generate interactive genui visual dashboard for benefits",
        answer="Benefits include health and dental.",
        grounded_context="Benefits doc",
    )
    assert widget is not None
    assert widget["type"] == "genui_iframe"
    assert widget["ui_type"] == "custom"
    assert "Custom GenUI" in widget["html"]
