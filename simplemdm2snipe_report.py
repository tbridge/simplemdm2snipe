#!/usr/bin/env python3
# simplemdm2snipe_report
#
# ABOUT:
#   Companion to simplemdm2snipe.py. Run it right after a sync to report what the sync
#   added to Snipe-IT and any warnings or errors it logged, then post the summary to Slack.
#
#   What gets reported:
#     * New assets   - pulled from the Snipe-IT API (anything created since the run started)
#     * New models   - pulled from the Snipe-IT API (anything created since the run started)
#     * Problems     - WARNING / ERROR / CRITICAL lines from simplemdm2snipe.log for this run
#     * Run status   - the sync's exit code, when the wrapper passes it in
#
#   Snipe-IT is treated as the source of truth for "what was added", so the report stays
#   accurate no matter which logging flags the sync was run with. The log adds problems,
#   plus (when the sync ran with -v) devices that were deferred because a model was new.
#
# CONFIGURATION:
#   Uses the same settings.conf as simplemdm2snipe.py, plus an optional [reporting] section:
#
#     [reporting]
#     slack_webhook_url = https://hooks.slack.com/services/...
#     log_file = /opt/simplemdm2snipe/simplemdm2snipe.log
#     title = SimpleMDM -> Snipe-IT sync
#     post_when_quiet = yes
#
#   SLACK_WEBHOOK_URL and SNIPE_APIKEY environment variables override settings.conf.
#
# USAGE:
#   Normally called by run_sync.sh. Standalone examples:
#     ./simplemdm2snipe_report.py --since-hours 24 --print
#     ./simplemdm2snipe_report.py --since 2026-10-05T06:00:00Z --exit-code 0
#
# LICENSE:
#   MIT

version = "1.0.0"

import argparse
import configparser
import json
import logging
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

try:
    import requests
except ImportError as import_error:
    print(import_error)
    sys.exit("Looks like you need to install the requests module. Run: python3 -m pip install requests")

try:
    import pytz
except ImportError as import_error:
    print(import_error)
    sys.exit("Looks like you need to install the pytz module. Run: python3 -m pip install pytz")


# Same search order as simplemdm2snipe.py
CONFIG_PATHS = [
    "/opt/simplemdm2snipe/settings.conf",
    "/etc/simplemdm2snipe/settings.conf",
    "settings.conf",
]

# simplemdm2snipe.py log format: '%(asctime)s - %(levelname)s - %(message)s'
LOG_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - ([A-Z]+) - (.*)$")
PROBLEM_LEVELS = ("WARNING", "ERROR", "CRITICAL")

