"""Configuration loading, credential management, and password encryption."""

import json
import os
import secrets

from cryptography.fernet import Fernet

CONFIG_DIR = os.path.expanduser("~/.config/jira-cli")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
KEY_PATH = os.path.join(CONFIG_DIR, "secret.key")
_OLD_CONFIG_PATH = os.path.expanduser("~/.jira-cli.json")


# -------------------------------------------------------------------
# Encryption helpers (Fernet symmetric key stored in ~/.config/jira-cli/secret.key)
# -------------------------------------------------------------------

def _ensure_config_dir():
    """Create config directory with 0o700 if it doesn't exist."""
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)


def _load_or_create_key():
    """Load the Fernet key from disk, or generate and store a new one."""
    _ensure_config_dir()
    if os.path.exists(KEY_PATH):
        with open(KEY_PATH, "rb") as f:
            key = f.read()
        # Validate key
        try:
            Fernet(key)
            return key
        except Exception:
            pass  # corrupted key file — regenerate
    # Generate new key
    key = Fernet.generate_key()
    with open(KEY_PATH, "wb") as f:
        f.write(key)
    os.chmod(KEY_PATH, 0o600)
    return key


def _get_cipher():
    """Return a Fernet cipher instance."""
    return Fernet(_load_or_create_key())


def encrypt_password(plaintext: str) -> str:
    """Encrypt a password string. Returns base64-encoded ciphertext."""
    if not plaintext:
        return ""
    cipher = _get_cipher()
    return cipher.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_password(ciphertext: str) -> str:
    """Decrypt a password string. Returns plaintext."""
    if not ciphertext:
        return ""
    cipher = _get_cipher()
    return cipher.decrypt(ciphertext.encode("utf-8")).decode("utf-8")


# -------------------------------------------------------------------
# Config load / save
# -------------------------------------------------------------------

def _migrate_old_config():
    """Migrate config from old ~/.jira-cli.json to new location."""
    if os.path.exists(_OLD_CONFIG_PATH) and not os.path.exists(CONFIG_PATH):
        try:
            with open(_OLD_CONFIG_PATH) as f:
                old = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        url = old.get("url", "")
        user = old.get("user", "")
        passwd = old.get("pass", "")
        if url or user or passwd:
            save_config(url, user, passwd)
            # Remove old file after successful migration
            try:
                os.remove(_OLD_CONFIG_PATH)
            except OSError:
                pass


def load_config():
    """Load config from env vars or config file. Env vars take priority.

    Returns dict with keys: url, user, pass (plaintext).
    """
    cfg = {}
    cfg["url"] = os.environ.get("JIRA_URL")
    cfg["user"] = os.environ.get("JIRA_USER")
    cfg["pass"] = os.environ.get("JIRA_PASS")

    # Migrate old config if present
    _migrate_old_config()

    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            file_cfg = json.load(f)
        if not cfg["url"]:
            cfg["url"] = file_cfg.get("url", "")
        if not cfg["user"]:
            cfg["user"] = file_cfg.get("user", "")
        if not cfg["pass"]:
            encrypted = file_cfg.get("pass_encrypted", "")
            cfg["pass"] = decrypt_password(encrypted) if encrypted else file_cfg.get("pass", "")

    if cfg.get("url"):
        cfg["url"] = cfg["url"].rstrip("/")
    return cfg


def save_config(url, user, passwd):
    """Persist credentials to config file with encrypted password."""
    _ensure_config_dir()
    encrypted = encrypt_password(passwd) if passwd else ""
    config = {
        "url": url,
        "user": user,
        "pass_encrypted": encrypted,
        "pass": "",  # kept empty; plaintext not persisted
    }
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
    os.chmod(CONFIG_PATH, 0o600)
    print(f"Config saved to {CONFIG_PATH}")
