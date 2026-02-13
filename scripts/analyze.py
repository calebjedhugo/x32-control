#!/usr/bin/env python3
"""
Mix analysis engine for X-32 session captures.

Designed for Claude Code consumption: outputs JSON by default with
actionable fix commands (control.py invocations) for each finding.

Usage:
    python analyze.py                                    # Latest session (JSON)
    python analyze.py captures/session_2026-01-25.json   # Specific file
    python analyze.py --text                             # Human-readable report
    python analyze.py -p warning                         # Warnings only
"""

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))

from common import fader_to_db, hpf_value_to_hz, PROJECT_ROOT


# =============================================================================
# Conversion utilities
# =============================================================================

def eq_freq_to_hz(value: float) -> float:
    """Convert X32 EQ frequency value (0.0-1.0) to Hz.
    Logarithmic: 20Hz at 0.0, 20kHz at 1.0."""
    return 20 * (1000 ** value)


def eq_gain_to_db(value: float) -> float:
    """Convert X32 EQ gain value (0.0-1.0) to dB. 0.5 = 0dB (flat).
    Range: -15dB to +15dB."""
    return (value - 0.5) * 30


def db_to_eq_gain_raw(db: float) -> float:
    """Convert dB to raw EQ gain value (0.0-1.0) for control.py --gain parameter."""
    return (db / 30.0) + 0.5


def format_freq(hz: float) -> str:
    """Format frequency for display."""
    if hz >= 1000:
        return f"{hz/1000:.1f}kHz"
    return f"{hz:.0f}Hz"


def format_gain(db: float) -> str:
    """Format gain for display."""
    if db > 0:
        return f"+{db:.1f}dB"
    return f"{db:.1f}dB"


# =============================================================================
# Fix command generation
# =============================================================================

CMD_PREFIX = "python scripts/control.py"


def eq_gain_fix(ch_num: int, band_num: int, target_db: float) -> str:
    """Generate control.py command to set a channel EQ band gain."""
    raw = db_to_eq_gain_raw(target_db)
    return f"{CMD_PREFIX} --channel {ch_num} --eq-band {band_num} --gain {raw:.3f}"


def main_eq_gain_fix(band_num: int, target_db: float) -> str:
    """Generate control.py command to set a main bus EQ band gain."""
    raw = db_to_eq_gain_raw(target_db)
    return f"{CMD_PREFIX} --main --eq-band {band_num} --gain {raw:.3f}"


def main_eq_on_fix() -> str:
    """Generate control.py command to enable main bus EQ."""
    return f"{CMD_PREFIX} --main --eq-on"


# =============================================================================
# Channel classification
# =============================================================================

# Channel group assignments (from config.json favorites)
CHANNEL_GROUPS = {
    "vocal": [1, 2, 3, 4, 5, 6, 7],
    "speaking": [8, 9],
    "auxiliary": [10, 11, 12, 13, 14, 15, 16],
    "piano": [17, 18],
    "acoustic_guitar": [19, 20],
    "flute": [21],
    "drums": [22, 23, 24, 25, 26, 27, 28],
    "keys": [29, 30],
    "bass": [31],
    "electric_guitar": [32],
}

# More specific drum channel types
DRUM_CHANNEL_TYPES = {
    22: "floor_tom",
    23: "rack_tom",
    24: "rack_tom",
    25: "snare",
    26: "kick",
    27: "overhead",
    28: "overhead",
}


def classify_channel(ch_num: int) -> str:
    """Return the source type for a channel number."""
    for group, channels in CHANNEL_GROUPS.items():
        if ch_num in channels:
            return group
    return "unknown"


def drum_subtype(ch_num: int) -> str:
    """Return specific drum type (kick, snare, etc.)."""
    return DRUM_CHANNEL_TYPES.get(ch_num, "drum")


# =============================================================================
# Target profiles - what "reasonable" looks like per source type
# =============================================================================

