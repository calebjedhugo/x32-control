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
# Channel classification (label-driven)
# =============================================================================

# Keywords checked in order — first match wins. More specific patterns first.
_LABEL_RULES = [
    # Drums
    ("kick",            ["kick", "bass drum", "bassdrum"]),
    ("snare",           ["snare"]),
    ("floor_tom",       ["floor tom", "flr tom"]),
    ("rack_tom",        ["mid tom", "hi tom", "rack tom", "mid high"]),
    ("overhead",        ["overhead", "oh-", "oh ", "hi-hat", "hihat", "ride", "cymbal"]),
    # Instruments (specific before generic)
    ("piano",           ["piano", "pno"]),
    ("flute",           ["flute", "flt"]),
    ("violin",          ["violin", "fiddle"]),
    ("bass",            ["bass"]),
    ("keys",            ["kb-", "kb ", "keyboard", "keys", "synth", "electric key", "elec key"]),
    ("electric_guitar", ["elec gtr", "electric gtr", "elec guitar", "electric guitar", "amp sim"]),
    ("acoustic_guitar", ["acoustic", "acou", "guitar", "gtr"]),
    # Speaking
    ("speaking",        ["pastor", "announce", "speak", "headset"]),
    # Auxiliary
    ("ambient",         ["ambient", "amb "]),
    ("computer",        ["computer", "pc ", "playback"]),
    ("auxiliary",       ["aux", "phone", "zoom"]),
]


def classify_channel(ch_name: str) -> str:
    """Classify a channel by its mixer label. Returns source type.

    Labels should be descriptive (e.g. 'Kick', 'Tammy', 'Elec Gtr').
    Unrecognized non-empty names default to 'vocal' (most common case).
    """
    if not ch_name or not ch_name.strip():
        return "unknown"
    name = ch_name.lower().strip()
    for ch_type, keywords in _LABEL_RULES:
        if any(kw in name for kw in keywords):
            return ch_type
    # Default: person names with no instrument keyword are vocals
    return "vocal"


