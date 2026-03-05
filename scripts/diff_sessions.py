#!/usr/bin/env python3
"""
Compare two X-32 session captures and show meaningful differences.

Designed for Claude Code consumption: outputs JSON by default.

Usage:
    python diff_sessions.py                                    # Compare two most recent (JSON)
    python diff_sessions.py session_a.json session_b.json      # Specific files
    python diff_sessions.py --text                             # Human-readable report
"""

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

sys.path.insert(0, str(Path(__file__).parent))

from common import fader_to_db, hpf_value_to_hz, PROJECT_ROOT


# =============================================================================
# Conversion utilities (matching analyze.py)
# =============================================================================

def eq_freq_to_hz(value: float) -> float:
    """Convert X32 EQ frequency value (0.0-1.0) to Hz."""
    return 20 * (1000 ** value)


def eq_gain_to_db(value: float) -> float:
    """Convert X32 EQ gain value (0.0-1.0) to dB. 0.5 = flat."""
    return (value - 0.5) * 30


def format_freq(hz: float) -> str:
    if hz >= 1000:
        return f"{hz/1000:.1f}kHz"
    return f"{hz:.0f}Hz"


def format_gain(db: float) -> str:
    if db > 0:
        return f"+{db:.1f}dB"
    return f"{db:.1f}dB"


def format_fader_db(fader: float) -> str:
    db = fader_to_db(fader)
    if math.isinf(db):
        return "-inf dB"
    return f"{db:.1f} dB"


def get_fader_db_str(ch_data: dict) -> str:
    """Get fader dB string from session data, preferring the mixer-reported value."""
    fader_db = ch_data.get("fader_db")
    if fader_db and isinstance(fader_db, str):
        return fader_db
    # Fall back to main_send level_db if available
    main = ch_data.get("main_send", {})
    if main.get("level_db"):
        return main["level_db"]
    return format_fader_db(ch_data.get("fader", 0))


# =============================================================================
# Diff logic
# =============================================================================

# Thresholds for "meaningful" changes
FADER_THRESHOLD = 0.01    # ~0.4 dB
EQ_GAIN_THRESHOLD = 0.02  # ~0.6 dB
EQ_FREQ_THRESHOLD = 0.02  # small frequency shift
HPF_THRESHOLD = 5         # Hz


class Change:
    """A single detected change between sessions."""
    def __init__(self, channel: str, category: str, description: str,
                 before: str = "", after: str = "", suspicious: bool = False):
        self.channel = channel
        self.category = category
        self.description = description
        self.before = before
        self.after = after
        self.suspicious = suspicious

    def to_dict(self):
        d = {
            "channel": self.channel,
            "category": self.category,
            "description": self.description,
        }
        if self.before:
            d["before"] = self.before
        if self.after:
            d["after"] = self.after
        if self.suspicious:
            d["suspicious"] = True
        return d