TARGETS = {
    "vocal": {
        "hpf_on": True,
        "hpf_range": (80, 180),       # Hz - varies by voice type
        "max_boost_db": 4.0,           # per band
        "max_presence_boost_db": 3.0,  # 2-4kHz specifically
        "mud_range": (200, 500),       # Hz - check for boosts here
        "comp_ratio_range": (2.0, 5.0),
        "label": "vocal",
    },
    "speaking": {
        "hpf_on": True,
        "hpf_range": (80, 150),
        "max_boost_db": 4.0,
        "max_presence_boost_db": 3.0,
        "mud_range": (200, 500),
        "comp_ratio_range": (2.0, 5.0),
        "label": "speaking mic",
    },
    "piano": {
        "hpf_on": True,
        "hpf_range": (25, 80),        # Grand piano needs low end
        "max_boost_db": 5.0,
        "mud_range": (250, 500),       # Boxiness range
        "comp_ratio_range": (2.0, 4.0),
        "label": "piano",
    },
    "acoustic_guitar": {
        "hpf_on": True,
        "hpf_range": (60, 150),
        "max_boost_db": 5.0,
        "mud_range": (200, 400),
        "comp_ratio_range": (2.0, 5.0),
        "label": "acoustic guitar",
    },
    "flute": {
        "hpf_on": True,
        "hpf_range": (150, 300),       # Flute fundamental starts ~260Hz
        "max_boost_db": 4.0,
        "mud_range": (200, 400),
        "comp_ratio_range": (2.0, 4.0),
        "label": "flute",
    },
    "keys": {
        "hpf_on": True,
        "hpf_range": (50, 120),
        "max_boost_db": 5.0,
        "mud_range": (200, 500),
        "comp_ratio_range": (2.0, 5.0),
        "label": "keyboard",
    },
    "bass": {
        "hpf_on": False,              # Bass needs sub content
        "hpf_range": (0, 40),         # If on, should be very low
        "max_boost_db": 6.0,
        "mud_range": (200, 400),
        "comp_ratio_range": (3.0, 10.0),
        "label": "bass guitar",
    },
    "electric_guitar": {
        "hpf_on": None,               # Depends on amp sim
        "hpf_range": (50, 120),
        "max_boost_db": 5.0,
        "mud_range": (200, 400),
        "comp_ratio_range": (2.0, 5.0),
        "label": "electric guitar",
    },
}

# Drum-specific targets
DRUM_TARGETS = {
    "kick": {
        "hpf_on": False,
        "hpf_range": (0, 40),
        "max_boost_db": 6.0,
        "comp_ratio_range": (3.0, 7.0),
        "label": "kick drum",
    },
    "snare": {
        "hpf_on": True,
        "hpf_range": (80, 180),
        "max_boost_db": 5.0,
        "comp_ratio_range": (3.0, 7.0),
        "label": "snare",
    },
    "rack_tom": {
        "hpf_on": True,
        "hpf_range": (50, 120),
        "max_boost_db": 5.0,
        "comp_ratio_range": (3.0, 7.0),
        "label": "tom",
    },
    "floor_tom": {
        "hpf_on": True,
        "hpf_range": (40, 80),
        "max_boost_db": 5.0,
        "comp_ratio_range": (3.0, 7.0),
        "label": "floor tom",
    },
    "overhead": {
        "hpf_on": True,
        "hpf_range": (150, 300),       # High HPF to cut bleed
        "max_boost_db": 5.0,
        "comp_ratio_range": (2.0, 5.0),
        "label": "overhead",
    },
}


def get_target(ch_num: int) -> Optional[dict]:
    """Get target profile for a channel."""
    ch_type = classify_channel(ch_num)
    if ch_type == "drums":
        sub = drum_subtype(ch_num)
        return DRUM_TARGETS.get(sub)
    if ch_type == "auxiliary":
        return None  # Skip auxiliary channels
    return TARGETS.get(ch_type)


# =============================================================================
# Finding / recommendation classes
# =============================================================================

PRIORITY_ORDER = {"critical": 0, "warning": 1, "suggestion": 2, "good": 3}


