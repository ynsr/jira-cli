#!/usr/bin/env sh
# install.sh - build and install jira-cli from source.
#
# Usage:
#   ./install.sh [options]
#
# Options:
#   -p, --prefix DIR   Install prefix (default: /usr/local).
#                      Binary goes to <prefix>/bin/jira.
#   --uninstall        Remove the installed binary and exit.
#                      Uses --prefix to locate the binary.
#   -h, --help         Show this help and exit.
#
# Behavior:
#   - Idempotent: re-running reinstalls the binary in place.
#   - If a jira binary already exists on PATH or at the target,
#     it is overwritten (force reinstall).
#   - Requires: go (>= 1.26, see go.mod), git, sh.
#   - Works on Linux and macOS. Needs sudo when prefix is not writable.
#
# Examples:
#   ./install.sh
#   ./install.sh --prefix "$HOME/.local"
#   sudo ./install.sh --prefix /usr/local
#   ./install.sh --uninstall
#   ./install.sh --prefix "$HOME/.local" --uninstall

set -eu

PREFIX="/usr/local"
UNINSTALL=0
SCRIPT_DIR=""

usage() {
  sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
}

log() {
  printf '%s\n' "$*"
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--prefix)
      [ $# -ge 2 ] || die "--prefix needs a directory argument"
      PREFIX="$2"
      shift 2
      ;;
    --prefix=*)
      PREFIX="${1#--prefix=}"
      shift
      ;;
    --uninstall)
      UNINSTALL=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1 (see --help)"
      ;;
  esac
done

[ -n "$PREFIX" ] || die "--prefix must not be empty"
BIN_DIR="$PREFIX/bin"
TARGET="$BIN_DIR/jira"

uninstall() {
  if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
    if [ -w "$TARGET" ] || [ -w "$BIN_DIR" ]; then
      rm -f "$TARGET" || die "failed to remove $TARGET"
    else
      log "Need write access to $TARGET, retrying with sudo..."
      sudo rm -f "$TARGET" || die "failed to remove $TARGET"
    fi
    log "Uninstalled $TARGET"
  else
    log "Nothing to uninstall: $TARGET not found"
  fi

  # Optional per-user config cleanup. Keep by default; user deletes manually.
  log "Config files (if any) were left untouched."
  log "To remove config manually: \${XDG_CONFIG_HOME:-\$HOME/.config}/.jira/"
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

install_binary() {
  command_exists git || die "git is required but not installed"
  command_exists go || die "go is required but not installed (see https://go.dev/dl/)"

  if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
    log "Existing installation found at $TARGET - reinstalling (forced)."
  else
    if command_exists jira; then
      log "Found '$(command -v jira)' on PATH - (re)installing to $TARGET (forced)."
    fi
  fi

  log "Building jira-cli from $SCRIPT_DIR ..."
  (cd "$SCRIPT_DIR" && go build -o "$SCRIPT_DIR/.install-tmp-jira" ./cmd/jira) \
    || die "build failed (run with --help for requirements)"

  if [ ! -w "$BIN_DIR" ]; then
    if [ ! -d "$BIN_DIR" ]; then
      log "Creating $BIN_DIR (may need sudo)..."
      mkdir -p "$BIN_DIR" 2>/dev/null || sudo mkdir -p "$BIN_DIR" \
        || die "cannot create $BIN_DIR"
    else
      log "Need write access to $BIN_DIR, will use sudo to install."
    fi
  fi

  if [ -w "$BIN_DIR" ]; then
    mv -f "$SCRIPT_DIR/.install-tmp-jira" "$TARGET" \
      || die "failed to install to $TARGET"
    chmod 755 "$TARGET" || die "failed to chmod $TARGET"
  else
    sudo mv -f "$SCRIPT_DIR/.install-tmp-jira" "$TARGET" \
      || die "failed to install to $TARGET"
    sudo chmod 755 "$TARGET" || die "failed to chmod $TARGET"
  fi

  case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) log "NOTE: $BIN_DIR is not on your PATH. Add: export PATH=\"$BIN_DIR:\$PATH\"" ;;
  esac

  if ! command_exists jira && [ ! -x "$TARGET" ]; then
    die "install finished but $TARGET is not executable"
  fi

  log "Installed $($TARGET version 2>/dev/null || echo jira) to $TARGET"
  log "Next: run 'jira init' to configure server/login credentials."
}

if [ "$UNINSTALL" -eq 1 ]; then
  uninstall
  exit 0
fi

install_binary