def find_channels_by_type(channels: dict, target_type: str) -> List[Tuple[int, dict]]:
    """Find all channels matching a source type. Returns [(ch_num, ch_data), ...]."""
    results = []
    for ch_key, ch_data in channels.items():
        ch_num = int(ch_key.replace("ch", ""))
        if classify_channel(ch_data.get("name", "")) == target_type:
            results.append((ch_num, ch_data))
    return results


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
    "violin": {
        "hpf_on": True,
        "hpf_range": (150, 300),       # Violin fundamental starts ~196Hz (G3)
        "max_boost_db": 4.0,
        "mud_range": (200, 400),
        "comp_ratio_range": (2.0, 4.0),
        "label": "violin",
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


def get_target(ch_name: str) -> Optional[dict]:
    """Get target profile for a channel by its label."""
    ch_type = classify_channel(ch_name)
    if ch_type in DRUM_TARGETS:
        return DRUM_TARGETS[ch_type]
    if ch_type in ("ambient", "computer", "auxiliary", "unknown"):
        return None  # Skip non-musical channels
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

        # Check mud range boosts first (most specific, subsumes excessive boost)
        # Exempt channels not routed to main LR (e.g. Ambient L/R ch12-13
        # which are livestream-only) — the mud range warning is FOH-specific
        routes_to_main = ch_data.get("routing", {}).get("main_lr", True)
        is_mud = gain_db > 1.0 and mud_lo <= freq_hz <= mud_hi and routes_to_main
        is_presence = (gain_db > max_presence and 2000 <= freq_hz <= 4000 and
                       classify_channel(ch_data.get("name", "")) in ("vocal", "speaking"))

        if is_mud:
            findings.append(Finding(
                "warning", label, "eq",
                f"Band {band_num}: {gain_str} boost at {freq_str} in room problem area ({mud_lo}-{mud_hi}Hz)",
                "Room has 200-400Hz buildup from corner-loaded sub and hard walls. "
                "Boosts here add to the problem. Consider cutting or staying flat.",
                fix=eq_gain_fix(ch_num, band_num, 0.0)
            ))
        elif is_presence:
            findings.append(Finding(
                "warning", label, "eq",
                f"Band {band_num}: {gain_str} boost at {freq_str} in presence range",
                f"Presence boosts stack across vocals. Keep under {format_gain(max_presence)} to avoid harshness",
                fix=eq_gain_fix(ch_num, band_num, max_presence)
            ))
        elif gain_db > max_boost:
            findings.append(Finding(
                "warning", label, "eq",
                f"Band {band_num}: {gain_str} at {freq_str} exceeds {format_gain(max_boost)} limit for {source_label}",
                f"Consider reducing to under {format_gain(max_boost)}",
                fix=eq_gain_fix(ch_num, band_num, max_boost)
            ))

        # Note good subtractive cuts in problem range (skip bass/kick where these freqs are fundamental)
        if gain_db < -2.0 and 200 <= freq_hz <= 400:
            ch_type = classify_channel(ch_data.get("name", ""))
            if ch_type not in ("bass", "kick"):
                findings.append(Finding(
                    "good", label, "eq",
                    f"Band {band_num}: {gain_str} cut at {freq_str} - good room compensation",
                    ""
                ))

    return findings


def check_compressor(ch_num: int, ch_data: dict, target: dict) -> List[Finding]:
    """Check compressor settings against target profile."""
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


def check_fader_balance(ch_num: int, ch_data: dict, dcas: dict = None) -> List[Finding]:
    """Check for extreme fader positions that suggest gain staging issues.
    No fix commands - these are gain staging issues requiring preamp adjustment.

    When DCA data is available, computes effective fader level by multiplying
    channel fader * DCA fader(s) in linear space (minimum DCA fader wins).
    A channel at unity with its DCA at -10dB is effectively at -10dB.
    """
    findings = []
    label = ch_label(ch_num, ch_data)
    fader = ch_data.get("fader", 0.0)

    if ch_data.get("mute", False):
        return findings  # Skip muted channels

    # Compute effective fader level accounting for DCA groups
    # X32 multiplies all assigned DCA faders together (not just the lowest)
    effective_fader = fader
    dca_note = ""
    if dcas and ch_data.get("dca_groups"):
        combined_dca = 1.0
        dca_names = []
        for dca_num in ch_data["dca_groups"]:
            dca_key = f"dca{dca_num}"
            dca_data = dcas.get(dca_key, {})
            dca_fader = dca_data.get("fader", 1.0)
            combined_dca *= dca_fader
            if dca_fader < 0.95:
                dca_db = fader_to_db(dca_fader)
                dca_db_str = f"{dca_db:.1f}dB" if not math.isinf(dca_db) else "-inf"
                dca_names.append(f"'{dca_data.get('name', dca_key)}' at {dca_db_str}")
        effective_fader = fader * combined_dca
        if dca_names:
            dca_note = f" (DCA: {', '.join(dca_names)})"

    # Use effective fader for dB display
    effective_db = fader_to_db(effective_fader)
    effective_db_str = f"{effective_db:.1f} dB" if not math.isinf(effective_db) else "-inf dB"

    # Also show raw fader for context when DCA is pulling it down
    raw_db = fader_to_db(fader)
    raw_db_str = f"{raw_db:.1f} dB" if not math.isinf(raw_db) else "-inf dB"

    if effective_fader > 0.9:  # Above +6dB effective
        findings.append(Finding(
            "warning", label, "gain",
            f"Effective fader at {effective_db_str}{dca_note} - near maximum",
            "May need more preamp gain instead of pushing the fader this high"
        ))
    elif effective_fader < 0.3 and effective_fader > 0.01:  # Very low but not off
        if dca_note:
            findings.append(Finding(
                "suggestion", label, "gain",
                f"Effective fader at {effective_db_str}{dca_note} (channel fader at {raw_db_str})",
                "Effective level is low due to DCA position. Check if DCA is intentionally pulled down."
            ))
        else:
            findings.append(Finding(
                "suggestion", label, "gain",
                f"Fader at {effective_db_str} - very low",
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
        if classify_channel(ch_data.get("name", "")) != "vocal":
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

        ch_type = classify_channel(ch_data.get("name", ""))
        if ch_type == "piano":
            for band_num, freq_hz, gain_db in get_active_eq_bands(ch_data):
                piano_bands.append((ch_num, band_num, freq_hz, gain_db))
        elif ch_type == "keys":
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

    kick_channels = find_channels_by_type(channels, "kick")
    bass_channels = find_channels_by_type(channels, "bass")

    if not kick_channels or not bass_channels:
        return findings

    kick_num, kick_data = kick_channels[0]
    bass_num, bass_data = bass_channels[0]

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
                    fix=eq_gain_fix(bass_num, b_bn, 0.0)
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

def check_livestream_routing(session: dict) -> List[Finding]:
    """Check that subgroup buses properly feed the livestream matrices (Cam L/R).

    Only checks buses that are actual subgroups: not feeding main LR, have a
    non-zero fader, and have at least one active matrix send (indicating they're
    meant to feed outputs other than main).
    """
    findings = []
    buses = session.get("buses", {})
    matrices = session.get("matrices", {})
    channels = session.get("channels", {})

    if not matrices:
        return findings

    # Find livestream matrices by name
    cam_matrices = {}
    for mtx_key, mtx_data in matrices.items():
        name = mtx_data.get("name", "").lower()
        if "cam" in name:
            cam_matrices[mtx_key] = mtx_data

    if not cam_matrices:
        return findings

    # Identify actual subgroup buses: not feeding main, fader up, and has at
    # least one active matrix send at non-zero level (distinguishes subgroups
    # from monitor buses which typically have zero-level matrix sends)
    subgroup_buses = {}
    for bus_key, bus_data in buses.items():
        routing = bus_data.get("routing", {})
        if routing.get("main_lr", True):
            continue  # Feeds main, not a subgroup

        fader = bus_data.get("fader", 0)
        if fader < 0.01:
            continue  # Bus fader is down

        # Check if this bus has any active matrix sends at non-zero level
        mtx_sends = bus_data.get("matrix_sends", {})
        has_active_mtx_send = any(
            s.get("on") and s.get("level", 0) > 0.01
            for s in mtx_sends.values()
        )
        if not has_active_mtx_send:
            continue  # No active matrix sends — likely a monitor bus

        bus_name = bus_data.get("name", bus_key)
        subgroup_buses[bus_key] = bus_data

    # Check each subgroup feeds each cam matrix
    for mtx_key, mtx_data in cam_matrices.items():
        mtx_name = mtx_data.get("name", mtx_key)
        for bus_key, bus_data in subgroup_buses.items():
            bus_name = bus_data.get("name", bus_key)
            mtx_sends = bus_data.get("matrix_sends", {})
            send = mtx_sends.get(mtx_key, {})

            if not send.get("on", False):
                findings.append(Finding(
                    "critical", f"Livestream: {bus_name}", "routing",
                    f"{bus_name} ({bus_key}) is NOT sending to {mtx_name} ({mtx_key})",
                    f"This subgroup won't be heard on the {mtx_name} livestream feed"
                ))
            elif send.get("level", 0) < 0.01:
                findings.append(Finding(
                    "warning", f"Livestream: {bus_name}", "routing",
                    f"{bus_name} ({bus_key}) send to {mtx_name} is at {send.get('level_db', '-inf dB')}",
                    f"Send is ON but level is zero - {bus_name} won't be heard on {mtx_name}. May be intentional (ready but silent)."
                ))

    return findings


def check_dca_coverage(session: dict) -> List[Finding]:
    """Check that active channels are assigned to a DCA group."""
    findings = []
    channels = session.get("channels", {})
    dcas = session.get("dcas", {})

    if not dcas:
        return findings

    unassigned = []
    for ch_key, ch_data in channels.items():
        ch_num = int(ch_key.replace("ch", ""))
        if ch_data.get("mute", False):
            continue
        if ch_data.get("fader", 0) < 0.01:
            continue
        ch_type = classify_channel(ch_data.get("name", ""))
        if ch_type in ("auxiliary", "ambient", "computer", "unknown"):
            continue

        dca_groups = ch_data.get("dca_groups", [])
        if not dca_groups:
            name = ch_data.get("name", ch_key)
            unassigned.append(f"Ch{ch_num} {name}")

    if unassigned:
        findings.append(Finding(
            "suggestion", "DCA Groups", "routing",
            f"{len(unassigned)} active channel(s) not in any DCA: {', '.join(unassigned[:5])}",
            "Unassigned channels can't be trimmed via DCA faders during the service"
        ))

    return findings


def check_matrix_eq(session: dict) -> List[Finding]:
    """Check livestream matrix EQ for reasonable settings."""
    findings = []
    matrices = session.get("matrices", {})

    for mtx_key, mtx_data in matrices.items():
        name = mtx_data.get("name", mtx_key)
        if "cam" not in name.lower():
            continue

        eq = mtx_data.get("eq", {})
        if not eq.get("on", False):
            findings.append(Finding(
                "warning", f"Matrix {name}", "eq",
                f"Livestream matrix {name} has EQ OFF",
                "Livestream typically needs different EQ than FOH (LF compensation, etc.)"
            ))
            continue

        for band in eq.get("bands", []):
            gain_db = eq_gain_to_db(band["gain"])
            freq_hz = eq_freq_to_hz(band["freq"])

            if gain_db > 6.0:
                findings.append(Finding(
                    "warning", f"Matrix {name}", "eq",
                    f"Band {band['band']}: {format_gain(gain_db)} boost at {format_freq(freq_hz)}",
                    "Large boosts on livestream matrix - check if this is intentional"
                ))

    return findings


def check_matrix_faders(session: dict) -> List[Finding]:
    """Check livestream matrix fader levels.

    Reasonable livestream range: -10dB to 0dB. Flag if outside range.
    """
    findings = []
    matrices = session.get("matrices", {})

    for mtx_key, mtx_data in matrices.items():
        name = mtx_data.get("name", mtx_key)
        if "cam" not in name.lower():
            continue

        if mtx_data.get("mute", False):
            findings.append(Finding(
                "critical", f"Matrix {name}", "fader",
                f"Livestream matrix {name} is MUTED",
                "Livestream output is muted - no audio going to stream"
            ))
            continue

        fader = mtx_data.get("fader", 0.0)
        fader_db = fader_to_db(fader)

        if math.isinf(fader_db):
            findings.append(Finding(
                "critical", f"Matrix {name}", "fader",
                f"Livestream matrix {name} fader is at -inf dB",
                "Fader is all the way down - no audio going to stream"
            ))
        elif fader_db < -10:
            findings.append(Finding(
                "warning", f"Matrix {name}", "fader",
                f"Livestream matrix {name} fader at {fader_db:.1f}dB is below -10dB",
                "Livestream level may be too low. Typical range is -10dB to 0dB."
            ))
        elif fader_db > 0:
            findings.append(Finding(
                "warning", f"Matrix {name}", "fader",
                f"Livestream matrix {name} fader at {fader_db:.1f}dB is above 0dB",
                "Livestream level is boosted above unity - risk of distortion on the stream."
            ))
        else:
            findings.append(Finding(
                "good", f"Matrix {name}", "fader",
                f"Livestream matrix {name} fader at {fader_db:.1f}dB (within -10 to 0dB range)",
                ""
            ))

    return findings


def check_matrix_compressor(session: dict) -> List[Finding]:
    """Check livestream matrix compressor settings.

    Livestream should be tighter than FOH: lower threshold (more compression),
    higher ratio. Flag if threshold is too high (not engaging) or ratio is too
    low for broadcast.
    """
    findings = []
    matrices = session.get("matrices", {})

    for mtx_key, mtx_data in matrices.items():
        name = mtx_data.get("name", mtx_key)
        if "cam" not in name.lower():
            continue

        comp = mtx_data.get("compressor", {})

        if not comp.get("on", False):
            findings.append(Finding(
                "warning", f"Matrix {name}", "dynamics",
                f"Livestream matrix {name} compressor is OFF",
                "Livestream benefits from compression to maintain consistent levels. "
                "Consider enabling with a moderate ratio (3:1-5:1) and low threshold."
            ))
            continue

        # Check threshold - livestream comp should be engaging (threshold not too high)
        # Threshold is 0.0-1.0 raw; higher value = higher threshold = less compression
        threshold = comp.get("threshold", 0.5)
        if threshold > 0.7:
            findings.append(Finding(
                "warning", f"Matrix {name}", "dynamics",
                f"Livestream compressor threshold is high ({threshold:.2f}) - may not be engaging",
                "Lower the threshold so the compressor catches more of the signal. "
                "Livestream needs tighter dynamics control than FOH.",
                fix=f"{CMD_PREFIX} /mtx/{mtx_key.replace('mtx', '')}/dyn/thr 0.5"
            ))
        elif threshold < 0.2:
            findings.append(Finding(
                "suggestion", f"Matrix {name}", "dynamics",
                f"Livestream compressor threshold is very low ({threshold:.2f}) - heavy compression",
                "This may be squashing dynamics too much. Check that the stream still sounds natural."
            ))
        else:
            findings.append(Finding(
                "good", f"Matrix {name}", "dynamics",
                f"Livestream compressor threshold at {threshold:.2f} - actively engaging",
                ""
            ))

        # Check ratio if available (stored as string like "3:1")
        ratio_str = comp.get("ratio", "")
        if ratio_str:
            try:
                ratio_val = float(ratio_str.replace(":1", ""))
                if ratio_val < 2.0:
                    findings.append(Finding(
                        "warning", f"Matrix {name}", "dynamics",
                        f"Livestream compressor ratio {ratio_str} is low for broadcast",
                        "Livestream typically needs tighter compression (3:1 to 5:1) "
                        "to maintain consistent levels for viewers."
                    ))
                elif ratio_val > 10.0:
                    findings.append(Finding(
                        "suggestion", f"Matrix {name}", "dynamics",
                        f"Livestream compressor ratio {ratio_str} is very aggressive",
                        "This is approaching limiting territory. May sound unnatural on stream."
                    ))
            except (ValueError, AttributeError):
                pass

    return findings


def check_muted_channels_with_eq(channels: dict) -> List[Finding]:
    """Flag muted channels that have significant EQ - might be forgotten settings."""
    findings = []
    for ch_key, ch_data in channels.items():
        if not ch_data.get("mute", False):
            continue
        ch_num = int(ch_key.replace("ch", ""))
        ch_type = classify_channel(ch_data.get("name", ""))
        if ch_type in ("auxiliary", "ambient", "computer", "unknown"):
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
    dcas = session.get("dcas", {})

    # --- Per-channel checks ---
    for ch_key, ch_data in channels.items():
        ch_num = int(ch_key.replace("ch", ""))
        ch_name = ch_data.get("name", "")
        target = get_target(ch_name)
        if target is None:
            continue  # Skip auxiliary/unknown channels

        if ch_data.get("mute", False):
            continue  # Skip muted channels for active checks

        findings.extend(check_hpf(ch_num, ch_data, target))
        findings.extend(check_eq(ch_num, ch_data, target))
        findings.extend(check_compressor(ch_num, ch_data, target))
        findings.extend(check_fader_balance(ch_num, ch_data, dcas))

    # --- Cross-channel checks ---
    findings.extend(check_vocal_presence_stacking(channels))
    findings.extend(check_piano_keyboard_masking(channels))
    findings.extend(check_kick_bass_conflict(channels))

    # Dynamic stereo pair detection: check all stereo-linked odd channels
    for ch_key, ch_data in channels.items():
        ch_num = int(ch_key.replace("ch", ""))
        if ch_num % 2 == 1 and ch_data.get("stereo_linked"):
            pair_key = f"ch{ch_num + 1:02d}"
            if pair_key in channels and channels[pair_key].get("stereo_linked"):
                pair_label = f"{ch_data.get('name', ch_key)} L/R"
                findings.extend(check_stereo_pair_consistency(
                    channels, (ch_num, ch_num + 1), pair_label
                ))

    # --- Main bus ---
    findings.extend(check_main_bus(session.get("main", {})))

    # --- Livestream / matrix ---
    findings.extend(check_livestream_routing(session))
    findings.extend(check_matrix_eq(session))
    findings.extend(check_matrix_faders(session))
    findings.extend(check_matrix_compressor(session))

    # --- DCA coverage ---
    findings.extend(check_dca_coverage(session))

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