class Finding:
    """A single analysis finding with optional fix command."""
    def __init__(self, priority: str, channel: str, category: str,
                 message: str, suggestion: str = "", fix: str = None):
        self.priority = priority      # critical, warning, suggestion, good
        self.channel = channel        # "Ch1 Tammy" or "Main Bus"
        self.category = category      # hpf, eq, comp, masking, etc.
        self.message = message
        self.suggestion = suggestion
        self.fix = fix                # control.py command string, or None

    def to_dict(self):
        d = {
            "priority": self.priority,
            "channel": self.channel,
            "category": self.category,
            "message": self.message,
            "suggestion": self.suggestion,
        }
        if self.fix:
            d["fix"] = self.fix
        return d

    def __repr__(self):
        return f"[{self.priority.upper()}] {self.channel}: {self.message}"


def ch_label(ch_num: int, ch_data: dict) -> str:
    """Format channel label: 'Ch1 Tammy'."""
    name = ch_data.get("name", "")
    return f"Ch{ch_num} {name}".strip()


# =============================================================================
# Per-channel analysis checks
# =============================================================================

def check_hpf(ch_num: int, ch_data: dict, target: dict) -> List[Finding]:
    """Check high-pass filter settings against target.
    No fix commands available - control.py does not support HPF."""
    findings = []
    label = ch_label(ch_num, ch_data)
    preamp = ch_data.get("preamp", {})
    hpf_on = preamp.get("hpf_on", False)
    hpf_hz = preamp.get("hpf_hz", 20)
    source_label = target.get("label", "source")

    if target.get("hpf_on") is True and not hpf_on:
        findings.append(Finding(
            "warning", label, "hpf",
            f"HPF is OFF - recommended for {source_label}",
            f"Enable HPF at ~{target['hpf_range'][0]}-{target['hpf_range'][1]}Hz"
        ))
    elif target.get("hpf_on") is False and hpf_on and hpf_hz > target["hpf_range"][1]:
        findings.append(Finding(
            "warning", label, "hpf",
            f"HPF at {hpf_hz}Hz is high for {source_label} (sub content may be lost)",
            f"Consider lowering to {target['hpf_range'][1]}Hz or below"
        ))
    elif hpf_on:
        lo, hi = target["hpf_range"]
        if hpf_hz < lo * 0.7:  # Significantly below range
            findings.append(Finding(
                "suggestion", label, "hpf",
                f"HPF at {hpf_hz}Hz is low for {source_label} (target: {lo}-{hi}Hz)",
                f"Could raise to ~{lo}Hz to clean up low-end bleed"
            ))
        elif hpf_hz > hi * 1.3:  # Significantly above range
            findings.append(Finding(
                "suggestion", label, "hpf",
                f"HPF at {hpf_hz}Hz is high for {source_label} (target: {lo}-{hi}Hz)",
                f"May be cutting useful content. Consider lowering toward {hi}Hz"
            ))

    return findings


