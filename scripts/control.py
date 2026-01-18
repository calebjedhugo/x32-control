#!/usr/bin/env python3
"""
Set X-32 mixer parameters.

Usage:
    python control.py --channel 5 --fader -10dB
    python control.py --channel 5 --gain-trim 0.5
    python control.py --channel 5 --eq-band 2 --gain 3.0
    python control.py --channel 5 --eq-on
    python control.py --main --eq-band 3 --gain 0.45
    python control.py --main --comp-threshold 0.6
    python control.py --fx 1 --fx-param 1 --fx-value 0.5
    python control.py --fxrtn 1 --fader -10dB
    python control.py --channel 5 --fader -10dB --dry-run
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from common import load_config, get_mixer, parse_channel, parse_bus, db_to_fader, fader_to_db, format_db


async def set_value(mixer, address, value, dry_run=False):
    """
    Set a parameter value using direct OSC send.

    Uses mixer.send() instead of mixer.set_value() because the library's
    set_value() silently fails for addresses not in its mapping (EQ, dynamics, FX).

    Args:
        mixer: Connected mixer instance
        address: OSC address
        value: Value to set
        dry_run: If True, show what would be changed without executing

    Returns:
        Success status
    """
    if dry_run:
        print(f"[DRY RUN] Would set {address} = {value}")
        return True

    try:
        # Use send() directly - set_value() silently fails for unmapped addresses
        await mixer.send(address, value)
        print(f"Set {address} = {value}", file=sys.stderr)
        return True
    except Exception as e:
        print(f"Error setting {address}: {e}", file=sys.stderr)
        return False


def parse_fader_input(fader_str):
    """
    Parse fader input string.

    Accepts:
        - "0.75" → 0.75 (raw float)
        - "-10dB" → converted to float
        - "-10" → converted to float

    Returns:
        Float between 0.0 and 1.0
    """
    fader_str = fader_str.strip().lower()

    # Check if it's dB
    if "db" in fader_str:
        db_str = fader_str.replace("db", "").strip()
        db = float(db_str)
        return db_to_fader(db)
    else:
        # Try as raw float first
        try:
            value = float(fader_str)
            if 0.0 <= value <= 1.0:
                return value
            # If outside range, treat as dB
            return db_to_fader(value)
        except ValueError:
            raise ValueError(f"Invalid fader value: {fader_str}")


async def main():
    parser = argparse.ArgumentParser(description="Set X-32 mixer parameters")

    # Raw OSC command
    parser.add_argument(
        "raw_address",
        nargs="?",
        help="Raw OSC address (e.g., /ch/05/mix/fader)"
    )
    parser.add_argument(
        "raw_value",
        nargs="?",
        help="Raw value to set"
    )

    # Channel selection
    parser.add_argument(
        "--channel", "-c",
        help="Channel to control (e.g., 5 or ch5)"
    )
    parser.add_argument(
        "--bus", "-b",
        help="Bus to control"
    )
    parser.add_argument(
        "--main",
        action="store_true",
        help="Control main LR bus (6-band EQ, dynamics)"
    )

    # Fader control
    parser.add_argument(
        "--fader", "-f",
        help="Set fader (0.0-1.0 or -90dB to +10dB)"
    )

    # Preamp gain
    parser.add_argument(
        "--gain-trim",
        type=float,
        help="Set preamp/input gain (0.0-1.0, channels only)"
    )

    # EQ control
    parser.add_argument(
        "--eq-band",
        type=int,
        choices=[1, 2, 3, 4, 5, 6],
        help="EQ band number (1-4 for channels, 1-6 for main)"
    )
    parser.add_argument(
        "--freq",
        type=float,
        help="EQ frequency (requires --eq-band)"
    )
    parser.add_argument(
        "--gain",
        type=float,
        help="EQ gain (requires --eq-band)"
    )
    parser.add_argument(
        "--q",
        type=float,
        help="EQ Q factor (requires --eq-band)"
    )
    parser.add_argument(
        "--eq-on",
        action="store_true",
        help="Turn EQ on"
    )
    parser.add_argument(
        "--eq-off",
        action="store_true",
        help="Turn EQ off"
    )

    # Dynamics control
    parser.add_argument(
        "--comp-threshold",
        type=float,
        help="Compressor threshold"
    )
    parser.add_argument(
        "--gate-threshold",
        type=float,
        help="Gate threshold"
    )

    # Bus sends
    parser.add_argument(
        "--send-bus",
        type=int,
        help="Bus number for send level (1-16)"
    )
    parser.add_argument(
        "--level",
        type=float,
        help="Send level (requires --send-bus)"
    )

    # FX slot control
    parser.add_argument(
        "--fx",
        type=int,
        choices=range(1, 9),
        metavar="1-8",
        help="FX slot to control (1-8)"
    )
    parser.add_argument(
        "--fx-param",
        type=int,
        choices=range(1, 65),
        metavar="1-64",
        help="FX parameter number (1-64, requires --fx)"
    )
    parser.add_argument(
        "--fx-value",
        type=float,
        help="FX parameter value 0.0-1.0 (requires --fx and --fx-param)"
    )

    # FX return control
    parser.add_argument(
        "--fxrtn",
        type=int,
        choices=range(1, 9),
        metavar="1-8",
        help="FX return to control (1-8)"
    )

    # Options
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without executing"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompts"
    )

    args = parser.parse_args()

    # Validate arguments
    if args.raw_address and args.raw_value:
        # Raw OSC mode
        pass
    elif args.channel or args.bus:
        # Channel/bus mode
        if not any([
            args.fader,
            args.gain_trim,
            args.eq_band, args.eq_on, args.eq_off,
            args.comp_threshold, args.gate_threshold,
            args.send_bus
        ]):
            parser.error("Must specify an operation (--fader, --eq-band, etc.)")
    elif args.main:
        # Main LR bus mode
        if not any([
            args.fader,
            args.eq_band, args.eq_on, args.eq_off,
            args.comp_threshold
        ]):
            parser.error("--main requires --eq-band, --eq-on/off, --comp-threshold, or --fader")
    elif args.fx:
        # FX slot mode
        if not (args.fx_param and args.fx_value is not None):
            parser.error("--fx requires --fx-param and --fx-value")
    elif args.fxrtn:
        # FX return mode
        if not args.fader:
            parser.error("--fxrtn requires --fader")
    else:
        parser.error("Must specify raw address, --channel, --bus, --main, --fx, or --fxrtn")

    # Connect to mixer
    print(f"Connecting to mixer...", file=sys.stderr)
    mixer = await get_mixer()

    try:
        # Raw OSC command
        if args.raw_address and args.raw_value:
            # Try to parse value as float, fall back to string
            try:
                value = float(args.raw_value)
            except ValueError:
                value = args.raw_value

            await set_value(mixer, args.raw_address, value, args.dry_run)
            print("Success")
            return

        # Execute operations
        success = True
        target_addr = None

        # Determine target address for channel/bus operations
        if args.channel:
            try:
                target_addr = parse_channel(args.channel)
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)
        elif args.bus:
            try:
                target_addr = parse_bus(args.bus)
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)

        # Channel/bus operations (require target_addr)
        if target_addr:
            # Fader
            if args.fader:
                try:
                    fader_value = parse_fader_input(args.fader)
                    await set_value(mixer, f"{target_addr}/mix/fader", fader_value, args.dry_run)
                except ValueError as e:
                    print(f"Error: {e}", file=sys.stderr)
                    success = False

            # Preamp gain (headamp)
            if args.gain_trim is not None:
                await set_value(mixer, f"{target_addr}/headamp/gain", args.gain_trim, args.dry_run)

            # EQ band
            if args.eq_band:
                if args.freq is not None:
                    await set_value(mixer, f"{target_addr}/eq/{args.eq_band}/f", args.freq, args.dry_run)
                if args.gain is not None:
                    await set_value(mixer, f"{target_addr}/eq/{args.eq_band}/g", args.gain, args.dry_run)
                if args.q is not None:
                    await set_value(mixer, f"{target_addr}/eq/{args.eq_band}/q", args.q, args.dry_run)

            # EQ on/off
            if args.eq_on:
                await set_value(mixer, f"{target_addr}/eq/on", 1, args.dry_run)
            elif args.eq_off:
                await set_value(mixer, f"{target_addr}/eq/on", 0, args.dry_run)

            # Dynamics
            if args.comp_threshold is not None:
                await set_value(mixer, f"{target_addr}/dyn/thr", args.comp_threshold, args.dry_run)
            if args.gate_threshold is not None:
                await set_value(mixer, f"{target_addr}/gate/thr", args.gate_threshold, args.dry_run)

            # Bus send
            if args.send_bus and args.level is not None:
                await set_value(mixer, f"{target_addr}/mix/{args.send_bus:02d}/level", args.level, args.dry_run)

        # Main LR bus operations
        if args.main:
            main_addr = "/main/st"

            # Fader
            if args.fader:
                try:
                    fader_value = parse_fader_input(args.fader)
                    await set_value(mixer, f"{main_addr}/mix/fader", fader_value, args.dry_run)
                except ValueError as e:
                    print(f"Error: {e}", file=sys.stderr)
                    success = False

            # EQ band (main has 6 bands)
            if args.eq_band:
                if args.freq is not None:
                    await set_value(mixer, f"{main_addr}/eq/{args.eq_band}/f", args.freq, args.dry_run)
                if args.gain is not None:
                    await set_value(mixer, f"{main_addr}/eq/{args.eq_band}/g", args.gain, args.dry_run)
                if args.q is not None:
                    await set_value(mixer, f"{main_addr}/eq/{args.eq_band}/q", args.q, args.dry_run)

            # EQ on/off
            if args.eq_on:
                await set_value(mixer, f"{main_addr}/eq/on", 1, args.dry_run)
            elif args.eq_off:
                await set_value(mixer, f"{main_addr}/eq/on", 0, args.dry_run)

            # Dynamics (compressor only on main)
            if args.comp_threshold is not None:
                await set_value(mixer, f"{main_addr}/dyn/thr", args.comp_threshold, args.dry_run)

        # FX slot parameter
        if args.fx and args.fx_param and args.fx_value is not None:
            fx_addr = f"/fx/{args.fx}/par/{args.fx_param:02d}"
            await set_value(mixer, fx_addr, args.fx_value, args.dry_run)

        # FX return
        if args.fxrtn:
            fxrtn_addr = f"/fxrtn/{args.fxrtn:02d}"
            if args.fader:
                try:
                    fader_value = parse_fader_input(args.fader)
                    await set_value(mixer, f"{fxrtn_addr}/mix/fader", fader_value, args.dry_run)
                except ValueError as e:
                    print(f"Error: {e}", file=sys.stderr)
                    success = False

        if success:
            print("Success")
        else:
            sys.exit(1)

    finally:
        await mixer.stop()


if __name__ == "__main__":
    asyncio.run(main())