# Slack limits a section block's text to 3000 chars; stay well under it.
MAX_LIST_ITEMS = 25
MAX_SECTION_CHARS = 2800


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="simplemdm2snipe_report",
        description="Report what the last simplemdm2snipe run added to Snipe-IT, plus any warnings/errors.",
    )
    window = p.add_mutually_exclusive_group()
    window.add_argument("--since", help="Start of the run as an ISO-8601 timestamp (e.g. 2026-10-05T06:00:00Z). "
                                        "A timestamp without an offset is read as this machine's local time.")
    window.add_argument("--since-hours", type=float,
                        help="Report on the last N hours instead of a specific start time. Default: 24.")
    p.add_argument("--exit-code", type=int, help="Exit code of the sync run, so the report can flag a failed run.")
    p.add_argument("--log", help="Path to simplemdm2snipe.log. Overrides [reporting] log_file.")
    p.add_argument("--config", help="Path to settings.conf. Default: same search order as simplemdm2snipe.py.")
    p.add_argument("--print", dest="print_only", action="store_true",
                   help="Print the report to stdout and do not post to Slack.")
    p.add_argument("--json", action="store_true", help="Print the raw report data as JSON (implies --print).")
    p.add_argument("--quiet-if-clean", action="store_true",
                   help="Skip posting when nothing was added and there were no problems.")
    p.add_argument("--do_not_verify_ssl", action="store_false",
                   help="Skip SSL verification for Snipe-IT requests (matches the sync's flag).")
    p.add_argument("-d", "--debug", action="store_true", help="Debug logging.")
    p.add_argument("--version", action="store_true", help="Print the version and exit.")
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def load_settings(path=None):
    config = configparser.ConfigParser()
    paths = [path] if path else CONFIG_PATHS
    for candidate in paths:
        config.read(candidate)
        if "snipe-it" in config:
            logging.debug("Using settings from %s", candidate)
            break
    if "snipe-it" not in config:
        sys.exit("No valid settings.conf found (looked in: {}).".format(", ".join(paths)))

    snipe = config["snipe-it"]
    reporting = config["reporting"] if "reporting" in config else {}

    settings = {
        "snipe_base": snipe.get("url", "").rstrip("/"),
        "snipe_apikey": os.environ.get("SNIPE_APIKEY") or snipe.get("apikey", ""),
        "snipe_timezone": snipe.get("timezone", "UTC"),
        "slack_webhook_url": os.environ.get("SLACK_WEBHOOK_URL") or reporting.get("slack_webhook_url", ""),
        "log_file": reporting.get("log_file", "simplemdm2snipe.log"),
        "title": reporting.get("title", "SimpleMDM → Snipe-IT sync"),
        "post_when_quiet": str(reporting.get("post_when_quiet", "yes")).strip().lower() in ("yes", "true", "1"),
    }
    if not settings["snipe_base"] or settings["snipe_base"] == "https://your_snipe_instance.com":
        sys.exit("Invalid Snipe-IT URL in settings.conf.")
    if not settings["snipe_apikey"] or settings["snipe_apikey"] == "snipe-api-key-here":
        sys.exit("No Snipe-IT API key in settings.conf or SNIPE_APIKEY.")
    return settings


def resolve_since(args):
    """Return the run start as an aware UTC datetime."""
    if args.since:
        try:
            ts = datetime.fromisoformat(args.since.replace("Z", "+00:00"))
        except ValueError:
            sys.exit("Could not read --since '{}'. Use ISO-8601, e.g. 2026-10-05T06:00:00Z.".format(args.since))
        if ts.tzinfo is None:
            ts = ts.astimezone()  # naive -> this machine's local time
        return ts.astimezone(timezone.utc)
    hours = args.since_hours if args.since_hours is not None else 24
    return datetime.now(timezone.utc) - timedelta(hours=hours)


# ---------------------------------------------------------------------------
# Snipe-IT
# ---------------------------------------------------------------------------

def snipe_get(settings, endpoint, params, verify):
    url = "{}/api/v1/{}".format(settings["snipe_base"], endpoint)
    headers = {"Authorization": "Bearer {}".format(settings["snipe_apikey"]), "Accept": "application/json"}
    response = requests.get(url, headers=headers, params=params, verify=verify, timeout=60)
    response.raise_for_status()
    data = response.json()
    # Snipe-IT returns HTTP 200 with {"status": "error"} for some failures.
    if isinstance(data, dict) and data.get("status") == "error":
        raise RuntimeError("Snipe-IT error on {}: {}".format(endpoint, data.get("messages")))
    return data


def snipe_created_at(row, snipe_tz):
    """Snipe-IT gives created_at as {'datetime': 'YYYY-MM-DD HH:MM:SS', ...} in its own timezone."""
    created = row.get("created_at")
    if isinstance(created, dict):
        created = created.get("datetime")
    if not created:
        return None
    naive = datetime.strptime(created[:19], "%Y-%m-%d %H:%M:%S")
    return snipe_tz.localize(naive).astimezone(timezone.utc)


def fetch_created_since(settings, endpoint, since_utc, verify, page_size=100):
    """Walk an endpoint newest-first and return rows created at or after since_utc."""
    snipe_tz = pytz.timezone(settings["snipe_timezone"])
    found, offset = [], 0
    while True:
        data = snipe_get(settings, endpoint,
                         {"sort": "created_at", "order": "desc", "limit": page_size, "offset": offset}, verify)
        rows = data.get("rows", [])
        if not rows:
            break
        reached_older = False
        for row in rows:
            created = snipe_created_at(row, snipe_tz)
            if created is None:
                continue
            if created >= since_utc:
                row["_created_utc"] = created
                found.append(row)
            else:
                reached_older = True
        offset += len(rows)
        if reached_older or offset >= data.get("total", 0):
            break
    return found


