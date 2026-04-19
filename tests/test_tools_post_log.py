"""Tests for ``tools/_post_log.py`` — the per-(env, guild)
last-posted record that ``post_patch_notes`` writes after each
successful post and ``edit_patch_notes`` reads to know what to
edit by default. Files are isolated per ``db_env_var`` so a
LIVE post and a TEST post for the same guild can never
contaminate each other.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tools import _post_log


@pytest.fixture
def log_in_tmp(tmp_path: Path, monkeypatch):
    """Redirect the shared state-file directory (now in
    ``tools._common``) into ``tmp_path`` so tests don't touch
    the real ``.last_posted.*.json`` files."""
    from tools import _common
    monkeypatch.setattr(_common, "_STATE_DIR", tmp_path)
    return tmp_path


class TestRecordAndRead:
    def test_record_then_get_last_posted(self, log_in_tmp):
        _post_log.record_post(
            db_env_var="LIVE_DB_NAME", guild_id=1, channel_id=100, message_id=999,
        )
        entry = _post_log.get_last_posted("LIVE_DB_NAME", 1)
        assert entry is not None
        assert entry["channel_id"] == 100
        assert entry["message_id"] == 999
        assert "posted_at" in entry

    def test_get_last_posted_returns_none_for_unknown_guild(self, log_in_tmp):
        assert _post_log.get_last_posted("LIVE_DB_NAME", 42) is None

    def test_record_overwrites_prior_entry_for_same_env_guild_pair(self, log_in_tmp):
        """Only the most recent post per (env, guild) is editable
        via the default path."""
        _post_log.record_post("LIVE_DB_NAME", 1, 100, 111)
        _post_log.record_post("LIVE_DB_NAME", 1, 100, 222)
        entry = _post_log.get_last_posted("LIVE_DB_NAME", 1)
        assert entry["message_id"] == 222

    def test_records_for_different_envs_are_filesystem_isolated(self, log_in_tmp):
        """The whole point of per-env files: a TEST post and a
        LIVE post for the same guild get different message ids
        in different files; an edit invocation reading one env's
        file can't accidentally pick up the other's record."""
        _post_log.record_post("LIVE_DB_NAME", 1, 100, 111)
        _post_log.record_post("TEST_DB_NAME", 1, 200, 222)

        live = _post_log.get_last_posted("LIVE_DB_NAME", 1)
        test = _post_log.get_last_posted("TEST_DB_NAME", 1)

        assert live["message_id"] == 111
        assert live["channel_id"] == 100
        assert test["message_id"] == 222
        assert test["channel_id"] == 200
        # Two distinct files exist on disk.
        files = sorted(p.name for p in log_in_tmp.iterdir() if p.is_file())
        assert files == [
            ".last_posted.LIVE_DB_NAME.json",
            ".last_posted.TEST_DB_NAME.json",
        ]

    def test_get_all_last_posted_scopes_to_one_env(self, log_in_tmp):
        """The "all" iterator only walks the file matching the
        passed env var — by design, the iterator is per-env."""
        _post_log.record_post("LIVE_DB_NAME", 1, 100, 111)
        _post_log.record_post("LIVE_DB_NAME", 2, 100, 222)
        _post_log.record_post("TEST_DB_NAME", 99, 999, 333)

        live_all = _post_log.get_all_last_posted("LIVE_DB_NAME")
        assert set(live_all.keys()) == {"1", "2"}
        # TEST entry doesn't bleed into the LIVE iteration.
        assert "99" not in live_all

    def test_load_returns_empty_when_file_missing(self, log_in_tmp):
        assert _post_log.get_all_last_posted("LIVE_DB_NAME") == {}
        assert _post_log.get_last_posted("LIVE_DB_NAME", 1) is None

    def test_malformed_file_treated_as_empty(self, log_in_tmp):
        """Corrupted file shouldn't take down the post or edit
        flow — degrade to empty so the next post overwrites
        cleanly."""
        path = log_in_tmp / ".last_posted.LIVE_DB_NAME.json"
        path.write_text("{not json", encoding="utf-8")
        assert _post_log.get_all_last_posted("LIVE_DB_NAME") == {}

    def test_persisted_format_is_indented_json(self, log_in_tmp):
        """Human-readable on disk so an operator can poke at it
        without parsing."""
        _post_log.record_post("LIVE_DB_NAME", 1, 100, 111)
        path = log_in_tmp / ".last_posted.LIVE_DB_NAME.json"
        text = path.read_text(encoding="utf-8")
        assert "\n" in text
        parsed = json.loads(text)
        assert parsed["1"]["message_id"] == 111

    def test_path_uses_env_var_name_in_filename(self, log_in_tmp):
        """Filename schema is ``.last_posted.<env_var>.json`` —
        verify so a future rename in the shared
        ``state_file_path`` helper doesn't silently break the
        gitignore glob (``.last_posted.*.json``)."""
        from tools._common import state_file_path
        path = state_file_path("last_posted", "MY_VAR")
        assert path.name == ".last_posted.MY_VAR.json"