def check_eq(ch_num: int, ch_data: dict, target: dict) -> List[Finding]:
    """Check EQ settings: excessive boosts, mud range, presence stacking."""
    findings = []
    label = ch_label(ch_num, ch_data)
    eq = ch_data.get("eq", {})

    if not eq.get("on", False):
        return findings  # EQ off, nothing to check

    source_label = target.get("label", "source")
    max_boost = target.get("max_boost_db", 5.0)
    max_presence = target.get("max_presence_boost_db", max_boost)
    mud_lo, mud_hi = target.get("mud_range", (200, 400))

    for band_data in eq.get("bands", []):
        gain_db = eq_gain_to_db(band_data["gain"])
        freq_hz = eq_freq_to_hz(band_data["freq"])
        band_num = band_data["band"]

        # Skip flat bands
        if abs(gain_db) < 0.5:
            continue

        freq_str = format_freq(freq_hz)
        gain_str = format_gain(gain_db)

        # Check excessive boosts
        if gain_db > max_boost:
            findings.append(Finding(
                "warning", label, "eq",
                f"Band {band_num}: {gain_str} at {freq_str} exceeds {format_gain(max_boost)} limit for {source_label}",
                f"Consider reducing to under {format_gain(max_boost)}",
                fix=eq_gain_fix(ch_num, band_num, max_boost)
            ))

        # Check presence boost stacking (2-4kHz on vocals)
        if gain_db > max_presence and 2000 <= freq_hz <= 4000:
            if classify_channel(ch_num) in ("vocal", "speaking"):
                findings.append(Finding(
                    "warning", label, "eq",
                    f"Band {band_num}: {gain_str} boost at {freq_str} in presence range",
                    f"Presence boosts stack across vocals. Keep under {format_gain(max_presence)} to avoid harshness",
                    fix=eq_gain_fix(ch_num, band_num, max_presence)
                ))

        # Check mud range boosts (room issue: 200-400Hz)
        if gain_db > 1.0 and mud_lo <= freq_hz <= mud_hi:
            findings.append(Finding(
                "warning", label, "eq",
                f"Band {band_num}: {gain_str} boost at {freq_str} in room problem area ({mud_lo}-{mud_hi}Hz)",
                "Room has 200-400Hz buildup from corner-loaded sub and hard walls. "
                "Boosts here add to the problem. Consider cutting or staying flat.",
                fix=eq_gain_fix(ch_num, band_num, 0.0)
            ))

        # Note good subtractive cuts in problem range
        if gain_db < -2.0 and 180 <= freq_hz <= 500:
            findings.append(Finding(
                "good", label, "eq",
                f"Band {band_num}: {gain_str} cut at {freq_str} - good room compensation",
                ""
            ))

    return findings


def check_compressor(ch_num: int, ch_data: dict, target: dict) -> List[Finding]:
    """Check compressor settings against target profile.
    No fix commands - control.py does not support --comp-ratio."""
    findings = []
    label = ch_label(ch_num, ch_data)
    comp = ch_data.get("compressor", {})

    if not comp.get("on", False):
        return findings

    source_label = target.get("label", "source")
    ratio_range = target.get("comp_ratio_range")

    if ratio_range:
        ratio_str = comp.get("ratio", "")
        try:
            ratio_val = float(ratio_str.replace(":1", ""))
            lo, hi = ratio_range
            if ratio_val > hi * 1.5:
                findings.append(Finding(
                    "warning", label, "dynamics",
                    f"Compressor ratio {ratio_str} is very aggressive for {source_label}",
                    f"Typical range: {lo:.0f}:1 to {hi:.0f}:1"
                ))
            elif ratio_val < lo * 0.7 and ratio_val > 1.2:
                findings.append(Finding(
                    "suggestion", label, "dynamics",
                    f"Compressor ratio {ratio_str} is gentle for {source_label}",
                    f"Typical range: {lo:.0f}:1 to {hi:.0f}:1. May not be controlling dynamics enough."
                ))
        except (ValueError, AttributeError):
            pass

    return findings


def check_fader_balance(ch_num: int, ch_data: dict) -> List[Finding]:
    """Check for extreme fader positions that suggest gain staging issues.
    No fix commands - these are gain staging issues requiring preamp adjustment."""
    findings = []
    label = ch_label(ch_num, ch_data)
    fader = ch_data.get("fader", 0.0)

    # Use mixer-reported dB when available
    fader_db_str = ch_data.get("fader_db", "")
    if not fader_db_str:
        db = fader_to_db(fader)
        fader_db_str = f"{db:.1f} dB" if not math.isinf(db) else "-inf dB"

    if ch_data.get("mute", False):
        return findings  # Skip muted channels

    if fader > 0.9:  # Above +6dB
        findings.append(Finding(
            "warning", label, "gain",
            f"Fader at {fader_db_str} - near maximum",
            "May need more preamp gain instead of pushing the fader this high"
        ))
    elif fader < 0.3 and fader > 0.01:  # Very low but not off
        findings.append(Finding(
            "suggestion", label, "gain",
            f"Fader at {fader_db_str} - very low",
            "May have too much preamp gain. Consider reducing preamp and raising fader toward unity"
        ))

    return findings


