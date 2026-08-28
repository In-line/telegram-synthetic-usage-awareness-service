#!/bin/sh
# Pre-remove script: stop and disable the user timer before uninstalling.
set -e

if command -v systemctl >/dev/null 2>&1; then
    systemctl --user stop synthetic-usage-awareness.timer 2>/dev/null || true
    systemctl --user disable synthetic-usage-awareness.timer 2>/dev/null || true
    systemctl --user daemon-reload 2>/dev/null || true
fi

exit 0