def name_of(value):
    return value.get("name") if isinstance(value, dict) else (value or "")


def summarize_asset(row, snipe_base):
    assigned = row.get("assigned_to")
    if isinstance(assigned, dict):
        assigned = assigned.get("username") or assigned.get("email") or assigned.get("name")
    return {
        "id": row.get("id"),
        "name": row.get("name") or "(no name)",
        "asset_tag": row.get("asset_tag") or "",
        "serial": row.get("serial") or "",
        "model": name_of(row.get("model")),
        "category": name_of(row.get("category")),
        "status": name_of(row.get("status_label")),
        "assigned_to": assigned or "",
        "url": "{}/hardware/{}".format(snipe_base, row.get("id")),
        "created": row["_created_utc"].isoformat(),
    }


def summarize_model(row, snipe_base):
    return {
        "id": row.get("id"),
        "name": row.get("name") or "(no name)",
        "model_number": row.get("model_number") or "",
        "category": name_of(row.get("category")),
        "url": "{}/models/{}".format(snipe_base, row.get("id")),
        "created": row["_created_utc"].isoformat(),
    }


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------

def read_log_entries(path, since_local_naive):
    """Return (entries, found_file). Each entry: {'ts', 'level', 'message'}.

    Lines without the standard prefix (multi-line messages, tracebacks) are folded into
    the entry before them. Only entries at or after since_local_naive are returned, which
    is what slices the latest run out of a log that appends across runs.
    """
    if not path or not os.path.exists(path):
        return [], False
    entries, current = [], None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            m = LOG_LINE.match(line)
            if m:
                ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                current = {"ts": ts, "level": m.group(2), "message": m.group(3)}
                if ts >= since_local_naive:
                    entries.append(current)
                else:
                    current = None
            elif current is not None and line.strip():
                current["message"] += "\n" + line
    return entries, True


DEFERRED_MODEL = re.compile(r"Could not find a model ID in Snipe-IT for: (.+)$")
SERIAL_IN_MSG = re.compile(r"serial number (\S+)")


