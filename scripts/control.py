#!/usr/bin/env python3
"""
Set X-32 mixer parameters.

Usage:
    python control.py --channel 5 --fader -10dB
    python control.py --channel 5 --gain-trim 0.5
    python control.py --channel 5 --eq-band 2 --gain 0.6
    python control.py --channel 5 --eq-on
    python control.py --channel 5 --mute
    python control.py --channel 5 --unmute
    python control.py --channel 5 --pan 0.3
    python control.py --channel 5 --comp-ratio 3.0
    python control.py --channel 5 --comp-mix 0.5
    python control.py --channel 5 --comp-mgain 0.3
    python control.py --channel 5 --gate-range 0.8
    python control.py --main --eq-band 3 --gain 0.45
    python control.py --main --comp-threshold 0.6
    python control.py --fx 1 --fx-param 1 --fx-value 0.5
    python control.py --fxrtn 1 --fader -10dB
    python control.py --channel 5 --fader -10dB --dry-run
    python control.py --batch changes.json
    python control.py --batch changes.json --dry-run
    python control.py --batch changes.json --changelog captures/changelog_2026-06-10.jsonl --phase eq --iter 2

Batch mode validates every command before applying anything (address allowlist,
value ranges, integer indices, mute/scene/routing blocked), then PRE-WRITE
VERIFIES each command against the live board: the claimed old_value must match
the live read (tolerance 0.03), and move size is checked against the live
value, not the claim. Exits:
    0 = all applied, 1 = load error, 2 = validation failed (batch kept),
    3 = partial (send failures in <file>.failed.json; pre-write refusals in
        BATCH_RESULT.refused_detail — never retried)
The last stdout line is machine-readable: BATCH_RESULT {...json...}
"""

import argparse
import asyncio
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path


def db_to_eq_gain_raw(db: float) -> float:
    """Convert dB to raw EQ gain (0.0-1.0). 0 dB = 0.5, ±15 dB range."""
    if not -15.0 <= db <= 15.0:
        raise ValueError(f"EQ gain must be between -15 and +15 dB (got {db})")
    return db / 30.0 + 0.5


def hz_to_eq_freq_raw(hz: float) -> float:
    """Convert Hz to raw EQ frequency (0.0-1.0). Log scale 20 Hz to 20 kHz."""
    if not 20.0 <= hz <= 20000.0:
        raise ValueError(f"EQ frequency must be between 20 and 20000 Hz (got {hz})")
    return math.log(hz / 20.0) / math.log(1000.0)


def _validate_raw_unit(name: str, value: float) -> None:
    """Error out if a raw 0-1 parameter is clearly outside range (would be silently clamped by X32)."""
    if not 0.0 <= value <= 1.0:
        raise ValueError(
            f"--{name} expects a raw 0.0-1.0 value (got {value}). "
            f"Use --{name}-db or --{name}-hz for human units, or check the value."
        )


def _resolve_eq_gain(args):
    """Pick gain from --gain (raw) or --gain-db (human). Returns raw 0-1 or None."""
    if args.gain_db is not None and args.gain is not None:
        raise ValueError("Specify only one of --gain or --gain-db")
    if args.gain_db is not None:
        return db_to_eq_gain_raw(args.gain_db)
    if args.gain is not None:
        _validate_raw_unit("gain", args.gain)
        return args.gain
    return None


def _resolve_eq_freq(args):
    """Pick freq from --freq (raw) or --freq-hz (human). Returns raw 0-1 or None."""
    if args.freq_hz is not None and args.freq is not None:
        raise ValueError("Specify only one of --freq or --freq-hz")
    if args.freq_hz is not None:
        return hz_to_eq_freq_raw(args.freq_hz)
    if args.freq is not None:
        _validate_raw_unit("freq", args.freq)
        return args.freq
    return None

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from common import load_config, get_mixer, parse_channel, parse_bus, db_to_fader, fader_to_db, format_db, ratio_value_to_index, reliable_query


# Addresses where readback after send is known to be unreliable.
# See docs/TECHNICAL.md for details.
_SKIP_READBACK_PATTERNS = [
    "/mtx/",       # Matrix faders: direct query() unreliable after send
    "/mix/",       # Send levels: readback after send is unreliable
]