# =============================================================================
# Cross-channel analysis
# =============================================================================

def get_active_eq_bands(ch_data: dict) -> List[Tuple[int, float, float]]:
    """Return list of (band_num, freq_hz, gain_db) for active EQ bands."""
    eq = ch_data.get("eq", {})
    if not eq.get("on", False):
        return []
    bands = []
    for b in eq.get("bands", []):
        gain_db = eq_gain_to_db(b["gain"])
        if abs(gain_db) > 0.5:
            freq_hz = eq_freq_to_hz(b["freq"])
            bands.append((b["band"], freq_hz, gain_db))
    return bands


def check_vocal_presence_stacking(channels: dict) -> List[Finding]:
    """Check if multiple vocals are boosting in the same presence range."""
    findings = []
    presence_boosts = []

    for ch_key, ch_data in channels.items():
        ch_num = int(ch_key.replace("ch", ""))
        if classify_channel(ch_num) != "vocal":
            continue
        if ch_data.get("mute", False):
            continue

        for band_num, freq_hz, gain_db in get_active_eq_bands(ch_data):
            if gain_db > 1.0 and 1500 <= freq_hz <= 5000:
                name = ch_data.get("name", ch_key)
                presence_boosts.append((ch_num, name, band_num, freq_hz, gain_db))

    if len(presence_boosts) >= 3:
        details = ", ".join(
            f"{name} {format_gain(g)} at {format_freq(f)}"
            for _, name, _, f, g in presence_boosts
        )
        # Fix: reduce each to +2dB
        fix_cmds = " && ".join(
            eq_gain_fix(ch, bn, 2.0)
            for ch, _, bn, _, g in presence_boosts if g > 2.0
        )
        findings.append(Finding(
            "warning", "Vocals", "masking",
            f"{len(presence_boosts)} vocals boosting in presence range: {details}",
            "Presence boosts stack and cause harshness. Consider keeping individual "
            "boosts under +2dB when 3+ vocals are active.",
            fix=fix_cmds if fix_cmds else None
        ))
    elif len(presence_boosts) == 2:
        details = ", ".join(
            f"{name} {format_gain(g)} at {format_freq(f)}"
            for _, name, _, f, g in presence_boosts
        )
        findings.append(Finding(
            "suggestion", "Vocals", "masking",
            f"2 vocals boosting presence: {details}",
            "Watch for harshness when both are singing. Stacked boosts add up."
        ))

    return findings


def check_piano_keyboard_masking(channels: dict) -> List[Finding]:
    """Check frequency overlap between piano and keyboard."""
    findings = []

    piano_bands = []
    kb_bands = []

    for ch_key, ch_data in channels.items():
        ch_num = int(ch_key.replace("ch", ""))
        if ch_data.get("mute", False):
            continue

        if ch_num in (17, 18):
            for band_num, freq_hz, gain_db in get_active_eq_bands(ch_data):
                piano_bands.append((ch_num, band_num, freq_hz, gain_db))
        elif ch_num in (29, 30):
            for band_num, freq_hz, gain_db in get_active_eq_bands(ch_data):
                kb_bands.append((ch_num, band_num, freq_hz, gain_db))

    if not piano_bands or not kb_bands:
        return findings

    # Check for boosts in overlapping frequency ranges
    for p_ch, p_bn, p_freq, p_gain in piano_bands:
        if p_gain <= 0:
            continue
        for k_ch, k_bn, k_freq, k_gain in kb_bands:
            if k_gain <= 0:
                continue
            # If both boosting within an octave of each other
            ratio = max(p_freq, k_freq) / min(p_freq, k_freq) if min(p_freq, k_freq) > 0 else 999
            if ratio < 2.0:
                # Fix: cut the keyboard's conflicting band to 0dB
                findings.append(Finding(
                    "warning", "Piano vs Keyboard", "masking",
                    f"Both boosting nearby: Piano {format_gain(p_gain)} at {format_freq(p_freq)}, "
                    f"KB {format_gain(k_gain)} at {format_freq(k_freq)}",
                    "These instruments fight for the same space. "
                    "Consider: piano owns warm mids (400-2kHz), keyboard owns sparkle (3kHz+).",
                    fix=eq_gain_fix(k_ch, k_bn, 0.0)
                ))
                return findings  # One finding is enough

    return findings


