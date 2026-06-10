#!/usr/bin/env python3
"""
Splice batch-collected RTA data into a session capture file.

Reads a JSONL file (one RTA result per line, from rta_listen.py --append-to)
and merges all results into the session capture's channel data.

The source JSONL is kept by default so it can be re-spliced into later
captures. Pass --delete-source to remove it after a successful splice.

Exit codes: 0 = spliced at least one channel, 1 = nothing spliced (bad input,
no valid results, or no matching channels).

Usage:
    python splice_rta.py /tmp/rta_data.jsonl captures/session_XXX.json
    python splice_rta.py --delete-source /tmp/rta_data.jsonl captures/session_XXX.json
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Splice RTA JSONL into a session capture")
    parser.add_argument("rta_file", help="JSONL file from rta_listen.py --append-to")
    parser.add_argument("capture_file", help="Session capture JSON file")
    parser.add_argument("--delete-source", action="store_true",
                        help="Delete the RTA JSONL after a successful splice (default: keep it)")
    args = parser.parse_args()

    rta_path = Path(args.rta_file)
    capture_path = Path(args.capture_file)

    if not rta_path.exists():
        print(f"Error: RTA file not found: {rta_path}", file=sys.stderr)
        sys.exit(1)
    if not capture_path.exists():
        print(f"Error: Capture file not found: {capture_path}", file=sys.stderr)
        sys.exit(1)

    # Read all RTA results
    rta_results = []
    with open(rta_path) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rta_results.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"Warning: Skipping invalid JSON on line {line_num}: {e}", file=sys.stderr)

    if not rta_results:
        print("No RTA results found in file", file=sys.stderr)
        sys.exit(1)

    # Read capture
    with open(capture_path) as f:
        capture = json.load(f)

    channels = capture.get("channels", {})
    spliced = 0

    for result in rta_results:
        ch_num = result.get("channel")
        if ch_num is None:
            print(f"Warning: RTA result missing channel number, skipping", file=sys.stderr)
            continue

        ch_key = f"ch{ch_num:02d}"
        if ch_key not in channels:
            print(f"Warning: {ch_key} not in capture, skipping", file=sys.stderr)
            continue

        # Skip invalid RTA data — don't poison the capture
        if not result.get("valid", False):
            notes = result.get("validation_notes", "unknown reason")
            print(f"Warning: {ch_key} RTA data invalid ({notes}), skipping", file=sys.stderr)
            continue

        channels[ch_key]["rta_analysis"] = {
            "timestamp": result.get("timestamp"),
            "valid": result.get("valid", False),
            "validation_notes": result.get("validation_notes"),
            "samples_collected": result.get("samples_collected"),
            "peak_meter": result.get("peak_meter"),
            "bands": result.get("bands", {}),
            "spectral_summary": result.get("spectral_summary"),
            "peaks": result.get("peaks", []),
            "problems": result.get("problems", []),
            "spectral_tilt": result.get("spectral_tilt"),
            "transient_character": result.get("transient_character"),
        }
        spliced += 1

    if spliced == 0:
        print(f"Error: no RTA results spliced into {capture_path.name} — "
              f"{len(rta_results)} result(s) read but none were valid for channels in this capture. "
              f"Source file kept.", file=sys.stderr)
        sys.exit(1)

    # Update timestamp
    capture["rta_last_updated"] = datetime.now().isoformat()

    # Write back
    with open(capture_path, "w") as f:
        json.dump(capture, f, indent=2)

    if args.delete_source:
        rta_path.unlink()

    print(f"Spliced RTA data for {spliced} channels into {capture_path.name}"
          + ("" if args.delete_source else f" (source kept: {rta_path})"), file=sys.stderr)


if __name__ == "__main__":
    main()
