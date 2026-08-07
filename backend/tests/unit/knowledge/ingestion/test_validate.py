"""Ported tests for the Document Validation stage (ingestion engine).

Kept 1:1 with ``ingestion_pipeline/tests/test_validate.py`` — they encode the
validation contract (supported-format / size / scanned / encrypted / corrupted
classification) that the worker relies on.
"""

from app.knowledge.ingestion import validate
from app.knowledge.ingestion.validate import (
    classify_error,
    classify_pdf_error,
    validate_and_parse,
)


def test_classify_pdf_error_scanned():
    cls = classify_pdf_error("no extractable text (Scanned PDF, 12 pages). OCR is required.")
    assert cls["code"] == "SCANNED_OR_IMAGE_ONLY"
    assert cls["pdf_type"] == "Scanned PDF"
    assert cls["page_count"] == 12


def test_classify_pdf_error_encrypted():
    cls = classify_pdf_error("document is encrypted")
    assert cls["code"] == "ENCRYPTED"


def test_classify_error_codes():
    assert classify_error("file is encrypted")["code"] == "ENCRYPTED"
    assert classify_error("malformed document: bad zip")["code"] == "CORRUPTED"
    assert classify_error("boom")["code"] == "PARSE_FAILED"


def test_markdown_passthrough(tmp_path):
    p = tmp_path / "faq.md"
    p.write_text("# FAQ\n\nHello.\n", encoding="utf-8")
    res = validate_and_parse(p.read_bytes(), file_path=str(p))
    assert res["ok"] is True
    assert res["format"] == "md"
    assert res["parsed"]["kind"] == "markdown"
    assert res["checks"]["format_supported"]["detail"] == "md"


def test_unsupported_format(tmp_path):
    p = tmp_path / "data.xyz"
    p.write_bytes(b"\x00\x01\x02 garbage")
    res = validate_and_parse(p.read_bytes(), file_path=str(p))
    assert res["ok"] is False
    assert res["code"] == "UNSUPPORTED_FORMAT"


def test_file_too_large(tmp_path, monkeypatch):
    monkeypatch.setitem(validate.config, "max_file_size_bytes", 10)
    p = tmp_path / "big.md"
    p.write_text("x" * 100, encoding="utf-8")
    res = validate_and_parse(p.read_bytes(), file_path=str(p))
    assert res["ok"] is False
    assert res["code"] == "FILE_TOO_LARGE"


def test_checks_recorded_on_success(tmp_path):
    p = tmp_path / "ok.md"
    p.write_text("hello", encoding="utf-8")
    res = validate_and_parse(p.read_bytes(), file_path=str(p))
    for name, entry in res["checks"].items():
        assert entry["ok"] is True, name
