#!/bin/bash
# run_sync.sh — run simplemdm2snipe, then report what it did.
#
# Point your existing Monday cron/launchd job at this script instead of at
# simplemdm2snipe.py directly. Any arguments are passed through to the sync;
# with none, SYNC_ARGS is used.
#
#   0 6 * * 1  /opt/simplemdm2snipe/run_sync.sh >> /var/log/simplemdm2snipe-cron.log 2>&1
#
# The report runs even if the sync fails, so a crashed run still shows up in Slack.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

PYTHON="${PYTHON:-python3}"

# -l writes to simplemdm2snipe.log (needed for the problems section).
# -v adds INFO detail, which lets the report call out devices deferred because their model was new.
SYNC_ARGS="${SYNC_ARGS:--l -v -r -u}"

if [ "$#" -eq 0 ]; then
    # shellcheck disable=SC2086
    set -- $SYNC_ARGS
fi

# Start time in UTC; the reporter converts to Snipe-IT's and the log's timezones.
START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

"$PYTHON" "$SCRIPT_DIR/simplemdm2snipe.py" "$@"
SYNC_RC=$?

"$PYTHON" "$SCRIPT_DIR/simplemdm2snipe_report.py" --since "$START" --exit-code "$SYNC_RC" \
    --log "$SCRIPT_DIR/simplemdm2snipe.log"
REPORT_RC=$?

if [ "$REPORT_RC" -ne 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') simplemdm2snipe_report exited with $REPORT_RC" >&2
fi

# Surface the sync's own result to cron.
exit "$SYNC_RC"
