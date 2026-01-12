#!/usr/bin/env python3
"""
Query specific X-32 mixer parameters.

Usage:
    python query.py /ch/05/mix/fader
    python query.py /ch/05/mix/fader /ch/05/mix/on
    python query.py --channel 5
    python query.py --channel 5 --eq
    python query.py --channel 5 --dynamics
    python query.py --bus 3
    python query.py --format plain
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from common import load_config, get_mixer, parse_channel, parse_bus, format_db, format_output


async def query_address(state, address):
    """
    Query a single OSC address.

    Args:
        state: Mixer state
        address: OSC address

    Returns:
        Value at address
    """
    try:
        value = state.get(address)
        if value is None:
            return {"error": f"Address not found: {address}"}
        return value
    except Exception as e:
        return {"error": str(e)}


async def query_channel_overview(state, ch_addr):
    """
    Query channel overview (fader, mute, name, color).

    Args:
        state: Mixer state
        ch_addr: Channel address like "/ch/05"

    Returns:
        Dictionary with channel info
    """
    try:
        fader = state.get(f"{ch_addr}/mix/fader", 0.0)
        name = state.get(f"{ch_addr}/config/name", "")
        mute = state.get(f"{ch_addr}/mix/on", 1) == 0
        color = state.get(f"{ch_addr}/config/color", 0)

        return {
            "channel": ch_addr,
            "name": name,
            "fader": round(fader, 3),
            "fader_db": format_db(fader),
            "mute": mute,
            "color": color
        }
    except Exception as e:
        return {"error": str(e)}


async def query_channel_eq(state, ch_addr):
    """
    Query channel EQ settings.

    Args:
        state: Mixer state
        ch_addr: Channel address

    Returns:
        Dictionary with EQ info
    """
    try:
        eq_on = state.get(f"{ch_addr}/eq/on", 0) == 1
        bands = []

        for band_num in range(1, 5):
            freq = state.get(f"{ch_addr}/eq/{band_num}/f", 0.5)
            gain = state.get(f"{ch_addr}/eq/{band_num}/g", 0.5)
            q = state.get(f"{ch_addr}/eq/{band_num}/q", 0.5)

            bands.append({
                "band": band_num,
                "freq": round(freq, 3),
                "gain": round(gain, 3),
                "q": round(q, 3)
            })

        return {
            "channel": ch_addr,
            "eq": {
                "on": eq_on,
                "bands": bands
            }
        }
    except Exception as e:
        return {"error": str(e)}


async def query_channel_dynamics(state, ch_addr):
    """
    Query channel dynamics (gate, comp).

    Args:
        state: Mixer state
        ch_addr: Channel address

    Returns:
        Dictionary with dynamics info
    """
    try:
        gate_on = state.get(f"{ch_addr}/gate/on", 0) == 1
        gate_thr = state.get(f"{ch_addr}/gate/thr", 0.5)

        comp_on = state.get(f"{ch_addr}/dyn/on", 0) == 1
        comp_thr = state.get(f"{ch_addr}/dyn/thr", 0.5)
        comp_ratio = state.get(f"{ch_addr}/dyn/ratio", 0.5)

        return {
            "channel": ch_addr,
            "dynamics": {
                "gate": {
                    "on": gate_on,
                    "threshold": round(gate_thr, 3)
                },
                "comp": {
                    "on": comp_on,
                    "threshold": round(comp_thr, 3),
                    "ratio": round(comp_ratio, 3)
                }
            }
        }
    except Exception as e:
        return {"error": str(e)}


async def query_channel_sends(state, ch_addr):
    """
    Query channel bus sends.

    Args:
        state: Mixer state
        ch_addr: Channel address

    Returns:
        Dictionary with send levels
    """
    try:
        sends = {}

        for bus_num in range(1, 17):
            bus_addr = f"/bus/{bus_num:02d}"
            level = state.get(f"{ch_addr}/mix/{bus_num:02d}/level", 0.0)
            sends[bus_addr] = round(level, 3)

        return {
            "channel": ch_addr,
            "sends": sends
        }
    except Exception as e:
        return {"error": str(e)}


async def main():
    parser = argparse.ArgumentParser(description="Query X-32 mixer parameters")
    parser.add_argument(
        "addresses",
        nargs="*",
        help="OSC addresses to query (e.g., /ch/05/mix/fader)"
    )
    parser.add_argument(
        "--channel", "-c",
        help="Query channel overview (e.g., 5 or ch5)"
    )
    parser.add_argument(
        "--bus", "-b",
        help="Query bus overview"
    )
    parser.add_argument(
        "--eq",
        action="store_true",
        help="Query EQ settings (requires --channel)"
    )
    parser.add_argument(
        "--dynamics",
        action="store_true",
        help="Query dynamics settings (requires --channel)"
    )
    parser.add_argument(
        "--sends",
        action="store_true",
        help="Query bus sends (requires --channel)"
    )
    parser.add_argument(
        "--format", "-f",
        choices=["json", "plain"],
        default="json",
        help="Output format (default: json)"
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.addresses and not args.channel and not args.bus:
        parser.error("Must specify addresses, --channel, or --bus")

    if (args.eq or args.dynamics or args.sends) and not args.channel:
        parser.error("--eq, --dynamics, and --sends require --channel")

    # Connect to mixer
    print(f"Connecting to mixer...", file=sys.stderr)
    mixer = await get_mixer()

    try:
        state = mixer.state()
        result = {}

        # Query specific addresses
        if args.addresses:
            for addr in args.addresses:
                value = await query_address(state, addr)
                result[addr] = value

        # Query channel
        if args.channel:
            try:
                ch_addr = parse_channel(args.channel)
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)

            if args.eq:
                result = await query_channel_eq(state, ch_addr)
            elif args.dynamics:
                result = await query_channel_dynamics(state, ch_addr)
            elif args.sends:
                result = await query_channel_sends(state, ch_addr)
            else:
                result = await query_channel_overview(state, ch_addr)

        # Query bus
        if args.bus:
            try:
                bus_addr = parse_bus(args.bus)
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)

            result = await query_channel_overview(state, bus_addr)

        # Output result
        print(format_output(result, args.format))

    finally:
        await mixer.stop()


if __name__ == "__main__":
    asyncio.run(main())
