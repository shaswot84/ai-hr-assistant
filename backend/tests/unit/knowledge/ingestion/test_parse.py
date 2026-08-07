"""Ported tests for the pipeline orchestrator (ingestion engine):
parse_file, version diffing, CLI — plus the in-memory ``build_normalized``
seam the worker consumes.
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

from app.knowledge.ingestion.parse import (
    ChunkingError,
    IngestionFailed,
    build_normalized,
    diff_versions,
    main,
    parse_file,
)

ROOT = Path(__file__).resolve().parents[1]  # backend/tests/unit/knowledge
FAQ = str(ROOT / "ingestion" / "fixtures" / "07_HR_FAQ.md")


def _hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def test_diff_versions():
    prev = [
        {"chunk_index": 0, "content_hash_sha256": _hash("a"), "section_path": ["S"], "parent_section": "S"},
        {"chunk_index": 1, "content_hash_sha256": _hash("b"), "section_path": ["S"], "parent_section": "S"},
    ]
    new = [
        {"chunk_index": 0, "content_hash_sha256": _hash("a"), "section_path": ["S"], "parent_section": "S"},
        {"chunk_index": 1, "content_hash_sha256": _hash("changed"), "section_path": ["S"], "parent_section": "S"},
        {"chunk_index": 2, "content_hash_sha256": _hash("c"), "section_path": ["S"], "parent_section": "S"},
    ]
    stats, removed = diff_versions(prev, new)
    assert stats == {"unchanged": 1, "changed": 1, "added": 1, "removed": 1}
    assert [c["change"] for c in new] == ["unchanged", "changed", "added"]
    assert len(removed) == 1
    assert removed[0]["content_hash_sha256"] == _hash("b")


def test_parse_file_markdown(tmp_path, capsys):
    parse_file(FAQ, str(tmp_path))
    out = tmp_path / "07_HR_FAQ.json"
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema"] == "normalized_document_v2"
    assert data["metadata"]["status"] == "NORMALIZED"
    assert data["metadata"]["pipeline_version"] == "structure_aware_v3"
    assert data["metadata"]["format"] == "md"
    assert data["chunks"], "md doc should produce chunks"
    assert data["structure"]["heading_hierarchy"]
    assert data["content"]["block_counts"]["heading"] == 4
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[0])
    assert summary["status"] == "NORMALIZED"
    assert summary["chunks"] == len(data["chunks"])


def test_parse_file_unsupported(tmp_path):
    bad = tmp_path / "x.xyz"
    bad.write_bytes(b"\x00\x01\x02 not a document")
    with pytest.raises(IngestionFailed) as ei:
        parse_file(str(bad), str(tmp_path))
    assert ei.value.code == "UNSUPPORTED_FORMAT"
    artifact = json.loads((tmp_path / "x.json").read_text(encoding="utf-8"))
    assert artifact["metadata"]["status"] == "FAILED"
    assert artifact["chunks"] == []


def test_parse_file_previous_diff(tmp_path):
    parse_file(FAQ, str(tmp_path))
    first = tmp_path / "07_HR_FAQ.json"
    main([FAQ, str(tmp_path), "--previous", str(first)])
    data = json.loads((tmp_path / "07_HR_FAQ.json").read_text(encoding="utf-8"))
    assert data["version_diff"] is not None
    assert data["version_diff"]["strategy"] == "chunk_hash_v1"
    # Diff keys on embeddable (leaf) chunks, not the full hierarchy rows.
    leaves = [c for c in data["chunks"] if c.get("embeddable")]
    assert data["version_diff"]["stats"]["unchanged"] == len(leaves)
    assert data["version_diff"]["stats"]["added"] == 0


def test_main_cli_success(tmp_path):
    rc = main([FAQ, str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "07_HR_FAQ.json").exists()


def test_main_cli_sys_argv_path(tmp_path, monkeypatch):
    """Regression: the real entry path (sys.argv, script name included)
    must behave the same as calling main() with an explicit argv list."""
    monkeypatch.setattr(sys, "argv", ["parse.py", FAQ, str(tmp_path)])
    assert main() == 0
    assert (tmp_path / "07_HR_FAQ.json").exists()


def test_main_cli_missing_args():
    with pytest.raises(SystemExit):
        main([FAQ])  # argparse requires <file> <out_dir>


# ---------------------------------------------------------------------------
# In-memory seam (worker path) -- additions on top of the ported suite
# ---------------------------------------------------------------------------

def test_build_normalized_in_memory():
    data = Path(FAQ).read_bytes()
    norm = build_normalized(data, filename="07_HR_FAQ.md", file_path=FAQ)
    assert norm["schema"] == "normalized_document_v2"
    assert norm["metadata"]["status"] == "NORMALIZED"
    assert norm["metadata"]["content_hash_sha256"] == hashlib.sha256(data).hexdigest()
    assert norm["chunks"] and any(c.get("embeddable") for c in norm["chunks"])


def test_build_normalized_rejects_unsupported():
    with pytest.raises(IngestionFailed) as ei:
        build_normalized(b"\x00\x01\x02 garbage", filename="x.xyz", file_path="x.xyz")
    assert ei.value.code == "UNSUPPORTED_FORMAT"
    assert ei.value.checks  # validation checks ride along for the FAILED record


def test_build_normalized_empty_text_fails(tmp_path):
    p = tmp_path / "empty.md"
    p.write_text("   \n\n  ", encoding="utf-8")
    with pytest.raises(IngestionFailed) as ei:
        build_normalized(p.read_bytes(), filename="empty.md", file_path=str(p))
    assert ei.value.code == "NO_EXTRACTABLE_TEXT"


def test_build_normalized_previous_diff_in_memory():
    data = Path(FAQ).read_bytes()
    first = build_normalized(data, filename="07_HR_FAQ.md", file_path=FAQ)
    second = build_normalized(
        data, filename="07_HR_FAQ.md", file_path=FAQ, previous_artifact=first
    )
    assert second["version_diff"] is not None
    leaves = [c for c in second["chunks"] if c.get("embeddable")]
    assert second["version_diff"]["stats"]["unchanged"] == len(leaves)


def test_chunking_error_is_classified():
    assert issubclass(ChunkingError, IngestionFailed)
