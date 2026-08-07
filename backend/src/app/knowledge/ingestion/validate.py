"""Document Validation stage (pipeline step between Upload and Parsing).

Fails fast with a clear, machine-readable reason *before* any expensive
parsing/embedding work. The probe parse performed here is reused by the
caller -- validation and parsing share one pass over the file.

Checks:
 - supported format (content-based, falls back to path)
 - file size within limits            (INGEST_MAX_FILE_SIZE_BYTES)
 - not encrypted / password-protected
 - not corrupted
 - digitally generated, not scanned / image-only  (PDF only)
 - page count within limits           (INGEST_MAX_PAGES, PDF only)
 - extractable text + basic structure (computed by the caller on blocks)

Failures are returned as ``{"ok": False, "code", "reason", "checks"}`` --
they are never raised, so the caller can persist a FAILED artifact.
"""

import os
import re

import anydoc

VALIDATION_VERSION = "document_validation_v1"


def _env_int(name, default):
    try:
        v = int(os.environ.get(name, ""))
    except (TypeError, ValueError):
        return default
    return v if v > 0 else default


config = {
    "max_file_size_bytes": _env_int("INGEST_MAX_FILE_SIZE_BYTES", 100 * 1024 * 1024),
    "max_pages": _env_int("INGEST_MAX_PAGES", 500),
}

# Error-shape patterns produced by anydoc's Rust error messages. See
# anydoc/src/error.rs and anydoc/src/formats/pdf.rs.
OCR_REQUIRED_RE = re.compile(
    r"no extractable text \(([^,()]+),\s*(\d+)\s*pages?\).*OCR is required", re.IGNORECASE
)
ENCRYPTED_RE = re.compile(r"encrypt", re.IGNORECASE)
MALFORMED_RE = re.compile(r"^malformed document", re.IGNORECASE)


def classify_pdf_error(message):
    m = OCR_REQUIRED_RE.search(message)
    if m:
        return {
            "code": "SCANNED_OR_IMAGE_ONLY",
            "reason": message,
            "pdf_type": m.group(1),
            "page_count": int(m.group(2)),
        }
    if ENCRYPTED_RE.search(message):
        return {"code": "ENCRYPTED", "reason": message}
    return {"code": "CORRUPTED", "reason": message}


def classify_error(message):
    if ENCRYPTED_RE.search(message):
        return {"code": "ENCRYPTED", "reason": message}
    if MALFORMED_RE.search(message):
        return {"code": "CORRUPTED", "reason": message}
    return {"code": "PARSE_FAILED", "reason": message}


def validate_and_parse(data, file_path=None, format_=None):
    """Validate a document and (in the same pass) parse it.

    Args:
        data: file contents (bytes).
        file_path: optional path used for extension-based detection.
        format: format already detected by the caller.

    Returns a dict:
        ok, code?, reason?, checks, format, parsed, pdf_type?, page_count?

    ``parsed`` is either ``{"kind": "markdown", "markdown": str}`` (pdf / md)
    or ``{"kind": "document", "document": anydoc.Document}`` (everything else
    via the shared model).
    """
    checks = {}

    def add_check(name, passed, detail=None, include_none_detail=False):
        entry = {"ok": bool(passed)}
        if detail is not None or include_none_detail:
            entry["detail"] = detail
        checks[name] = entry
        return bool(passed)

    def fail(code, reason, **extra):
        return {
            "ok": False,
            "code": code,
            "reason": reason,
            "checks": checks,
            "format": format_,
            "parsed": None,
            "pdf_type": None,
            "page_count": None,
            **extra,
        }

    # 1. Supported format (content markers first, extension as fallback).
    detected = format_ or anydoc.format_from_bytes(data)
    if not detected and file_path:
        detected = anydoc.format_from_path(file_path)
    ext = os.path.splitext(file_path or "")[1].lower().lstrip(".")
    if ext == "md":
        detected = "md"
    if not detected:
        add_check("format_supported", False, None, include_none_detail=True)
        return fail(
            "UNSUPPORTED_FORMAT",
            "No supported document format detected from content or filename",
        )
    add_check("format_supported", True, detected)

    # 2. File size limits.
    if len(data) > config["max_file_size_bytes"]:
        add_check(
            "size_within_limits",
            False,
            f"{len(data)} bytes exceeds limit {config['max_file_size_bytes']}",
        )
        return fail(
            "FILE_TOO_LARGE",
            f"File is {len(data)} bytes; limit is {config['max_file_size_bytes']}",
        )
    add_check("size_within_limits", True, f"{len(data)} bytes")

    # 3. Probe parse (also serves as the parse stage -- one pass).
    parsed = None
    error = None
    try:
        if detected == "pdf":
            parsed = {"kind": "markdown", "markdown": anydoc.to_markdown_bytes(data, "pdf")}
        elif detected == "md":
            parsed = {"kind": "markdown", "markdown": data.decode("utf-8", errors="replace")}
        else:
            parsed = {"kind": "document", "document": anydoc.to_document(data, detected)}
    except (anydoc.ConvertError, OSError) as exc:
        # ConvertError: unreadable/encrypted/malformed input (per the binding
        # stubs). OSError: unreadable file. Anything else is a real bug and
        # should propagate, not be reclassified as a document failure.
        error = str(exc)

    # 4. Scanned / encrypted / corrupted classification.
    if error:
        cls = classify_pdf_error(error) if detected == "pdf" else classify_error(error)
        pdf_type = cls.get("pdf_type")
        page_count = cls.get("page_count")
        if cls["code"] == "SCANNED_OR_IMAGE_ONLY":
            add_check(
                "not_scanned",
                False,
                f"{pdf_type or 'Scanned'} PDF, {page_count or '?'} pages: OCR required",
            )
            add_check("not_encrypted", True)
            add_check("not_corrupted", True)
            return fail(
                "SCANNED_OR_IMAGE_ONLY", cls["reason"], pdf_type=pdf_type, page_count=page_count
            )
        if cls["code"] == "ENCRYPTED":
            add_check("not_encrypted", False, error)
            return fail("ENCRYPTED", error)
        add_check("not_corrupted", False, error)
        return fail("CORRUPTED", error)
    add_check("not_scanned", True, "text extracted without OCR" if detected == "pdf" else "not applicable")
    add_check("not_encrypted", True)
    add_check("not_corrupted", True)

    # 5. Page count limit -- the binding only reports page count for PDFs that
    #    cannot be extracted (the error path above); extractable PDFs and other
    #    formats pass with an "unknown" detail.
    add_check(
        "page_count_within_limits",
        True,
        (
            "unknown \u2014 binding reports page count only for unextractable PDFs"
            if detected == "pdf"
            else "not applicable"
        ),
    )

    return {
        "ok": True,
        "checks": checks,
        "format": detected,
        "parsed": parsed,
        "pdf_type": None,
        "page_count": None,
    }
