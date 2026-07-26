"""Comprehensive pytest suite for jira-cli with coverage target >= 80%."""

import json
import os
import sys
from unittest.mock import ANY, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# -------------------------------------------------------------------
# Config & encryption
# -------------------------------------------------------------------


class TestConfigEncryption:
    """Encryption round-trip and edge cases."""

    def test_encrypt_decrypt_roundtrip(self):
        from jira_cli.config import encrypt_password, decrypt_password

        plain = "my-s3cret!@#$"
        encrypted = encrypt_password(plain)
        assert encrypted != plain
        assert isinstance(encrypted, str)
        assert decrypt_password(encrypted) == plain

    def test_decrypt_empty(self):
        from jira_cli.config import decrypt_password
        assert decrypt_password("") == ""

    def test_encrypt_empty(self):
        from jira_cli.config import encrypt_password
        assert encrypt_password("") == ""

    def test_encrypt_decrypt_unicode(self):
        from jira_cli.config import encrypt_password, decrypt_password
        plain = "héllo wörld \U0001f510"
        assert decrypt_password(encrypt_password(plain)) == plain

    def test_key_file_created(self, monkeypatch, tmp_path):
        from jira_cli.config import encrypt_password

        config_dir = tmp_path / "jira-cli"
        monkeypatch.setattr("jira_cli.config.CONFIG_DIR", str(config_dir))
        monkeypatch.setattr("jira_cli.config.KEY_PATH", str(config_dir / "secret.key"))
        monkeypatch.setattr("jira_cli.config.CONFIG_PATH", str(config_dir / "config.json"))

        assert not os.path.exists(str(config_dir / "secret.key"))
        encrypt_password("test")
        assert os.path.exists(str(config_dir / "secret.key"))
        with open(str(config_dir / "secret.key"), "rb") as f:
            key = f.read()
        assert len(key) > 0

    def test_encrypt_wrong_key_fails(self, monkeypatch, tmp_path):
        from jira_cli.config import encrypt_password, decrypt_password
        from cryptography.fernet import Fernet

        config_dir = tmp_path / "jira-cli-2"
        monkeypatch.setattr("jira_cli.config.CONFIG_DIR", str(config_dir))
        monkeypatch.setattr("jira_cli.config.KEY_PATH", str(config_dir / "secret.key"))
        monkeypatch.setattr("jira_cli.config.CONFIG_PATH", str(config_dir / "config.json"))

        ct = encrypt_password("secret")
        new_key = Fernet.generate_key()
        with open(str(config_dir / "secret.key"), "wb") as f:
            f.write(new_key)

        with pytest.raises(Exception):
            decrypt_password(ct)


class TestConfigLoadSave:
    """Config file read/write with encrypted password."""

    def test_save_and_load(self, monkeypatch, tmp_path):
        from jira_cli.config import save_config, load_config

        config_dir = tmp_path / "jira-cli-cfg"
        monkeypatch.setattr("jira_cli.config.CONFIG_DIR", str(config_dir))
        monkeypatch.setattr("jira_cli.config.CONFIG_PATH", str(config_dir / "config.json"))
        monkeypatch.setattr("jira_cli.config.KEY_PATH", str(config_dir / "secret.key"))
        monkeypatch.setattr("jira_cli.config._OLD_CONFIG_PATH", str(tmp_path / ".jira-cli.json"))

        save_config("https://jira.example.com", "alice", "p@ss")
        assert os.path.exists(str(config_dir / "config.json"))

        cfg = load_config()
        assert cfg["url"] == "https://jira.example.com"
        assert cfg["user"] == "alice"
        assert cfg["pass"] == "p@ss"

    def test_load_config_no_file(self, monkeypatch, tmp_path):
        from jira_cli.config import load_config

        config_dir = tmp_path / "jira-cli-none"
        monkeypatch.setattr("jira_cli.config.CONFIG_DIR", str(config_dir))
        monkeypatch.setattr("jira_cli.config.CONFIG_PATH", str(config_dir / "config.json"))
        monkeypatch.setattr("jira_cli.config.KEY_PATH", str(config_dir / "secret.key"))
        monkeypatch.setattr("jira_cli.config._OLD_CONFIG_PATH", str(tmp_path / ".jira-cli.json"))

        cfg = load_config()
        assert cfg == {"url": None, "user": None, "pass": None}

    def test_env_vars_override_file(self, monkeypatch, tmp_path):
        from jira_cli.config import save_config, load_config

        config_dir = tmp_path / "jira-cli-env"
        monkeypatch.setattr("jira_cli.config.CONFIG_DIR", str(config_dir))
        monkeypatch.setattr("jira_cli.config.CONFIG_PATH", str(config_dir / "config.json"))
        monkeypatch.setattr("jira_cli.config.KEY_PATH", str(config_dir / "secret.key"))
        monkeypatch.setattr("jira_cli.config._OLD_CONFIG_PATH", str(tmp_path / ".jira-cli.json"))
        monkeypatch.setenv("JIRA_URL", "https://env-override.example.com")
        monkeypatch.setenv("JIRA_USER", "envuser")
        monkeypatch.setenv("JIRA_PASS", "envpass")

        save_config("https://file.example.com", "fileuser", "filepass")

        cfg = load_config()
        assert cfg["url"] == "https://env-override.example.com"
        assert cfg["user"] == "envuser"
        assert cfg["pass"] == "envpass"

    def test_env_partial_override(self, monkeypatch, tmp_path):
        from jira_cli.config import save_config, load_config

        config_dir = tmp_path / "jira-cli-part"
        monkeypatch.setattr("jira_cli.config.CONFIG_DIR", str(config_dir))
        monkeypatch.setattr("jira_cli.config.CONFIG_PATH", str(config_dir / "config.json"))
        monkeypatch.setattr("jira_cli.config.KEY_PATH", str(config_dir / "secret.key"))
        monkeypatch.setattr("jira_cli.config._OLD_CONFIG_PATH", str(tmp_path / ".jira-cli.json"))
        monkeypatch.setenv("JIRA_URL", "https://partial.example.com")

        save_config("https://file.example.com", "fileuser", "filepass")

        cfg = load_config()
        assert cfg["url"] == "https://partial.example.com"
        assert cfg["user"] == "fileuser"
        assert cfg["pass"] == "filepass"

    def test_url_strips_trailing_slash(self, monkeypatch, tmp_path):
        from jira_cli.config import save_config, load_config

        config_dir = tmp_path / "jira-cli-slash"
        monkeypatch.setattr("jira_cli.config.CONFIG_DIR", str(config_dir))
        monkeypatch.setattr("jira_cli.config.CONFIG_PATH", str(config_dir / "config.json"))
        monkeypatch.setattr("jira_cli.config.KEY_PATH", str(config_dir / "secret.key"))
        monkeypatch.setattr("jira_cli.config._OLD_CONFIG_PATH", str(tmp_path / ".jira-cli.json"))

        save_config("https://jira.example.com/", "alice", "p@ss")
        cfg = load_config()
        assert cfg["url"] == "https://jira.example.com"