def check_kick_bass_conflict(channels: dict) -> List[Finding]:
    """Check kick vs bass low-end frequency overlap."""
    findings = []

    kick_data = channels.get("ch26", {})
    bass_data = channels.get("ch31", {})

    if kick_data.get("mute", False) or bass_data.get("mute", False):
        return findings

    kick_bands = get_active_eq_bands(kick_data)
    bass_bands = get_active_eq_bands(bass_data)

    # Check if both are boosting in the same low-frequency area
    for k_bn, k_freq, k_gain in kick_bands:
        if k_gain <= 0 or k_freq > 200:
            continue
        for b_bn, b_freq, b_gain in bass_bands:
            if b_gain <= 0 or b_freq > 200:
                continue
            ratio = max(k_freq, b_freq) / min(k_freq, b_freq) if min(k_freq, b_freq) > 0 else 999
            if ratio < 2.0:
                # Fix: cut the bass's conflicting band (kick typically owns the sub)
                findings.append(Finding(
                    "warning", "Kick vs Bass", "masking",
                    f"Both boosting in low-end: Kick {format_gain(k_gain)} at {format_freq(k_freq)}, "
                    f"Bass {format_gain(b_gain)} at {format_freq(b_freq)}",
                    "Choose who owns the sub: typically kick gets 50-80Hz fundamental, "
                    "bass gets 80-120Hz. One boosts, the other cuts at that frequency.",
                    fix=eq_gain_fix(31, b_bn, 0.0)
                ))
                return findings

    return findings


def check_stereo_pair_consistency(channels: dict, pair: Tuple[int, int],
                                  label: str) -> List[Finding]:
    """Check that stereo-linked channels have similar EQ."""
    findings = []
    ch_a = channels.get(f"ch{pair[0]:02d}", {})
    ch_b = channels.get(f"ch{pair[1]:02d}", {})

    if not ch_a or not ch_b:
        return findings

    eq_a = ch_a.get("eq", {})
    eq_b = ch_b.get("eq", {})

    if eq_a.get("on") != eq_b.get("on"):
        findings.append(Finding(
            "suggestion", label, "stereo",
            f"EQ on/off mismatch: Ch{pair[0]} EQ {'on' if eq_a.get('on') else 'off'}, "
            f"Ch{pair[1]} EQ {'on' if eq_b.get('on') else 'off'}",
            "Stereo pair should typically have matching EQ settings"
        ))
        return findings

    if not eq_a.get("on"):
        return findings

    bands_a = eq_a.get("bands", [])
    bands_b = eq_b.get("bands", [])

    for ba, bb in zip(bands_a, bands_b):
        gain_diff = abs(eq_gain_to_db(ba["gain"]) - eq_gain_to_db(bb["gain"]))
        freq_ratio = eq_freq_to_hz(ba["freq"]) / eq_freq_to_hz(bb["freq"]) if eq_freq_to_hz(bb["freq"]) > 0 else 1
        if gain_diff > 2.0 or freq_ratio > 1.5 or freq_ratio < 0.67:
            findings.append(Finding(
                "suggestion", label, "stereo",
                f"Stereo pair EQ differs significantly on band {ba['band']}",
                "This may be intentional (different mic positions) or a capture artifact. "
                "Verify on the mixer."
            ))
            break

    return findings


# =============================================================================
# Main bus analysis
# =============================================================================

