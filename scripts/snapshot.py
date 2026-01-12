#!/usr/bin/env python3
"""
Capture full mixer state to JSON file.

Usage:
    python snapshot.py
    python snapshot.py --output snapshots/2026-01-11_soundcheck.json
    python snapshot.py --sections channels,buses
    python snapshot.py --compact
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from common import load_config, get_mixer, get_snapshot_dir, format_db


async def capture_snapshot(mixer, sections=None):
    """
    Capture full mixer state.

    Args:
        mixer: Connected mixer instance
        sections: List of sections to capture (None = all)

    Returns:
        Dictionary with mixer state
    """
    config = load_config()
    state = mixer.state()

    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "mixer_ip": config["mixer_ip"],
        "mixer_type": config["mixer_type"],
    }

    # Get current scene info
    try:
        scene_num = state.get("scene_current", 0)
        snapshot["scene"] = {
            "number": scene_num
        }
    except:
        snapshot["scene"] = {"number": 0}

    # Capture channels (1-32)
    if sections is None or "channels" in sections:
        snapshot["channels"] = {}
        for ch_num in range(1, 33):
            ch_addr = f"/ch/{ch_num:02d}"
            channel_data = await capture_channel(state, ch_addr)
            if channel_data:
                snapshot["channels"][ch_addr.replace('/', '')] = channel_data

    # Capture buses (1-16)
    if sections is None or "buses" in sections:
        snapshot["buses"] = {}
        for bus_num in range(1, 17):
            bus_addr = f"/bus/{bus_num:02d}"
            bus_data = await capture_channel(state, bus_addr)
            if bus_data:
                snapshot["buses"][bus_addr.replace('/', '')] = bus_data

    # Capture main LR
    if sections is None or "main" in sections:
        snapshot["main"] = await capture_channel(state, "/main/st")

    # Capture DCA groups
    if sections is None or "dcas" in sections:
        snapshot["dcas"] = {}
        for dca_num in range(1, 9):
            dca_addr = f"/dca/{dca_num}"
            try:
                fader = state.get(f"{dca_addr}/fader", 0.0)
                name = state.get(f"{dca_addr}/config/name", f"DCA {dca_num}")
                mute = state.get(f"{dca_addr}/on", 1) == 0

                snapshot["dcas"][dca_addr.replace('/', '')] = {
                    "name": name,
                    "fader": fader,
                    "fader_db": format_db(fader),
                    "mute": mute
                }
            except:
                pass

    return snapshot


async def capture_channel(state, ch_addr):
    """
    Capture single channel/bus data.

    Args:
        state: Mixer state dictionary
        ch_addr: Channel address like "/ch/01" or "/bus/01"

    Returns:
        Dictionary with channel data
    """
    try:
        # Basic info
        fader = state.get(f"{ch_addr}/mix/fader", 0.0)
        name = state.get(f"{ch_addr}/config/name", "")
        mute = state.get(f"{ch_addr}/mix/on", 1) == 0
        color = state.get(f"{ch_addr}/config/color", 0)

        channel_data = {
            "name": name,
            "fader": round(fader, 3),
            "fader_db": format_db(fader),
            "mute": mute,
            "color": color
        }

        # EQ (4 bands)
        eq_on = state.get(f"{ch_addr}/eq/on", 0) == 1
        eq_bands = []
        for band_num in range(1, 5):
            try:
                freq = state.get(f"{ch_addr}/eq/{band_num}/f", 0.5)
                gain = state.get(f"{ch_addr}/eq/{band_num}/g", 0.5)
                q = state.get(f"{ch_addr}/eq/{band_num}/q", 0.5)

                eq_bands.append({
                    "band": band_num,
                    "freq": round(freq, 3),
                    "gain": round(gain, 3),
                    "q": round(q, 3)
                })
            except:
                pass

        if eq_bands:
            channel_data["eq"] = {
                "on": eq_on,
                "bands": eq_bands
            }

        # Dynamics (gate and comp)
        try:
            gate_on = state.get(f"{ch_addr}/gate/on", 0) == 1
            comp_on = state.get(f"{ch_addr}/dyn/on", 0) == 1

            channel_data["dynamics"] = {
                "gate": {
                    "on": gate_on,
                    "threshold": state.get(f"{ch_addr}/gate/thr", 0.5)
                },
                "comp": {
                    "on": comp_on,
                    "threshold": state.get(f"{ch_addr}/dyn/thr", 0.5),
                    "ratio": state.get(f"{ch_addr}/dyn/ratio", 0.5)
                }
            }
        except:
            pass

        return channel_data

    except Exception as e:
        print(f"Warning: Could not capture {ch_addr}: {e}", file=sys.stderr)
        return None


async def main():
    parser = argparse.ArgumentParser(description="Capture X-32 mixer snapshot")
    parser.add_argument(
        "--output", "-o",
        help="Output file path (default: snapshots/YYYY-MM-DD_HHMMSS.json)"
    )
    parser.add_argument(
        "--sections", "-s",
        help="Sections to capture (comma-separated: channels,buses,main,dcas)"
    )
    parser.add_argument(
        "--compact", "-c",
        action="store_true",
        help="Compact JSON output (no pretty-print)"
    )

    args = parser.parse_args()

    # Parse sections
    sections = None
    if args.sections:
        sections = [s.strip() for s in args.sections.split(',')]

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_path = get_snapshot_dir() / f"{timestamp}.json"

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Connect to mixer
    print(f"Connecting to mixer...", file=sys.stderr)
    mixer = await get_mixer()

    try:
        # Capture snapshot
        print(f"Capturing snapshot...", file=sys.stderr)
        snapshot = await capture_snapshot(mixer, sections)

        # Write to file
        with open(output_path, 'w') as f:
            if args.compact:
                json.dump(snapshot, f)
            else:
                json.dump(snapshot, f, indent=2)

        print(f"Snapshot saved to: {output_path}", file=sys.stderr)
        print(json.dumps({"success": True, "path": str(output_path)}))

    finally:
        await mixer.stop()


if __name__ == "__main__":
    asyncio.run(main())
