from __future__ import annotations

from pathlib import Path

import pytest

from app.repositories.env_settings import EnvFileSettingRepo


@pytest.fixture()
def env_file(tmp_path: Path) -> Path:
    path = tmp_path / "test.env"
    path.write_text(
        "# a comment\n"
        "\n"
        "POSTGRES_PASSWORD=super-secret\n"
        "OLLAMA_CHAT_API_BASE=https://ollama.com\n"
        "OLLAMA_CHAT_MODEL=gpt-oss:120b-cloud\n"
        "# OLLAMA_CHAT_API_KEY=commented-out-example\n"
    )
    return path


def test_get_value_reads_existing_key(env_file):
    repo = EnvFileSettingRepo(str(env_file))
    assert repo.get_value("OLLAMA_CHAT_API_BASE") == "https://ollama.com"


def test_get_value_returns_none_for_missing_key(env_file):
    repo = EnvFileSettingRepo(str(env_file))
    assert repo.get_value("NOT_A_KEY") is None


def test_get_value_ignores_commented_out_lines(env_file):
    """A commented-out example (e.g. `# OLLAMA_CHAT_API_KEY=...`) must not
    be read back as if it were the active value.
    """
    repo = EnvFileSettingRepo(str(env_file))
    assert repo.get_value("OLLAMA_CHAT_API_KEY") is None


def test_set_value_replaces_existing_line_in_place(env_file):
    repo = EnvFileSettingRepo(str(env_file))
    repo.set_value("OLLAMA_CHAT_MODEL", "new-model")
    assert repo.get_value("OLLAMA_CHAT_MODEL") == "new-model"
    # the line count and other keys are untouched
    lines = env_file.read_text().splitlines()
    assert sum(1 for line in lines if line.startswith("OLLAMA_CHAT_MODEL=")) == 1


def test_set_value_never_touches_unrelated_keys(env_file):
    repo = EnvFileSettingRepo(str(env_file))
    repo.set_value("OLLAMA_CHAT_MODEL", "new-model")
    assert repo.get_value("POSTGRES_PASSWORD") == "super-secret"
    assert "# a comment" in env_file.read_text()


def test_set_value_appends_new_key_at_end(env_file):
    repo = EnvFileSettingRepo(str(env_file))
    repo.set_value("BRAND_NEW_KEY", "value")
    assert repo.get_value("BRAND_NEW_KEY") == "value"
    # original keys still intact
    assert repo.get_value("OLLAMA_CHAT_API_BASE") == "https://ollama.com"


def test_set_value_quotes_and_escapes_multiline_values(env_file):
    repo = EnvFileSettingRepo(str(env_file))
    multiline = 'Line one.\nLine two with a "quote".'
    repo.set_value("RESUME_REVIEW_SYSTEM_PROMPT", multiline)
    assert repo.get_value("RESUME_REVIEW_SYSTEM_PROMPT") == multiline
    # stored as a single physical line in the file
    lines = env_file.read_text().splitlines()
    matching = [line for line in lines if line.startswith("RESUME_REVIEW_SYSTEM_PROMPT=")]
    assert len(matching) == 1


def test_set_value_escapes_literal_dollar_signs(env_file):
    """Manager-editable prompts can contain real `string.Template`
    placeholders like `$resume_text` (see evaluation/scoring.py's
    USER_PROMPT) — those must round-trip exactly, and must not appear
    unescaped in the file, since Docker Compose interpolates `$VAR`/`${VAR}`
    references inside `.env` values on its own, independent of this repo's
    parsing, and would otherwise warn/blank on an unset "resume_text" var.
    """
    value_with_placeholders = "Task: $job_title\n\n$resume_text"
    repo = EnvFileSettingRepo(str(env_file))
    repo.set_value("RESUME_REVIEW_USER_PROMPT", value_with_placeholders)
    assert repo.get_value("RESUME_REVIEW_USER_PROMPT") == value_with_placeholders

    raw_line = next(
        line for line in env_file.read_text().splitlines() if line.startswith("RESUME_REVIEW_USER_PROMPT=")
    )
    # every $ is doubled — Compose reads $$ as a literal, escaped $ and
    # won't try to interpolate it as a variable reference
    assert raw_line == 'RESUME_REVIEW_USER_PROMPT="Task: $$job_title\\n\\n$$resume_text"'


def test_set_value_dollar_sign_round_trips_without_other_special_chars(env_file):
    """A short, single-line value containing `$` (no newline/quote/padding)
    would otherwise be written bare — confirm it's still escaped even
    outside the quoted-multiline branch.
    """
    repo = EnvFileSettingRepo(str(env_file))
    repo.set_value("SOME_KEY", "$HOME/path")
    assert repo.get_value("SOME_KEY") == "$HOME/path"
    raw_line = next(line for line in env_file.read_text().splitlines() if line.startswith("SOME_KEY="))
    assert raw_line == "SOME_KEY=$$HOME/path"


def test_set_value_empty_string_round_trips(env_file):
    repo = EnvFileSettingRepo(str(env_file))
    repo.set_value("OLLAMA_CHAT_API_KEY", "")
    assert repo.get_value("OLLAMA_CHAT_API_KEY") == ""


def test_delete_removes_the_line(env_file):
    repo = EnvFileSettingRepo(str(env_file))
    repo.delete("OLLAMA_CHAT_MODEL")
    assert repo.get_value("OLLAMA_CHAT_MODEL") is None
    assert repo.get_value("OLLAMA_CHAT_API_BASE") == "https://ollama.com"


def test_delete_is_a_noop_for_missing_key(env_file):
    repo = EnvFileSettingRepo(str(env_file))
    repo.delete("NOT_A_KEY")  # must not raise
    assert repo.get_value("OLLAMA_CHAT_API_BASE") == "https://ollama.com"


def test_get_value_on_nonexistent_file_returns_none():
    repo = EnvFileSettingRepo("/tmp/definitely-does-not-exist-12345.env")
    assert repo.get_value("ANYTHING") is None


def test_set_value_creates_file_if_missing(tmp_path):
    path = tmp_path / "new.env"
    assert not path.exists()
    repo = EnvFileSettingRepo(str(path))
    repo.set_value("KEY", "value")
    assert path.exists()
    assert repo.get_value("KEY") == "value"


def test_reads_are_always_fresh_from_disk(env_file):
    """No caching — a change made by one repo instance is visible to another
    reading the same path, matching how the worker and API share state.
    """
    writer = EnvFileSettingRepo(str(env_file))
    reader = EnvFileSettingRepo(str(env_file))
    assert reader.get_value("OLLAMA_CHAT_MODEL") == "gpt-oss:120b-cloud"
    writer.set_value("OLLAMA_CHAT_MODEL", "changed-model")
    assert reader.get_value("OLLAMA_CHAT_MODEL") == "changed-model"


def test_default_path_reads_from_settings_env_file_path_env_var(monkeypatch, tmp_path):
    path = tmp_path / "via_env_var.env"
    path.write_text("SOME_KEY=some-value\n")
    monkeypatch.setenv("SETTINGS_ENV_FILE_PATH", str(path))
    repo = EnvFileSettingRepo()
    assert repo.get_value("SOME_KEY") == "some-value"
