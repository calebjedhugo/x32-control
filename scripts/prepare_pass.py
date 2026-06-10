#!/usr/bin/env python3
"""
Generate the per-pass context brief for x32-auto-awesome workers.

Does the deterministic pass setup the orchestrator used to do by hand:
classifies active channels by label (classify_channel from analyze.py),
builds per-group --channels lists, loads gain targets from docs/VENUE.md,
and writes the brief markdown that analysis workers read.

Channels that classify as 'unknown' are surfaced on stdout and in the brief —
they are NOT placed in any worker group, so they won't be optimized with
wrong-type targets. Tell the engineer to fix the label on the board.

Usage:
    python prepare_pass.py captures/session_XXX.json --mode full --rta-status pending
    python prepare_pass.py captures/session_XXX.json --mode focused:drums --rta-status present
    python prepare_pass.py captures/session_XXX.json --mode focused:ch:5 --rta-status unavailable \
        --pass-num 2 --changelog-summary "12 changes applied through iter 2" \
        --preferences "leave bass alone"

Writes /tmp/agent_prompt_context_brief.md (override with --output) and prints
a one-line summary the orchestrator routes on. Exit 1 on unusable capture.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from analyze import classify_channel

PROJECT_ROOT = Path(__file__).parent.parent

# Worker group <- classification types. The skill's section-scope mapping is
# derived from this; keep the two in sync (x32-auto-awesome.md, Mode section).
GROUP_TYPES = {
    "vocals": ["vocal"],
    "drums": ["kick", "snare", "floor_tom", "rack_tom", "overhead"],
    "instruments": ["piano", "keys", "bass", "electric_guitar", "acoustic_guitar", "flute", "violin"],
    "speaking": ["speaking"],
    "auxiliary": ["ambient", "computer", "auxiliary"],
}

# Focused-mode target -> classification types in scope.
FOCUS_TYPES = {
    "vocals": ["vocal"],
    "speaking": ["speaking"],
    "drums": GROUP_TYPES["drums"],
    "instruments": GROUP_TYPES["instruments"],
    "piano": ["piano"],
    "keys": ["keys"],
    "keyboard": ["keys"],
    "bass": ["bass"],
    "guitar": ["electric_guitar", "acoustic_guitar"],
    "flute": ["flute"],
    "livestream": [],  # downstream only — no channel scope
}

RTA_STATUS_TEXT = {
    "pending": "pending",
    "present": "present in capture",
    "unavailable": "not available",
}


def load_gain_targets():
    """Parse per-group target ranges from the docs/VENUE.md Metering Targets section.

    Returns {group_name: "0.145 – 0.460 raw (-16.8 to -6.7 dB)"} or {} if missing.
    """
    venue_md = PROJECT_ROOT / "docs" / "VENUE.md"
    targets = {}
    try:
        text = venue_md.read_text()
    except OSError:
        return targets
    match = re.search(r"## Metering Targets(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if not match:
        return targets
    section = match.group(1)
    for group_match in re.finditer(r"### (\w+)\n(.*?)(?=\n### |\Z)", section, re.DOTALL):
        group, body = group_match.group(1), group_match.group(2)
        row = re.search(r"\|\s*Target range\s*\|\s*([^|]+)\|\s*([^|]+)\|", body)
        if row:
            targets[group.lower()] = f"{row.group(1).strip()} raw ({row.group(2).strip()} dB)"
    return targets


def main():
    parser = argparse.ArgumentParser(description="Generate the x32-auto-awesome context brief")
    parser.add_argument("capture_file", help="Session capture JSON")
    parser.add_argument("--mode", default="full",
                        help="'full', 'focused:<target>', or 'focused:ch:<N>'")
    parser.add_argument("--rta-status", required=True,
                        choices=list(RTA_STATUS_TEXT.keys()),
                        help="RTA data status for this pass")
    parser.add_argument("--pass-num", type=int, default=1, help="Pass number (for the header)")
    parser.add_argument("--changelog-summary", default="first pass",
                        help='One-line changelog summary (e.g. "12 changes applied through iter 2")')
    parser.add_argument("--preferences", default="none yet",
                        help="Engineer preferences stated this session")
    parser.add_argument("--output", default="/tmp/agent_prompt_context_brief.md",
                        help="Brief output path")
    args = parser.parse_args()

    capture_path = Path(args.capture_file)
    if not capture_path.exists():
        print(f"Error: capture not found: {capture_path}", file=sys.stderr)
        sys.exit(1)
    try:
        capture = json.loads(capture_path.read_text())
    except json.JSONDecodeError as e:
        print(f"Error: {capture_path.name} is not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    active = capture.get("analysis", {}).get("gain_staging", {}).get("active_channels")
    if active is None:
        print(f"Error: {capture_path.name} has no analysis.gain_staging.active_channels — "
              f"re-capture with session_capture.py", file=sys.stderr)
        sys.exit(1)

    # Validate mode
    mode = args.mode.strip()
    focus_types = None
    focus_channels = None
    if mode != "full":
        focus = mode.removeprefix("focused:")
        if focus == mode:
            print(f"Error: --mode must be 'full' or 'focused:<target>' (got {mode!r})", file=sys.stderr)
            sys.exit(1)
        ch_match = re.fullmatch(r"ch:?(\d+)", focus)
        if ch_match:
            focus_channels = [int(ch_match.group(1))]
        elif focus in FOCUS_TYPES:
            focus_types = FOCUS_TYPES[focus]
        else:
            print(f"Error: unknown focus target {focus!r} — expected one of "
                  f"{sorted(FOCUS_TYPES)} or ch:<N>", file=sys.stderr)
            sys.exit(1)

    # Classify active channels
    channels = capture.get("channels", {})
    groups = {g: [] for g in GROUP_TYPES}  # group -> [(num, label, type)]
    unknown = []
    type_to_group = {t: g for g, types in GROUP_TYPES.items() for t in types}
    for ch_num in sorted(active):
        label = channels.get(f"ch{ch_num:02d}", {}).get("name", "")
        ch_type = classify_channel(label)
        group = type_to_group.get(ch_type)
        if group:
            groups[group].append((ch_num, label, ch_type))
        else:
            unknown.append((ch_num, label))

    # Focused scope channel list
    in_scope = None
    if focus_channels is not None:
        in_scope = [n for n in focus_channels if n in active]
    elif focus_types is not None:
        in_scope = [n for g in GROUP_TYPES for (n, _, t) in groups[g] if t in focus_types]

    gain_targets = load_gain_targets()

    # Build the brief
    lines = [f"## Context Brief — Pass {args.pass_num}", ""]
    lines.append(f"**Capture**: {capture_path}")
    lines.append(f"**Active channels**: {', '.join(f'ch{n}' for n in sorted(active)) or 'NONE'}")
    lines.append("**Channel classification** (from mixer labels via classify_channel()):")
    for group in GROUP_TYPES:
        if groups[group]:
            members = ", ".join(f"ch{n} {label}" for n, label, _ in groups[group])
            lines.append(f"  {group.capitalize()}: {members}")
    if unknown:
        members = ", ".join(f"ch{n} {label!r}" for n, label in unknown)
        lines.append(f"  UNKNOWN (not optimized — fix labels on the board): {members}")
    ch_lists = "  ".join(
        f"{g}={','.join(str(n) for n, _, _ in groups[g])}" for g in GROUP_TYPES if groups[g]
    )
    lines.append(f"**Channel lists for --channels**: {ch_lists or 'none'}")
    lines.append("**Docs**: docs/CHANNELS.md, docs/VENUE.md, docs/CORRECTIONS.md, docs/TECHNICAL.md (value conversions)")
    if mode == "full":
        lines.append("**Mode**: full")
    elif in_scope:
        lines.append(f"**Mode**: {mode} (in scope: {', '.join(f'ch{n}' for n in in_scope)})")
    elif focus_channels is not None or focus_types:
        requested = (f"ch{focus_channels[0]}" if focus_channels is not None
                     else "/".join(focus_types))
        lines.append(f"**Mode**: {mode} (WARNING: no active channels match {requested} — "
                     f"downstream stages only)")
    else:
        lines.append(f"**Mode**: {mode} (downstream only — no channel scope)")
    if gain_targets:
        targets_str = "; ".join(f"{g.capitalize()}: {t}" for g, t in gain_targets.items())
        lines.append(f"**Gain targets** (peak ranges from VENUE.md): {targets_str}")
    else:
        lines.append("**Gain targets**: NOT FOUND in VENUE.md — skip trim adjustments this session")
    lines.append(f"**RTA status**: {RTA_STATUS_TEXT[args.rta_status]}")
    lines.append(f"**User preferences**: {args.preferences}")
    lines.append(f"**Changelog**: {args.changelog_summary}")
    lines.append("")

    Path(args.output).write_text("\n".join(lines))

    # One-line summary for the orchestrator
    summary = f"brief: {args.output}  {ch_lists or 'no active channels'}"
    if unknown:
        summary += f"  UNKNOWN={','.join(str(n) for n, _ in unknown)} (alert engineer)"
    if not gain_targets:
        summary += "  NO-GAIN-TARGETS"
    if mode != "full" and not in_scope and (focus_channels is not None or focus_types):
        summary += "  EMPTY-SCOPE (focus target not active)"
    print(summary)


if __name__ == "__main__":
    main()
