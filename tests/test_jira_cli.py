"""Comprehensive pytest suite for jira-cli with coverage target >= 80%."""

import json
import os
import sys
from unittest.mock import ANY, MagicMock, call, patch

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
        cmd_issue_update_status(cfg, "PROJ-123", "41")

        mock_post.assert_called_once_with(
            cfg, "issue/PROJ-123/transitions", {"transition": {"id": "41"}}
        )


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
            priority="High", assignee="jane.doe",
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
        cmd_issue_update(cfg, "PROJ-123", summary="Only title")
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
        cmd_issue_update(cfg, "PROJ-123", description="New desc")

        payload = mock_put.call_args[0][2]
        assert payload["fields"]["description"] == "New desc"

    def test_issue_update_v3_sends_adf_description(self, monkeypatch):
        from jira_cli.commands import cmd_issue_update

        monkeypatch.setenv("JIRA_API_VERSION", "3")
        mock_put = MagicMock(return_value={})
        monkeypatch.setattr("jira_cli.commands.jira_put", mock_put)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_update(cfg, "PROJ-123", description="New desc")

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
        cmd_issue_update_comment(cfg, "PROJ-123", "54321", "Updated body")
        mock_put.assert_called_once_with(
            cfg, "issue/PROJ-123/comment/54321", {"body": "Updated body"})

    def test_edit_comment_v3_sends_adf_body(self, monkeypatch):
        from jira_cli.commands import cmd_issue_update_comment

        monkeypatch.setenv("JIRA_API_VERSION", "3")
        mock_put = MagicMock(return_value={"updated": ""})
        monkeypatch.setattr("jira_cli.commands.jira_put", mock_put)

        cfg = {"url": "https://jira.x", "user": "u", "pass": "p"}
        cmd_issue_update_comment(cfg, "PROJ-123", "54321", "Updated body")
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
        deleted = cmd_issue_delete_attachment(cfg, "PROJ-123", attachment_ids=["1", "2"])

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
        deleted = cmd_issue_delete_attachment(cfg, "PROJ-123", all_attachments=True)

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
