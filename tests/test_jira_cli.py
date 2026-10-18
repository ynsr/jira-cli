"""Comprehensive pytest suite for jira-cli with coverage target >= 80%."""

import io
import json
import os
import sys
import urllib.error
from unittest.mock import ANY, MagicMock, call, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture(autouse=True)
def _isolate_field_cache(monkeypatch, tmp_path, request):
    """Keep the /field ID cache off disk and network unless a test opts in."""
    from jira_cli import fields as _fields_mod

    monkeypatch.setenv("JIRA_CLI_FIELD_CACHE_DIR", str(tmp_path / "field-cache"))
    _fields_mod._reset_field_cache()
    if "real_field_cache" not in getattr(request, "keywords", {}):
        monkeypatch.setattr(
            _fields_mod, "get_custom_field_ids",
            lambda cfg, project=None: {"story_points": None, "sprint": None, "epic_link": None},
        )
    yield
    _fields_mod._reset_field_cache()


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

    def test_jira_post_attachment_multipart(self, tmp_path, monkeypatch):
        from jira_cli.http import jira_post_attachment

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'[{"id": "10001", "filename": "a.txt", "size": 2}]'

        f = tmp_path / "a.txt"
        f.write_text("hi")
        mock_urlopen = MagicMock(return_value=FakeResp())
        monkeypatch.setattr("jira_cli.http.urllib.request.urlopen", mock_urlopen)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        result = jira_post_attachment(cfg, "PROJ-123", [str(f)])

        assert result[0]["filename"] == "a.txt"
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "https://jira.x/rest/api/2/issue/PROJ-123/attachments"
        assert req.get_method() == "POST"
        assert req.headers["X-atlassian-token"] == "no-check"
        assert req.get_header("Content-type").startswith("multipart/form-data; boundary=")
        body = req.data.decode()
        assert 'name="file"; filename="a.txt"' in body
        assert "Content-Type: text/plain" in body
        assert "hi" in body

    def test_jira_get_binary_returns_bytes(self, monkeypatch):
        from jira_cli.http import jira_get_binary

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"\x89PNG fake"

        mock_urlopen = MagicMock(return_value=FakeResp())
        monkeypatch.setattr("jira_cli.http.urllib.request.urlopen", mock_urlopen)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        data = jira_get_binary(cfg, "https://jira.x/secure/attachment/1/a.txt")
        assert data == b"\x89PNG fake"
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "https://jira.x/secure/attachment/1/a.txt"
        assert req.get_header("Accept") == "application/octet-stream"

        # REST-relative path form
        jira_get_binary(cfg, "attachment/2/content")
        req2 = mock_urlopen.call_args[0][0]
        assert req2.full_url == "https://jira.x/rest/api/2/attachment/2/content"

    def test_jira_delete_attachment_headers(self, monkeypatch):
        from jira_cli.http import jira_delete_attachment

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b""

        mock_urlopen = MagicMock(return_value=FakeResp())
        monkeypatch.setattr("jira_cli.http.urllib.request.urlopen", mock_urlopen)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        assert jira_delete_attachment(cfg, "42") == {}
        req = mock_urlopen.call_args[0][0]
        assert req.get_method() == "DELETE"
        assert req.full_url == "https://jira.x/rest/api/2/attachment/42"
        assert req.headers["X-atlassian-token"] == "no-check"


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


class TestCommandsUpdateStatus:
    def test_transition_by_id(self, monkeypatch):
        from jira_cli.commands import cmd_issue_update_status

        mock_post = MagicMock(return_value={})
        monkeypatch.setattr("jira_cli.commands.jira_post", mock_post)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_update_status(cfg, "PROJ-123", "41", yes=True)

        mock_post.assert_called_once_with(
            cfg, "issue/PROJ-123/transitions", {"transition": {"id": "41"}}
        )


class TestCommandsUpdateComment:
    def test_update_comment(self, monkeypatch):
        from jira_cli.commands import cmd_issue_update_comment

        mock_put = MagicMock(return_value={"updated": "2024-01-15T10:30:00.000+0000"})
        monkeypatch.setattr("jira_cli.commands.jira_put", mock_put)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_update_comment(cfg, "PROJ-123", "54321", "Updated body", yes=True)

        mock_put.assert_called_once_with(cfg, "issue/PROJ-123/comment/54321", {"body": "Updated body"})

    def test_update_comment_empty_body(self, monkeypatch):
        from jira_cli.commands import cmd_issue_update_comment

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        with pytest.raises(SystemExit):
            cmd_issue_update_comment(cfg, "PROJ-123", "54321", "")


