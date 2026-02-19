#!/usr/bin/env python3
"""
Splice batch-collected RTA data into a session capture file.

Reads a JSONL file (one RTA result per line, from rta_listen.py --append-to)
and merges all results into the session capture's channel data.

Usage:
    python splice_rta.py /tmp/rta_data.jsonl captures/session_XXX.json
"""

import json
import sys
from datetime import datetime
from pathlib import Path


def main():
    if len(sys.argv) != 3:
        print("Usage: splice_rta.py <rta_jsonl_file> <capture_json_file>", file=sys.stderr)
        sys.exit(1)

    rta_path = Path(sys.argv[1])
    capture_path = Path(sys.argv[2])

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

        channels[ch_key]["rta_analysis"] = {
            "timestamp": result.get("timestamp"),
            "samples_collected": result.get("samples_collected"),
            "peak_meter": result.get("peak_meter"),
            "bands": result.get("bands", {}),
            "interpretation": result.get("interpretation", {}),
        }
        spliced += 1

    # Update timestamp
    capture["rta_last_updated"] = datetime.now().isoformat()

    # Write back
    with open(capture_path, "w") as f:
        json.dump(capture, f, indent=2)

    # Clean up temp file
    rta_path.unlink()

    print(f"Spliced RTA data for {spliced} channels into {capture_path.name}", file=sys.stderr)


if __name__ == "__main__":
    main()
