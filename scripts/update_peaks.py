#!/usr/bin/env python3
"""
Update channel meter peaks in a session capture after trim changes.

After the editor applies preamp trim changes, the meter peaks in the capture
no longer reflect the actual signal levels. This script adjusts the peaks
by the dB offset of each trim change, then recalculates the average and
gain staging issues so subsequent agents see accurate data.

Usage:
    python scripts/update_peaks.py captures/session_XXX.json 5:+3.0 17:-2.0

Arguments are channel:offset_dB pairs. Positive = trim increased (signal hotter).
"""

import argparse
import json
import math
import sys
from pathlib import Path

INACTIVE_THRESHOLD_RAW = 0.0005


def db_to_linear(db):
    """Convert a dB offset to a linear amplitude multiplier."""
    return 10 ** (db / 20)


def update_peaks(capture, trim_offsets):
    """Apply trim dB offsets to channel_peaks and recalculate gain staging.

    Args:
        capture: parsed session capture dict (modified in place)
        trim_offsets: dict of {channel_num: offset_db}
    """
    gain_staging = capture.get("analysis", {}).get("gain_staging", {})
    channel_peaks = gain_staging.get("channel_peaks", {})

    if not channel_peaks:
        print("No channel_peaks in capture — was this captured with the updated session_capture.py?",
              file=sys.stderr)
        return False

    # Build channel name lookup
    channel_names = {}
    for ch_key, ch_data in capture.get("channels", {}).items():
        channel_names[ch_key] = ch_data.get("name", ch_key)

    # Apply trim offsets to peaks
    applied = []
    for ch_num, offset_db in trim_offsets.items():
        ch_key = f"ch{ch_num:02d}"
        if ch_key not in channel_peaks:
            print(f"  {ch_key}: no meter peak data, skipping", file=sys.stderr)
            continue

        old_peak = channel_peaks[ch_key]
        multiplier = db_to_linear(offset_db)
        new_peak = round(old_peak * multiplier, 6)
        channel_peaks[ch_key] = new_peak
        applied.append(f"ch{ch_num:02d} ({channel_names.get(ch_key, '?')}): "
                       f"peak {old_peak:.6f} -> {new_peak:.6f} ({offset_db:+.1f}dB)")

    if not applied:
        print("No peaks updated.", file=sys.stderr)
        return False

    # Recalculate active channels, average, and issues
    active = {ch: peak for ch, peak in channel_peaks.items() if peak > INACTIVE_THRESHOLD_RAW}

    if not active:
        gain_staging["active_channels"] = []
        gain_staging["issues"] = []
        gain_staging["average_peak"] = 0
    else:
        avg_peak = sum(active.values()) / len(active)

        issues = []
        for ch, peak in active.items():
            ch_num = int(ch.replace('ch', ''))
            name = channel_names.get(ch, ch)
            ratio = peak / avg_peak if avg_peak > 0 else 1

            if ratio > 2.0:
                db_diff = 20 * math.log10(ratio)
                issues.append({
                    "channel": ch_num,
                    "name": name,
                    "peak_raw": peak,
                    "issue": "hot",
                    "detail": f"Running {db_diff:.0f}dB above average - consider reducing preamp gain",
                })
            elif ratio < 0.3:
                db_diff = -20 * math.log10(ratio)
                issues.append({
                    "channel": ch_num,
                    "name": name,
                    "peak_raw": peak,
                    "issue": "quiet",
                    "detail": f"Running {db_diff:.0f}dB below average - may need more preamp gain",
                })

        gain_staging["active_channels"] = sorted([int(ch.replace('ch', '')) for ch in active.keys()])
        gain_staging["issues"] = issues
        gain_staging["average_peak"] = round(avg_peak, 6)

    gain_staging["channel_peaks"] = channel_peaks

    for line in applied:
        print(f"  {line}", file=sys.stderr)

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Update channel meter peaks after trim changes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/update_peaks.py captures/session_XXX.json 5:+3.0 17:-2.0
    python scripts/update_peaks.py captures/session_XXX.json 1:-1.5 22:+2 23:+2
        """
    )
    parser.add_argument("capture", help="Path to session capture JSON file")
    parser.add_argument("offsets", nargs="+",
                        help="channel:offset_dB pairs (e.g. 5:+3.0 17:-2.0)")

    args = parser.parse_args()

    # Parse and validate offsets — fail fast, don't silently skip bad input
    trim_offsets = {}
    for pair in args.offsets:
        try:
            ch_str, db_str = pair.split(":")
            ch_num = int(ch_str)
            offset_db = float(db_str)
        except (ValueError, IndexError):
            print(f"Invalid offset format '{pair}' — expected channel:dB (e.g. 5:+3.0)",
                  file=sys.stderr)
            sys.exit(1)
        if not 1 <= ch_num <= 32:
            print(f"Invalid channel {ch_num} in '{pair}' — channels are 1-32", file=sys.stderr)
            sys.exit(1)
        if abs(offset_db) > 20:
            print(f"Implausible offset {offset_db:+.1f}dB in '{pair}' — trim moves should be "
                  f"small; refusing anything beyond ±20dB", file=sys.stderr)
            sys.exit(1)
        trim_offsets[ch_num] = offset_db

    # Load capture
    capture_path = Path(args.capture)
    if not capture_path.exists():
        print(f"Capture file not found: {capture_path}", file=sys.stderr)
        sys.exit(1)

    with open(capture_path) as f:
        capture = json.load(f)

    # Update peaks
    print(f"Updating peaks in {capture_path.name}:", file=sys.stderr)
    if update_peaks(capture, trim_offsets):
        with open(capture_path, 'w') as f:
            json.dump(capture, f, indent=2)
        print("Capture updated.", file=sys.stderr)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