class TestCommandsCreateIssue:
    def test_create_basic(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_create_issue

        mock_post = MagicMock(return_value={"key": "PROJ-456", "id": "456"})
        monkeypatch.setattr("jira_cli.commands.jira_post", mock_post)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_create_issue(cfg, "PROJ", "My new issue")

        payload = mock_post.call_args[0][2]
        assert payload["fields"]["project"] == {"key": "PROJ"}
        assert payload["fields"]["summary"] == "My new issue"
        assert payload["fields"]["issuetype"] == {"name": "Task"}
        captured = capsys.readouterr()
        assert "PROJ-456" in captured.out

    def test_create_full_options(self, monkeypatch):
        from jira_cli.commands import cmd_create_issue

        mock_post = MagicMock(return_value={"key": "PROJ-457", "id": "457"})
        monkeypatch.setattr("jira_cli.commands.jira_post", mock_post)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_create_issue(
            cfg, "PROJ", "Bug summary", issue_type="Bug",
            description="Some description", priority="High", assignee="jane.doe",
        )

        payload = mock_post.call_args[0][2]
        fields = payload["fields"]
        assert fields["issuetype"] == {"name": "Bug"}
        assert fields["priority"] == {"name": "High"}
        assert fields["assignee"] == {"name": "jane.doe"}
        assert fields["description"] == "Some description"

    def test_create_json_format(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_create_issue

        mock_post = MagicMock(return_value={"key": "PROJ-458", "id": "458"})
        monkeypatch.setattr("jira_cli.commands.jira_post", mock_post)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_create_issue(cfg, "PROJ", "Summary", fmt="json")
        captured = capsys.readouterr()
        assert '"key": "PROJ-458"' in captured.out


class TestCommandsLinkIssues:
    def test_link_basic(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_link_issues

        mock_post = MagicMock(return_value={})
        monkeypatch.setattr("jira_cli.commands.jira_post", mock_post)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_link_issues(cfg, "PROJ-123", "PROJ-456")

        expected = {
            "type": {"name": "Relates"},
            "inwardIssue": {"key": "PROJ-456"},
            "outwardIssue": {"key": "PROJ-123"},
        }
        mock_post.assert_called_once_with(cfg, "issueLink", expected)
        captured = capsys.readouterr()
        assert "PROJ-123" in captured.out and "PROJ-456" in captured.out

    def test_link_with_type_and_comment(self, monkeypatch):
        from jira_cli.commands import cmd_link_issues

        mock_post = MagicMock(return_value={})
        monkeypatch.setattr("jira_cli.commands.jira_post", mock_post)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_link_issues(cfg, "PROJ-123", "PROJ-456", link_type="Blocks", comment="Depends on fix")

        payload = mock_post.call_args[0][2]
        assert payload["type"] == {"name": "Blocks"}
        assert payload["comment"] == {"body": "Depends on fix"}


class TestCommandsUpdateIssue:
    def test_update_all_fields(self, monkeypatch):
        from jira_cli.commands import cmd_issue_update

        mock_put = MagicMock(return_value={})
        monkeypatch.setattr("jira_cli.commands.jira_put", mock_put)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_update(
            cfg, "PROJ-123", summary="New title", description="New desc",
            priority="High", assignee="jane.doe", yes=True,
        )

        payload = mock_put.call_args[0][2]
        fields = payload["fields"]
        assert fields["summary"] == "New title"
        assert fields["priority"] == {"name": "High"}
        assert fields["assignee"] == {"name": "jane.doe"}
        assert fields["description"] == "New desc"

    def test_update_single_field(self, monkeypatch):
        from jira_cli.commands import cmd_issue_update

        mock_put = MagicMock(return_value={})
        monkeypatch.setattr("jira_cli.commands.jira_put", mock_put)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_update(cfg, "PROJ-123", summary="Only title", yes=True)
        payload = mock_put.call_args[0][2]
        assert payload["fields"] == {"summary": "Only title"}

    def test_update_no_fields_exits(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue_update

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        with pytest.raises(SystemExit):
            cmd_issue_update(cfg, "PROJ-123")
        captured = capsys.readouterr()
        assert "nothing to update" in captured.err


class TestApiVersionCompat:
    """v2 (Server/DC) vs v3 (Cloud) compatibility.

    v2: description/comment bodies are plain wiki-markup strings.
    v3: description/comment bodies are ADF documents.
    """

    @pytest.fixture(autouse=True)
    def _reset_api_version(self):
        from jira_cli.http import _reset_version_state

        _reset_version_state()
        yield
        _reset_version_state()

    # ---- detection ---------------------------------------------------

    def test_detect_v2_when_deployment_type_is_server(self, monkeypatch):
        from jira_cli import http

        monkeypatch.setattr(http, "_probe_server_info",
                            MagicMock(return_value={"deploymentType": "Server"}))
        assert http.detect_write_api_version({"url": "https://x"}) == 2
        assert http.get_write_api_version() == 2
        assert not http.is_api_v3({"url": "https://x"})

    def test_detect_v3_when_deployment_type_is_cloud(self, monkeypatch):
        from jira_cli import http

        monkeypatch.setattr(http, "_probe_server_info",
                            MagicMock(return_value={"deploymentType": "Cloud"}))
        assert http.detect_write_api_version({"url": "https://x"}) == 3
        assert http.is_api_v3({"url": "https://x"})

    def test_detect_is_cached(self, monkeypatch):
        from jira_cli import http

        monkeypatch.setattr(http, "_probe_server_info",
                            MagicMock(return_value={"deploymentType": "Cloud"}))
        http.ensure_api_version_detected({"url": "https://x"})
        monkeypatch.setattr(http, "_probe_server_info",
                            MagicMock(side_effect=AssertionError("must not probe twice")))
        assert http.ensure_api_version_detected({"url": "https://x"}) == 3

    def test_env_override_forces_v2(self, monkeypatch):
        from jira_cli import http

        monkeypatch.setenv("JIRA_API_VERSION", "2")
        monkeypatch.setattr(http, "_probe_server_info",
                            MagicMock(side_effect=AssertionError("env override must not probe")))
        assert http.detect_write_api_version({"url": "https://x"}) == 2

    def test_env_override_forces_v3(self, monkeypatch):
        from jira_cli import http

        monkeypatch.setenv("JIRA_API_VERSION", "v3")
        assert http.detect_write_api_version({"url": "https://x"}) == 3

    def test_env_override_auto_falls_back_to_detection(self, monkeypatch):
        from jira_cli import http

        monkeypatch.setenv("JIRA_API_VERSION", "auto")
        monkeypatch.setattr(http, "_probe_server_info",
                            MagicMock(return_value={"deploymentType": "Server"}))
        assert http.detect_write_api_version({"url": "https://x"}) == 2

    def test_detection_failure_falls_back_to_v2(self, monkeypatch):
        from jira_cli import http

        monkeypatch.setattr(http, "_probe_server_info", MagicMock(return_value=None))
        assert http.detect_write_api_version({"url": "https://x"}) == 2

    def test_detection_ignores_deployment_type_case(self, monkeypatch):
        from jira_cli import http

        monkeypatch.setattr(http, "_probe_server_info",
                            MagicMock(return_value={"deploymentType": "  ClOuD  "}))
        assert http.detect_write_api_version({"url": "https://x"}) == 3

    def test_missing_deployment_type_means_v2(self, monkeypatch):
        from jira_cli import http

        monkeypatch.setattr(http, "_probe_server_info", MagicMock(return_value={}))
        assert http.detect_write_api_version({"url": "https://x"}) == 2

    def test_set_write_api_version_validates(self):
        from jira_cli import http

        with pytest.raises(ValueError):
            http.set_write_api_version(4)

    # ---- write routing -----------------------------------------------

    def test_write_methods_route_to_v3_on_cloud(self, monkeypatch):
        from jira_cli import http

        monkeypatch.setenv("JIRA_API_VERSION", "3")
        captured_urls = []

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"{}"

        def fake_urlopen(req, timeout=None):
            captured_urls.append(req.full_url)
            return FakeResp()

        monkeypatch.setattr("jira_cli.http.urllib.request.urlopen", fake_urlopen)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        http.jira_post(cfg, "issue", {"fields": {}})
        http.jira_put(cfg, "issue/P-1", {"fields": {}})
        http.jira_delete(cfg, "issue/P-1")
        http.jira_get(cfg, "issue/P-1")

        assert captured_urls[0].startswith("https://jira.x/rest/api/3/issue")
        assert captured_urls[1].startswith("https://jira.x/rest/api/3/issue/P-1")
        assert captured_urls[2].startswith("https://jira.x/rest/api/3/issue/P-1")
        # reads always stay on v2
        assert captured_urls[3].startswith("https://jira.x/rest/api/2/issue/P-1")

    def test_write_methods_route_to_v2_on_server(self, monkeypatch):
        from jira_cli import http

        monkeypatch.setenv("JIRA_API_VERSION", "2")
        captured_urls = []

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"{}"

        monkeypatch.setattr(
            "jira_cli.http.urllib.request.urlopen",
            lambda req, timeout=None: (captured_urls.append(req.full_url), FakeResp())[1],
        )

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        http.jira_post(cfg, "issue", {"fields": {}})
        http.jira_put(cfg, "issue/P-1", {"fields": {}})

        assert captured_urls[0].startswith("https://jira.x/rest/api/2/issue")
        assert captured_urls[1].startswith("https://jira.x/rest/api/2/issue/P-1")

    # ---- body shaping -------------------------------------------------

    def test_description_body_v2_is_plain_string(self, monkeypatch):
        from jira_cli import http

        monkeypatch.setenv("JIRA_API_VERSION", "2")
        cfg = {"url": "https://x"}
        http.ensure_api_version_detected(cfg)
        assert http.description_body("h3. Hello") == "h3. Hello"
        assert http.comment_body("plain comment") == "plain comment"

    def test_description_body_v3_is_adf(self, monkeypatch):
        from jira_cli import http

        monkeypatch.setenv("JIRA_API_VERSION", "3")
        cfg = {"url": "https://x"}
        http.ensure_api_version_detected(cfg)
        doc = http.description_body("Hello")
        assert doc["type"] == "doc" and doc["version"] == 1
        assert doc["content"][0]["content"][0]["text"] == "Hello"
        assert http.comment_body("hello")["type"] == "doc"

    # ---- commands respect the detected version ------------------------

    def test_create_issue_v2_sends_plain_description(self, monkeypatch):
        from jira_cli.commands import cmd_create_issue
        from jira_cli import http

        monkeypatch.setenv("JIRA_API_VERSION", "2")
        mock_post = MagicMock(return_value={"key": "PROJ-1", "id": "1"})
        monkeypatch.setattr("jira_cli.commands.jira_post", mock_post)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_create_issue(cfg, "PROJ", "Summary", description="h3. Wiki markup")

        payload = mock_post.call_args[0][2]
        assert payload["fields"]["description"] == "h3. Wiki markup"

    def test_create_issue_v3_sends_adf_description(self, monkeypatch):
        from jira_cli.commands import cmd_create_issue

        monkeypatch.setenv("JIRA_API_VERSION", "3")
        mock_post = MagicMock(return_value={"key": "PROJ-1", "id": "1"})
        monkeypatch.setattr("jira_cli.commands.jira_post", mock_post)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_create_issue(cfg, "PROJ", "Summary", description="Hello")

        payload = mock_post.call_args[0][2]
        assert payload["fields"]["description"]["type"] == "doc"

    def test_issue_update_v2_sends_plain_description(self, monkeypatch):
        from jira_cli.commands import cmd_issue_update

        monkeypatch.setenv("JIRA_API_VERSION", "2")
        mock_put = MagicMock(return_value={})
        monkeypatch.setattr("jira_cli.commands.jira_put", mock_put)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_update(cfg, "PROJ-123", description="New desc", yes=True)

        payload = mock_put.call_args[0][2]
        assert payload["fields"]["description"] == "New desc"

    def test_issue_update_v3_sends_adf_description(self, monkeypatch):
        from jira_cli.commands import cmd_issue_update

        monkeypatch.setenv("JIRA_API_VERSION", "3")
        mock_put = MagicMock(return_value={})
        monkeypatch.setattr("jira_cli.commands.jira_put", mock_put)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_update(cfg, "PROJ-123", description="New desc", yes=True)

        payload = mock_put.call_args[0][2]
        assert payload["fields"]["description"]["type"] == "doc"

    def test_add_comment_v2_sends_plain_body(self, monkeypatch):
        from jira_cli.commands import cmd_issue_add_comment

        monkeypatch.setenv("JIRA_API_VERSION", "2")
        mock_post = MagicMock(return_value={"id": "9", "created": ""})
        monkeypatch.setattr("jira_cli.commands.jira_post", mock_post)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_add_comment(cfg, "TEST-1", "plain body")
        mock_post.assert_called_once_with(cfg, "issue/TEST-1/comment", {"body": "plain body"})

    def test_add_comment_v3_sends_adf_body(self, monkeypatch):
        from jira_cli.commands import cmd_issue_add_comment

        monkeypatch.setenv("JIRA_API_VERSION", "3")
        mock_post = MagicMock(return_value={"id": "9", "created": ""})
        monkeypatch.setattr("jira_cli.commands.jira_post", mock_post)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_add_comment(cfg, "TEST-1", "body")
        body = mock_post.call_args[0][2]["body"]
        assert body["type"] == "doc"

    def test_edit_comment_v2_sends_plain_body(self, monkeypatch):
        from jira_cli.commands import cmd_issue_update_comment

        monkeypatch.setenv("JIRA_API_VERSION", "2")
        mock_put = MagicMock(return_value={"updated": ""})
        monkeypatch.setattr("jira_cli.commands.jira_put", mock_put)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_update_comment(cfg, "PROJ-123", "54321", "Updated body", yes=True)
        mock_put.assert_called_once_with(
            cfg, "issue/PROJ-123/comment/54321", {"body": "Updated body"})

    def test_edit_comment_v3_sends_adf_body(self, monkeypatch):
        from jira_cli.commands import cmd_issue_update_comment

        monkeypatch.setenv("JIRA_API_VERSION", "3")
        mock_put = MagicMock(return_value={"updated": ""})
        monkeypatch.setattr("jira_cli.commands.jira_put", mock_put)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_update_comment(cfg, "PROJ-123", "54321", "Updated body", yes=True)
        body = mock_put.call_args[0][2]["body"]
        assert body["type"] == "doc"

    def test_link_v2_sends_plain_comment(self, monkeypatch):
        from jira_cli.commands import cmd_link_issues

        monkeypatch.setenv("JIRA_API_VERSION", "2")
        mock_post = MagicMock(return_value={})
        monkeypatch.setattr("jira_cli.commands.jira_post", mock_post)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_link_issues(cfg, "PROJ-123", "PROJ-456", link_type="Blocks", comment="Depends")
        payload = mock_post.call_args[0][2]
        assert payload["comment"] == {"body": "Depends"}

    def test_link_v3_sends_adf_comment(self, monkeypatch):
        from jira_cli.commands import cmd_link_issues

        monkeypatch.setenv("JIRA_API_VERSION", "3")
        mock_post = MagicMock(return_value={})
        monkeypatch.setattr("jira_cli.commands.jira_post", mock_post)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_link_issues(cfg, "PROJ-123", "PROJ-456", comment="Depends")
        payload = mock_post.call_args[0][2]
        assert payload["comment"]["body"]["type"] == "doc"


class TestCommandsAttach:
    """Upload attachment files to an issue."""

    def test_attach_single(self, monkeypatch, tmp_path, capsys):
        from jira_cli.commands import cmd_issue_attach

        f = tmp_path / "a.txt"
        f.write_text("hi")
        mock_attach = MagicMock(return_value=[{"id": "10001", "filename": "a.txt", "size": 2}])
        monkeypatch.setattr("jira_cli.commands.jira_post_attachment", mock_attach)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        result = cmd_issue_attach(cfg, "PROJ-123", [str(f)])

        mock_attach.assert_called_once_with(cfg, "PROJ-123", [str(f)])
        captured = capsys.readouterr()
        assert "a.txt" in captured.out and "10001" in captured.out
        assert result[0]["filename"] == "a.txt"

    def test_attach_multiple_files(self, monkeypatch, tmp_path):
        from jira_cli.commands import cmd_issue_attach

        f1 = tmp_path / "a.txt"
        f1.write_text("hi")
        f2 = tmp_path / "b.png"
        f2.write_text("x")
        mock_attach = MagicMock(return_value=[])
        monkeypatch.setattr("jira_cli.commands.jira_post_attachment", mock_attach)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_attach(cfg, "PROJ-123", [str(f1), str(f2)])

        mock_attach.assert_called_once_with(cfg, "PROJ-123", [str(f1), str(f2)])

    def test_attach_empty_response(self, monkeypatch, tmp_path, capsys):
        from jira_cli.commands import cmd_issue_attach

        f = tmp_path / "a.txt"
        f.write_text("hi")
        monkeypatch.setattr("jira_cli.commands.jira_post_attachment", MagicMock(return_value={}))

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        result = cmd_issue_attach(cfg, "PROJ-123", [str(f)])

        assert result == []
        captured = capsys.readouterr()
        assert "Attached to PROJ-123" in captured.out

    def test_attach_missing_file_exits(self, monkeypatch, tmp_path, capsys):
        from jira_cli.commands import cmd_issue_attach

        mock_attach = MagicMock()
        monkeypatch.setattr("jira_cli.commands.jira_post_attachment", mock_attach)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        with pytest.raises(SystemExit):
            cmd_issue_attach(cfg, "PROJ-123", [str(tmp_path / "nope.txt")])

        mock_attach.assert_not_called()
        captured = capsys.readouterr()
        assert "file not found" in captured.err


class TestCommandsAttachments:
    """List attachments of an issue."""

    def test_list_table(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue_attachments

        mock_get = MagicMock(return_value={"fields": {"attachment": [
            {"id": "1", "filename": "a.txt", "size": 10,
             "author": {"displayName": "Alice"}, "created": "2024-01-01T00:00:00.000+0000"},
            {"id": "2", "filename": "b.png", "size": 20,
             "author": {"displayName": "Bob"}, "created": "2024-01-02T00:00:00.000+0000"},
        ]}})
        monkeypatch.setattr("jira_cli.commands.jira_get", mock_get)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        result = cmd_issue_attachments(cfg, "PROJ-123")

        assert len(result) == 2
        mock_get.assert_called_once_with(cfg, "issue/PROJ-123", {"fields": "attachment"})
        captured = capsys.readouterr()
        assert "Attachments for PROJ-123" in captured.out
        assert "a.txt" in captured.out and "b.png" in captured.out

    def test_list_json(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue_attachments

        monkeypatch.setattr("jira_cli.commands.jira_get", MagicMock(
            return_value={"fields": {"attachment": [{"id": "1", "filename": "a.txt"}]}}))

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_attachments(cfg, "PROJ-123", fmt="json")
        captured = capsys.readouterr()
        assert '"filename": "a.txt"' in captured.out

    def test_list_empty(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue_attachments

        monkeypatch.setattr("jira_cli.commands.jira_get", MagicMock(
            return_value={"fields": {}}))

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        assert cmd_issue_attachments(cfg, "PROJ-123") == []
        captured = capsys.readouterr()
        assert "No attachments." in captured.out


class TestCommandsDownload:
    """Download attachments of an issue."""

    def test_download_by_id(self, monkeypatch, tmp_path, capsys):
        from jira_cli.commands import cmd_issue_download_attachment

        mock_get = MagicMock(return_value={
            "filename": "report.pdf",
            "content": "https://jira.x/secure/attachment/21523/report.pdf",
        })
        monkeypatch.setattr("jira_cli.commands.jira_get", mock_get)
        mock_bin = MagicMock(return_value=b"%PDF-1.4 fake")
        monkeypatch.setattr("jira_cli.commands.jira_get_binary", mock_bin)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        saved = cmd_issue_download_attachment(cfg, "PROJ-123",
                                              attachment_ids=["21523"], dest_dir=str(tmp_path))

        assert saved == [str(tmp_path / "report.pdf")]
        assert (tmp_path / "report.pdf").read_bytes() == b"%PDF-1.4 fake"
        mock_get.assert_called_once_with(cfg, "attachment/21523")
        mock_bin.assert_called_once_with(cfg, "https://jira.x/secure/attachment/21523/report.pdf")
        captured = capsys.readouterr()
        assert "report.pdf" in captured.out

    def test_download_missing_content_url_exits(self, monkeypatch, tmp_path, capsys):
        from jira_cli.commands import cmd_issue_download_attachment

        monkeypatch.setattr("jira_cli.commands.jira_get", MagicMock(return_value={"filename": "a.txt"}))
        mock_bin = MagicMock()
        monkeypatch.setattr("jira_cli.commands.jira_get_binary", mock_bin)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        with pytest.raises(SystemExit):
            cmd_issue_download_attachment(cfg, "PROJ-123",
                                          attachment_ids=["1"], dest_dir=str(tmp_path))
        mock_bin.assert_not_called()
        captured = capsys.readouterr()
        assert "no download URL" in captured.err

    def test_download_all_when_no_ids(self, monkeypatch, tmp_path):
        from jira_cli.commands import cmd_issue_download_attachment

        mock_get = MagicMock(return_value={"fields": {"attachment": [
            {"id": "1", "filename": "a.txt", "content": "https://jira.x/secure/attachment/1/a.txt"},
            {"id": "2", "filename": "b.txt", "content": "https://jira.x/secure/attachment/2/b.txt"},
        ]}})
        monkeypatch.setattr("jira_cli.commands.jira_get", mock_get)
        monkeypatch.setattr("jira_cli.commands.jira_get_binary", MagicMock(return_value=b"x"))

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        saved = cmd_issue_download_attachment(cfg, "PROJ-123", dest_dir=str(tmp_path))

        assert len(saved) == 2
        assert (tmp_path / "a.txt").exists() and (tmp_path / "b.txt").exists()
        mock_get.assert_called_once_with(cfg, "issue/PROJ-123", {"fields": "attachment"})

    def test_download_none_exist(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue_download_attachment

        monkeypatch.setattr("jira_cli.commands.jira_get", MagicMock(return_value={"fields": {}}))
        monkeypatch.setattr("jira_cli.commands.jira_get_binary", MagicMock())

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        assert cmd_issue_download_attachment(cfg, "PROJ-123", dest_dir=".") == []
        captured = capsys.readouterr()
        assert "No attachments to download." in captured.out


class TestCommandsDeleteAttachment:
    """Delete attachments of an issue."""

    def test_delete_by_ids(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue_delete_attachment

        mock_del = MagicMock()
        monkeypatch.setattr("jira_cli.commands.jira_delete_attachment", mock_del)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        deleted = cmd_issue_delete_attachment(cfg, "PROJ-123", attachment_ids=["1", "2"], yes=True)

        assert deleted == ["1", "2"]
        assert mock_del.call_args_list == [call(cfg, "1"), call(cfg, "2")]
        captured = capsys.readouterr()
        assert "Deleted attachment 1 from PROJ-123" in captured.out

    def test_delete_all(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue_delete_attachment

        monkeypatch.setattr("jira_cli.commands.jira_get", MagicMock(
            return_value={"fields": {"attachment": [
                {"id": "1", "filename": "a.txt"},
                {"id": "2", "filename": "b.txt"},
            ]}}))
        mock_del = MagicMock()
        monkeypatch.setattr("jira_cli.commands.jira_delete_attachment", mock_del)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        deleted = cmd_issue_delete_attachment(cfg, "PROJ-123", all_attachments=True, yes=True)

        assert deleted == ["1", "2"]
        assert mock_del.call_count == 2
        captured = capsys.readouterr()
        assert "Deleted attachment 2 from PROJ-123" in captured.out

    def test_delete_none_exits_cleanly(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue_delete_attachment

        monkeypatch.setattr("jira_cli.commands.jira_get", MagicMock(return_value={"fields": {}}))
        mock_del = MagicMock()
        monkeypatch.setattr("jira_cli.commands.jira_delete_attachment", mock_del)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        assert cmd_issue_delete_attachment(cfg, "PROJ-123", all_attachments=True) == []
        mock_del.assert_not_called()
        captured = capsys.readouterr()
        assert "No attachments to delete." in captured.out


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

    def test_cmd_issue_json(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue

        mock_get = MagicMock(
            side_effect=[
                {
                    "key": "TEST-1",
                    "fields": {
                        "summary": "Test summary",
                        "status": {"name": "In Progress"},
                        "description": {
                            "type": "doc", "version": 1,
                            "content": [{"type": "paragraph", "content": [{"text": "Fix the bug", "type": "text"}]}],
                        },
                    },
                },
                {"comments": [
                    {"id": "7", "author": {"displayName": "Alice"}, "created": "2024-01-01T00:00:00.000+0000",
                     "body": {"type": "doc", "version": 1,
                              "content": [{"type": "paragraph", "content": [{"text": "Looks good", "type": "text"}]}]}},
                ]},
            ]
        )
        monkeypatch.setattr("jira_cli.commands.jira_get", mock_get)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue(cfg, "TEST-1", fmt="json")
        out = json.loads(capsys.readouterr().out)
        assert out["key"] == "TEST-1"
        assert out["summary"] == "Test summary"
        assert out["description"] == "Fix the bug"
        assert out["status"]["name"] == "In Progress"
        assert [c["body"] for c in out["comments"]] == ["Looks good"]
        assert out["comments"][0]["author"] == "Alice"
        assert "raw" not in out

    def test_cmd_issue_json_include_raw_v2_plain_bodies(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue

        mock_get = MagicMock(
            side_effect=[
                {"key": "TEST-1", "fields": {"summary": "S", "description": "Plain wiki text"}},
                {"comments": [
                    {"id": "1", "author": {"displayName": "Bob"}, "created": "2024-01-01T00:00:00.000+0000", "body": "Plain comment"},
                ]},
            ]
        )
        monkeypatch.setattr("jira_cli.commands.jira_get", mock_get)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue(cfg, "TEST-1", fmt="json", include_raw=True)
        out = json.loads(capsys.readouterr().out)
        assert out["description"] == "Plain wiki text"
        assert out["comments"][0]["body"] == "Plain comment"
        assert out["raw"]["key"] == "TEST-1"

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
            cmd_issue_update_status, cmd_issue_update_comment, cmd_projects,
            cmd_search, cmd_setup, cmd_create_issue, cmd_link_issues, cmd_issue_update,
        )
        for fn in [cmd_issue, cmd_issue_comments, cmd_issue_comment, cmd_issue_add_comment,
                   cmd_issue_update_status, cmd_issue_update_comment, cmd_projects,
                   cmd_search, cmd_setup, cmd_create_issue, cmd_link_issues, cmd_issue_update]:
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

    def test_parse_flags_create(self):
        from jira_cli.flags import parse_flags
        r, f = parse_flags([
            "--project", "BANKING", "--summary", "Fix bug", "--type", "Bug",
            "--description", "Some desc", "--priority", "High", "--assignee", "jane.doe",
        ])
        assert f["project"] == "BANKING"
        assert f["summary"] == "Fix bug"
        assert f["type"] == "Bug"
        assert f["description"] == "Some desc"
        assert f["priority"] == "High"
        assert f["assignee"] == "jane.doe"

    def test_parse_flags_link(self):
        from jira_cli.flags import parse_flags
        r, f = parse_flags(["--link-type", "Blocks", "--comment", "Depends"])
        assert f["link_type"] == "Blocks"
        assert f["comment"] == "Depends"

    def test_parse_flags_dir_all(self):
        from jira_cli.flags import parse_flags
        r, f = parse_flags(["--dir", "/tmp/x", "--all"])
        assert f["dir"] == "/tmp/x"
        assert f["all"] is True
        r, f = parse_flags([])
        assert f["dir"] is None
        assert f["all"] is False

    def test_parse_flags_json_alias(self):
        from jira_cli.flags import parse_flags
        r, f = parse_flags(["--json", "PROJ-1"])
        assert f["format"] == "json"
        assert r == ["PROJ-1"]

    def test_parse_flags_include_raw(self):
        from jira_cli.flags import parse_flags
        r, f = parse_flags(["--include-raw"])
        assert f["include_raw"] is True
        r, f = parse_flags([])
        assert f["include_raw"] is False


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

    def test_main_issue_format_json(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "--format", "json"])
        mock_cmd = MagicMock()
        monkeypatch.setattr("jira_cli.cli.cmd_issue", mock_cmd)
        from jira_cli.cli import main
        main()
        mock_cmd.assert_called_once()
        _, kwargs = mock_cmd.call_args
        assert kwargs["fmt"] == "json"
        assert kwargs["include_raw"] is False

    def test_main_issue_json_alias_include_raw(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "--json", "--include-raw"])
        mock_cmd = MagicMock()
        monkeypatch.setattr("jira_cli.cli.cmd_issue", mock_cmd)
        from jira_cli.cli import main
        main()
        mock_cmd.assert_called_once()
        _, kwargs = mock_cmd.call_args
        assert kwargs["fmt"] == "json"
        assert kwargs["include_raw"] is True

    def test_main_issue_comments(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "comments"])
        mock_cmd = MagicMock()
        monkeypatch.setattr("jira_cli.cli.cmd_issue_comments", mock_cmd)
        from jira_cli.cli import main
        main()
        mock_cmd.assert_called_once()

    def test_main_issue_transition(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "transition", "41"])
        mock_cmd = MagicMock()
        monkeypatch.setattr("jira_cli.cli.cmd_issue_update_status", mock_cmd)
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

    def test_main_issue_attach(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "attach", "a.txt"])
        mock_cmd = MagicMock()
        monkeypatch.setattr("jira_cli.cli.cmd_issue_attach", mock_cmd)
        from jira_cli.cli import main
        main()
        mock_cmd.assert_called_once()

    def test_main_issue_attachments(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "attachments"])
        mock_cmd = MagicMock()
        monkeypatch.setattr("jira_cli.cli.cmd_issue_attachments", mock_cmd)
        from jira_cli.cli import main
        main()
        mock_cmd.assert_called_once()
        assert mock_cmd.call_args[0][2] == "table"

    def test_main_issue_download(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "download", "21523", "--dir", "/tmp"])
        mock_cmd = MagicMock()
        monkeypatch.setattr("jira_cli.cli.cmd_issue_download_attachment", mock_cmd)
        from jira_cli.cli import main
        main()
        mock_cmd.assert_called_once()
        assert mock_cmd.call_args[1]["attachment_ids"] == ["21523"]
        assert mock_cmd.call_args[1]["dest_dir"] == "/tmp"

    def test_main_issue_delete_attachment(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "delete-attachment", "21523"])
        mock_cmd = MagicMock()
        monkeypatch.setattr("jira_cli.cli.cmd_issue_delete_attachment", mock_cmd)
        from jira_cli.cli import main
        main()
        mock_cmd.assert_called_once()
        assert mock_cmd.call_args[1]["attachment_ids"] == ["21523"]

    def test_main_create(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jira-cli", "create", "--project", "PROJ", "--summary", "New issue"])
        mock_cmd = MagicMock()
        monkeypatch.setattr("jira_cli.cli.cmd_create_issue", mock_cmd)
        from jira_cli.cli import main
        main()
        mock_cmd.assert_called_once()

    def test_main_create_missing_args(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "create", "--summary", "No project"])
        from jira_cli.cli import main
        with pytest.raises(SystemExit):
            main()
        captured = capsys.readouterr()
        assert "Usage" in captured.err

    def test_main_link(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jira-cli", "link", "PROJ-123", "PROJ-456"])
        mock_cmd = MagicMock()
        monkeypatch.setattr("jira_cli.cli.cmd_link_issues", mock_cmd)
        from jira_cli.cli import main
        main()
        mock_cmd.assert_called_once()

    def test_main_link_missing_second_key(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "link", "PROJ-123"])
        from jira_cli.cli import main
        with pytest.raises(SystemExit):
            main()
        captured = capsys.readouterr()
        assert "Usage" in captured.err

    def test_main_issue_update(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "update", "--summary", "New title"])
        mock_cmd = MagicMock()
        monkeypatch.setattr("jira_cli.cli.cmd_issue_update", mock_cmd)
        from jira_cli.cli import main
        main()
        mock_cmd.assert_called_once()

    def test_main_issue_update_help(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "update", "-h"])
        from jira_cli.cli import main
        main()
        captured = capsys.readouterr()
        assert "issue" in captured.out.lower()

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

    def test_main_issue_edit_comment_no_id(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "edit-comment"])
        from jira_cli.cli import main
        with pytest.raises(SystemExit):
            main()
        captured = capsys.readouterr()
        assert "Usage" in captured.err

    def test_main_issue_attach_no_files(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "attach"])
        from jira_cli.cli import main
        with pytest.raises(SystemExit):
            main()
        captured = capsys.readouterr()
        assert "Usage" in captured.err

    def test_main_issue_delete_attachment_no_ids(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["jira-cli", "issue", "PROJ-123", "delete-attachment"])
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

    def test_cmd_search_json_empty(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_search

        mock_get = MagicMock(return_value={"issues": [], "total": 0})
        monkeypatch.setattr("jira_cli.commands.jira_get", mock_get)

        cmd_search({"url": "https://jira.x", "user": "u", "pass": "p"}, "project=NONE", fmt="json")
        assert json.loads(capsys.readouterr().out) == []

    def test_cmd_issue_comments_json_empty(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue_comments

        mock_get = MagicMock(return_value={"comments": [], "total": 0})
        monkeypatch.setattr("jira_cli.commands.jira_get", mock_get)

        cmd_issue_comments({"url": "https://jira.x", "user": "u", "pass": "p"}, "TEST-1", fmt="json")
        assert json.loads(capsys.readouterr().out) == []

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

    def test_request_empty_response_body(self):
        from jira_cli.http import _request

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        mock_resp = MagicMock()
        mock_resp.read.return_value = b""
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        with patch("jira_cli.http.urllib.request.urlopen", return_value=mock_resp) as mock_open:
            result = _request(cfg, "POST", "issueLink", data={"type": {"name": "Relates"}})
        assert result == {}
        mock_open.assert_called_once()


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

    def test_bash_completion_has_new_commands(self, capsys):
        from jira_cli.completion import cmd_completion
        cmd_completion("bash")
        captured = capsys.readouterr()
        assert "create" in captured.out
        assert "link" in captured.out
        assert "update" in captured.out

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

    def test_eval_lines(self):
        from jira_cli.completion import eval_line
        assert eval_line("bash") == 'eval "$(jira-cli completion bash)"'
        assert eval_line("zsh") == 'eval "$(jira-cli completion zsh)"'
        assert eval_line("fish") == "jira-cli completion fish | source"

    def test_install_creates_marker_block(self, tmp_path):
        from jira_cli.completion import install_completion, START_MARKER, END_MARKER

        rc = tmp_path / "bashrc"
        rc.write_text("export EDITOR=vim\n", encoding="utf-8")
        path, changed = install_completion("bash", rcfile=str(rc))
        assert changed is True
        assert path == rc
        content = rc.read_text(encoding="utf-8")
        assert "export EDITOR=vim\n" in content            # existing content preserved
        assert START_MARKER in content and END_MARKER in content
        assert 'eval "$(jira-cli completion bash)"' in content
        assert (tmp_path / "bashrc.bak").is_file()         # backup created

    def test_install_is_idempotent(self, tmp_path):
        from jira_cli.completion import install_completion

        rc = tmp_path / "zshrc"
        rc.write_text("autoload -U compinit && compinit\n", encoding="utf-8")
        install_completion("zsh", rcfile=str(rc))
        first = rc.read_text(encoding="utf-8")
        path, changed = install_completion("zsh", rcfile=str(rc))
        assert changed is False
        assert rc.read_text(encoding="utf-8") == first      # byte-identical no-op
        assert first.count("jira-cli completion zsh") == 1  # no duplicate block

    def test_install_replaces_stale_block(self, tmp_path):
        from jira_cli.completion import install_completion, START_MARKER, END_MARKER

        rc = tmp_path / "bashrc"
        rc.write_text(
            f"{START_MARKER}\neval \"$(old-cmd completion bash)\"\n{END_MARKER}\n",
            encoding="utf-8",
        )
        path, changed = install_completion("bash", rcfile=str(rc))
        assert changed is True
        content = rc.read_text(encoding="utf-8")
        assert content.count(START_MARKER) == 1             # replaced, not duplicated
        assert "old-cmd" not in content
        assert 'eval "$(jira-cli completion bash)"' in content

    def test_install_zsh_ensures_compinit(self, tmp_path):
        from jira_cli.completion import install_completion

        rc = tmp_path / "zshrc"
        install_completion("zsh", rcfile=str(rc))
        content = rc.read_text(encoding="utf-8")
        assert "compinit" in content

    def test_install_unsupported_shell_raises(self, tmp_path):
        from jira_cli.completion import install_completion
        with pytest.raises(ValueError):
            install_completion("tcsh", rcfile=str(tmp_path / "rc"))

    def test_install_cmd_requires_yes_when_non_tty(self, tmp_path, monkeypatch, capsys):
        from jira_cli.completion import cmd_completion_install

        monkeypatch.delenv("SHELL", raising=False)
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        rc = tmp_path / "bashrc"
        with pytest.raises(SystemExit):
            cmd_completion_install(["bash", "--rcfile", str(rc)])
        assert "requires --yes" in capsys.readouterr().err

    def test_install_cmd_writes_with_yes(self, tmp_path, monkeypatch, capsys):
        from jira_cli.completion import cmd_completion_install

        rc = tmp_path / "bashrc"
        cmd_completion_install(["bash", "--rcfile", str(rc), "--yes"])
        err = capsys.readouterr().err
        assert "installed" in err
        assert 'eval "$(jira-cli completion bash)"' in rc.read_text(encoding="utf-8")

    def test_install_cmd_unknown_shell_exits(self, capsys):
        from jira_cli.completion import cmd_completion_install
        with pytest.raises(SystemExit):
            cmd_completion_install(["tcsh"])
        assert "Unknown shell" in capsys.readouterr().err

    def test_install_cmd_no_shell_detected_exits(self, monkeypatch, capsys):
        from jira_cli.completion import cmd_completion_install

        monkeypatch.delenv("SHELL", raising=False)
        with pytest.raises(SystemExit):
            cmd_completion_install([])
        assert "cannot detect shell" in capsys.readouterr().err

    def test_fish_completion_scoping_fixed(self, capsys):
        from jira_cli.completion import cmd_completion
        cmd_completion("fish")
        out = capsys.readouterr().out
        assert "set -l cmd" in out                      # function-local variables
        assert "jira-cll" not in out                    # no command-name typo
        assert "__fish_jira_cli_using_subcommand comments" in out  # matches issue subcommands
        assert "transition" in out and "edit-comment" in out

    def test_zsh_completion_ends_with_compdef(self, capsys):
        from jira_cli.completion import cmd_completion
        cmd_completion("zsh")
        out = capsys.readouterr().out
        assert out.rstrip().endswith("compdef _jira_cli jira-cli")

# -------------------------------------------------------------------
# Help texts
# -------------------------------------------------------------------


class TestHelpTexts:
    def test_help_texts_exist(self):
        from jira_cli.help_texts import HELP
        for t in ["main", "search", "issue", "projects", "setup", "create", "link"]:
            assert len(HELP.get(t, "")) > 50

    def test_help_contains_new_commands(self):
        from jira_cli.help_texts import HELP
        main = HELP["main"]
        assert "update-description" not in main
        assert "transition" in main
        assert "edit-comment" in main
        assert "create" in main
        assert "link" in main
        assert "issue <KEY> update" in main
        assert "issue <KEY> assign" not in main

    def test_print_help(self, capsys):
        from jira_cli.help_texts import print_help
        print_help("main")
        captured = capsys.readouterr()
        assert "JIRA-CLI HELP" in captured.out


class TestVersionFlag:
    def test_version_flag(self, monkeypatch, capsys):
        from jira_cli.cli import main
        from jira_cli import __version__

        monkeypatch.setattr("sys.argv", ["jira-cli", "--version"])
        main()
        captured = capsys.readouterr()
        assert captured.out.strip() == f"jira-cli {__version__}"


class TestDestructiveGuards:
    @pytest.fixture(autouse=True)
    def _force_v2(self, monkeypatch):
        """Keep dry-run/execute tests off the network via forced API version."""
        monkeypatch.setenv("JIRA_API_VERSION", "2")

    def test_dry_run_update_prints_request(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue_update

        mock_put = MagicMock()
        monkeypatch.setattr("jira_cli.commands.jira_put", mock_put)
        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_update(cfg, "PROJ-123", summary="New title", dry_run=True)
        out = capsys.readouterr().out
        assert "DRY-RUN" in out
        assert "PUT issue/PROJ-123" in out
        assert '"summary": "New title"' in out
        mock_put.assert_not_called()                     # nothing sent

    def test_dry_run_edit_comment_prints_request(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue_update_comment

        mock_put = MagicMock()
        monkeypatch.setattr("jira_cli.commands.jira_put", mock_put)
        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_update_comment(cfg, "PROJ-123", "54321", "New body", dry_run=True)
        out = capsys.readouterr().out
        assert "PUT issue/PROJ-123/comment/54321" in out
        assert '"New body"' in out
        mock_put.assert_not_called()

    def test_dry_run_delete_attachment_prints_ids(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue_delete_attachment

        mock_del = MagicMock()
        monkeypatch.setattr("jira_cli.commands.jira_delete_attachment", mock_del)
        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_delete_attachment(cfg, "PROJ-123", attachment_ids=["1", "2"], dry_run=True)
        out = capsys.readouterr().out
        assert "DELETE" in out and "attachment_ids" in out
        mock_del.assert_not_called()

    def test_non_tty_without_yes_refuses(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue_update

        mock_put = MagicMock()
        monkeypatch.setattr("jira_cli.commands.jira_put", mock_put)
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        with pytest.raises(SystemExit) as excinfo:
            cmd_issue_update(cfg, "PROJ-123", summary="New title")
        assert excinfo.value.code == 2
        err = capsys.readouterr().err
        assert "--yes" in err and "--dry-run" in err
        mock_put.assert_not_called()

    def test_tty_confirm_yes_executes(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue_update

        mock_put = MagicMock(return_value={})
        monkeypatch.setattr("jira_cli.commands.jira_put", mock_put)
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda prompt="": "y")
        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_update(cfg, "PROJ-123", summary="New title")
        mock_put.assert_called_once()

    def test_tty_confirm_declined_aborts(self, monkeypatch, capsys):
        from jira_cli.commands import cmd_issue_update

        mock_put = MagicMock()
        monkeypatch.setattr("jira_cli.commands.jira_put", mock_put)
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda prompt="": "n")
        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        with pytest.raises(SystemExit):
            cmd_issue_update(cfg, "PROJ-123", summary="New title")
        assert "Aborted" in capsys.readouterr().err
        mock_put.assert_not_called()


class TestNetworkFlags:
    def _reset(self):
        from jira_cli.http import _reset_network_settings
        _reset_network_settings()

    def test_extract_network_flags_sets_settings(self, monkeypatch):
        from jira_cli import http
        from jira_cli.cli import _extract_network_flags

        self._reset()
        monkeypatch.setattr("sys.argv", ["jira-cli", "search", "--timeout", "5", "project=X", "--retries", "3", "--retry-delay", "0.5"])
        _extract_network_flags()
        assert http.get_network_settings() == (5.0, 3, 0.5)
        assert sys.argv == ["jira-cli", "search", "project=X"]   # flags stripped
        self._reset()

    def test_extract_network_flags_ignores_bad_values(self, monkeypatch, capsys):
        from jira_cli.cli import _extract_network_flags

        monkeypatch.setattr("sys.argv", ["jira-cli", "search", "--timeout", "abc"])
        with pytest.raises(SystemExit):
            _extract_network_flags()
        assert "numeric" in capsys.readouterr().err

    def test_send_retries_with_backoff(self, monkeypatch):
        from jira_cli import http

        self._reset()
        http.set_network_settings(timeout=5, retries=2, retry_delay=0.0)
        sleeps = []
        monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{"ok": true}'

        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(1)
            if len(calls) < 3:
                raise urllib.error.URLError("connection reset")
            return FakeResp()

        monkeypatch.setattr(http.urllib.request, "urlopen", fake_urlopen)
        req = urllib.request.Request("https://jira.x/rest/api/2/project")
        assert http._send(req) == {"ok": True}
        assert len(calls) == 3
        assert sleeps == [0.0, 0.0]                      # exponential, base 0
        self._reset()

    def test_send_retries_http_5xx(self, monkeypatch):
        from jira_cli import http

        self._reset()
        http.set_network_settings(retries=1, retry_delay=0.0)
        monkeypatch.setattr("time.sleep", lambda s: None)

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"{}"

        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.HTTPError(req.full_url, 503, "unavailable", {}, io.BytesIO(b""))
            return FakeResp()

        monkeypatch.setattr(http.urllib.request, "urlopen", fake_urlopen)
        req = urllib.request.Request("https://jira.x/rest/api/2/project")
        assert http._send(req) == {}
        assert len(calls) == 2
        self._reset()

    def test_send_no_retry_on_4xx(self, monkeypatch):
        from jira_cli import http

        self._reset()
        http.set_network_settings(retries=3, retry_delay=0.0)
        monkeypatch.setattr("time.sleep", lambda s: None)

        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 404, "not found", {}, io.BytesIO(b""))

        monkeypatch.setattr(http.urllib.request, "urlopen", fake_urlopen)
        req = urllib.request.Request("https://jira.x/rest/api/2/nope")
        with pytest.raises(SystemExit):
            http._send(req)
        self._reset()

    def test_send_write_retries_pre_send_error(self, monkeypatch):
        from jira_cli import http

        self._reset()
        http.set_network_settings(retries=2, retry_delay=0.0)
        monkeypatch.setattr("time.sleep", lambda s: None)

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"{}"

        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.URLError(ConnectionRefusedError(111, "refused"))
            return FakeResp()

        monkeypatch.setattr(http.urllib.request, "urlopen", fake_urlopen)
        req = urllib.request.Request(
            "https://jira.x/rest/api/2/issue", data=b"{}", method="POST")
        assert http._send(req) == {}
        assert len(calls) == 2                     # connection refused = never sent → retried
        self._reset()

    def test_send_write_not_retried_on_ambiguous_error(self, monkeypatch):
        from jira_cli import http

        self._reset()
        http.set_network_settings(retries=3, retry_delay=0.0)
        monkeypatch.setattr("time.sleep", lambda s: None)

        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(1)
            raise urllib.error.URLError("SSL: EOF occurred mid-request")

        monkeypatch.setattr(http.urllib.request, "urlopen", fake_urlopen)
        req = urllib.request.Request(
            "https://jira.x/rest/api/2/issue", data=b"{}", method="POST")
        with pytest.raises(SystemExit):
            http._send(req)
        assert len(calls) == 1                     # may have reached server → never retried
        self._reset()

    def test_send_write_not_retried_on_5xx(self, monkeypatch):
        from jira_cli import http

        self._reset()
        http.set_network_settings(retries=3, retry_delay=0.0)
        monkeypatch.setattr("time.sleep", lambda s: None)

        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(1)
            raise urllib.error.HTTPError(req.full_url, 502, "bad gateway", {}, io.BytesIO(b""))

        monkeypatch.setattr(http.urllib.request, "urlopen", fake_urlopen)
        req = urllib.request.Request(
            "https://jira.x/rest/api/2/issue", data=b"{}", method="POST")
        with pytest.raises(SystemExit):
            http._send(req)
        assert len(calls) == 1                     # 5xx response on write → not retried
        self._reset()


class TestAgileFields:
    """Resolution / Story Points / Sprint extraction and output."""

    SPRINT_RAW = (
        "com.atlassian.greenhopper.service.sprint.Sprint@9"
        "[id=9,name=Alpha,state=ACTIVE,goal=,startDate=2024-01-01]"
    )

    def _isolate_cache(self, monkeypatch, tmp_path):
        from jira_cli import fields as _fields_mod

        monkeypatch.setenv("JIRA_CLI_FIELD_CACHE_DIR", str(tmp_path))
        _fields_mod._reset_field_cache()

    def _fields(self):
        return {
            "summary": "S",
            "status": {"name": "Done"},
            "priority": {"name": "High"},
            "assignee": {"displayName": "A"},
            "created": "2024-01-01T00:00:00.000+0000",
            "resolution": {"name": "Fixed"},
            "customfield_10016": 3,
            "customfield_10020": [self.SPRINT_RAW],
        }

    def test_extract_greenhopper_shapes(self):
        from jira_cli.fields import extract_agile_fields

        agile = extract_agile_fields(self._fields())
        assert agile == {
            "resolution": "Fixed",
            "story_points": 3,
            "sprint": ["Alpha (ACTIVE)"],
            "sprints": [{"id": 9, "name": "Alpha", "state": "ACTIVE",
                         "start": "2024-01-01", "end": ""}],
            "epic_key": None,
        }

    def test_extract_absent_and_bool_safe(self):
        from jira_cli.fields import extract_agile_fields

        assert extract_agile_fields({}) == {
            "resolution": None, "story_points": None, "sprint": [],
            "sprints": [], "epic_key": None,
        }
        agile = extract_agile_fields({"resolution": None, "customfield_1": True})
        assert agile["story_points"] is None
        assert agile["sprint"] == []
        assert agile["sprints"] == []
        assert agile["epic_key"] is None

    def test_extract_dict_sprint(self):
        from jira_cli.fields import extract_agile_fields

        agile = extract_agile_fields({"customfield_2": [{"name": "Beta", "state": "CLOSED"}]})
        assert agile["sprint"] == ["Beta (CLOSED)"]
        assert agile["sprints"] == [{"id": None, "name": "Beta", "state": "CLOSED",
                                    "start": "", "end": ""}]

    def test_search_table_suffix(self, monkeypatch, capsys, tmp_path):
        from jira_cli.commands import cmd_search

        self._isolate_cache(monkeypatch, tmp_path)
        mock_get = MagicMock(return_value={
            "issues": [{"key": "T-1", "fields": self._fields()}], "total": 1,
        })
        monkeypatch.setattr("jira_cli.commands.jira_get", mock_get)
        monkeypatch.setattr("jira_cli.fields.get_custom_field_ids",
                            lambda cfg, project=None: {"story_points": None, "sprint": None, "epic_link": None})
        cmd_search({"url": "https://jira.x", "user": "u", "pass": "p"}, "project=T")
        out = capsys.readouterr().out
        assert "Resolution: Fixed | SP: 3 | Sprint: Alpha (ACTIVE)" in out
        _, params = mock_get.call_args[0][1], mock_get.call_args[0][2]
        assert "resolution" in params["fields"]
        assert "*navigable" in params["fields"]

    def test_search_json_curated_keys(self, monkeypatch, capsys, tmp_path):
        from jira_cli.commands import cmd_search

        self._isolate_cache(monkeypatch, tmp_path)
        mock_get = MagicMock(return_value={
            "issues": [{"key": "T-1", "fields": self._fields()}], "total": 1,
        })
        monkeypatch.setattr("jira_cli.commands.jira_get", mock_get)
        monkeypatch.setattr("jira_cli.fields.get_custom_field_ids",
                            lambda cfg, project=None: {"story_points": None, "sprint": None, "epic_link": None})
        cmd_search({"url": "https://jira.x", "user": "u", "pass": "p"}, "project=T", fmt="json")
        payload = json.loads(capsys.readouterr().out)
        assert payload[0]["fields"]["story_points"] == 3
        assert payload[0]["fields"]["sprint"] == ["Alpha (ACTIVE)"]

    def test_issue_table_and_json(self, monkeypatch, capsys, tmp_path):
        from jira_cli.commands import cmd_issue

        self._isolate_cache(monkeypatch, tmp_path)
        detail = {"key": "T-1", "fields": dict(
            self._fields(), project={"name": "P", "key": "T"})}
        monkeypatch.setattr("jira_cli.fields.get_custom_field_ids",
                            lambda cfg, project=None: {"story_points": None, "sprint": None, "epic_link": None})
        mock_get = MagicMock(side_effect=[detail, {"comments": [], "total": 0}])
        monkeypatch.setattr("jira_cli.commands.jira_get", mock_get)
        cmd_issue({"url": "https://jira.x", "user": "u", "pass": "p"}, "T-1")
        out = capsys.readouterr().out
        assert "Resolution: Fixed" in out
        assert "Story Points: 3" in out
        assert "Sprint:    Alpha (ACTIVE)" in out

        mock_get = MagicMock(side_effect=[detail, {"comments": [], "total": 0}])
        monkeypatch.setattr("jira_cli.commands.jira_get", mock_get)
        cmd_issue({"url": "https://jira.x", "user": "u", "pass": "p"}, "T-1", fmt="json")
        payload = json.loads(capsys.readouterr().out)
        assert payload["resolution"] == "Fixed"
        assert payload["story_points"] == 3
        assert payload["sprint"] == ["Alpha (ACTIVE)"]


@pytest.mark.real_field_cache
class TestFieldIdCache:
    """Monthly per-domain+project cache for GET /rest/api/2/field."""

    CFG = {"url": "https://jira.example.com", "user": "u", "pass": "p"}

    FIELD_LIST = [
        {"id": "customfield_10016", "name": "Original Story Points"},
        {"id": "customfield_10020", "name": "Sprint"},
        {"id": "customfield_10021", "name": "Epic Link"},
        {"id": "summary", "name": "Summary"},
    ]
    EXPECTED_IDS = {"story_points": "customfield_10016", "sprint": "customfield_10020",
                    "epic_link": "customfield_10021"}

    def _isolate(self, monkeypatch, tmp_path):
        from jira_cli import fields as _fields_mod

        monkeypatch.setenv("JIRA_CLI_FIELD_CACHE_DIR", str(tmp_path))
        _fields_mod._reset_field_cache()
        return _fields_mod

    def test_fetch_cached_by_domain_and_project(self, monkeypatch, tmp_path):
        mod = self._isolate(monkeypatch, tmp_path)
        seen = []

        def fake_get(cfg, path, params=None):
            seen.append((cfg, path))
            return list(self.FIELD_LIST)

        monkeypatch.setattr("jira_cli.http.jira_get", fake_get)
        ids = mod.get_custom_field_ids(self.CFG, "BANKING")
        assert ids == self.EXPECTED_IDS
        assert seen == [(self.CFG, "field")]

        # Second call: memory cache, no new fetch.
        assert mod.get_custom_field_ids(self.CFG, "BANKING") == ids
        assert len(seen) == 1

        # New process (memory cleared): fresh file cache, still no fetch.
        mod._reset_field_cache()
        assert mod.get_custom_field_ids(self.CFG, "BANKING") == ids
        assert len(seen) == 1

    def test_project_scoping(self, monkeypatch, tmp_path):
        mod = self._isolate(monkeypatch, tmp_path)
        calls = []

        def fake_get(cfg, path, params=None):
            calls.append(path)
            return list(self.FIELD_LIST)

        monkeypatch.setattr("jira_cli.http.jira_get", fake_get)
        mod.get_custom_field_ids(self.CFG, "A")
        mod.get_custom_field_ids(self.CFG, "B")
        assert len(calls) == 2
        files = sorted(p.name for p in tmp_path.iterdir())
        assert len(files) == 2 and files[0] != files[1]

    def test_expiry_refetches_after_30d(self, monkeypatch, tmp_path):
        mod = self._isolate(monkeypatch, tmp_path)
        monkeypatch.setattr("jira_cli.http.jira_get", lambda c, p, params=None: list(self.FIELD_LIST))
        mod.get_custom_field_ids(self.CFG, "P")
        path = mod._cache_path(self.CFG["url"], "P")
        with open(path) as f:
            data = json.load(f)
        data["fetched_at"] -= mod.FIELD_CACHE_TTL + 1
        with open(path, "w") as f:
            json.dump(data, f)

        calls = []
        monkeypatch.setattr(
            "jira_cli.http.jira_get",
            lambda c, p, params=None: calls.append(p) or list(self.FIELD_LIST),
        )
        mod._reset_field_cache()
        assert mod.get_custom_field_ids(self.CFG, "P")["sprint"] == "customfield_10020"
        assert calls == ["field"]

    def test_fetch_failure_falls_back_to_stale(self, monkeypatch, tmp_path):
        mod = self._isolate(monkeypatch, tmp_path)
        monkeypatch.setattr("jira_cli.http.jira_get", lambda c, p, params=None: list(self.FIELD_LIST))
        mod.get_custom_field_ids(self.CFG, "P")
        path = mod._cache_path(self.CFG["url"], "P")
        with open(path) as f:
            data = json.load(f)
        data["fetched_at"] -= mod.FIELD_CACHE_TTL + 1
        with open(path, "w") as f:
            json.dump(data, f)

        def boom(cfg, path_, params=None):
            raise OSError("offline")

        monkeypatch.setattr("jira_cli.http.jira_get", boom)
        mod._reset_field_cache()
        ids = mod.get_custom_field_ids(self.CFG, "P")
        assert ids == self.EXPECTED_IDS

    def test_exact_ids_preferred_over_shape(self, monkeypatch, tmp_path):
        mod = self._isolate(monkeypatch, tmp_path)
        monkeypatch.setattr(
            "jira_cli.http.jira_get",
            lambda c, p, params=None: [
                {"id": "customfield_77777", "name": "Story Points"},
                {"id": "customfield_88888", "name": "Sprint"},
            ],
        )
        fields = {
            "customfield_77777": 8,
            "customfield_10016": 99,
            "customfield_88888": [{"name": "Gamma", "state": "ACTIVE"}],
        }
        agile = mod.extract_agile_fields(fields, self.CFG, "P")
        assert agile["story_points"] == 8
        assert agile["sprint"] == ["Gamma (ACTIVE)"]

@pytest.mark.real_field_cache
class TestPlannerSupport:
    """F1-F7 mock tests: SP regression, sprint parsing, paging, changelog, moves."""

    CFG = {"url": "https://tribe.jibit.cloud", "user": "u", "pass": "p"}
    SPRINT_RAW = (
        "com.atlassian.greenhopper.service.sprint.Sprint@1"
        "[id=547,name=IPG Sprint 66,state=ACTIVE,startDate=2026-09-01T00:00:00.000,"
        "endDate=2026-10-15T00:00:00.000,completeDate=<null>,goal=]"
    )

    def _isolate(self, monkeypatch, tmp_path):
        from jira_cli import fields as mod
        monkeypatch.setenv("JIRA_CLI_FIELD_CACHE_DIR", str(tmp_path / "fc"))
        mod._reset_field_cache()
        return mod

    def _field_list(self):
        return [
            {"id": "customfield_10104", "name": "Original story points"},
            {"id": "customfield_10108", "name": "Sprint"},
            {"id": "customfield_10109", "name": "Epic Link"},
        ]

    def test_sp_regression_original_story_points(self, monkeypatch, tmp_path):
        """cf_10104=3.0 named 'Original story points' -> story_points 3.0 (was null)."""
        mod = self._isolate(monkeypatch, tmp_path)
        monkeypatch.setattr("jira_cli.http.jira_get", lambda c, p, params=None: self._field_list())
        ids = mod.get_custom_field_ids(self.CFG, "IPG")
        assert ids["story_points"] == "customfield_10104"
        agile = mod.extract_agile_fields({"customfield_10104": 3.0}, self.CFG, "IPG")
        assert agile["story_points"] == 3.0

    def test_sprint_string_parsing(self):
        from jira_cli.fields import parse_sprints, parse_sprint_value
        out = parse_sprints([self.SPRINT_RAW])
        assert out == [{"id": 547, "name": "IPG Sprint 66", "state": "ACTIVE",
                        "start": "2026-09-01T00:00:00.000",
                        "end": "2026-10-15T00:00:00.000"}]
        assert parse_sprint_value([self.SPRINT_RAW]) == ["IPG Sprint 66 (ACTIVE)"]
        cloud = parse_sprints([{"id": 9, "name": "S1", "state": "closed",
                                "startDate": "2024-01-01", "endDate": "2024-01-15"}])
        assert cloud[0]["state"] == "closed"

    def test_search_pagination_envelope(self, monkeypatch, capsys, tmp_path):
        from jira_cli.commands import cmd_search
        self._isolate(monkeypatch, tmp_path)
        pages = [
            {"issues": [{"key": f"IPG-{i}", "fields": {"summary": "s"}} for i in (1, 2)],
             "total": 3, "maxResults": 2},
            {"issues": [{"key": "IPG-3", "fields": {"summary": "s"}}], "total": 3, "maxResults": 2},
        ]
        calls = {"n": 0}
        def fake_search(cfg, path, params=None):
            assert path == "search"
            page = pages[calls["n"]]
            calls["n"] += 1
            return page
        def fake_field(cfg, path, params=None):
            return list(self._field_list())
        monkeypatch.setattr("jira_cli.commands.jira_get", fake_search)
        monkeypatch.setattr("jira_cli.fields.get_custom_field_ids",
                            lambda cfg, project=None: {"story_points": "customfield_10104",
                                                      "sprint": "customfield_10108",
                                                      "epic_link": "customfield_10109"})
        out = cmd_search(self.CFG, "project=IPG", limit=2, fmt="json",
                         fetch_all=True, max_results=1000, envelope=True)
        assert out["total"] == 3 and out["returned"] == 3
        assert [i["key"] for i in out["issues"]] == ["IPG-1", "IPG-2", "IPG-3"]
        assert out["next_start_at"] is None
        payload = json.loads(capsys.readouterr().out)
        assert payload["total"] == 3
        # Persian text survives ensure_ascii=False
        assert "\\u" not in capsys.readouterr().out

    def test_search_persian_not_escaped(self, monkeypatch, capsys, tmp_path):
        from jira_cli.commands import cmd_search
        self._isolate(monkeypatch, tmp_path)
        monkeypatch.setattr("jira_cli.commands.jira_get", MagicMock(return_value={
            "issues": [{"key": "IPG-1", "fields": {"summary": "رفع باگ ورود"}}], "total": 1}))
        monkeypatch.setattr("jira_cli.fields.get_custom_field_ids",
                            lambda cfg, project=None: {"story_points": "customfield_10104",
                                                      "sprint": "customfield_10108",
                                                      "epic_link": "customfield_10109"})
        cmd_search(self.CFG, "project=IPG", fmt="json")
        assert "رفع باگ ورود" in capsys.readouterr().out

    def test_changelog_filtering_and_backfill(self, monkeypatch):
        from jira_cli.changelog import normalize_histories, iter_full_histories
        histories = [
            {"created": "2026-10-01T10:00:00.000+0000",
             "author": {"name": "jdoe", "displayName": "John Doe"},
             "items": [
                 {"field": "status", "fromString": "To Do", "toString": "In Progress"},
                 {"field": "assignee", "from": "a", "fromString": "Ann",
                  "to": "jdoe", "toString": "John Doe"},
                 {"field": "summary", "fromString": "x", "toString": "y"}]},
        ]
        entries = normalize_histories(histories, ["assignee", "status", "sprint"])
        assert [(e["field"], e["from"], e["to"]) for e in entries] == [
            ("status", "To Do", "In Progress"),
            ("assignee", "a (Ann)", "jdoe (John Doe)"),
        ]
        # truncated inline histories backfilled via issue/K/changelog
        block = {"histories": histories[:1], "total": 2, "maxResults": 1}
        extra = {"histories": [{"created": "2026-10-02T00:00:00.000+0000",
                                "author": "bot", "items": []}], "total": 2}
        calls = []
        def fake_get(cfg, path, params=None):
            calls.append((path, params))
            return extra
        full = list(iter_full_histories(self.CFG, "IPG-1", block, fake_get))
        assert len(full) == 2
        assert calls[0][0] == "issue/IPG-1/changelog"

    def test_move_writes_journal_before_first_write(self, monkeypatch, tmp_path):
        from jira_cli import agile as A
        journal = str(tmp_path / "j.json")
        events = []
        monkeypatch.setattr("jira_cli.agile.jira_get",
                            lambda c, p, params=None: {"key": "IPG-1", "fields": {}})
        orig_write = A._write_journal
        def spy_write(path, payload):
            events.append("journal")
            return orig_write(path, payload)
        monkeypatch.setattr(A, "_write_journal", spy_write)
        membership = {"now": [547]}
        monkeypatch.setattr(A, "_current_sprint_ids", lambda c, k, sid=None: list(membership["now"]))
        def spy_post_and_flip(cfg, path, data):
            events.append(("post", path))
            assert events[0] == "journal", "write happened before journal!"
            membership["now"] = [548]
            return {}
        monkeypatch.setattr(A, "agile_post", spy_post_and_flip)
        A.cmd_sprint_move(self.CFG, "548", ["IPG-1"], journal=journal, yes=True)
        assert events[0] == "journal"
        assert ("post", "sprint/548/issue") in events
        saved = json.loads(open(journal, encoding="utf-8").read())
        assert saved["items"][0] == {"key": "IPG-1", "from_sprint_ids": [547], "to": "548"}
        import stat
        assert stat.S_IMODE(os.stat(journal).st_mode) == 0o600

    def test_dry_run_makes_zero_writes(self, monkeypatch, tmp_path):
        from jira_cli import agile as A
        posts = []
        monkeypatch.setattr("jira_cli.agile.jira_get",
                            lambda c, p, params=None: {"key": "IPG-1", "fields": {}})
        monkeypatch.setattr(A, "agile_post",
                            lambda c, p, d: posts.append((p, d)) or {})
        monkeypatch.setattr(A, "_current_sprint_ids", lambda c, k, sid=None: [547])
        A.cmd_sprint_move(self.CFG, "548", ["IPG-1"],
                          journal=str(tmp_path / "j.json"), dry_run=True)
        A.cmd_backlog_move(self.CFG, ["IPG-1"],
                           journal=str(tmp_path / "j2.json"), dry_run=True)
        assert posts == []

    def test_verify_mismatch_exits_nonzero(self, monkeypatch, tmp_path):
        from jira_cli import agile as A
        monkeypatch.setattr("jira_cli.agile.jira_get",
                            lambda c, p, params=None: {"key": "IPG-1", "fields": {}})
        monkeypatch.setattr(A, "agile_post", lambda c, p, d: {})
        monkeypatch.setattr(A, "_current_sprint_ids", lambda c, k, sid=None: [])
        with pytest.raises(SystemExit) as e:
            A.cmd_sprint_move(self.CFG, "548", ["IPG-1"],
                              journal=str(tmp_path / "j.json"), yes=True)
        assert e.value.code != 0

    def test_restore_round_trip(self, monkeypatch, tmp_path):
        from jira_cli import agile as A
        journal = tmp_path / "move.json"
        before = json.dumps({"created_at": "t", "user": "u",
                             "base_url": "b", "action": "sprint.move",
                             "items": [{"key": "IPG-1", "from_sprint_ids": [547],
                                        "to": "548"}]})
        journal.write_text(before)
        posts = []
        monkeypatch.setattr("jira_cli.agile.jira_get",
                            lambda c, p, params=None: {"key": "IPG-1", "fields": {}})
        monkeypatch.setattr(A, "agile_get",
                            lambda c, p, params=None: {"id": 547, "name": "S",
                                                      "state": "ACTIVE"})
        monkeypatch.setattr(A, "agile_post", lambda c, p, d: posts.append(p) or {})
        # membership flips to the destination after the write
        monkeypatch.setattr(A, "_current_sprint_ids", lambda c, k, sid=None: [547])
        monkeypatch.chdir(tmp_path)
        audit_path = A.cmd_sprint_restore(self.CFG, str(journal), yes=True)
        assert "sprint/547/issue" in posts
        # source journal untouched; separate audit file returned
        assert journal.read_text() == before
        assert audit_path != str(journal)
        audit = json.loads(open(audit_path, encoding="utf-8").read())
        assert audit["action"] == "sprint.restore"
        assert audit["restores"] == str(journal)
