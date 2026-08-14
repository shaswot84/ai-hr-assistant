from __future__ import annotations

import os
import re

#: Path to the `.env` file this repo reads/writes. Overridable via env var so
#: tests can point at a throwaway file instead of touching the real one —
#: never rely on the default in a test context.
DEFAULT_ENV_FILE_PATH = "/app/.env"

_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def _quote(value: str) -> str:
    """Encode a value for a single `.env` line, quoting when it needs it.

    Multi-line values (a manager can paste a multi-paragraph system prompt)
    can't appear as literal newlines in a single KEY=VALUE line, so they're
    escaped and quoted; simple values are written bare to keep the file
    readable for anyone opening it by hand.

    A literal `$` is always escaped to `$$` first. Docker Compose
    interpolates `$VAR`/`${VAR}` references inside `.env` file values on its
    own, independent of this app's own parsing below — a manager-editable
    prompt containing a real template placeholder like `$resume_text`
    (see evaluation/scoring.py's USER_PROMPT) would otherwise trip Compose's
    "variable not set" warning on every command. This app is unaffected
    either way, since it re-reads the raw file itself rather than the
    process environment Compose populates, but escaping keeps `.env` quiet.
    """
    value = value.replace("$", "$$")
    if value == "" or "\n" in value or '"' in value or value != value.strip():
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    return value


def _unquote(raw: str) -> str:
    """Reverse `_quote`: strip surrounding quotes, un-escape, and restore literal `$`."""
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        inner = raw[1:-1]
        value = inner.replace('\\n', "\n").replace('\\"', '"').replace("\\\\", "\\")
    else:
        value = raw
    return value.replace("$$", "$")


class EnvFileSettingRepo:
    """A key/value settings store backed by a live-read `.env` file.

    Every call re-reads the file from disk (like the DB-backed repo it
    replaced re-queried Postgres on every call) — no in-process caching, so
    a change made through the API is visible to the worker on its very next
    poll with no container restart needed. Only ever touches the specific
    key it's asked about; every other line (comments, unrelated secrets) is
    preserved byte-for-byte and in its original position.
    """

    def __init__(self, path: str | None = None) -> None:
        self._path = path or os.environ.get("SETTINGS_ENV_FILE_PATH", DEFAULT_ENV_FILE_PATH)

    def _read_lines(self) -> list[str]:
        try:
            with open(self._path, encoding="utf-8") as f:
                return f.read().splitlines()
        except FileNotFoundError:
            return []

    def _write_lines(self, lines: list[str]) -> None:
        """Write the file's full new content in place, flushed to disk before returning.

        A temp-file-plus-`os.replace` swap would normally be the safer,
        atomic way to do this, but `.env` is bind-mounted into the
        container as a single file — replacing that path's inode from
        inside the container fails with EBUSY, since the mount is tied to
        the specific inode Docker mounted, not the path. Writing in place
        (truncate + rewrite the same file) is the option that actually
        works through a single-file bind mount; the write is small and
        infrequent (a manager saving settings, not a hot loop), so the
        brief non-atomic window is an acceptable trade-off here.
        """
        with open(self._path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
            if lines:
                f.write("\n")
            f.flush()
            os.fsync(f.fileno())

    def get_value(self, key: str) -> str | None:
        """Return the stored value for `key`, or None if it's unset or only present commented-out."""
        for line in self._read_lines():
            match = _LINE_RE.match(line)
            if match and match.group(1) == key:
                return _unquote(match.group(2))
        return None

    def set_value(self, key: str, value: str) -> None:
        """Upsert `value` for `key`, replacing an existing active line or appending a new one."""
        lines = self._read_lines()
        encoded = f"{key}={_quote(value)}"
        for i, line in enumerate(lines):
            match = _LINE_RE.match(line)
            if match and match.group(1) == key:
                lines[i] = encoded
                self._write_lines(lines)
                return
        lines.append(encoded)
        self._write_lines(lines)

    def delete(self, key: str) -> None:
        """Remove the active line for `key` if present (restoring default behaviour)."""
        lines = self._read_lines()
        kept = [line for line in lines if not (_LINE_RE.match(line) and _LINE_RE.match(line).group(1) == key)]
        if len(kept) != len(lines):
            self._write_lines(kept)
