"""Configuration loading and credential management."""

import json
import os

CONFIG_PATH = os.path.expanduser("~/.jira-cli.json")


def load_config():
    """Load config from env vars or config file. Env vars take priority."""
    cfg = {}
    cfg["url"] = os.environ.get("JIRA_URL")
    cfg["user"] = os.environ.get("JIRA_USER")
    cfg["pass"] = os.environ.get("JIRA_PASS")
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            file_cfg = json.load(f)
        if not cfg["url"]:
            cfg["url"] = file_cfg.get("url", "")
        if not cfg["user"]:
            cfg["user"] = file_cfg.get("user", "")
        if not cfg["pass"]:
            cfg["pass"] = file_cfg.get("pass", "")
    if cfg.get("url"):
        cfg["url"] = cfg["url"].rstrip("/")
    return cfg


def save_config(url, user, passwd):
    """Persist credentials to config file."""
    with open(CONFIG_PATH, "w") as f:
        json.dump({"url": url, "user": user, "pass": passwd}, f, indent=2)
    os.chmod(CONFIG_PATH, 0o600)
    print(f"Config saved to {CONFIG_PATH}")