def diff_channels(ch_key: str, old: dict, new: dict) -> List[Change]:
    """Compare a single channel between two sessions."""
    changes = []
    ch_num = int(ch_key.replace("ch", ""))
    name = new.get("name") or old.get("name") or ch_key
    label = f"Ch{ch_num} {name}".strip()

    # Name change
    old_name = old.get("name", "")
    new_name = new.get("name", "")
    if old_name != new_name and old_name and new_name:
        changes.append(Change(label, "name", "Name changed",
                              old_name, new_name))

    # Mute state
    old_mute = old.get("mute", False)
    new_mute = new.get("mute", False)
    if old_mute != new_mute:
        changes.append(Change(label, "mute",
                              "MUTED" if new_mute else "UNMUTED",
                              "muted" if old_mute else "unmuted",
                              "muted" if new_mute else "unmuted"))

    # Fader
    old_fader = old.get("fader", 0)
    new_fader = new.get("fader", 0)
    if abs(old_fader - new_fader) > FADER_THRESHOLD:
        changes.append(Change(label, "fader", "Fader changed",
                              get_fader_db_str(old),
                              get_fader_db_str(new)))

    # HPF
    old_preamp = old.get("preamp", {})
    new_preamp = new.get("preamp", {})
    if old_preamp.get("hpf_on") != new_preamp.get("hpf_on"):
        changes.append(Change(label, "hpf",
                              f"HPF {'enabled' if new_preamp.get('hpf_on') else 'disabled'}",
                              "on" if old_preamp.get("hpf_on") else "off",
                              "on" if new_preamp.get("hpf_on") else "off"))
    elif (old_preamp.get("hpf_on") and new_preamp.get("hpf_on") and
          abs((old_preamp.get("hpf_hz", 20)) - (new_preamp.get("hpf_hz", 20))) > HPF_THRESHOLD):
        changes.append(Change(label, "hpf", "HPF frequency changed",
                              f"{old_preamp.get('hpf_hz', 20)}Hz",
                              f"{new_preamp.get('hpf_hz', 20)}Hz"))

    # Preamp gain
    old_gain = old_preamp.get("gain", 0.5)
    new_gain = new_preamp.get("gain", 0.5)
    if abs(old_gain - new_gain) > 0.02:
        changes.append(Change(label, "preamp", "Preamp gain changed",
                              f"{old_gain:.3f}", f"{new_gain:.3f}"))

    # Phantom power
    if old_preamp.get("phantom") != new_preamp.get("phantom"):
        changes.append(Change(label, "preamp",
                              f"Phantom {'enabled' if new_preamp.get('phantom') else 'disabled'}"))

    # EQ on/off
    old_eq = old.get("eq", {})
    new_eq = new.get("eq", {})
    if old_eq.get("on") != new_eq.get("on"):
        # Suspicious if EQ was ON with tuned bands and now shows OFF
        sus = (old_eq.get("on") and not new_eq.get("on") and
               any(b.get("gain", 0.5) != 0.5 for b in old_eq.get("bands", [])))
        desc = f"EQ {'enabled' if new_eq.get('on') else 'disabled'}"
        if sus:
            desc += "  (possible query failure — was ON with tuned bands)"
        changes.append(Change(label, "eq", desc, suspicious=sus))

    # EQ band changes
    if old_eq.get("on") and new_eq.get("on"):
        old_bands = old_eq.get("bands", [])
        new_bands = new_eq.get("bands", [])
        for ob, nb in zip(old_bands, new_bands):
            band_num = ob.get("band", "?")
            gain_diff = abs(ob.get("gain", 0.5) - nb.get("gain", 0.5))
            freq_diff = abs(ob.get("freq", 0.5) - nb.get("freq", 0.5))

            parts = []
            if gain_diff > EQ_GAIN_THRESHOLD:
                old_db = eq_gain_to_db(ob["gain"])
                new_db = eq_gain_to_db(nb["gain"])
                parts.append(f"gain {format_gain(old_db)} -> {format_gain(new_db)}")

            if freq_diff > EQ_FREQ_THRESHOLD:
                old_hz = eq_freq_to_hz(ob["freq"])
                new_hz = eq_freq_to_hz(nb["freq"])
                parts.append(f"freq {format_freq(old_hz)} -> {format_freq(new_hz)}")

            if parts:
                freq_hz = eq_freq_to_hz(nb["freq"])
                # Flag as suspicious if freq is changing TO or FROM exactly 0.5 (632Hz default)
                sus = (ob.get("freq") == 0.5 or nb.get("freq") == 0.5) and freq_diff > EQ_FREQ_THRESHOLD
                desc = f"EQ band {band_num} at {format_freq(freq_hz)}: {', '.join(parts)}"
                if sus:
                    desc += "  (possible query failure)"
                changes.append(Change(
                    label, "eq", desc, "", "", suspicious=sus
                ))

    # Gate
    old_gate = old.get("gate", {})
    new_gate = new.get("gate", {})
    if old_gate.get("on") != new_gate.get("on"):
        # Suspicious if gate was ON with tuned params and now shows OFF
        sus = (old_gate.get("on") and not new_gate.get("on") and
               old_gate.get("threshold", 0.5) != 0.5)
        desc = f"Gate {'enabled' if new_gate.get('on') else 'disabled'}"
        if sus:
            desc += "  (possible query failure — was ON with tuned params)"
        changes.append(Change(label, "gate", desc, suspicious=sus))

    # Compressor
    old_comp = old.get("compressor", {})
    new_comp = new.get("compressor", {})
    if old_comp.get("on") != new_comp.get("on"):
        # Suspicious if comp was ON with tuned params and now shows OFF
        sus = (old_comp.get("on") and not new_comp.get("on") and
               old_comp.get("threshold", 0.5) != 0.5)
        desc = f"Compressor {'enabled' if new_comp.get('on') else 'disabled'}"
        if sus:
            desc += "  (possible query failure — was ON with tuned params)"
        changes.append(Change(label, "dynamics", desc, suspicious=sus))

    if old_comp.get("on") and new_comp.get("on"):
        if old_comp.get("ratio") != new_comp.get("ratio"):
            changes.append(Change(label, "dynamics", "Compressor ratio changed",
                                  old_comp.get("ratio", "?"),
                                  new_comp.get("ratio", "?")))
        old_thr = old_comp.get("threshold", 0.5)
        new_thr = new_comp.get("threshold", 0.5)
        if abs(old_thr - new_thr) > 0.02:
            changes.append(Change(label, "dynamics", "Compressor threshold changed",
                                  f"{old_thr:.3f}", f"{new_thr:.3f}"))

    # Insert
    old_ins = old.get("insert", {})
    new_ins = new.get("insert", {})
    if old_ins.get("on") != new_ins.get("on") or old_ins.get("fx_slot") != new_ins.get("fx_slot"):
        old_fx = f"FX{old_ins.get('fx_slot')}" if old_ins.get("on") else "none"
        new_fx = f"FX{new_ins.get('fx_slot')}" if new_ins.get("on") else "none"
        if old_fx != new_fx:
            changes.append(Change(label, "insert", "Insert changed",
                                  old_fx, new_fx))

    return changes


