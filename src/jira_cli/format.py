"""Formatting helpers for Jira CLI output."""

from datetime import datetime

COMMENT_TRUNCATE = 250  # chars for AI-agent-friendly truncated comment text


def fmt_date(iso_str):
    """Format ISO date to human-readable."""
    if not iso_str:
        return ""
    try:
        dt = datetime.strptime(
            iso_str.replace("+0000", "").replace("Z", ""), "%Y-%m-%dT%H:%M:%S.%f"
        )
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso_str[:10] if iso_str else ""


def status_badge(name):
    """ANSI-colorize status name."""
    colors = {
        "To Do": "\033[38;5;245m",
        "In Progress": "\033[38;5;220m",
        "Done": "\033[38;5;76m",
        "Closed": "\033[38;5;76m",
        "Open": "\033[38;5;39m",
        "Reopened": "\033[38;5;208m",
        "Resolved": "\033[38;5;76m",
        "Backlog": "\033[38;5;245m",
        "Selected for Development": "\033[38;5;39m",
        "In Review": "\033[38;5;141m",
        "Blocked": "\033[38;5;196m",
        "QA": "\033[38;5;141m",
    }
    color = colors.get(name, "\033[0m")
    return f"{color}{name}\033[0m"


def priority_label(p):
    """ANSI-colorize priority name."""
    if not p:
        return ""
    name = p.get("name", "")
    colors = {
        "Highest": "\033[38;5;196m",
        "High": "\033[38;5;202m",
        "Medium": "\033[38;5;220m",
        "Low": "\033[38;5;244m",
        "Lowest": "\033[38;5;242m",
    }
    color = colors.get(name, "\033[0m")
    return f"{color}{name}\033[0m" if name else ""


def extract_adf_text(node):
    """Extract plain text from Atlassian Document Format (ADF) JSON."""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        content = node.get("content", [])
        text = node.get("text", "")
        if text:
            return text
        parts = []
        for child in content:
            t = extract_adf_text(child)
            if t:
                parts.append(t)
        return "\n".join(parts) if parts else ""
    if isinstance(node, list):
        return "\n".join(filter(None, [extract_adf_text(n) for n in node]))
    return ""


def truncate(text, maxlen=COMMENT_TRUNCATE):
    """Truncate text to maxlen chars, appending \u2026 if cut."""
    if not text:
        return ""
    text = text.strip()
    if len(text) <= maxlen:
        return text
    return text[:maxlen].rsplit(" ", 1)[0] + " \u2026"