def _should_skip_readback(address: str) -> bool:
    """Check if readback verification should be skipped for this address."""
    # Skip matrix parameters and bus send levels
    if "/mtx/" in address:
        return True
    # Send levels: /ch/XX/mix/YY/level or /bus/XX/mix/YY/level
    # But NOT simple /ch/XX/mix/fader or /ch/XX/mix/on
    if re.search(r'/mix/\d{2}/level', address):
        return True
    return False


async def set_value(mixer, address, value, dry_run=False):
    """
    Set a parameter value using direct OSC send, with readback verification.

    Uses mixer.send() instead of mixer.set_value() because the library's
    set_value() silently fails for addresses not in its mapping (EQ, dynamics, FX).

    After sending, queries the value back and warns if it doesn't match.
    Known unreliable readback parameters (matrix faders, send levels) are
    skipped for verification.

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

        # Readback verification (skip known unreliable parameters)
        if not _should_skip_readback(address):
            try:
                await asyncio.sleep(0.1)  # Brief delay for mixer to process
                readback = await mixer.query(address)
                if readback is not None:
                    rb_val = readback[0] if isinstance(readback, tuple) else readback
                    # Compare with tolerance (0.02 for floats — X32 quantizes some values)
                    if isinstance(value, (int, float)) and isinstance(rb_val, (int, float)):
                        if abs(float(rb_val) - float(value)) > 0.02:
                            print(
                                f"WARNING: {address} readback mismatch: sent {value}, got {rb_val}",
                                file=sys.stderr
                            )
                    elif str(rb_val) != str(value):
                        print(
                            f"WARNING: {address} readback mismatch: sent {value}, got {rb_val}",
                            file=sys.stderr
                        )
            except Exception:
                pass  # Don't break on readback failure

        return True
    except Exception as e:
        print(f"Error setting {address}: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Batch mode: validation + changelog + apply
#
# Batch files are JSON arrays of change objects. Only "address" and "value"
# are required; enriched fields (old_value, human, ch, label, reason, trim_db)
# are logged to the changelog when --changelog is given.
# ---------------------------------------------------------------------------

# Addresses that batch mode refuses outright (safety rules).
_BLOCKED_BATCH_PATTERNS = [
    (re.compile(r'^/(ch|bus|mtx|fxrtn|auxin)/\d{2}/mix/on$'), "mute toggle — never touch mute"),
    (re.compile(r'^/main/(st|m)/mix/on$'), "mute toggle — never touch mute"),
    (re.compile(r'^/(ch|bus)/\d{2}/mix/(st|mono)$'), "routing flag — alert the engineer instead"),
    (re.compile(r'^/fx/[1-8]/type$'), "FX type change — too drastic for batch"),
    (re.compile(r'^/-'), "console/scene operation — never save scenes"),
    (re.compile(r'^/dca/'), "DCA — engineer's live controls"),
]

# Targets batch mode may address at all.
_ALLOWED_BATCH_TARGET = re.compile(
    r'^(/(ch|bus|auxin|fxrtn)/\d{2}|/mtx/\d{2}|/main/(st|m)|/fx/[1-8])(/|$)'
)

# Value rules for index-style parameters. Anything not matched here must be a
# float in 0.0-1.0 (the X32 normalized-unit convention).
_BATCH_INT_RULES = [
    (re.compile(r'/dyn/ratio$'), 0, 11),     # compressor ratio is an INDEX, not the ratio value
    (re.compile(r'/dyn/knee$'), 0, 5),
    (re.compile(r'/(dyn|gate|eq)/on$'), 0, 1),
    (re.compile(r'/dyn/(det|env|auto)$'), 0, 1),
    (re.compile(r'/preamp/(hpon|invert)$'), 0, 1),
    (re.compile(r'/mix/\d{2}/on$'), 0, 1),   # send enable (not mute)
    (re.compile(r'/gate/mode$'), 0, 4),
    (re.compile(r'/eq/[1-6]/type$'), 0, 5),
]

# Backstop against drastic moves when old_value is provided. 0.34 raw on the
# EQ-gain scale is ~10dB — far beyond the "small moves" rule; real clamping to
# 2-3dB is the apply worker's job, this just catches runaway suggestions.
_MAX_RAW_DELTA = 0.34

# Pre-write verification tolerance. The X32 quantizes some params
# (e.g. 0.72 stored as 0.725), so claimed old_value won't match the live
# read exactly. 0.03 covers quantization without masking real disagreement.
_PRE_WRITE_TOLERANCE = 0.03


def _coerce_batch_value(value):
    """Normalize a batch value to a number (strings like '0.5' become floats)."""
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    return value


def validate_batch(commands):
    """Validate a batch of change objects. Returns (errors, normalized_commands)."""
    errors = []
    normalized = []
    for i, cmd in enumerate(commands):
        where = f"command {i + 1}"
        if not isinstance(cmd, dict) or "address" not in cmd or "value" not in cmd:
            errors.append(f"{where}: must be an object with 'address' and 'value'")
            continue
        address = cmd["address"]
        if not isinstance(address, str) or not address.startswith("/"):
            errors.append(f"{where}: bad address {address!r}")
            continue
        where = f"{where} ({address})"

        blocked = next((reason for pat, reason in _BLOCKED_BATCH_PATTERNS if pat.search(address)), None)
        if blocked:
            errors.append(f"{where}: BLOCKED — {blocked}")
            continue
        if not _ALLOWED_BATCH_TARGET.match(address):
            errors.append(f"{where}: unrecognized target — not in the batch allowlist")
            continue

        value = _coerce_batch_value(cmd["value"])
        if not isinstance(value, (int, float)):
            errors.append(f"{where}: non-numeric value {cmd['value']!r}")
            continue

        int_rule = next(((lo, hi) for pat, lo, hi in _BATCH_INT_RULES if pat.search(address)), None)
        if int_rule:
            lo, hi = int_rule
            if float(value) != int(value) or not lo <= int(value) <= hi:
                errors.append(
                    f"{where}: expects an integer index {lo}-{hi}, got {value!r}"
                    + (" (compressor ratio is an index, not the ratio value)" if address.endswith("/dyn/ratio") else "")
                )
                continue
            value = int(value)
        else:
            if not 0.0 <= float(value) <= 1.0:
                errors.append(f"{where}: expects a raw 0.0-1.0 value, got {value!r}")
                continue
            old = _coerce_batch_value(cmd.get("old_value"))
            if isinstance(old, (int, float)) and abs(float(value) - float(old)) > _MAX_RAW_DELTA:
                errors.append(
                    f"{where}: drastic move (raw delta {abs(float(value) - float(old)):.2f} > {_MAX_RAW_DELTA}) — "
                    f"small moves only; split into iterations"
                )
                continue

        normalized.append({**cmd, "value": value})
    return errors, normalized


def _append_changelog(changelog_path, cmd, phase, iteration):
    """Append one applied change to the changelog (JSONL, O_APPEND)."""
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "phase": phase,
        "iter": iteration,
        "ch": cmd.get("ch"),
        "label": cmd.get("label"),
        "param": cmd["address"],
        "old_raw": cmd.get("old_value"),
        "new_raw": cmd["value"],
        "human": cmd.get("human"),
        "reason": cmd.get("reason"),
    }
    if cmd.get("trim_db") is not None:
        entry["trim_db"] = cmd["trim_db"]
    changelog_path.parent.mkdir(parents=True, exist_ok=True)
    with open(changelog_path, "a") as f:
        f.write(json.dumps(entry) + "\n")


async def run_batch(args):
    """Run --batch mode. Exit codes: 0 = all applied, 1 = usage/load error,
    2 = validation failed (nothing applied, batch file kept),
    3 = partial: some commands failed (written to <batch>.failed.json) or were
    refused by pre-write verification (listed in BATCH_RESULT.refused_detail —
    do NOT retry those; the analysis was based on wrong data)."""
    batch_path = Path(args.batch)
    if not batch_path.exists():
        print(f"Error: Batch file not found: {batch_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(batch_path) as f:
            commands = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Batch file is not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(commands, list):
        print("Error: Batch file must be a JSON array of change objects", file=sys.stderr)
        sys.exit(1)

    changelog_path = Path(args.changelog) if args.changelog else None

    errors, commands = validate_batch(commands)
    if errors:
        print("Batch validation FAILED — nothing applied, batch file kept:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        print(f"BATCH_RESULT {json.dumps({'total': len(errors) + len(commands), 'applied': 0, 'failed': 0, 'validation_errors': len(errors)})}")
        sys.exit(2)

    if not commands:
        batch_path.unlink()
        print(f"BATCH_RESULT {json.dumps({'total': 0, 'applied': 0, 'failed': 0})}")
        return

    print(f"Batch: {len(commands)} commands", file=sys.stderr)

    if args.dry_run:
        for cmd in commands:
            print(f"[DRY RUN] Would set {cmd['address']} = {cmd['value']}")
        print(f"BATCH_RESULT {json.dumps({'total': len(commands), 'applied': 0, 'failed': 0, 'dry_run': True})}")
        return

    applied = 0
    failed_cmds = []
    refused = []
    mixer = await get_mixer()
    try:
        for cmd in commands:
            address, value = cmd["address"], cmd["value"]

            # Pre-write verification: the analysis worker's old_value claim is
            # never load-bearing — read the board and compare. A mismatch means
            # the worker misread/hallucinated its data, the data was stale, or
            # the engineer changed the param; in every case the suggestion was
            # computed from a wrong starting point, so refuse it.
            live = await reliable_query(mixer, address, default=None)
            if isinstance(live, (int, float)):
                claimed_old = _coerce_batch_value(cmd.get("old_value"))
                if isinstance(claimed_old, (int, float)) \
                        and abs(float(live) - float(claimed_old)) > _PRE_WRITE_TOLERANCE:
                    if _should_skip_readback(address):
                        # Known-unreliable read addresses: warn, don't refuse
                        print(f"WARNING: {address} live={live} != old_value={claimed_old} "
                              f"(read unreliable for this address — applying anyway)", file=sys.stderr)
                    else:
                        print(f"REFUSED {address}: old_value={claimed_old} but board reads "
                              f"{live} — suggestion was computed from wrong data", file=sys.stderr)
                        refused.append({**cmd, "live_value": live, "refusal": "old_value mismatch"})
                        continue
                # Authoritative drastic-move check against the LIVE value
                if not _should_skip_readback(address) \
                        and abs(float(value) - float(live)) > _MAX_RAW_DELTA:
                    print(f"REFUSED {address}: move from live {live} to {value} is drastic "
                          f"(delta {abs(float(value) - float(live)):.2f} > {_MAX_RAW_DELTA})", file=sys.stderr)
                    refused.append({**cmd, "live_value": live, "refusal": "drastic vs live value"})
                    continue

            ok = await set_value(mixer, address, value)
            if ok:
                applied += 1
                if changelog_path:
                    _append_changelog(changelog_path, cmd, args.phase, args.iter)
            else:
                failed_cmds.append(cmd)
            await asyncio.sleep(0.05)
    finally:
        await mixer.stop()

    result = {"total": len(commands), "applied": applied, "failed": len(failed_cmds),
              "refused": len(refused)}
    if refused:
        result["refused_detail"] = [
            {"address": r["address"], "old_value": r.get("old_value"),
             "live_value": r["live_value"], "refusal": r["refusal"]} for r in refused
        ]
    if changelog_path:
        result["changelog"] = str(changelog_path)
        result["changelog_appended"] = applied
    if failed_cmds:
        failed_path = batch_path.with_name(batch_path.stem + ".failed.json")
        with open(failed_path, "w") as f:
            json.dump(failed_cmds, f, indent=2)
        result["failed_file"] = str(failed_path)
    batch_path.unlink()

    print(f"Batch complete: {applied}/{len(commands)} succeeded"
          + (f", {len(refused)} refused" if refused else ""), file=sys.stderr)
    print(f"BATCH_RESULT {json.dumps(result)}")
    if failed_cmds or refused:
        sys.exit(3)


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
        help="EQ frequency as raw 0.0-1.0 value (log scale: 0.0=20Hz, 1.0=20kHz). Requires --eq-band"
    )
    parser.add_argument(
        "--freq-hz",
        type=float,
        help="EQ frequency in Hz (20-20000). Converted to raw internally. Requires --eq-band"
    )
    parser.add_argument(
        "--gain",
        type=float,
        help="EQ gain as raw 0.0-1.0 value (0.5 = 0dB, 0.0 = -15dB, 1.0 = +15dB). Requires --eq-band"
    )
    parser.add_argument(
        "--gain-db",
        type=float,
        help="EQ gain in dB (-15 to +15). Converted to raw internally. Requires --eq-band"
    )
    parser.add_argument(
        "--q",
        type=float,
        help="EQ Q factor as raw 0.0-1.0 value. Requires --eq-band. (No human-units flag — Q raw mapping is not verified.)"
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

    # Mute/unmute
    mute_group = parser.add_mutually_exclusive_group()
    mute_group.add_argument(
        "--mute",
        action="store_true",
        help="Mute channel/bus (set mix/on to 0)"
    )
    mute_group.add_argument(
        "--unmute",
        action="store_true",
        help="Unmute channel/bus (set mix/on to 1)"
    )

    # Pan
    parser.add_argument(
        "--pan",
        type=float,
        help="Set pan (0.0=hard left, 0.5=center, 1.0=hard right)"
    )

    # Dynamics control
    parser.add_argument(
        "--comp-threshold",
        type=float,
        help="Compressor threshold (raw 0.0-1.0 value)"
    )
    parser.add_argument(
        "--comp-ratio",
        type=float,
        help="Compressor ratio (actual value like 3.0 for 3:1, converted to X32 index)"
    )
    parser.add_argument(
        "--comp-mix",
        type=float,
        help="Compressor mix/blend (raw 0.0-1.0 value)"
    )
    parser.add_argument(
        "--comp-mgain",
        type=float,
        help="Compressor makeup gain (raw 0.0-1.0 value)"
    )
    parser.add_argument(
        "--gate-threshold",
        type=float,
        help="Gate threshold (raw 0.0-1.0 value)"
    )
    parser.add_argument(
        "--gate-range",
        type=float,
        help="Gate range (raw 0.0-1.0 value)"
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

    # Batch mode
    parser.add_argument(
        "--batch",
        type=str,
        metavar="FILE",
        help='Execute batch of change objects from JSON file [{"address": ..., "value": ..., ...}, ...]. '
             'Validates all commands before applying. Deletes the file on completion; '
             'failures are written to <file>.failed.json'
    )
    parser.add_argument(
        "--changelog",
        type=str,
        metavar="FILE",
        help="Batch mode: append one JSONL line per applied change to this file"
    )
    parser.add_argument(
        "--phase",
        type=str,
        help="Batch mode: phase name recorded in the changelog (e.g. metering, eq, upstream)"
    )
    parser.add_argument(
        "--iter",
        type=int,
        default=1,
        help="Batch mode: iteration number recorded in the changelog"
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

    # Batch mode — bypass all other argument validation
    if args.batch:
        await run_batch(args)
        return

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
            args.comp_threshold, args.comp_ratio, args.comp_mix, args.comp_mgain,
            args.gate_threshold, args.gate_range,
            args.mute, args.unmute, args.pan is not None,
            args.send_bus and args.level is not None
        ]):
            parser.error("Must specify an operation (--fader, --eq-band, --mute, etc.)")
    elif args.main:
        # Main LR bus mode
        if not any([
            args.fader,
            args.eq_band, args.eq_on, args.eq_off,
            args.comp_threshold, args.comp_ratio, args.comp_mix, args.comp_mgain,
            args.mute, args.unmute
        ]):
            parser.error("--main requires --eq-band, --eq-on/off, --comp-threshold, --comp-ratio, --comp-mix, --comp-mgain, --mute/--unmute, or --fader")
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

            # Preamp gain
            if args.gain_trim is not None:
                await set_value(mixer, f"{target_addr}/preamp/trim", args.gain_trim, args.dry_run)

            # EQ band
            if args.eq_band:
                freq_raw = _resolve_eq_freq(args)
                gain_raw = _resolve_eq_gain(args)
                if freq_raw is not None:
                    await set_value(mixer, f"{target_addr}/eq/{args.eq_band}/f", freq_raw, args.dry_run)
                if gain_raw is not None:
                    await set_value(mixer, f"{target_addr}/eq/{args.eq_band}/g", gain_raw, args.dry_run)
                if args.q is not None:
                    _validate_raw_unit("q", args.q)
                    await set_value(mixer, f"{target_addr}/eq/{args.eq_band}/q", args.q, args.dry_run)

            # EQ on/off
            if args.eq_on:
                await set_value(mixer, f"{target_addr}/eq/on", 1, args.dry_run)
            elif args.eq_off:
                await set_value(mixer, f"{target_addr}/eq/on", 0, args.dry_run)

            # Mute/unmute
            if args.mute:
                await set_value(mixer, f"{target_addr}/mix/on", 0, args.dry_run)
            elif args.unmute:
                await set_value(mixer, f"{target_addr}/mix/on", 1, args.dry_run)

            # Pan
            if args.pan is not None:
                await set_value(mixer, f"{target_addr}/mix/pan", args.pan, args.dry_run)

            # Dynamics
            if args.comp_threshold is not None:
                await set_value(mixer, f"{target_addr}/dyn/thr", args.comp_threshold, args.dry_run)
            if args.comp_ratio is not None:
                ratio_idx = ratio_value_to_index(args.comp_ratio)
                await set_value(mixer, f"{target_addr}/dyn/ratio", ratio_idx, args.dry_run)
            if args.comp_mix is not None:
                await set_value(mixer, f"{target_addr}/dyn/mix", args.comp_mix, args.dry_run)
            if args.comp_mgain is not None:
                await set_value(mixer, f"{target_addr}/dyn/mgain", args.comp_mgain, args.dry_run)
            if args.gate_threshold is not None:
                await set_value(mixer, f"{target_addr}/gate/thr", args.gate_threshold, args.dry_run)
            if args.gate_range is not None:
                await set_value(mixer, f"{target_addr}/gate/range", args.gate_range, args.dry_run)

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
                freq_raw = _resolve_eq_freq(args)
                gain_raw = _resolve_eq_gain(args)
                if freq_raw is not None:
                    await set_value(mixer, f"{main_addr}/eq/{args.eq_band}/f", freq_raw, args.dry_run)
                if gain_raw is not None:
                    await set_value(mixer, f"{main_addr}/eq/{args.eq_band}/g", gain_raw, args.dry_run)
                if args.q is not None:
                    _validate_raw_unit("q", args.q)
                    await set_value(mixer, f"{main_addr}/eq/{args.eq_band}/q", args.q, args.dry_run)

            # EQ on/off
            if args.eq_on:
                await set_value(mixer, f"{main_addr}/eq/on", 1, args.dry_run)
            elif args.eq_off:
                await set_value(mixer, f"{main_addr}/eq/on", 0, args.dry_run)

            # Mute/unmute
            if args.mute:
                await set_value(mixer, f"{main_addr}/mix/on", 0, args.dry_run)
            elif args.unmute:
                await set_value(mixer, f"{main_addr}/mix/on", 1, args.dry_run)

            # Dynamics (compressor on main)
            if args.comp_threshold is not None:
                await set_value(mixer, f"{main_addr}/dyn/thr", args.comp_threshold, args.dry_run)
            if args.comp_ratio is not None:
                ratio_idx = ratio_value_to_index(args.comp_ratio)
                await set_value(mixer, f"{main_addr}/dyn/ratio", ratio_idx, args.dry_run)
            if args.comp_mix is not None:
                await set_value(mixer, f"{main_addr}/dyn/mix", args.comp_mix, args.dry_run)
            if args.comp_mgain is not None:
                await set_value(mixer, f"{main_addr}/dyn/mgain", args.comp_mgain, args.dry_run)

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
