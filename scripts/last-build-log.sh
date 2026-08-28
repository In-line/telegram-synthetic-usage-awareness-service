#!/bin/sh
# Show the last pkger build log tail (ANSI stripped).
LOG=$(ls -t .pkger-logs/ | grep -E "synthetic" | head -1)
echo "== $LOG =="
sed 's/\x1b\[[0-9;]*m//g' ".pkger-logs/$LOG" | grep -viE "fetching files|'[^']*' ->|^\./" | tail -14