def analyze_log(entries):
    problems = Counter()
    first_seen = {}
    deferred_models = Counter()
    for e in entries:
        if e["level"] in PROBLEM_LEVELS:
            # Collapse whitespace, cap length, and dedupe identical messages.
            text = " ".join(e["message"].split())
            if len(text) > 300:
                text = text[:297] + "..."
            key = (e["level"], text)
            problems[key] += 1
            first_seen.setdefault(key, e["ts"])
        elif e["level"] == "INFO":
            m = DEFERRED_MODEL.search(e["message"])
            if m:
                deferred_models[m.group(1).strip()] += 1

    level_rank = {"CRITICAL": 0, "ERROR": 1, "WARNING": 2}
    problem_list = [
        {"level": lvl, "message": msg, "count": n}
        for (lvl, msg), n in sorted(problems.items(), key=lambda kv: (level_rank.get(kv[0][0], 9), first_seen[kv[0]]))
    ]
    return {
        "problems": problem_list,
        "error_count": sum(n for (lvl, _), n in problems.items() if lvl in ("ERROR", "CRITICAL")),
        "warning_count": sum(n for (lvl, _), n in problems.items() if lvl == "WARNING"),
        "deferred_models": dict(deferred_models),
        "line_count": len(entries),
        "verbose": any(e["level"] == "INFO" for e in entries),
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def build_report(args, settings, since_utc):
    report = {
        "title": settings["title"],
        "since": since_utc.isoformat(),
        "generated": datetime.now(timezone.utc).isoformat(),
        "exit_code": args.exit_code,
        "assets": [],
        "models": [],
        "snipe_error": None,
    }

    try:
        assets = fetch_created_since(settings, "hardware", since_utc, args.do_not_verify_ssl)
        models = fetch_created_since(settings, "models", since_utc, args.do_not_verify_ssl)
        report["assets"] = [summarize_asset(r, settings["snipe_base"]) for r in assets]
        report["models"] = [summarize_model(r, settings["snipe_base"]) for r in models]
    except Exception as exc:  # report the failure instead of dying silently
        logging.exception("Could not query Snipe-IT")
        report["snipe_error"] = str(exc)

    log_path = args.log or settings["log_file"]
    since_local = since_utc.astimezone().replace(tzinfo=None)  # log timestamps are this machine's local time
    entries, found = read_log_entries(log_path, since_local)
    report["log_path"] = log_path
    report["log_found"] = found
    report.update(analyze_log(entries))

    failed = (args.exit_code not in (None, 0)) or report["error_count"] > 0 or report["snipe_error"]
    if failed:
        report["status"] = "failed" if args.exit_code not in (None, 0) else "errors"
    elif report["warning_count"] > 0:
        report["status"] = "warnings"
    elif not found or report["line_count"] == 0:
        report["status"] = "no_log"
    else:
        report["status"] = "ok"
    return report


STATUS_TEXT = {
    "ok": (":white_check_mark:", "Completed cleanly"),
    "warnings": (":warning:", "Completed with warnings"),
    "errors": (":x:", "Completed with errors"),
    "failed": (":rotating_light:", "Sync failed"),
    "no_log": (":grey_question:", "Completed, but no log entries found for this run"),
}


def fmt_local(iso, tzname):
    return datetime.fromisoformat(iso).astimezone(pytz.timezone(tzname)).strftime("%a %b %-d, %-I:%M %p %Z")


def clip_lines(lines, total, noun):
    shown = lines[:MAX_LIST_ITEMS]
    text = "\n".join(shown)
    while len(text) > MAX_SECTION_CHARS and shown:
        shown = shown[:-1]
        text = "\n".join(shown)
    if total > len(shown):
        text += "\n_...and {} more {}_".format(total - len(shown), noun)
    return text


def slack_escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_slack_payload(report, tzname):
    emoji, status = STATUS_TEXT[report["status"]]
    n_assets, n_models = len(report["assets"]), len(report["models"])
    summary = "{} {} — {} new asset{}, {} new model{}, {} error{}, {} warning{}".format(
        emoji, status,
        n_assets, "" if n_assets == 1 else "s",
        n_models, "" if n_models == 1 else "s",
        report["error_count"], "" if report["error_count"] == 1 else "s",
        report["warning_count"], "" if report["warning_count"] == 1 else "s",
    )
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": report["title"]}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*{}*".format(summary)}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "Run started {}{}".format(
            fmt_local(report["since"], tzname),
            "" if report["exit_code"] is None else " · exit code {}".format(report["exit_code"]))}]},
    ]

    if report["snipe_error"]:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text":
            ":x: *Couldn't query Snipe-IT for new records:* {}".format(slack_escape(report["snipe_error"]))}})

    if report["assets"]:
        lines = []
        for a in report["assets"]:
            bits = [a["model"], "SN {}".format(a["serial"]) if a["serial"] else ""]
            if a["assigned_to"]:
                bits.append("→ {}".format(a["assigned_to"]))
            lines.append("• <{}|{}> `{}` — {}".format(
                a["url"], slack_escape(a["name"]), slack_escape(a["asset_tag"]),
                slack_escape(" · ".join(b for b in bits if b))))
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text":
            "*New assets ({})*\n{}".format(n_assets, clip_lines(lines, n_assets, "assets"))}})

    if report["models"]:
        lines = ["• <{}|{}> `{}` — {}".format(m["url"], slack_escape(m["name"]),
                 slack_escape(m["model_number"]), slack_escape(m["category"])) for m in report["models"]]
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text":
            "*New models ({})*\n{}".format(n_models, clip_lines(lines, n_models, "models"))}})

    if report["deferred_models"]:
        count = sum(report["deferred_models"].values())
        names = ", ".join("{} ×{}".format(k, v) if v > 1 else k for k, v in report["deferred_models"].items())
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text":
            ":hourglass_flowing_sand: *{} device{} deferred to next run* because their model was new to Snipe-IT: {}".format(
                count, "" if count == 1 else "s", slack_escape(names))}})

    if report["problems"]:
        icon = {"CRITICAL": ":rotating_light:", "ERROR": ":x:", "WARNING": ":warning:"}
        lines = ["{} {}{}".format(icon.get(p["level"], "•"), slack_escape(p["message"]),
                                  " _(×{})_".format(p["count"]) if p["count"] > 1 else "")
                 for p in report["problems"]]
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text":
            "*Problems logged*\n{}".format(clip_lines(lines, len(lines), "distinct messages"))}})

    notes = []
    if not report["log_found"]:
        notes.append("Log file `{}` not found — run the sync with `-l` so problems can be reported.".format(report["log_path"]))
    elif report["line_count"] and not report["verbose"]:
        notes.append("Sync ran without `-v`, so deferred-device details aren't available.")
    if notes:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": " ".join(notes)}]})

    return {"text": "{}: {}".format(report["title"], summary), "blocks": blocks}


