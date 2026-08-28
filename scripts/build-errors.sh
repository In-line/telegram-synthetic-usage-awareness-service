#!/bin/sh
# Show the last N pkger build logs' error lines (ANSI stripped), one image at a time.
cd ~/Documents/projects/telegram-synthetic-usage-awareness-service || exit 1
for img in ubuntu-2404 ubuntu-2604 fedora-44 rhel-8 rhel-9; do
    LOG=$(ls -t .pkger-logs/ | grep -E "synthetic.*${img}" | head -1)
    echo "=== $img ($LOG) ==="
    sed 's/\x1b\[[0-9;]*m//g' ".pkger-logs/$LOG" 2>/dev/null | grep -iE "ERROR|not found|denied|manifest|pull access|failed to" | tail -6
done