def check_main_bus(main_data: dict) -> List[Finding]:
    """Check main bus EQ and compression."""
    findings = []
    eq = main_data.get("eq", {})

    if not eq.get("on", False):
        findings.append(Finding(
            "critical", "Main Bus", "eq",
            "Main bus EQ is OFF - room correction is not active",
            "This room needs LF cuts on the master to compensate for the "
            "corner-loaded sub and low-mid buildup.",
            fix=main_eq_on_fix()
        ))
        return findings

    # Check for LF correction
    has_lf_cut = False
    for band in eq.get("bands", []):
        freq_hz = eq_freq_to_hz(band["freq"])
        gain_db = eq_gain_to_db(band["gain"])

        if freq_hz < 250 and gain_db < -5:
            has_lf_cut = True
            findings.append(Finding(
                "good", "Main Bus", "eq",
                f"LF correction active: {format_gain(gain_db)} at {format_freq(freq_hz)}",
                ""
            ))

    if not has_lf_cut:
        findings.append(Finding(
            "critical", "Main Bus", "eq",
            "No significant LF cut found on main bus",
            "Room needs LF compensation. Expect -8 to -12dB cuts below 200Hz."
        ))

    # Check compressor
    comp = main_data.get("compressor", {})
    if comp.get("on"):
        findings.append(Finding(
            "good", "Main Bus", "dynamics",
            "Main bus compressor enabled",
            ""
        ))

    # Check for excessive high-frequency cuts (reflective ceiling)
    for band in eq.get("bands", []):
        freq_hz = eq_freq_to_hz(band["freq"])
        gain_db = eq_gain_to_db(band["gain"])
        if 2000 <= freq_hz <= 6000 and gain_db < -4:
            findings.append(Finding(
                "suggestion", "Main Bus", "eq",
                f"{format_gain(gain_db)} cut at {format_freq(freq_hz)} on main bus",
                "This is likely compensating for the reflective wood ceiling. "
                "Verify it's still needed and not over-cutting clarity."
            ))

    return findings


# =============================================================================
# Session-level checks
# =============================================================================

def check_muted_channels_with_eq(channels: dict) -> List[Finding]:
    """Flag muted channels that have significant EQ - might be forgotten settings."""
    findings = []
    for ch_key, ch_data in channels.items():
        if not ch_data.get("mute", False):
            continue
        ch_num = int(ch_key.replace("ch", ""))
        if classify_channel(ch_num) == "auxiliary":
            continue

        eq = ch_data.get("eq", {})
        if eq.get("on"):
            has_significant = False
            for band in eq.get("bands", []):
                if abs(eq_gain_to_db(band["gain"])) > 2:
                    has_significant = True
                    break
            if has_significant:
                label = ch_label(ch_num, ch_data)
                findings.append(Finding(
                    "suggestion", label, "state",
                    "Muted but has active EQ - person may not be here today",
                    "EQ from a previous week. Verify settings match the current person before unmuting."
                ))

    return findings


# =============================================================================
# Report generation
# =============================================================================

def generate_text_report(findings: List[Finding], session_data: dict) -> str:
    """Generate human-readable analysis report."""
    lines = []
    meta = session_data.get("metadata", {})
    capture_time = meta.get("capture_time", "unknown")

    lines.append("=" * 65)
    lines.append("  MIX ANALYSIS REPORT")
    lines.append("=" * 65)
    lines.append(f"Session: {capture_time}")

    # Count active channels
    active = [
        ch_key for ch_key, ch_data in session_data.get("channels", {}).items()
        if not ch_data.get("mute", False)
        and ch_data.get("fader", 0) > 0.01
    ]
    lines.append(f"Active channels: {len(active)}")
    lines.append("")

    # Sort findings by priority
    findings.sort(key=lambda f: PRIORITY_ORDER.get(f.priority, 99))

    # Group by priority
    for priority in ["critical", "warning", "suggestion", "good"]:
        group = [f for f in findings if f.priority == priority]
        if not group:
            continue

        header = {
            "critical": "CRITICAL",
            "warning": "WARNINGS",
            "suggestion": "SUGGESTIONS",
            "good": "LOOKS GOOD",
        }[priority]

        lines.append(f"--- {header} ({len(group)}) ---")
        lines.append("")

        for f in group:
            prefix = {"critical": "!!", "warning": " >", "suggestion": " -", "good": " +"}[priority]
            lines.append(f"  {prefix} [{f.channel}] {f.message}")
            if f.suggestion:
                lines.append(f"     -> {f.suggestion}")
            if f.fix:
                lines.append(f"     fix: {f.fix}")
            lines.append("")

    # Summary
    counts = {}
    for f in findings:
        counts[f.priority] = counts.get(f.priority, 0) + 1

    lines.append("-" * 65)
    parts = []
    for p in ["critical", "warning", "suggestion", "good"]:
        if counts.get(p, 0) > 0:
            parts.append(f"{counts[p]} {p}")
    lines.append(f"Total: {', '.join(parts)}")
    lines.append("")

    return "\n".join(lines)


