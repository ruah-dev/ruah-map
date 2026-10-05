#!/usr/bin/env bash
# Package the plugin as ruah.plugin (zip) for installing from the Claude app.
# The Claude Code mod (hooks/) is left out: the app installs skills + agents; Claude Code
# installs the full plugin (mod included) from this folder as a marketplace.
set -euo pipefail
cd "$(dirname "$0")"
python3 tests/test_fixture.py
claude plugin validate . >/dev/null
CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude plugin test . | tail -3
rm -f ruah.plugin
tmp=$(mktemp -d)
cp -R .claude-plugin agents skills scripts README.md "$tmp/"
(cd "$tmp" && zip -qr - . -x '*/__pycache__/*' '*.DS_Store') > ruah.plugin
rm -rf "$tmp"
echo "built $(pwd)/ruah.plugin ($(du -h ruah.plugin | cut -f1))"
