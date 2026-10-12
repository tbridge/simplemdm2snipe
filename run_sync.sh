#!/bin/bash
# run_sync.sh — run simplemdm2snipe, then report what it did.
#
# Point your scheduled job (cron or a launchd LaunchAgent/LaunchDaemon) at this script
# instead of at simplemdm2snipe.py. Any arguments are passed through to the sync;
# with none, SYNC_ARGS is used.
#
#   launchd ProgramArguments:  /bin/bash  /path/to/simplemdm2snipe/run_sync.sh
#   cron:                      0 6 * * 1  /path/to/simplemdm2snipe/run_sync.sh
#
# The sync's output is captured to simplemdm2snipe-lastrun.log (overwritten each run)
# and still passed through to stdout, so launchd/cron logging keeps working. The
# report reads that file for warnings and errors. If you run the sync with -l instead,
# the report reads simplemdm2snipe.log.
#
# The report runs even if the sync fails, so a crashed run still shows up in Slack.
# Compatible with macOS /bin/bash 3.2.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Prefer the project's venv when there is one.
if [ -z "${PYTHON:-}" ]; then
    if [ -x "$SCRIPT_DIR/venv/bin/python" ]; then
        PYTHON="$SCRIPT_DIR/venv/bin/python"
    else
        PYTHON="python3"
    fi
fi

# -v gives INFO detail, which lets the report call out devices deferred because their model was new.
SYNC_ARGS="${SYNC_ARGS:--v -r}"

if [ "$#" -eq 0 ]; then
    # shellcheck disable=SC2086
    set -- $SYNC_ARGS
fi

# With -l the sync writes its own log file; otherwise capture its output.
LOG="$SCRIPT_DIR/simplemdm2snipe-lastrun.log"
for arg in "$@"; do
    case "$arg" in
        -l|--logfile) LOG="$SCRIPT_DIR/simplemdm2snipe.log" ;;
    esac
done

# Start time in UTC; the reporter converts to Snipe-IT's and the log's timezones.
START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# -u: unbuffered, so output streams to launchd/cron as it happens.
"$PYTHON" -u "$SCRIPT_DIR/simplemdm2snipe.py" "$@" 2>&1 | tee "$SCRIPT_DIR/simplemdm2snipe-lastrun.log"
SYNC_RC=${PIPESTATUS[0]}

"$PYTHON" "$SCRIPT_DIR/simplemdm2snipe_report.py" --since "$START" --exit-code "$SYNC_RC" --log "$LOG"
REPORT_RC=$?

if [ "$REPORT_RC" -ne 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') simplemdm2snipe_report exited with $REPORT_RC" >&2
fi

# Surface the sync's own result to the scheduler.
exit "$SYNC_RC"
