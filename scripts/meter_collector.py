#!/usr/bin/env python3
"""
Background meter collector for X-32 mixer.

Collects meter peaks via raw UDP until signaled to stop via sentinel file.
Tracks both running peaks (full-duration max) and a rolling 60-second window.

Usage:
    python meter_collector.py --output /tmp/meter_peaks.json
    python meter_collector.py --output /tmp/meter_peaks.json --stop-file /tmp/meter_collector_stop
"""

import argparse
import collections
import json
import os
import signal
import socket
import struct
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from common import (
    load_config, parse_meter_blob, parse_bus_meter_blob, extract_blob,
)

WINDOW_SECONDS = 60


def main():
    parser = argparse.ArgumentParser(description="Background meter collector for X-32 mixer")
    parser.add_argument("--output", required=True, help="Where to write peak data JSON on exit")
    parser.add_argument("--stop-file", default="/tmp/meter_collector_stop",
                        help="Sentinel file; writes output and exits when file appears")
    parser.add_argument("--max-duration", type=int, default=1800,
                        help="Safety timeout in seconds (default: 1800 = 30 min)")
    args = parser.parse_args()

    config = load_config()
    mixer_ip = config["mixer_ip"]
    mixer_port = config["mixer_port"]

    # Delete stale stop file if it exists
    stop_file = Path(args.stop_file)
    if stop_file.exists():
        stop_file.unlink()

    # Setup UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.1)
    sock.bind(('', 0))

    # Running peaks (full duration max)
    channel_peaks = {f'ch{i:02d}': 0.0 for i in range(1, 33)}
    bus_peaks = {f'bus{i:02d}': 0.0 for i in range(1, 17)}

    # Rolling window: store (timestamp, peaks_dict) snapshots
    channel_window = collections.deque()  # (timestamp, {ch: peak})
    bus_window = collections.deque()  # (timestamp, {bus: peak})

    # OSC message builders
    xremote_msg = b'/xremote\x00\x00\x00\x00,\x00\x00\x00'
    ch_meter_msg = b'/meters\x00,siii\x00\x00\x00' + b'/meters/0\x00\x00\x00' + struct.pack('>iii', 0, 0, 3)
    bus_meter_msg = b'/meters\x00,siii\x00\x00\x00' + b'/meters/2\x00\x00\x00' + struct.pack('>iii', 0, 0, 3)

    # Signal handling for clean shutdown
    shutdown = False

    def handle_signal(signum, frame):
        nonlocal shutdown
        shutdown = True

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    start_time = time.time()
    started_at = datetime.now().isoformat()
    last_request = 0.0
    samples_received = 0

    print(f"Meter collector started (max {args.max_duration}s, stop file: {args.stop_file})", file=sys.stderr)

    ended_by = "signal"
    try:
        while not shutdown:
            current = time.time()
            elapsed = current - start_time

            # Check safety timeout
            if elapsed >= args.max_duration:
                print(f"Max duration ({args.max_duration}s) reached", file=sys.stderr)
                ended_by = "max_duration"
                break

            # Check sentinel file
            if stop_file.exists():
                print("Stop file detected", file=sys.stderr)
                ended_by = "stop_file"
                break

            # Send meter requests every 100ms
            if current - last_request >= 0.1:
                sock.sendto(xremote_msg, (mixer_ip, mixer_port))
                sock.sendto(ch_meter_msg, (mixer_ip, mixer_port))
                sock.sendto(bus_meter_msg, (mixer_ip, mixer_port))
                last_request = current

            # Drain all queued responses
            while True:
                try:
                    data, _ = sock.recvfrom(8192)
                    now = time.time()

                    if data.startswith(b'/meters/0'):
                        blob_data = extract_blob(data)
                        if blob_data:
                            peaks = parse_meter_blob(blob_data)
                            for ch, val in peaks.items():
                                if val > channel_peaks.get(ch, 0.0):
                                    channel_peaks[ch] = val
                            channel_window.append((now, peaks))
                            samples_received += 1
                    elif data.startswith(b'/meters/2'):
                        blob_data = extract_blob(data)
                        if blob_data:
                            peaks = parse_bus_meter_blob(blob_data)
                            for key, val in peaks.items():
                                if key in bus_peaks and val > bus_peaks[key]:
                                    bus_peaks[key] = val
                            bus_window.append((now, peaks))
                            samples_received += 1
                except socket.timeout:
                    break

            # Prune window entries older than WINDOW_SECONDS
            cutoff = time.time() - WINDOW_SECONDS
            while channel_window and channel_window[0][0] < cutoff:
                channel_window.popleft()
            while bus_window and bus_window[0][0] < cutoff:
                bus_window.popleft()

            time.sleep(0.001)

    finally:
        sock.close()

    # Calculate rolling window peaks
    channel_peaks_window = {f'ch{i:02d}': 0.0 for i in range(1, 33)}
    for _, peaks in channel_window:
        for ch, val in peaks.items():
            if val > channel_peaks_window.get(ch, 0.0):
                channel_peaks_window[ch] = val

    bus_peaks_window = {f'bus{i:02d}': 0.0 for i in range(1, 17)}
    for _, peaks in bus_window:
        for key, val in peaks.items():
            if key in bus_peaks_window and val > bus_peaks_window[key]:
                bus_peaks_window[key] = val

    stopped_at = datetime.now().isoformat()
    duration = time.time() - start_time

    output = {
        "channel_peaks": {ch: round(v, 6) for ch, v in channel_peaks.items()},
        "channel_peaks_window": {ch: round(v, 6) for ch, v in channel_peaks_window.items()},
        "bus_peaks": {bus: round(v, 6) for bus, v in bus_peaks.items()},
        "bus_peaks_window": {bus: round(v, 6) for bus, v in bus_peaks_window.items()},
        "duration_seconds": round(duration, 1),
        "window_seconds": WINDOW_SECONDS,
        "samples_received": samples_received,
        "started_at": started_at,
        "stopped_at": stopped_at,
        "ended_by": ended_by,
    }

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)

    # Clean up sentinel file
    if stop_file.exists():
        stop_file.unlink()

    print(f"Meter data written to {args.output} ({duration:.0f}s collection)", file=sys.stderr)


if __name__ == "__main__":
    main()
