#!/usr/bin/env bash
set -euo pipefail
DEST="${1:-$HOME/.claude/skills/epiphany-executor}"
mkdir -p "$DEST"
HERE="$(cd "$(dirname "$0")" && pwd)"
cp -r "$HERE"/* "$DEST"/
echo "installed epiphany-executor -> $DEST"
