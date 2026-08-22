"""Unit tests for AG-UI GenUI generator."""

from __future__ import annotations

import pytest

from app.agents.knowledge_agent.genui import (
    build_calculator_genui,
    build_comparison_genui,
    build_procedure_genui,
    build_skeleton_genui,
    detect_genui_type,
    format_inline_markdown,
    generate_knowledge_genui,
    parse_markdown_table,
    should_generate_genui,
    split_title_and_body,
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

    # Double dashes cleanup
    res = format_inline_markdown("Annual Leave -- 20 days per year")
    assert "--" not in res
    assert "Annual Leave — 20 days per year" in res


def test_split_title_and_body():
    t1, b1 = split_title_and_body("**Sick Leave:** 10 days allowed per year")
    assert t1 == "Sick Leave"
    assert b1 == "10 days allowed per year"

    t2, b2 = split_title_and_body("Casual Leave: 5 days allowed")
    assert t2 == "Casual Leave"
    assert b2 == "5 days allowed"

    t3, b3 = split_title_and_body("Annual Leave -- 20 days")
    assert t3 == "Annual Leave"
    assert b3 == "20 days"


def test_parse_markdown_table():
    md = """
    | Policy | Entitlement | Carryover |
    |---|---|---|
    | Annual Leave | 20 days [1] | 5 days [2] |
    | Sick Leave | 12 days [3] | 0 days |
    """
    res = parse_markdown_table(md)
    assert res is not None
    headers, rows = res
    assert headers == ["Policy", "Entitlement", "Carryover"]
    assert len(rows) == 2
    assert rows[0][0] == "Annual Leave"


def test_should_generate_genui_keywords():
    assert should_generate_genui("compare sick leave and casual leave")
    assert should_generate_genui("calculate my overtime pay")
    assert should_generate_genui("how to apply for resignation checklist")
    assert should_generate_genui("visualize this as a genui widget")
    assert should_generate_genui("what is the policy?", "| Col 1 | Col 2 |\n|---|---|")
    assert not should_generate_genui("hello who are you?")


def test_detect_genui_type():
    assert detect_genui_type("calculate my leave carryover")[0] == "calculator"
    assert detect_genui_type("how to apply step by step checklist")[0] == "procedure"
    assert detect_genui_type("compare annual and sick leave")[0] == "comparison"
    assert detect_genui_type("visualize dashboard genui")[0] == "custom"


def test_build_skeleton_genui():
    calc_skel = build_skeleton_genui("calculator", "calculate carryover")
    assert "animate-pulse" in calc_skel
    assert "Calculating..." in calc_skel
    assert "ag_ui:resize" in calc_skel

    proc_skel = build_skeleton_genui("procedure", "steps to apply")
    assert "animate-pulse" in proc_skel
    assert "Structuring steps..." in proc_skel

    comp_skel = build_skeleton_genui("comparison", "compare policies")
    assert "animate-pulse" in comp_skel
    assert "Synthesizing matrix..." in comp_skel


def test_build_comparison_genui_with_table():
    table_answer = """
    | Policy | Entitlement | Carryover |
    |---|---|---|
    | Annual Leave | 20 days [1] | 5 days [2] |
    | Casual Leave | 10 days [3] | 0 days |
    """
    html_doc = build_comparison_genui("compare leave types", table_answer, "")
    assert "<table" in html_doc
    assert "<th" in html_doc
    assert "Annual Leave" in html_doc
    assert "divide-y" in html_doc


def test_build_comparison_genui_with_bullets():
    bullet_answer = "- **Sick Leave:** 10 days [1]\n- **Casual Leave:** 5 days [2]"
    html_doc = build_comparison_genui("compare sick and casual leave", bullet_answer, "")
    assert "Policy Comparison Matrix" in html_doc
    assert "Sick Leave" in html_doc
    assert "Casual Leave" in html_doc
    assert "**" not in html_doc


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
    assert "Fill out" in html_doc
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
    assert widget["status"] == "ready"
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
    assert widget["status"] == "ready"
    assert "Custom GenUI" in widget["html"]