class TestConfigMigration:
    """Migration from old ~/.jira-cli.json to new location."""

    def test_migration_from_old_path(self, monkeypatch, tmp_path):
        from jira_cli.config import load_config

        config_dir = tmp_path / "jira-cli-migrate"
        old_path = str(tmp_path / ".jira-cli.json")
        new_path = str(config_dir / "config.json")
        key_path = str(config_dir / "secret.key")

        monkeypatch.setattr("jira_cli.config.CONFIG_DIR", str(config_dir))
        monkeypatch.setattr("jira_cli.config.CONFIG_PATH", new_path)
        monkeypatch.setattr("jira_cli.config.KEY_PATH", key_path)
        monkeypatch.setattr("jira_cli.config._OLD_CONFIG_PATH", old_path)

        with open(old_path, "w") as f:
            json.dump({"url": "https://old.example.com", "user": "olduser", "pass": "oldpass"}, f)

        cfg = load_config()
        assert cfg["url"] == "https://old.example.com"
        assert cfg["user"] == "olduser"
        assert cfg["pass"] == "oldpass"
        assert not os.path.exists(old_path)
        assert os.path.exists(new_path)
        with open(new_path) as f:
            new_cfg = json.load(f)
        assert new_cfg["url"] == "https://old.example.com"
        assert new_cfg["user"] == "olduser"
        assert new_cfg["pass_encrypted"] != "oldpass"
        assert new_cfg["pass"] == ""

    def test_no_migration_if_new_exists(self, monkeypatch, tmp_path):
        from jira_cli.config import save_config, load_config

        config_dir = tmp_path / "jira-cli-nomig"
        old_path = str(tmp_path / ".jira-cli.json")
        new_path = str(config_dir / "config.json")
        key_path = str(config_dir / "secret.key")

        monkeypatch.setattr("jira_cli.config.CONFIG_DIR", str(config_dir))
        monkeypatch.setattr("jira_cli.config.CONFIG_PATH", new_path)
        monkeypatch.setattr("jira_cli.config.KEY_PATH", key_path)
        monkeypatch.setattr("jira_cli.config._OLD_CONFIG_PATH", old_path)

        with open(old_path, "w") as f:
            json.dump({"url": "https://old.example.com", "user": "olduser", "pass": "oldpass"}, f)

        save_config("https://new.example.com", "newuser", "newpass")

        cfg = load_config()
        assert cfg["url"] == "https://new.example.com"
        assert os.path.exists(old_path)

    def test_migration_corrupt_old_ignored(self, monkeypatch, tmp_path):
        from jira_cli.config import load_config

        config_dir = tmp_path / "jira-cli-corrupt"
        old_path = str(tmp_path / ".jira-cli.json")
        new_path = str(config_dir / "config.json")
        key_path = str(config_dir / "secret.key")

        monkeypatch.setattr("jira_cli.config.CONFIG_DIR", str(config_dir))
        monkeypatch.setattr("jira_cli.config.CONFIG_PATH", new_path)
        monkeypatch.setattr("jira_cli.config.KEY_PATH", key_path)
        monkeypatch.setattr("jira_cli.config._OLD_CONFIG_PATH", old_path)

        with open(old_path, "w") as f:
            f.write("not-json")

        cfg = load_config()
        assert cfg == {"url": None, "user": None, "pass": None}


# -------------------------------------------------------------------
# HTTP helpers
# -------------------------------------------------------------------