# =============================================================================
# Main analysis pipeline
# =============================================================================

def analyze_session(session_path: Path) -> Tuple[List[Finding], dict]:
    """Run all analysis checks on a session capture file."""
    with open(session_path) as f:
        session = json.load(f)

    findings = []
    channels = session.get("channels", {})

    # --- Per-channel checks ---
    for ch_key, ch_data in channels.items():
        ch_num = int(ch_key.replace("ch", ""))
        target = get_target(ch_num)
        if target is None:
            continue  # Skip auxiliary/unknown channels

        if ch_data.get("mute", False):
            continue  # Skip muted channels for active checks

        findings.extend(check_hpf(ch_num, ch_data, target))
        findings.extend(check_eq(ch_num, ch_data, target))
        findings.extend(check_compressor(ch_num, ch_data, target))
        findings.extend(check_fader_balance(ch_num, ch_data))

    # --- Cross-channel checks ---
    findings.extend(check_vocal_presence_stacking(channels))
    findings.extend(check_piano_keyboard_masking(channels))
    findings.extend(check_kick_bass_conflict(channels))
    findings.extend(check_stereo_pair_consistency(channels, (17, 18), "Piano L/R"))
    findings.extend(check_stereo_pair_consistency(channels, (29, 30), "KB L/R"))

    # --- Main bus ---
    findings.extend(check_main_bus(session.get("main", {})))

    # --- Session-level ---
    findings.extend(check_muted_channels_with_eq(channels))

    return findings, session


def find_latest_session() -> Optional[Path]:
    """Find most recent session_*.json in captures/."""
    captures_dir = PROJECT_ROOT / "captures"
    if not captures_dir.exists():
        return None

    sessions = sorted(captures_dir.glob("session_*.json"))
    return sessions[-1] if sessions else None


def main():
    parser = argparse.ArgumentParser(
        description="Analyze X-32 session capture and produce mix recommendations (JSON default)",
    )
    parser.add_argument(
        "session_file",
        nargs="?",
        help="Path to session capture JSON (default: latest)"
    )
    parser.add_argument(
        "--text", action="store_true",
        help="Output human-readable text report instead of JSON"
    )
    parser.add_argument(
        "--priority", "-p",
        choices=["critical", "warning", "suggestion", "good", "all"],
        default="all",
        help="Filter by priority level (default: all)"
    )

    args = parser.parse_args()

    # Find session file
    if args.session_file:
        session_path = Path(args.session_file)
        if not session_path.is_absolute():
            session_path = PROJECT_ROOT / session_path
    else:
        session_path = find_latest_session()

    if not session_path or not session_path.exists():
        print(json.dumps({"error": "No session capture found. Run session_capture.py first."}))
        sys.exit(1)

    print(f"Analyzing: {session_path.name}", file=sys.stderr)

    # Run analysis
    findings, session_data = analyze_session(session_path)

    # Filter by priority
    if args.priority != "all":
        findings = [f for f in findings if f.priority == args.priority]

    # Output
    if args.text:
        print(generate_text_report(findings, session_data))
    else:
        output = {
            "session": str(session_path),
            "findings": [f.to_dict() for f in findings],
            "summary": {
                p: len([f for f in findings if f.priority == p])
                for p in ["critical", "warning", "suggestion", "good"]
            },
        }
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