def diff_buses(bus_key: str, old: dict, new: dict) -> List[Change]:
    """Compare a single bus between two sessions."""
    changes = []
    bus_num = int(bus_key.replace("bus", ""))
    name = new.get("name") or old.get("name") or bus_key
    label = f"Bus{bus_num} {name}".strip()

    # Fader
    old_fader = old.get("fader", 0)
    new_fader = new.get("fader", 0)
    if abs(old_fader - new_fader) > FADER_THRESHOLD:
        changes.append(Change(label, "fader", "Fader changed",
                              get_fader_db_str(old),
                              get_fader_db_str(new)))

    # Mute
    if old.get("mute") != new.get("mute"):
        changes.append(Change(label, "mute",
                              "MUTED" if new.get("mute") else "UNMUTED"))

    # EQ on/off
    old_eq = old.get("eq", {})
    new_eq = new.get("eq", {})
    if old_eq.get("on") != new_eq.get("on"):
        changes.append(Change(label, "eq",
                              f"EQ {'enabled' if new_eq.get('on') else 'disabled'}"))

    return changes


def diff_main(old: dict, new: dict) -> List[Change]:
    """Compare main bus between sessions."""
    changes = []
    label = "Main LR"

    old_fader = old.get("fader", 0)
    new_fader = new.get("fader", 0)
    if abs(old_fader - new_fader) > FADER_THRESHOLD:
        changes.append(Change(label, "fader", "Fader changed",
                              get_fader_db_str(old),
                              get_fader_db_str(new)))

    # EQ band changes
    old_eq = old.get("eq", {})
    new_eq = new.get("eq", {})
    if old_eq.get("on") and new_eq.get("on"):
        for ob, nb in zip(old_eq.get("bands", []), new_eq.get("bands", [])):
            gain_diff = abs(ob.get("gain", 0.5) - nb.get("gain", 0.5))
            if gain_diff > EQ_GAIN_THRESHOLD:
                freq_hz = eq_freq_to_hz(nb["freq"])
                old_db = eq_gain_to_db(ob["gain"])
                new_db = eq_gain_to_db(nb["gain"])
                changes.append(Change(
                    label, "eq",
                    f"Band {ob['band']} at {format_freq(freq_hz)}: "
                    f"{format_gain(old_db)} -> {format_gain(new_db)}"
                ))

    return changes


def diff_fx(fx_key: str, old: dict, new: dict) -> List[Change]:
    """Compare FX slot between sessions."""
    changes = []
    label = fx_key.upper()

    if old.get("type_id") != new.get("type_id"):
        # Suspicious if FX type changed TO 0 (Hall Reverb = default) from non-zero
        sus = (new.get("type_id") == 0 and old.get("type_id", 0) != 0)
        desc = "Effect type changed"
        if sus:
            desc += "  (possible query failure — changed to default Hall Reverb)"
        changes.append(Change(label, "fx", desc,
                              old.get("type_name", "?"),
                              new.get("type_name", "?"),
                              suspicious=sus))

    # Parameter changes (only check if same effect type)
    if old.get("type_id") == new.get("type_id"):
        old_params = old.get("parameters", {})
        new_params = new.get("parameters", {})
        for key in set(list(old_params.keys()) + list(new_params.keys())):
            old_val = old_params.get(key)
            new_val = new_params.get(key)
            # Skip NaN values
            if old_val is not None and new_val is not None:
                try:
                    if math.isnan(float(old_val)) or math.isnan(float(new_val)):
                        continue
                except (TypeError, ValueError):
                    continue
                if abs(float(old_val) - float(new_val)) > 0.02:
                    changes.append(Change(label, "fx",
                                          f"Parameter {key} changed",
                                          f"{old_val}", f"{new_val}"))

    return changes


# =============================================================================
# Report generation
# =============================================================================