def render_text(report, tzname):
    _, status = STATUS_TEXT[report["status"]]
    out = ["{} — {}".format(report["title"], status),
           "Run started: {}".format(fmt_local(report["since"], tzname))]
    if report["exit_code"] is not None:
        out.append("Exit code: {}".format(report["exit_code"]))
    if report["snipe_error"]:
        out.append("Snipe-IT query failed: {}".format(report["snipe_error"]))
    out.append("\nNew assets ({}):".format(len(report["assets"])))
    out += ["  - {} [{}] {} SN {} {}".format(a["name"], a["asset_tag"], a["model"], a["serial"], a["url"]) for a in report["assets"]] or ["  (none)"]
    out.append("\nNew models ({}):".format(len(report["models"])))
    out += ["  - {} ({}) {}".format(m["name"], m["model_number"], m["url"]) for m in report["models"]] or ["  (none)"]
    if report["deferred_models"]:
        out.append("\nDeferred to next run (new model): {}".format(report["deferred_models"]))
    out.append("\nProblems ({} errors, {} warnings):".format(report["error_count"], report["warning_count"]))
    out += ["  [{}] {}{}".format(p["level"], p["message"], " (x{})".format(p["count"]) if p["count"] > 1 else "") for p in report["problems"]] or ["  (none)"]
    if not report["log_found"]:
        out.append("\nNote: log file {} not found.".format(report["log_path"]))
    return "\n".join(out)


def post_to_slack(webhook_url, payload):
    response = requests.post(webhook_url, data=json.dumps(payload),
                             headers={"Content-Type": "application/json"}, timeout=30)
    if response.status_code != 200:
        raise RuntimeError("Slack returned HTTP {}: {}".format(response.status_code, response.text[:200]))


def main(argv=None):
    args = parse_args(argv)
    if args.version:
        print("simplemdm2snipe_report v" + version)
        return 0
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING,
                        format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    settings = load_settings(args.config)
    since_utc = resolve_since(args)
    report = build_report(args, settings, since_utc)
    tzname = settings["snipe_timezone"]

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0
    if args.print_only:
        print(render_text(report, tzname))
        return 0

    quiet = report["status"] == "ok" and not report["assets"] and not report["models"]
    if quiet and (args.quiet_if_clean or not settings["post_when_quiet"]):
        logging.info("Nothing to report; not posting.")
        return 0

    if not settings["slack_webhook_url"]:
        print(render_text(report, tzname))
        print("\n(No Slack webhook configured; printed instead.)", file=sys.stderr)
        return 0

    try:
        post_to_slack(settings["slack_webhook_url"], build_slack_payload(report, tzname))
    except Exception as exc:
        print(render_text(report, tzname))
        print("\nFailed to post to Slack: {}".format(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
