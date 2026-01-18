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
    python query.py --main
    python query.py --main --eq
    python query.py --main --dynamics
    python query.py --fx 1
    python query.py --fxrtn 1
    python query.py --format plain
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from common import load_config, get_mixer, parse_channel, parse_bus, format_db, format_output, get_state_value, reliable_query, warmup_connection, ratio_index_to_value, hpf_value_to_hz


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
    Query channel overview (fader, mute, name, color, gain).

    Args:
        state: Mixer state
        ch_addr: Channel address like "/ch/05"

    Returns:
        Dictionary with channel info
    """
    try:
        fader = get_state_value(state, ch_addr, "mix_fader", 0.0)
        fader_db = get_state_value(state, ch_addr, "mix_fader_db", None)
        name = get_state_value(state, ch_addr, "config_name", "")
        mute = get_state_value(state, ch_addr, "mix_on", True) == False
        color = get_state_value(state, ch_addr, "config_color", 0)
        gain = get_state_value(state, ch_addr, "headamp_gain", 0.0)

        return {
            "channel": ch_addr,
            "name": name,
            "gain": round(gain, 3) if gain else 0.0,
            "fader": round(fader, 3),
            "fader_db": f"{fader_db} dB" if fader_db is not None else format_db(fader),
            "mute": mute,
            "color": color
        }
    except Exception as e:
        return {"error": str(e)}


async def query_channel_eq(mixer, ch_addr):
    """
    Query channel EQ settings using direct mixer queries.

    Args:
        mixer: Connected mixer instance
        ch_addr: Channel address like "/ch/08"

    Returns:
        Dictionary with EQ info
    """
    try:
        # Extract channel number for OSC address
        ch_num = int(ch_addr.split('/')[-1])

        eq_on = await reliable_query(mixer, f'/ch/{ch_num:02d}/eq/on', default=0) == 1
        bands = []

        for band_num in range(1, 5):
            freq = await reliable_query(mixer, f'/ch/{ch_num:02d}/eq/{band_num}/f', default=0.5)
            gain = await reliable_query(mixer, f'/ch/{ch_num:02d}/eq/{band_num}/g', default=0.5)
            q = await reliable_query(mixer, f'/ch/{ch_num:02d}/eq/{band_num}/q', default=0.5)

            bands.append({
                "band": band_num,
                "freq": round(freq, 3) if freq else 0.5,
                "gain": round(gain, 3) if gain else 0.5,
                "q": round(q, 3) if q else 0.5
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


async def query_channel_dynamics(mixer, ch_addr):
    """
    Query channel dynamics (gate, comp, HPF) using direct mixer queries.

    Args:
        mixer: Connected mixer instance
        ch_addr: Channel address like "/ch/08"

    Returns:
        Dictionary with dynamics info
    """
    try:
        ch_num = int(ch_addr.split('/')[-1])

        # Gate
        gate_on = await reliable_query(mixer, f'/ch/{ch_num:02d}/gate/on', default=0) == 1
        gate_thr = await reliable_query(mixer, f'/ch/{ch_num:02d}/gate/thr', default=0.5)

        # Compressor
        comp_on = await reliable_query(mixer, f'/ch/{ch_num:02d}/dyn/on', default=0) == 1
        comp_thr = await reliable_query(mixer, f'/ch/{ch_num:02d}/dyn/thr', default=0.5)
        comp_ratio_idx = await reliable_query(mixer, f'/ch/{ch_num:02d}/dyn/ratio', default=5)
        comp_attack = await reliable_query(mixer, f'/ch/{ch_num:02d}/dyn/attack', default=0.5)
        comp_release = await reliable_query(mixer, f'/ch/{ch_num:02d}/dyn/release', default=0.5)

        # Convert ratio index to actual value
        comp_ratio = ratio_index_to_value(int(comp_ratio_idx)) if comp_ratio_idx is not None else 3

        # HPF (High-Pass Filter)
        hpf_on = await reliable_query(mixer, f'/ch/{ch_num:02d}/preamp/hpon', default=0) == 1
        hpf_freq_val = await reliable_query(mixer, f'/ch/{ch_num:02d}/preamp/hpf', default=0.5)
        hpf_freq_hz = hpf_value_to_hz(hpf_freq_val) if hpf_freq_val is not None else 80

        return {
            "channel": ch_addr,
            "dynamics": {
                "hpf": {
                    "on": hpf_on,
                    "freq_value": round(hpf_freq_val, 3) if hpf_freq_val else 0.5,
                    "freq_hz": hpf_freq_hz
                },
                "gate": {
                    "on": gate_on,
                    "threshold": round(gate_thr, 3) if gate_thr else 0.5
                },
                "comp": {
                    "on": comp_on,
                    "threshold": round(comp_thr, 3) if comp_thr else 0.5,
                    "ratio": f"{comp_ratio}:1",
                    "attack": round(comp_attack, 3) if comp_attack else 0.5,
                    "release": round(comp_release, 3) if comp_release else 0.5
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


async def query_main_overview(state):
    """
    Query main LR bus overview.

    Args:
        state: Mixer state

    Returns:
        Dictionary with main bus info
    """
    try:
        main_addr = "/main/st"
        fader = get_state_value(state, main_addr, "mix_fader", 0.0)
        mute = get_state_value(state, main_addr, "mix_on", True) == False

        return {
            "target": "main/st",
            "fader": round(fader, 3),
            "fader_db": format_db(fader),
            "mute": mute
        }
    except Exception as e:
        return {"error": str(e)}


async def query_main_eq(mixer):
    """
    Query main LR bus EQ settings (6 bands) using direct mixer queries.

    Args:
        mixer: Connected mixer instance

    Returns:
        Dictionary with EQ info
    """
    try:
        eq_on = await reliable_query(mixer, '/main/st/eq/on', default=0) == 1
        bands = []

        for band_num in range(1, 7):  # Main has 6 bands
            freq = await reliable_query(mixer, f'/main/st/eq/{band_num}/f', default=0.5)
            gain = await reliable_query(mixer, f'/main/st/eq/{band_num}/g', default=0.5)
            q = await reliable_query(mixer, f'/main/st/eq/{band_num}/q', default=0.5)

            bands.append({
                "band": band_num,
                "freq": round(freq, 3) if freq else 0.5,
                "gain": round(gain, 3) if gain else 0.5,
                "q": round(q, 3) if q else 0.5
            })

        return {
            "target": "main/st",
            "eq": {
                "on": eq_on,
                "bands": bands
            }
        }
    except Exception as e:
        return {"error": str(e)}


async def query_main_dynamics(mixer):
    """
    Query main LR bus dynamics using direct mixer queries.

    Args:
        mixer: Connected mixer instance

    Returns:
        Dictionary with dynamics info
    """
    try:
        comp_on = await reliable_query(mixer, '/main/st/dyn/on', default=0) == 1
        comp_thr = await reliable_query(mixer, '/main/st/dyn/thr', default=0.5)
        comp_ratio = await reliable_query(mixer, '/main/st/dyn/ratio', default=0.5)

        return {
            "target": "main/st",
            "dynamics": {
                "comp": {
                    "on": comp_on,
                    "threshold": round(comp_thr, 3) if comp_thr else 0.5,
                    "ratio": round(comp_ratio, 3) if comp_ratio else 0.5
                }
            }
        }
    except Exception as e:
        return {"error": str(e)}


async def query_fx_slot(mixer, fx_num):
    """
    Query FX slot parameters using direct mixer queries.

    Args:
        mixer: Connected mixer instance
        fx_num: FX slot number (1-8)

    Returns:
        Dictionary with FX info
    """
    try:
        # Get FX type
        fx_type = await reliable_query(mixer, f'/fx/{fx_num}/type', default=0)

        # Get first 24 parameters (most effects use fewer)
        params = {}
        for param_num in range(1, 25):
            value = await reliable_query(mixer, f'/fx/{fx_num}/par/{param_num:02d}', default=None)
            if value is not None:
                params[param_num] = round(value, 3)

        return {
            "fx_slot": fx_num,
            "type": fx_type,
            "parameters": params
        }
    except Exception as e:
        return {"error": str(e)}


async def query_fx_return(mixer, state, fxrtn_num):
    """
    Query FX return settings.

    Args:
        mixer: Connected mixer instance
        state: Mixer state (for fader/name which work from state)
        fxrtn_num: FX return number (1-8)

    Returns:
        Dictionary with FX return info
    """
    try:
        fxrtn_addr = f"/fxrtn/{fxrtn_num:02d}"

        # Try state first for fader/name (usually works), fallback to query
        fader = get_state_value(state, fxrtn_addr, "mix_fader", None)
        if fader is None:
            fader = await reliable_query(mixer, f'/fxrtn/{fxrtn_num:02d}/mix/fader', default=0.0)

        mute = get_state_value(state, fxrtn_addr, "mix_on", True) == False
        name = get_state_value(state, fxrtn_addr, "config_name", "")

        return {
            "fx_return": fxrtn_num,
            "name": name,
            "fader": round(fader, 3) if fader else 0.0,
            "fader_db": format_db(fader) if fader else "-inf dB",
            "mute": mute
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
        "--main",
        action="store_true",
        help="Query main LR bus (use with --eq or --dynamics for details)"
    )
    parser.add_argument(
        "--eq",
        action="store_true",
        help="Query EQ settings (use with --channel or --main)"
    )
    parser.add_argument(
        "--dynamics",
        action="store_true",
        help="Query dynamics settings (use with --channel or --main)"
    )
    parser.add_argument(
        "--sends",
        action="store_true",
        help="Query bus sends (requires --channel)"
    )
    parser.add_argument(
        "--fx",
        type=int,
        choices=range(1, 9),
        metavar="1-8",
        help="Query FX slot (1-8)"
    )
    parser.add_argument(
        "--fxrtn",
        type=int,
        choices=range(1, 9),
        metavar="1-8",
        help="Query FX return (1-8)"
    )
    parser.add_argument(
        "--format", "-f",
        choices=["json", "plain"],
        default="json",
        help="Output format (default: json)"
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.addresses and not args.channel and not args.bus and not args.main and not args.fx and not args.fxrtn:
        parser.error("Must specify addresses, --channel, --bus, --main, --fx, or --fxrtn")

    if (args.eq or args.dynamics) and not (args.channel or args.main):
        parser.error("--eq and --dynamics require --channel or --main")

    if args.sends and not args.channel:
        parser.error("--sends requires --channel")

    # Connect to mixer
    print(f"Connecting to mixer...", file=sys.stderr)
    mixer = await get_mixer()

    try:
        # Warm up connection for reliable queries
        await warmup_connection(mixer)

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
                result = await query_channel_eq(mixer, ch_addr)
            elif args.dynamics:
                result = await query_channel_dynamics(mixer, ch_addr)
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

        # Query main LR bus
        if args.main:
            if args.eq:
                result = await query_main_eq(mixer)
            elif args.dynamics:
                result = await query_main_dynamics(mixer)
            else:
                result = await query_main_overview(state)

        # Query FX slot
        if args.fx:
            result = await query_fx_slot(mixer, args.fx)

        # Query FX return
        if args.fxrtn:
            result = await query_fx_return(mixer, state, args.fxrtn)

        # Output result
        print(format_output(result, args.format))

    finally:
        await mixer.stop()


if __name__ == "__main__":
    asyncio.run(main())