class TestHttpHelpers:
    """HTTP helper functions exist and work correctly."""

    def test_auth_header(self):
        from jira_cli.http import auth_header
        import base64

        cfg = {"user": "alice", "pass": "p@ss"}
        hdr = auth_header(cfg)
        expected = base64.b64encode(b"alice:p@ss").decode()
        assert hdr == {"Authorization": f"Basic {expected}"}

    def test_jira_put_exists(self):
        from jira_cli.http import jira_put
        assert callable(jira_put)

    def test_jira_delete_exists(self):
        from jira_cli.http import jira_delete
        assert callable(jira_delete)

    def test_jira_get_exists(self):
        from jira_cli.http import jira_get
        assert callable(jira_get)

    def test_jira_post_exists(self):
        from jira_cli.http import jira_post
        assert callable(jira_post)


# -------------------------------------------------------------------
# Format / ADF helpers
# -------------------------------------------------------------------


class TestFormat:
    """Formatting and ADF construction."""

    def test_build_adf_doc_single_line(self):
        from jira_cli.format import _build_adf_doc

        doc = _build_adf_doc("Hello world")
        assert doc["type"] == "doc"
        assert doc["version"] == 1
        assert len(doc["content"]) == 1
        assert doc["content"][0]["content"][0]["text"] == "Hello world"

    def test_build_adf_doc_multi_line(self):
        from jira_cli.format import _build_adf_doc

        doc = _build_adf_doc("Line 1\nLine 2\nLine 3")
        assert len(doc["content"]) == 3
        assert doc["content"][0]["content"][0]["text"] == "Line 1"
        assert doc["content"][1]["content"][0]["text"] == "Line 2"
        assert doc["content"][2]["content"][0]["text"] == "Line 3"

    def test_build_adf_doc_empty(self):
        from jira_cli.format import _build_adf_doc

        doc = _build_adf_doc("")
        assert doc["content"] == []

    def test_extract_adf_text_string_input(self):
        from jira_cli.format import extract_adf_text
        assert extract_adf_text("plain string") == "plain string"

    def test_extract_adf_text_empty(self):
        from jira_cli.format import extract_adf_text
        assert extract_adf_text("") == ""

    def test_extract_adf_text_none(self):
        from jira_cli.format import extract_adf_text
        assert extract_adf_text(None) == ""

    def test_extract_adf_text_complex(self):
        from jira_cli.format import extract_adf_text

        adf = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"text": "Hello", "type": "text"}]},
                {"type": "paragraph", "content": [{"text": "World", "type": "text"}]},
            ],
        }
        assert extract_adf_text(adf) == "Hello\nWorld"

    def test_extract_adf_text_nested_inline(self):
        from jira_cli.format import extract_adf_text

        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"text": "Bold ", "type": "text"},
                        {"text": "and ", "type": "text"},
                        {"text": "more", "type": "text"},
                    ],
                }
            ],
        }
        result = extract_adf_text(adf)
        assert "Bold" in result
        assert "and" in result
        assert "more" in result

    def test_truncate(self):
        from jira_cli.format import truncate
        assert truncate("short") == "short"
        long = "hello world " * 50
        t = truncate(long, 30)
        assert len(t) < len(long)
        assert t.endswith("\u2026")

    def test_status_badge(self):
        from jira_cli.format import status_badge
        assert "\033[38;5;196m" in status_badge("Blocked")
        assert "\033[38;5;76m" in status_badge("Done")


# -------------------------------------------------------------------
# Commands
# -------------------------------------------------------------------


class TestCommandsUpdateDescription:
    def test_updates_description(self, monkeypatch):
        from jira_cli.commands import cmd_issue_update_description

        mock_put = MagicMock(return_value={})
        monkeypatch.setattr("jira_cli.commands.jira_put", mock_put)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_update_description(cfg, "PROJ-123", "New desc")

        mock_put.assert_called_once()
        payload = mock_put.call_args[0][2]
        assert payload["update"]["description"][0]["set"]["type"] == "doc"

    def test_updates_description_empty_body(self, monkeypatch):
        from jira_cli.commands import cmd_issue_update_description

        mock_put = MagicMock(return_value={})
        monkeypatch.setattr("jira_cli.commands.jira_put", mock_put)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_update_description(cfg, "PROJ-123", "")

        mock_put.assert_called_once()
        payload = mock_put.call_args[0][2]
        assert payload["update"]["description"][0]["set"]["content"] == []


class TestCommandsUpdateStatus:
    def test_transition_by_id(self, monkeypatch):
        from jira_cli.commands import cmd_issue_update_status

        mock_post = MagicMock(return_value={})
        monkeypatch.setattr("jira_cli.commands.jira_post", mock_post)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_update_status(cfg, "PROJ-123", "41")

        mock_post.assert_called_once_with(
            cfg, "issue/PROJ-123/transitions", {"transition": {"id": "41"}}
        )


class TestCommandsAssign:
    def test_assign_user(self, monkeypatch):
        from jira_cli.commands import cmd_issue_assign

        mock_put = MagicMock(return_value={})
        monkeypatch.setattr("jira_cli.commands.jira_put", mock_put)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_assign(cfg, "PROJ-123", "jane.doe")

        mock_put.assert_called_once_with(cfg, "issue/PROJ-123/assignee", {"name": "jane.doe"})

    def test_assign_unassign(self, monkeypatch):
        from jira_cli.commands import cmd_issue_assign

        mock_put = MagicMock(return_value={})
        monkeypatch.setattr("jira_cli.commands.jira_put", mock_put)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_assign(cfg, "PROJ-123", "")
        mock_put.assert_called_once_with(cfg, "issue/PROJ-123/assignee", {"name": ""})