def generate_text_diff(changes: List[Change],
                       old_meta: dict, new_meta: dict) -> str:
    """Generate human-readable diff report."""
    lines = []
    lines.append("=" * 65)
    lines.append("  SESSION COMPARISON")
    lines.append("=" * 65)

    old_time = old_meta.get("capture_time", "?")
    new_time = new_meta.get("capture_time", "?")
    lines.append(f"Before: {old_time}")
    lines.append(f"After:  {new_time}")
    suspicious_count = sum(1 for c in changes if c.suspicious)
    lines.append(f"Changes found: {len(changes)}" +
                 (f" ({suspicious_count} suspicious — marked [?])" if suspicious_count else ""))
    lines.append("")

    if not changes:
        lines.append("  No meaningful changes detected.")
        return "\n".join(lines)

    # Group by category
    categories = {}
    for c in changes:
        cat = c.category
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(c)

    # Display order
    cat_order = ["mute", "fader", "preamp", "hpf", "eq", "dynamics",
                 "gate", "insert", "fx", "name", "stereo"]

    for cat in cat_order:
        if cat not in categories:
            continue
        cat_changes = categories[cat]

        header = {
            "mute": "Mute Changes",
            "fader": "Fader Changes",
            "preamp": "Preamp Changes",
            "hpf": "HPF Changes",
            "eq": "EQ Changes",
            "dynamics": "Dynamics Changes",
            "gate": "Gate Changes",
            "insert": "Insert Changes",
            "fx": "FX Changes",
            "name": "Name Changes",
            "stereo": "Stereo Link Changes",
        }.get(cat, cat.title())

        lines.append(f"--- {header} ---")
        for c in cat_changes:
            prefix = "[?] " if c.suspicious else "  "
            if c.before and c.after:
                lines.append(f"{prefix}[{c.channel}] {c.description}: {c.before} -> {c.after}")
            else:
                lines.append(f"{prefix}[{c.channel}] {c.description}")
        lines.append("")

    return "\n".join(lines)


# =============================================================================
# Main
# =============================================================================

def find_recent_sessions(n: int = 2) -> List[Path]:
    """Find the N most recent session_*.json files."""
    captures_dir = PROJECT_ROOT / "captures"
    if not captures_dir.exists():
        return []
    sessions = sorted(captures_dir.glob("session_*.json"))
    return sessions[-n:] if len(sessions) >= n else sessions


def main():
    parser = argparse.ArgumentParser(
        description="Compare two X-32 session captures (JSON default)",
    )
    parser.add_argument("old_session", nargs="?", help="Older session file")
    parser.add_argument("new_session", nargs="?", help="Newer session file")
    parser.add_argument("--text", action="store_true",
                        help="Output human-readable text report instead of JSON")

    args = parser.parse_args()

    # Determine files
    if args.old_session and args.new_session:
        old_path = Path(args.old_session)
        new_path = Path(args.new_session)
        if not old_path.is_absolute():
            old_path = PROJECT_ROOT / old_path
        if not new_path.is_absolute():
            new_path = PROJECT_ROOT / new_path
    else:
        recent = find_recent_sessions(2)
        if len(recent) < 2:
            print(json.dumps({"error": "Need at least 2 session captures to compare.",
                               "found": [str(p.name) for p in recent]}))
            sys.exit(1)
        old_path, new_path = recent[0], recent[1]

    for p in [old_path, new_path]:
        if not p.exists():
            print(json.dumps({"error": f"File not found: {p}"}))
            sys.exit(1)

    print(f"Comparing:", file=sys.stderr)
    print(f"  Old: {old_path.name}", file=sys.stderr)
    print(f"  New: {new_path.name}", file=sys.stderr)

    with open(old_path) as f:
        old_session = json.load(f)
    with open(new_path) as f:
        new_session = json.load(f)

    all_changes = []

    # Diff channels
    old_channels = old_session.get("channels", {})
    new_channels = new_session.get("channels", {})
    for ch_key in sorted(set(list(old_channels.keys()) + list(new_channels.keys()))):
        if ch_key in old_channels and ch_key in new_channels:
            all_changes.extend(diff_channels(ch_key, old_channels[ch_key], new_channels[ch_key]))

    # Diff buses
    old_buses = old_session.get("buses", {})
    new_buses = new_session.get("buses", {})
    for bus_key in sorted(set(list(old_buses.keys()) + list(new_buses.keys()))):
        if bus_key in old_buses and bus_key in new_buses:
            all_changes.extend(diff_buses(bus_key, old_buses[bus_key], new_buses[bus_key]))

    # Diff main
    all_changes.extend(diff_main(
        old_session.get("main", {}), new_session.get("main", {})))

    # Diff FX
    old_fx = old_session.get("fx", {})
    new_fx = new_session.get("fx", {})
    for fx_key in sorted(set(list(old_fx.keys()) + list(new_fx.keys()))):
        if fx_key in old_fx and fx_key in new_fx:
            all_changes.extend(diff_fx(fx_key, old_fx[fx_key], new_fx[fx_key]))

    # Output
    if args.text:
        print(generate_text_diff(
            all_changes,
            old_session.get("metadata", {}),
            new_session.get("metadata", {}),
        ))
    else:
        output = {
            "old_session": str(old_path),
            "new_session": str(new_path),
            "changes": [c.to_dict() for c in all_changes],
            "total_changes": len(all_changes),
        }
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
