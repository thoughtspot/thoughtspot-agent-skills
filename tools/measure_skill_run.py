#!/usr/bin/env python3
"""
measure_skill_run.py — where does a skill run's wall-clock and token spend go?

Read-only. Parses a Claude Code transcript (``~/.claude/projects/<slug>/*.jsonl``)
and splits an interactive skill run into the three things that can actually be
optimised differently:

  answering me      short gaps where the assistant is waiting on your reply.
                    Removed by cutting confirmation gates.
  model + tools     time the assistant spent thinking and running commands.
                    Removed by moving mechanical work into Python.
  away              reply gaps at or over --idle-secs. You went to lunch; that
                    is not a workflow cost. Reported, then EXCLUDED from the
                    split above, because otherwise one break swamps everything.
  long tool calls   individual gaps over --slow-call-secs, listed separately.
                    Usually irreducible (a dbt Cloud job, a dependency walk).

Percentages are of ACTIVE time (elapsed minus away), so they answer "of the
time this workflow actually cost, what would codifying it remove?"

Written for `.claude/rules/repo-audit.md` angle 11 ("agentic -> deterministic"):
measure before codifying, then measure again, so the claim is a number and not
a feeling.

Usage:
    python3 tools/measure_skill_run.py                      # newest session, this repo
    python3 tools/measure_skill_run.py --session <uuid|path>
    python3 tools/measure_skill_run.py --grep ts-convert-from-dbt
    python3 tools/measure_skill_run.py --json

Exit codes: 0 always (a report, never a gate).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# "Step 10.3", "Step 8-pre", "Step 5.5" — how the dbt SKILL.md files number themselves
STEP_RE = re.compile(r"\bStep\s+(\d+(?:\.\d+)?(?:-pre)?[a-z]?)\b")
DEFAULT_SLOW_CALL = 20.0
# A human reply gap longer than this is someone stepping away, not someone
# answering a prompt. Counting it as "waiting on you" makes a lunch break
# look like a workflow problem.
DEFAULT_IDLE = 300.0


def _parse_ts(raw: str) -> "datetime | None":
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _project_dir(cwd: Path) -> Path:
    """Claude Code slugifies the project path: `/` and `.` both become `-`,
    so /Users/ada.lovelace/proj -> -Users-ada-lovelace-proj.

    Walks up from `cwd` so running inside a subdirectory of the project still
    finds the transcripts.
    """
    root = Path.home() / ".claude" / "projects"
    for candidate in [cwd, *cwd.parents]:
        slug = re.sub(r"[/.]", "-", str(candidate))
        if (root / slug).is_dir():
            return root / slug
    return root / re.sub(r"[/.]", "-", str(cwd))


def _resolve_session(arg: "str | None", cwd: Path) -> "Path | None":
    if arg and Path(arg).is_file():
        return Path(arg)
    root = Path.home() / ".claude" / "projects"
    d = _project_dir(cwd)
    if arg:
        # A session uuid is globally unique, so fall back to every project dir —
        # nested repos each get their own slug and the id may live in the parent's.
        hit = d / f"{arg}.jsonl"
        if hit.is_file():
            return hit
        return next(iter(sorted(root.glob(f"*/{arg}.jsonl"))), None) if root.is_dir() else None
    if not d.is_dir():
        return None
    files = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    out = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            out.append(str(block.get("text") or ""))
    return "\n".join(out)


def _tool_names(content) -> list:
    if not isinstance(content, list):
        return []
    return [b.get("name") for b in content
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name")]


def load_events(path: Path) -> list:
    """Flatten the transcript to the user/assistant records we can time."""
    events = []
    for line in path.read_text(errors="replace").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") not in ("user", "assistant"):
            continue
        ts = _parse_ts(d.get("timestamp"))
        if ts is None:
            continue
        msg = d.get("message") or {}
        usage = msg.get("usage") or {} if isinstance(msg, dict) else {}
        content = msg.get("content") if isinstance(msg, dict) else None
        events.append({
            "kind": d["type"],
            "ts": ts,
            "text": _text_of(content),
            "tools": _tool_names(content),
            "is_tool_result": bool(
                isinstance(content, list)
                and any(isinstance(b, dict) and b.get("type") == "tool_result"
                        for b in content)),
            "in": usage.get("input_tokens", 0) or 0,
            "out": usage.get("output_tokens", 0) or 0,
            "cache_read": usage.get("cache_read_input_tokens", 0) or 0,
            "cache_write": usage.get("cache_creation_input_tokens", 0) or 0,
        })
    events.sort(key=lambda e: e["ts"])
    return events


def analyse(events: list, slow_call: float, idle_secs: float = DEFAULT_IDLE) -> dict:
    """Attribute every inter-event gap to a bucket.

    A gap where the assistant is waiting on a human reply splits in two:
    up to ``idle_secs`` counts as *answering* (the cost a confirmation gate
    imposes); anything longer is *away* and is excluded from the optimisation
    split entirely. Without that cut a single lunch break dwarfs every real
    number — one 107-minute gap once accounted for 43% of a session and made
    "waiting on you: 54%" look like a finding when it was an absence.
    """
    user_wait = model_tools = idle = 0.0
    slow = []
    steps = {}          # step label -> {"secs", "turns"}
    assistant_turns = 0
    human_msgs = 0
    tok = {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0}
    tool_counts = {}

    for e in events:
        if e["kind"] == "assistant":
            assistant_turns += 1
            for k in tok:
                tok[k] += e[k]
            for t in e["tools"]:
                tool_counts[t] = tool_counts.get(t, 0) + 1
        # A real human message is a `user` record that is NOT a tool result.
        elif not e["is_tool_result"]:
            human_msgs += 1

    for prev, nxt in zip(events, events[1:]):
        gap = (nxt["ts"] - prev["ts"]).total_seconds()
        if gap <= 0:
            continue
        # Attribute a gap to a step ONLY when one of the two events bounding it
        # names that step. An earlier version latched onto the last mention and
        # carried it forward, which billed a whole 4-hour session to one step —
        # undercounting is recoverable, a confidently wrong number is not.
        here = STEP_RE.search(prev["text"] or "") or STEP_RE.search(nxt["text"] or "")
        current_step = here.group(1) if here else None

        # assistant finished -> a genuine human reply = waiting on the user
        if prev["kind"] == "assistant" and nxt["kind"] == "user" and not nxt["is_tool_result"]:
            if gap >= idle_secs:
                idle += gap
                continue        # away — not attributable to the workflow
            user_wait += gap
        else:
            model_tools += gap
            if gap >= slow_call:
                slow.append({
                    "secs": round(gap, 1),
                    "after_tools": prev["tools"],
                    "step": current_step,
                })
        if current_step:
            s = steps.setdefault(current_step, {"secs": 0.0, "turns": 0})
            s["secs"] += gap
            if nxt["kind"] == "assistant":
                s["turns"] += 1

    total = (events[-1]["ts"] - events[0]["ts"]).total_seconds() if len(events) > 1 else 0.0
    slow.sort(key=lambda s: -s["secs"])
    return {
        "total_secs": round(total, 1),
        "active_secs": round(total - idle, 1),
        "idle_secs": round(idle, 1),
        "user_wait_secs": round(user_wait, 1),
        "model_tools_secs": round(model_tools, 1),
        "assistant_turns": assistant_turns,
        "human_messages": human_msgs,
        "tokens": tok,
        "tool_counts": dict(sorted(tool_counts.items(), key=lambda kv: -kv[1])),
        "slow_calls": slow[:15],
        "by_step": {k: {"secs": round(v["secs"], 1), "turns": v["turns"]}
                    for k, v in sorted(steps.items())},
    }


def _fmt(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"


def render(rep: dict, path: Path) -> str:
    active = rep["active_secs"] or 1
    pct = lambda v: f"{100 * v / active:4.1f}%"        # noqa: E731
    idle_note = (f"   (excludes {_fmt(rep['idle_secs'])} you were away)"
                 if rep["idle_secs"] else "")
    lines = [
        f"Session: {path.name}",
        f"Elapsed: {_fmt(rep['total_secs'])}   "
        f"assistant turns: {rep['assistant_turns']}   "
        f"your messages: {rep['human_messages']}",
        f"Active:  {_fmt(rep['active_secs'])}{idle_note}",
        "",
        "Where the active time went",
        f"  answering me     {_fmt(rep['user_wait_secs']):>8}  {pct(rep['user_wait_secs'])}"
        "   <- removed by cutting confirmation gates",
        f"  model + tools    {_fmt(rep['model_tools_secs']):>8}  {pct(rep['model_tools_secs'])}"
        "   <- removed by codifying mechanical work",
        "",
        "Tokens",
        f"  in {rep['tokens']['in']:,}   out {rep['tokens']['out']:,}   "
        f"cache read {rep['tokens']['cache_read']:,}   "
        f"cache write {rep['tokens']['cache_write']:,}",
    ]
    if rep["tool_counts"]:
        top = ", ".join(f"{k} x{v}" for k, v in list(rep["tool_counts"].items())[:8])
        lines += ["", f"Tools: {top}"]
    if rep["slow_calls"]:
        lines += ["", "Slowest single gaps (often irreducible — a dbt job, a dep walk)"]
        for s in rep["slow_calls"][:8]:
            after = ", ".join(s["after_tools"]) or "-"
            step = f" [Step {s['step']}]" if s["step"] else ""
            lines.append(f"  {_fmt(s['secs']):>8}  after {after}{step}")
    if rep["by_step"]:
        lines += ["", "By SKILL step (only gaps whose surrounding text names the step —\n  a lower bound, never inflated)"]
        for k, v in rep["by_step"].items():
            lines.append(f"  Step {k:<8} {_fmt(v['secs']):>8}  {v['turns']} turn(s)")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", help="Transcript path, or a session uuid.")
    ap.add_argument("--cwd", default=os.getcwd(),
                    help="Project dir whose transcripts to search (default: cwd).")
    ap.add_argument("--grep", help="Only report if the transcript mentions this string.")
    ap.add_argument("--idle-secs", type=float, default=DEFAULT_IDLE,
                    help="A human reply gap at or over this is counted as AWAY and "
                         f"excluded, not as answering a prompt (default: {DEFAULT_IDLE:.0f}).")
    ap.add_argument("--slow-call-secs", type=float, default=DEFAULT_SLOW_CALL,
                    help=f"Gap size counted as a slow call (default: {DEFAULT_SLOW_CALL}).")
    ap.add_argument("--json", action="store_true", help="Emit the report as JSON.")
    args = ap.parse_args()

    path = _resolve_session(args.session, Path(args.cwd).resolve())
    if path is None:
        print("No transcript found. Pass --session <path>, or check --cwd.",
              file=sys.stderr)
        return 0

    events = load_events(path)
    if len(events) < 2:
        print(f"{path.name}: too few timed events to measure.", file=sys.stderr)
        return 0
    if args.grep and not any(args.grep in (e["text"] or "") for e in events):
        print(f"{path.name}: no mention of {args.grep!r}.", file=sys.stderr)
        return 0

    rep = analyse(events, args.slow_call_secs, args.idle_secs)
    print(json.dumps(rep, indent=2) if args.json else render(rep, path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