class TestCommandsUpdateComment:
    def test_update_comment(self, monkeypatch):
        from jira_cli.commands import cmd_issue_update_comment

        mock_put = MagicMock(return_value={"updated": "2024-01-15T10:30:00.000+0000"})
        monkeypatch.setattr("jira_cli.commands.jira_put", mock_put)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_update_comment(cfg, "PROJ-123", "54321", "Updated body")

        mock_put.assert_called_once_with(cfg, "issue/PROJ-123/comment/54321", {"body": "Updated body"})

    def test_update_comment_empty_body(self, monkeypatch):
        from jira_cli.commands import cmd_issue_update_comment

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        with pytest.raises(SystemExit):
            cmd_issue_update_comment(cfg, "PROJ-123", "54321", "")


class TestCommandsLegacy:
    """Existing command behaviors (mocked HTTP)."""

    def test_cmd_projects(self, monkeypatch):
        from jira_cli.commands import cmd_projects

        mock_get = MagicMock(
            return_value=[{"key": "PROJ", "name": "Project X", "lead": {"displayName": "Alice"}, "projectTypeKey": "business"}]
        )
        monkeypatch.setattr("jira_cli.commands.jira_get", mock_get)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_projects(cfg)
        mock_get.assert_called_once_with(cfg, "project")

    def test_cmd_search_with_jql(self, monkeypatch):
        from jira_cli.commands import cmd_search

        mock_get = MagicMock(return_value={"issues": [], "total": 0})
        monkeypatch.setattr("jira_cli.commands.jira_get", mock_get)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_search(cfg, "project=TEST")
        mock_get.assert_called_once_with(cfg, "search", ANY)

    def test_cmd_search_json_format(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_search

        issues = [{
            "key": "TEST-1",
            "fields": {
                "summary": "Test issue",
                "status": {"name": "Open"},
                "priority": {"name": "Medium"},
                "assignee": {"displayName": "Alice"},
                "created": "2024-01-01T00:00:00.000+0000",
                "issuetype": {"name": "Bug"},
                "reporter": {"displayName": "Bob"},
                "updated": "2024-01-02T00:00:00.000+0000",
            },
        }]
        mock_get = MagicMock(return_value={"issues": issues, "total": 1})
        monkeypatch.setattr("jira_cli.commands.jira_get", mock_get)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_search(cfg, "project=TEST", fmt="json")
        captured = capsys.readouterr()
        assert "TEST-1" in captured.out

    def test_cmd_issue(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue

        mock_get = MagicMock(
            side_effect=[
                {
                    "key": "TEST-1",
                    "fields": {
                        "summary": "Test",
                        "status": {"name": "Open"},
                        "priority": {"name": "Medium"},
                        "assignee": {"displayName": "Alice"},
                        "reporter": {"displayName": "Bob"},
                        "created": "2024-01-01T00:00:00.000+0000",
                        "updated": "2024-01-02T00:00:00.000+0000",
                        "issuetype": {"name": "Bug"},
                        "project": {"name": "Test Project", "key": "TEST"},
                        "description": {
                            "type": "doc", "version": 1,
                            "content": [{"type": "paragraph", "content": [{"text": "Desc", "type": "text"}]}],
                        },
                    },
                },
                {"comments": [], "total": 0},
            ]
        )
        monkeypatch.setattr("jira_cli.commands.jira_get", mock_get)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue(cfg, "TEST-1")
        captured = capsys.readouterr()
        assert "TEST-1" in captured.out

    def test_cmd_issue_comments(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue_comments

        mock_get = MagicMock(
            return_value={
                "comments": [{"id": "123", "author": {"displayName": "Alice"}, "created": "2024-01-01T00:00:00.000+0000", "body": {"type": "doc", "version": 1, "content": []}}],
                "total": 1,
            }
        )
        monkeypatch.setattr("jira_cli.commands.jira_get", mock_get)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_comments(cfg, "TEST-1")
        captured = capsys.readouterr()
        assert "123" in captured.out

    def test_cmd_issue_add_comment(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue_add_comment

        mock_post = MagicMock(return_value={"id": "999", "created": "2024-01-01T00:00:00.000+0000"})
        monkeypatch.setattr("jira_cli.commands.jira_post", mock_post)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_add_comment(cfg, "TEST-1", "New comment body")
        mock_post.assert_called_once_with(cfg, "issue/TEST-1/comment", {"body": "New comment body"})
        captured = capsys.readouterr()
        assert "999" in captured.out

    def test_issue_comment_functions_exist(self):
        from jira_cli.commands import (
            cmd_issue, cmd_issue_comments, cmd_issue_comment, cmd_issue_add_comment,
            cmd_issue_update_description, cmd_issue_update_status, cmd_issue_assign,
            cmd_issue_update_comment, cmd_projects, cmd_search, cmd_setup,
        )
        for fn in [cmd_issue, cmd_issue_comments, cmd_issue_comment, cmd_issue_add_comment,
                   cmd_issue_update_description, cmd_issue_update_status, cmd_issue_assign,
                   cmd_issue_update_comment, cmd_projects, cmd_search, cmd_setup]:
            assert callable(fn)


# -------------------------------------------------------------------
# Filters
# -------------------------------------------------------------------


class TestFilters:
    """Saved filter JQL logic."""

    def test_filters_exist(self):
        from jira_cli.filters import FILTERS
        for name in ["my-issues", "active-sprint", "todo", "in-progress", "blocked"]:
            assert name in FILTERS

    def test_resolve_filter(self):
        from jira_cli.filters import resolve_filter
        assert resolve_filter("my") == "my-issues"
        assert resolve_filter("blocked") == "blocked"
        assert resolve_filter("nope") is None

    def test_combine_filters(self):
        from jira_cli.filters import combine_filters
        j = combine_filters(["my-issues", "in-progress"])
        assert "assignee=currentUser()" in j
        assert 'status="In Progress"' in j

    def test_combine_filters_plus_syntax(self):
        from jira_cli.filters import combine_filters
        j = combine_filters(["my-issues+blocked"])
        assert "resolution=Unresolved" in j
        assert "status=Blocked" in j


# -------------------------------------------------------------------
# Flags & JQL
# -------------------------------------------------------------------


class TestFlags:
    """Flag parsing and JQL construction."""

    def test_parse_flags(self):
        from jira_cli.flags import parse_flags
        r, f = parse_flags(["--saved", "my-issues,blocked", "--limit", "50", "--format", "json"])
        assert f["saved"] == ["my-issues", "blocked"]
        assert f["limit"] == 50
        assert f["format"] == "json"

    def test_parse_flags_defaults(self):
        from jira_cli.flags import parse_flags
        r, f = parse_flags([])
        assert f["limit"] == 20 and f["page"] == 1 and f["format"] == "table"
        assert f["desc"] is False and f["saved"] == [] and f["body"] is None

    def test_parse_flags_body(self):
        from jira_cli.flags import parse_flags
        r, f = parse_flags(["--body", "hello world"])
        assert f["body"] == "hello world"

    def test_parse_flags_list_filters(self):
        from jira_cli.flags import parse_flags
        r, f = parse_flags(["--list-filters"])
        assert f["list_filters"] is True

    def test_has_help_flag(self):
        from jira_cli.flags import has_help_flag
        assert has_help_flag(["--help"])
        assert has_help_flag(["-h"])
        assert not has_help_flag(["--limit", "5"])

    def test_build_jql(self):
        from jira_cli.flags import build_jql
        j = build_jql(["todo"], ["project=BANKING"])
        assert "project=BANKING" in j and 'status="To Do"' in j

        j = build_jql([], ["project=BANKING", "ORDER BY", "created", "DESC"])
        assert j == "project=BANKING ORDER BY created DESC"

        j = build_jql(["blocked"], [])
        assert "status=Blocked" in j


# -------------------------------------------------------------------
# CLI Dispatch
# -------------------------------------------------------------------


class TestCLIDispatch:
    """CLI main() dispatcher with mocked commands."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        config_dir = tmp_path / "jira-cli-test"
        monkeypatch.setattr("jira_cli.config.CONFIG_DIR", str(config_dir))
        monkeypatch.setattr("jira_cli.config.CONFIG_PATH", str(config_dir / "config.json"))
        monkeypatch.setattr("jira_cli.config.KEY_PATH", str(config_dir / "secret.key"))
        monkeypatch.setattr("jira_cli.config._OLD_CONFIG_PATH", str(tmp_path / ".jira-cli.json"))
        from jira_cli.config import save_config
        save_config("https://jira.x.com", "testuser", "testpass")

    def test_main_shows_usage_no_args(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli"])
        from jira_cli.cli import main
        main()
        captured = capsys.readouterr()
        assert "Usage" in captured.out

    def test_main_help(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "--help"])
        from jira_cli.cli import main
        main()
        captured = capsys.readouterr()
        assert "JIRA-CLI HELP" in captured.out

    def test_main_setup(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jira-cli", "setup"])
        mock_setup = MagicMock()
        monkeypatch.setattr("jira_cli.cli.cmd_setup", mock_setup)
        from jira_cli.cli import main
        main()
        mock_setup.assert_called_once()

    def test_main_completion_bash(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "completion", "bash"])
        from jira_cli.cli import main
        main()
        captured = capsys.readouterr()
        assert "jira-cli" in captured.out

    def test_main_projects(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jira-cli", "projects"])
        mock_cmd = MagicMock()
        monkeypatch.setattr("jira_cli.cli.cmd_projects", mock_cmd)
        from jira_cli.cli import main
        main()
        mock_cmd.assert_called_once()

    def test_main_search(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jira-cli", "search", "project=TEST"])
        mock_cmd = MagicMock()
        monkeypatch.setattr("jira_cli.cli.cmd_search", mock_cmd)
        from jira_cli.cli import main
        main()
        mock_cmd.assert_called_once()

    def test_main_issue(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123"])
        mock_cmd = MagicMock()
        monkeypatch.setattr("jira_cli.cli.cmd_issue", mock_cmd)
        from jira_cli.cli import main
        main()
        mock_cmd.assert_called_once()

    def test_main_issue_comments(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "comments"])
        mock_cmd = MagicMock()
        monkeypatch.setattr("jira_cli.cli.cmd_issue_comments", mock_cmd)
        from jira_cli.cli import main
        main()
        mock_cmd.assert_called_once()

    def test_main_issue_update_description(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "update-description", "--body", "New desc"])
        mock_cmd = MagicMock()
        monkeypatch.setattr("jira_cli.cli.cmd_issue_update_description", mock_cmd)
        from jira_cli.cli import main
        main()
        mock_cmd.assert_called_once()

    def test_main_issue_update_description_no_body(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "update-description"])
        from jira_cli.cli import main
        with pytest.raises(SystemExit):
            main()
        captured = capsys.readouterr()
        assert "required" in captured.err

    def test_main_issue_transition(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "transition", "41"])
        mock_cmd = MagicMock()
        monkeypatch.setattr("jira_cli.cli.cmd_issue_update_status", mock_cmd)
        from jira_cli.cli import main
        main()
        mock_cmd.assert_called_once()

    def test_main_issue_assign(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "assign", "jane.doe"])
        mock_cmd = MagicMock()
        monkeypatch.setattr("jira_cli.cli.cmd_issue_assign", mock_cmd)
        from jira_cli.cli import main
        main()
        mock_cmd.assert_called_once()

    def test_main_issue_edit_comment(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "edit-comment", "54321", "--body", "Updated"])
        mock_cmd = MagicMock()
        monkeypatch.setattr("jira_cli.cli.cmd_issue_update_comment", mock_cmd)
        from jira_cli.cli import main
        main()
        mock_cmd.assert_called_once()

    def test_main_unknown_command(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "blargh"])
        from jira_cli.cli import main
        with pytest.raises(SystemExit):
            main()
        captured = capsys.readouterr()
        assert "Unknown" in captured.err

    def test_main_unknown_issue_subcommand(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "blargh"])
        from jira_cli.cli import main
        with pytest.raises(SystemExit):
            main()
        captured = capsys.readouterr()
        assert "Unknown" in captured.err

    def test_main_no_config_stops(self, monkeypatch, capsys, tmp_path):
        config_dir = tmp_path / "jira-cli-nocfg"
        monkeypatch.setattr("jira_cli.config.CONFIG_DIR", str(config_dir))
        monkeypatch.setattr("jira_cli.config.CONFIG_PATH", str(config_dir / "config.json"))
        monkeypatch.setattr("jira_cli.config.KEY_PATH", str(config_dir / "secret.key"))
        monkeypatch.setattr("jira_cli.config._OLD_CONFIG_PATH", str(tmp_path / ".jira-cli.json"))
        monkeypatch.setattr("sys.argv", ["jira-cli", "projects"])
        from jira_cli.cli import main
        with pytest.raises(SystemExit):
            main()
        captured = capsys.readouterr()
        assert "not configured" in captured.err

    def test_main_setup_no_config_ok(self, monkeypatch, capsys, tmp_path):
        config_dir = tmp_path / "jira-cli-setup"
        monkeypatch.setattr("jira_cli.config.CONFIG_DIR", str(config_dir))
        monkeypatch.setattr("jira_cli.config.CONFIG_PATH", str(config_dir / "config.json"))
        monkeypatch.setattr("jira_cli.config.KEY_PATH", str(config_dir / "secret.key"))
        monkeypatch.setattr("jira_cli.config._OLD_CONFIG_PATH", str(tmp_path / ".jira-cli.json"))
        monkeypatch.setattr("sys.argv", ["jira-cli", "setup"])
        mock_setup = MagicMock()
        monkeypatch.setattr("jira_cli.cli.cmd_setup", mock_setup)
        from jira_cli.cli import main
        main()
        mock_setup.assert_called_once()

    def test_main_completion_no_config_ok(self, monkeypatch, capsys, tmp_path):
        config_dir = tmp_path / "jira-cli-compl"
        monkeypatch.setattr("jira_cli.config.CONFIG_DIR", str(config_dir))
        monkeypatch.setattr("jira_cli.config.CONFIG_PATH", str(config_dir / "config.json"))
        monkeypatch.setattr("jira_cli.config.KEY_PATH", str(config_dir / "secret.key"))
        monkeypatch.setattr("jira_cli.config._OLD_CONFIG_PATH", str(tmp_path / ".jira-cli.json"))
        monkeypatch.setattr("sys.argv", ["jira-cli", "completion", "bash"])
        from jira_cli.cli import main
        main()
        captured = capsys.readouterr()
        assert "jira-cli" in captured.out


# -------------------------------------------------------------------
# CLI edge cases coverage
# -------------------------------------------------------------------


class TestCLIDispatchEdgeCases:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        config_dir = tmp_path / "jira-cli-edge"
        monkeypatch.setattr("jira_cli.config.CONFIG_DIR", str(config_dir))
        monkeypatch.setattr("jira_cli.config.CONFIG_PATH", str(config_dir / "config.json"))
        monkeypatch.setattr("jira_cli.config.KEY_PATH", str(config_dir / "secret.key"))
        monkeypatch.setattr("jira_cli.config._OLD_CONFIG_PATH", str(tmp_path / ".jira-cli.json"))
        from jira_cli.config import save_config
        save_config("https://jira.x.com", "testuser", "testpass")

    def test_main_search_help(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "search", "--help"])
        from jira_cli.cli import main
        main()
        captured = capsys.readouterr()
        assert "search issues" in captured.out.lower()

    def test_main_search_list_filters(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "search", "--list-filters"])
        from jira_cli.cli import main
        main()
        captured = capsys.readouterr()
        assert "my-issues" in captured.out

    def test_main_search_no_jql(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "search"])
        from jira_cli.cli import main
        with pytest.raises(SystemExit):
            main()
        captured = capsys.readouterr()
        assert "search" in captured.out.lower() or "search" in captured.err.lower()

    def test_main_projects_help(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "projects", "--help"])
        from jira_cli.cli import main
        main()
        captured = capsys.readouterr()
        assert "projects" in captured.out.lower()

    def test_main_completion_help(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "completion", "--help"])
        from jira_cli.cli import main
        main()
        captured = capsys.readouterr()
        assert "JIRA-CLI HELP" in captured.out

    def test_main_completion_no_shell(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "completion"])
        from jira_cli.cli import main
        main()
        captured = capsys.readouterr()
        assert "Usage" in captured.err

    def test_main_issue_help(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "--help"])
        from jira_cli.cli import main
        main()
        captured = capsys.readouterr()
        assert "issue" in captured.out.lower()

    def test_main_issue_comments_help(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "comments", "-h"])
        from jira_cli.cli import main
        main()
        captured = capsys.readouterr()
        assert "issue" in captured.out.lower()

    def test_main_issue_no_key(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue"])
        from jira_cli.cli import main
        with pytest.raises(SystemExit):
            main()
        captured = capsys.readouterr()
        assert "Usage" in captured.err

    def test_main_issue_comment_no_id(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "comment"])
        from jira_cli.cli import main
        with pytest.raises(SystemExit):
            main()
        captured = capsys.readouterr()
        assert "Usage" in captured.err

    def test_main_issue_add_comment_help(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "add-comment", "-h"])
        from jira_cli.cli import main
        main()
        captured = capsys.readouterr()
        assert "issue" in captured.out.lower()

    def test_main_issue_transition_no_id(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "transition"])
        from jira_cli.cli import main
        with pytest.raises(SystemExit):
            main()
        captured = capsys.readouterr()
        assert "Usage" in captured.err

    def test_main_issue_assign_no_user(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "assign"])
        from jira_cli.cli import main
        with pytest.raises(SystemExit):
            main()
        captured = capsys.readouterr()
        assert "Usage" in captured.err

    def test_main_issue_edit_comment_no_id(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "edit-comment"])
        from jira_cli.cli import main
        with pytest.raises(SystemExit):
            main()
        captured = capsys.readouterr()
        assert "Usage" in captured.err

    def test_setup_help(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "setup", "-h"])
        from jira_cli.cli import main
        main()
        captured = capsys.readouterr()
        assert "setup" in captured.out.lower()


# -------------------------------------------------------------------
# Command coverage
# -------------------------------------------------------------------


class TestCommandCoverage:
    """Coverage for command edge cases."""

    def test_cmd_search_table_format(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_search

        mock_get = MagicMock(return_value={
            "issues": [{
                "key": "TEST-1",
                "fields": {
                    "summary": "Test issue",
                    "status": {"name": "Open"},
                    "priority": {"name": "Medium"},
                    "assignee": {"displayName": "Alice"},
                    "created": "2024-01-01T00:00:00.000+0000",
                    "issuetype": {"name": "Bug"},
                    "reporter": {"displayName": "Bob"},
                    "updated": "2024-01-02T00:00:00.000+0000",
                },
            }],
            "total": 1,
        })
        monkeypatch.setattr("jira_cli.commands.jira_get", mock_get)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_search(cfg, "project=TEST", fmt="table")
        captured = capsys.readouterr()
        assert "TEST-1" in captured.out
        assert "Query" in captured.out

    def test_cmd_search_no_results(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_search

        mock_get = MagicMock(return_value={"issues": [], "total": 0})
        monkeypatch.setattr("jira_cli.commands.jira_get", mock_get)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_search(cfg, "project=NONE")
        captured = capsys.readouterr()
        assert "No issues" in captured.out

    def test_cmd_issue_comments_pagination(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue_comments

        mock_get = MagicMock(return_value={
            "comments": [
                {"id": str(i), "author": {"displayName": f"User{i}"},
                 "created": "2024-01-01T00:00:00.000+0000",
                 "body": {"type": "doc", "version": 1, "content": []}}
                for i in range(3)
            ],
            "total": 10,
        })
        monkeypatch.setattr("jira_cli.commands.jira_get", mock_get)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_comments(cfg, "TEST-1", limit=3, page=2)
        captured = capsys.readouterr()
        assert "page 2" in captured.out

    def test_cmd_issue_comments_json(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue_comments

        mock_get = MagicMock(return_value={
            "comments": [{"id": "1", "author": {"displayName": "A"}, "created": "2024-01-01T00:00:00.000+0000", "body": {}}],
            "total": 1,
        })
        monkeypatch.setattr("jira_cli.commands.jira_get", mock_get)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_comments(cfg, "TEST-1", fmt="json")
        captured = capsys.readouterr()
        assert '"id": "1"' in captured.out

    def test_cmd_issue_comment_json(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue_comment

        mock_get = MagicMock(return_value={
            "id": "123", "author": {"displayName": "Alice"},
            "created": "2024-01-01T00:00:00.000+0000",
            "updated": "2024-01-02T00:00:00.000+0000",
            "body": {"type": "doc", "version": 1, "content": []},
        })
        monkeypatch.setattr("jira_cli.commands.jira_get", mock_get)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_comment(cfg, "TEST-1", "123", fmt="json")
        captured = capsys.readouterr()
        assert '"id": "123"' in captured.out

    def test_cmd_issue_comments_no_results(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue_comments

        mock_get = MagicMock(return_value={"comments": [], "total": 0})
        monkeypatch.setattr("jira_cli.commands.jira_get", mock_get)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_comments(cfg, "TEST-1")
        captured = capsys.readouterr()
        assert "No comments" in captured.out

    def test_cmd_setup_interactive(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_setup

        monkeypatch.setattr("builtins.input",
                            lambda prompt="": "https://jira.x.com" if "URL" in prompt
                            else ("admin" if "Username" in prompt else "secret"))
        mock_save = MagicMock()
        monkeypatch.setattr("jira_cli.commands.save_config", mock_save)

        cmd_setup({"url": "", "user": "", "pass": ""})
        mock_save.assert_called_once()

    def test_cmd_setup_with_defaults(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_setup

        monkeypatch.setattr("builtins.input", lambda prompt="": "")
        mock_save = MagicMock()
        monkeypatch.setattr("jira_cli.commands.save_config", mock_save)

        cmd_setup({"url": "https://default.x.com", "user": "defaultuser", "pass": "defaultpass"})
        mock_save.assert_called_once()


# -------------------------------------------------------------------
# HTTP coverage
# -------------------------------------------------------------------


class TestHTTPCoverage:
    def test_jira_get_calls_request(self):
        from jira_cli.http import jira_get
        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        with patch("jira_cli.http._request") as mock_req:
            jira_get(cfg, "project")
            mock_req.assert_called_once_with(cfg, "GET", "project", params=None)

    def test_jira_put_calls_request(self):
        from jira_cli.http import jira_put
        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        with patch("jira_cli.http._request") as mock_req:
            jira_put(cfg, "issue/TEST-1", {"key": "val"})
            mock_req.assert_called_once_with(cfg, "PUT", "issue/TEST-1", data={"key": "val"})

    def test_jira_delete_calls_request(self):
        from jira_cli.http import jira_delete
        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        with patch("jira_cli.http._request") as mock_req:
            jira_delete(cfg, "issue/TEST-1")
            mock_req.assert_called_once_with(cfg, "DELETE", "issue/TEST-1")

    def test_auth_header_base64(self):
        from jira_cli.http import auth_header
        hdr = auth_header({"user": "admin", "pass": "p@ss"})
        assert hdr["Authorization"].startswith("Basic ")


# -------------------------------------------------------------------
# Format edge cases
# -------------------------------------------------------------------


class TestFormatCoverage:
    def test_fmt_date_empty(self):
        from jira_cli.format import fmt_date
        assert fmt_date("") == ""
        assert fmt_date(None) == ""

    def test_fmt_date_bad_format(self):
        from jira_cli.format import fmt_date
        result = fmt_date("not-a-date")
        assert result is not None

    def test_priority_label_empty(self):
        from jira_cli.format import priority_label
        assert priority_label({}) == ""
        assert priority_label(None) == ""

    def test_priority_label_known(self):
        from jira_cli.format import priority_label
        assert "Highest" in priority_label({"name": "Highest"})

    def test_priority_label_unknown(self):
        from jira_cli.format import priority_label
        result = priority_label({"name": "Trivial"})
        assert "Trivial" in result

    def test_truncate_empty(self):
        from jira_cli.format import truncate
        assert truncate("") == ""
        assert truncate(None) == ""

    def test_extract_adf_text_list(self):
        from jira_cli.format import extract_adf_text
        result = extract_adf_text([
            {"type": "paragraph", "content": [{"text": "A", "type": "text"}]},
            {"type": "paragraph", "content": [{"text": "B", "type": "text"}]},
        ])
        assert "A" in result

    def test_extract_adf_text_deep_dict_no_text(self):
        from jira_cli.format import extract_adf_text
        result = extract_adf_text({"type": "doc", "content": [{"type": "paragraph", "content": []}]})
        assert result == ""


# -------------------------------------------------------------------
# Completion
# -------------------------------------------------------------------


class TestCompletion:
    def test_bash_completion(self, capsys):
        from jira_cli.completion import cmd_completion
        cmd_completion("bash")
        captured = capsys.readouterr()
        assert "jira-cli" in captured.out
        assert "_init_completion" in captured.out

    def test_zsh_completion(self, capsys):
        from jira_cli.completion import cmd_completion
        cmd_completion("zsh")
        captured = capsys.readouterr()
        assert "_arguments" in captured.out

    def test_fish_completion(self, capsys):
        from jira_cli.completion import cmd_completion
        cmd_completion("fish")
        captured = capsys.readouterr()
        assert "complete -c" in captured.out

    def test_unknown_shell_exits(self):
        from jira_cli.completion import cmd_completion
        with pytest.raises(SystemExit):
            cmd_completion("tcsh")


# -------------------------------------------------------------------
# Help texts
# -------------------------------------------------------------------


class TestHelpTexts:
    def test_help_texts_exist(self):
        from jira_cli.help_texts import HELP
        for t in ["main", "search", "issue", "projects", "setup"]:
            assert len(HELP.get(t, "")) > 50

    def test_help_contains_new_commands(self):
        from jira_cli.help_texts import HELP
        main = HELP["main"]
        assert "update-description" in main
        assert "transition" in main
        assert "assign" in main
        assert "edit-comment" in main

    def test_print_help(self, capsys):
        from jira_cli.help_texts import print_help
        print_help("main")
        captured = capsys.readouterr()
        assert "JIRA-CLI HELP" in captured.out
