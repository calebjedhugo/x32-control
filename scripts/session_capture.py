#!/usr/bin/env python3
"""
Comprehensive session capture for X-32 mixer.

Captures everything needed for a mixing session:
- All channel settings (EQ, dynamics, preamp, routing)
- All bus settings (EQ, dynamics)
- All FX settings and routing
- Meter data for gain staging analysis
- Signal path tracing

Usage:
    python session_capture.py
    python session_capture.py --duration 10
    python session_capture.py --output captures/sunday-worship.json
"""

import argparse
import asyncio
import json
import socket
import struct
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

sys.path.insert(0, str(Path(__file__).parent))

from common import (
    load_config, get_mixer, format_db, get_state_value, reliable_query,
    warmup_connection, ratio_index_to_value, hpf_value_to_hz
)

# Meter constants
METER_CHANNEL_PRE = 0
INACTIVE_THRESHOLD_RAW = 500

# FX type names (index -> name)
# NOTE: Some names may be inaccurate. The X32 FX numbering varies by firmware
# and slot type (insert vs send). Names for types 45-50 are gaps in the official
# list. Verify against mixer display when possible. Types 47 and 50 were
# identified from live sessions but names need confirmation.
FX_TYPE_NAMES = {
    0: "Hall Reverb",
    1: "Ambience",
    2: "Rich Plate",
    3: "Room",
    4: "Chamber",
    5: "Plate",
    6: "Vintage Room",
    7: "Vintage Plate",
    8: "Gated Reverb",
    9: "Reverse Reverb",
    10: "Stereo Delay",
    11: "Precision Limiter",
    12: "3-Tap Delay",
    13: "4-Tap Delay",
    14: "Chorus",
    15: "Flanger",
    16: "Phaser",
    17: "Ultimo Compressor",
    18: "Rotary Speaker",
    19: "Tremolo/Panner",
    20: "Sub Octaver",
    21: "Delay+Chamber",
    22: "Stereo Exciter",
    23: "Flanger+Chamber",
    24: "Delay+Chorus",
    25: "Delay+Flanger",
    26: "Dual Guitar Amp",
    27: "Graphic EQ",
    28: "True EQ",
    29: "Stereo EQ",
    30: "Wave Designer",
    31: "Precision Limiter",
    32: "Combinator",
    33: "Fair Compressor",
    34: "Leisure Compressor",
    35: "Ultra Enhancer",
    36: "Exciter",
    37: "Stereo Imager",
    38: "Edison EX1",
    39: "Sound Maxer",
    40: "Dual Guitar Amp",
    41: "Tube Stage",
    42: "Stereo Pitch",
    43: "Dual Pitch",
    44: "De-Esser",
    47: "Ultimo Compressor",
    50: "Dual Exciter",
}


async def capture_channel_settings(mixer, ch_num: int) -> Dict:
    """Capture full settings for a single channel."""
    ch_addr = f"/ch/{ch_num:02d}"
    state = mixer.state()

    # Basic info from state
    fader = get_state_value(state, ch_addr, "mix_fader", 0.0)
    fader_db = get_state_value(state, ch_addr, "mix_fader_db", None)

    # Check stereo link status (pairs are 1-2, 3-4, etc.)
    if ch_num % 2 == 1:  # Odd channel - check link with next
        link_addr = f'/config/chlink/{ch_num}-{ch_num+1}'
    else:  # Even channel - check link with previous
        link_addr = f'/config/chlink/{ch_num-1}-{ch_num}'
    stereo_linked = await reliable_query(mixer, link_addr, default=0) == 1

    settings = {
        "name": get_state_value(state, ch_addr, "config_name", ""),
        "fader": round(fader, 3),
        "fader_db": f"{fader_db} dB" if fader_db is not None else format_db(fader),
        "mute": get_state_value(state, ch_addr, "mix_on", True) == False,
        "pan": round(val if (val := await reliable_query(mixer, f'{ch_addr}/mix/pan')) is not None else 0.5, 3),
        "stereo_linked": stereo_linked,
    }

    # Preamp
    hpf_val = await reliable_query(mixer, f'{ch_addr}/preamp/hpf', default=0.0)
    # Phantom power lives on the headamp, not the channel preamp.
    # Channel source tells us which physical input (and headamp) is patched.
    source = await reliable_query(mixer, f'{ch_addr}/config/source', default=None)
    if source is not None and 0 <= int(source) <= 31:
        phantom = await reliable_query(mixer, f'/headamp/{int(source):03d}/phantom', default=0) == 1
    else:
        phantom = False
    settings["preamp"] = {
        "gain": round(await reliable_query(mixer, f'{ch_addr}/preamp/trim', default=0.5), 3),
        "phantom": phantom,
        "hpf_on": await reliable_query(mixer, f'{ch_addr}/preamp/hpon', default=0) == 1,
        "hpf_hz": hpf_value_to_hz(hpf_val) if hpf_val is not None else 20,
    }

    # EQ
    eq_on = await reliable_query(mixer, f'{ch_addr}/eq/on', default=0) == 1
    eq_bands = []
    for band in range(1, 5):
        eq_bands.append({
            "band": band,
            "freq": round(await reliable_query(mixer, f'{ch_addr}/eq/{band}/f', default=0.5), 3),
            "gain": round(await reliable_query(mixer, f'{ch_addr}/eq/{band}/g', default=0.5), 3),
            "q": round(await reliable_query(mixer, f'{ch_addr}/eq/{band}/q', default=0.5), 3),
        })
    settings["eq"] = {"on": eq_on, "bands": eq_bands}

    # Gate
    settings["gate"] = {
        "on": await reliable_query(mixer, f'{ch_addr}/gate/on', default=0) == 1,
        "threshold": round(await reliable_query(mixer, f'{ch_addr}/gate/thr', default=0.5), 3),
    }

    # Compressor
    comp_ratio_idx = await reliable_query(mixer, f'{ch_addr}/dyn/ratio', default=5)
    settings["compressor"] = {
        "on": await reliable_query(mixer, f'{ch_addr}/dyn/on', default=0) == 1,
        "threshold": round(await reliable_query(mixer, f'{ch_addr}/dyn/thr', default=0.5), 3),
        "ratio": f"{ratio_index_to_value(int(comp_ratio_idx))}:1" if comp_ratio_idx is not None else "3:1",
        "attack": round(await reliable_query(mixer, f'{ch_addr}/dyn/attack', default=0.5), 3),
        "release": round(await reliable_query(mixer, f'{ch_addr}/dyn/release', default=0.5), 3),
    }

    # Insert
    insert_on = await reliable_query(mixer, f'{ch_addr}/insert/on', default=0) == 1
    insert_sel = await reliable_query(mixer, f'{ch_addr}/insert/sel', default=0)
    # Insert sel maps: 0-1=FX1, 2-3=FX2, 4-5=FX3, 6-7=FX4 (L/R pairs)
    settings["insert"] = {
        "on": insert_on,
        "fx_slot": (int(insert_sel) // 2) + 1 if insert_on and insert_sel is not None else None,
    }

    # Bus sends (routing)
    sends = {}
    for bus_num in range(1, 17):
        level = await reliable_query(mixer, f'{ch_addr}/mix/{bus_num:02d}/level', default=0.0)
        on = await reliable_query(mixer, f'{ch_addr}/mix/{bus_num:02d}/on', default=0) == 1
        if on or (level and level > 0.01):
            sends[f"bus{bus_num:02d}"] = {
                "level": round(level, 3) if level else 0.0,
                "level_db": format_db(level) if level else "-inf dB",
                "on": on,
            }
    settings["sends"] = sends

    # Main send
    main_level = get_state_value(state, ch_addr, "mix_fader", 0.0)
    main_on = get_state_value(state, ch_addr, "mix_on", True)
    settings["main_send"] = {
        "level": round(main_level, 3),
        "level_db": format_db(main_level),
        "on": main_on,
    }

    return settings


async def capture_bus_settings(mixer, bus_num: int) -> Dict:
    """Capture full settings for a single bus."""
    bus_addr = f"/bus/{bus_num:02d}"
    state = mixer.state()

    fader = get_state_value(state, bus_addr, "mix_fader", 0.0)
    fader_db = get_state_value(state, bus_addr, "mix_fader_db", None)

    settings = {
        "name": get_state_value(state, bus_addr, "config_name", ""),
        "fader": round(fader, 3),
        "fader_db": f"{fader_db} dB" if fader_db is not None else format_db(fader),
        "mute": get_state_value(state, bus_addr, "mix_on", True) == False,
    }

    # Bus EQ (6 bands)
    eq_on = await reliable_query(mixer, f'{bus_addr}/eq/on', default=0) == 1
    eq_bands = []
    for band in range(1, 7):
        eq_bands.append({
            "band": band,
            "freq": round(await reliable_query(mixer, f'{bus_addr}/eq/{band}/f', default=0.5), 3),
            "gain": round(await reliable_query(mixer, f'{bus_addr}/eq/{band}/g', default=0.5), 3),
            "q": round(await reliable_query(mixer, f'{bus_addr}/eq/{band}/q', default=0.5), 3),
        })
    settings["eq"] = {"on": eq_on, "bands": eq_bands}

    # Bus compressor
    comp_ratio_idx = await reliable_query(mixer, f'{bus_addr}/dyn/ratio', default=5)
    settings["compressor"] = {
        "on": await reliable_query(mixer, f'{bus_addr}/dyn/on', default=0) == 1,
        "threshold": round(await reliable_query(mixer, f'{bus_addr}/dyn/thr', default=0.5), 3),
        "ratio": f"{ratio_index_to_value(int(comp_ratio_idx))}:1" if comp_ratio_idx is not None else "3:1",
    }

    # Bus insert - sel maps: 0-1=FX1, 2-3=FX2, 4-5=FX3, 6-7=FX4 (L/R pairs)
    insert_on = await reliable_query(mixer, f'{bus_addr}/insert/on', default=0) == 1
    insert_sel = await reliable_query(mixer, f'{bus_addr}/insert/sel', default=0)
    settings["insert"] = {
        "on": insert_on,
        "fx_slot": (int(insert_sel) // 2) + 1 if insert_on and insert_sel is not None else None,
    }

    return settings


async def capture_fx_settings(mixer, fx_num: int) -> Dict:
    """Capture settings for an FX slot."""
    fx_type_idx = await reliable_query(mixer, f'/fx/{fx_num}/type', default=0)
    fx_type_idx = int(fx_type_idx) if fx_type_idx else 0

    settings = {
        "type_id": fx_type_idx,
        "type_name": FX_TYPE_NAMES.get(fx_type_idx, f"Unknown ({fx_type_idx})"),
        "parameters": {},
    }

    # Get parameters (first 12 are usually the important ones)
    for param_num in range(1, 13):
        value = await reliable_query(mixer, f'/fx/{fx_num}/par/{param_num:02d}', default=None)
        if value is not None:
            settings["parameters"][param_num] = round(value, 3)

    return settings


async def capture_main_settings(mixer) -> Dict:
    """Capture main LR bus settings."""
    state = mixer.state()
    main_addr = "/main/st"

    fader = get_state_value(state, main_addr, "mix_fader", 0.0)

    settings = {
        "fader": round(fader, 3),
        "fader_db": format_db(fader),
        "mute": get_state_value(state, main_addr, "mix_on", True) == False,
    }

    # Main EQ (6 bands)
    eq_on = await reliable_query(mixer, '/main/st/eq/on', default=0) == 1
    eq_bands = []
    for band in range(1, 7):
        eq_bands.append({
            "band": band,
            "freq": round(await reliable_query(mixer, f'/main/st/eq/{band}/f', default=0.5), 3),
            "gain": round(await reliable_query(mixer, f'/main/st/eq/{band}/g', default=0.5), 3),
            "q": round(await reliable_query(mixer, f'/main/st/eq/{band}/q', default=0.5), 3),
        })
    settings["eq"] = {"on": eq_on, "bands": eq_bands}

    # Main compressor
    settings["compressor"] = {
        "on": await reliable_query(mixer, '/main/st/dyn/on', default=0) == 1,
        "threshold": round(await reliable_query(mixer, '/main/st/dyn/thr', default=0.5), 3),
    }

    return settings


def parse_meter_blob(data: bytes) -> Dict[str, int]:
    """Parse meter blob to get channel peak values."""
    result = {}
    try:
        num_values = len(data) // 2
        values = struct.unpack(f'>{num_values}h', data[:num_values * 2])

        # Channels 1-16 (indices 2-17)
        for i in range(16):
            if i + 2 < len(values):
                result[f'ch{i + 1:02d}'] = abs(values[i + 2])

        # Channels 17-32 (indices 19-34)
        for i in range(16):
            if i + 19 < len(values):
                result[f'ch{i + 17:02d}'] = abs(values[i + 19])
    except Exception:
        pass
    return result


async def capture_meters(mixer_ip: str, mixer_port: int, duration: float) -> Dict:
    """Capture meter data for gain staging analysis."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.1)
    sock.bind(('', 0))

    channel_peaks = {f'ch{i:02d}': 0 for i in range(1, 33)}

    def send_osc(address: str):
        addr_bytes = address.encode('utf-8') + b'\x00'
        while len(addr_bytes) % 4 != 0:
            addr_bytes += b'\x00'
        type_tag = b',\x00\x00\x00'
        sock.sendto(addr_bytes + type_tag, (mixer_ip, mixer_port))

    def subscribe():
        # Subscribe to pre-fader meters
        msg = b'/batchsubscribe\x00' + b',ssiiii\x00'
        msg += b'/meters/0\x00\x00\x00' + b'/meters/0\x00\x00\x00'
        msg += struct.pack('>iiii', 0, 0, 2, 0)
        sock.sendto(msg, (mixer_ip, mixer_port))

    start_time = time.time()
    last_subscribe = 0

    print(f"Capturing meters for {duration}s...", file=sys.stderr)

    try:
        while time.time() - start_time < duration:
            current = time.time()

            if current - last_subscribe > 0.1:
                send_osc('/xremote')
                subscribe()
                last_subscribe = current

            try:
                data, _ = sock.recvfrom(4096)
                if data.startswith(b'/meters/0'):
                    # Find blob data
                    blob_start = data.find(b',b')
                    if blob_start > 0:
                        len_start = blob_start + 4
                        while len_start % 4 != 0:
                            len_start += 1
                        blob_len = struct.unpack('>i', data[len_start:len_start+4])[0]
                        blob_data = data[len_start+4:len_start+4+blob_len]

                        peaks = parse_meter_blob(blob_data)
                        for ch, val in peaks.items():
                            if val > channel_peaks[ch]:
                                channel_peaks[ch] = val
            except socket.timeout:
                pass

            await asyncio.sleep(0.001)
    finally:
        sock.close()

    return channel_peaks


def analyze_gain_staging(channel_peaks: Dict, channel_names: Dict) -> Dict:
    """Analyze gain staging and identify issues."""
    # Filter to active channels only
    active = {ch: peak for ch, peak in channel_peaks.items() if peak > INACTIVE_THRESHOLD_RAW}

    if not active:
        return {"active_channels": [], "issues": [], "average_peak": 0}

    # Calculate average peak of active channels
    avg_peak = sum(active.values()) / len(active)

    issues = []
    for ch, peak in active.items():
        ch_num = int(ch.replace('ch', ''))
        name = channel_names.get(ch, ch)

        ratio = peak / avg_peak if avg_peak > 0 else 1

        if ratio > 2.0:  # More than 2x average
            db_diff = 20 * (ratio - 1) if ratio > 1 else 0
            issues.append({
                "channel": ch_num,
                "name": name,
                "peak_raw": peak,
                "issue": "hot",
                "detail": f"Running {db_diff:.0f}dB above average - consider reducing preamp gain",
            })
        elif ratio < 0.3:  # Less than 30% of average
            db_diff = 20 * (1 - ratio) if ratio < 1 else 0
            issues.append({
                "channel": ch_num,
                "name": name,
                "peak_raw": peak,
                "issue": "quiet",
                "detail": f"Running {db_diff:.0f}dB below average - may need more preamp gain",
            })

    return {
        "active_channels": sorted([int(ch.replace('ch', '')) for ch in active.keys()]),
        "issues": issues,
        "average_peak": int(avg_peak),
    }


def build_signal_paths(channels: Dict, buses: Dict) -> Dict:
    """Build signal path mapping showing what routes where."""
    paths = {}

    # Group channels by their bus destinations
    for ch_key, ch_data in channels.items():
        sends = ch_data.get("sends", {})
        for bus_key, send_data in sends.items():
            if send_data.get("on"):
                if bus_key not in paths:
                    bus_num = int(bus_key.replace('bus', ''))
                    bus_name = buses.get(bus_key, {}).get("name", bus_key)
                    paths[bus_key] = {
                        "name": bus_name,
                        "sources": [],
                        "fx_insert": buses.get(bus_key, {}).get("insert", {}).get("fx_slot"),
                    }
                ch_num = int(ch_key.replace('ch', ''))
                ch_name = ch_data.get("name", ch_key)
                paths[bus_key]["sources"].append({
                    "channel": ch_num,
                    "name": ch_name,
                    "send_level": send_data.get("level_db"),
                })

    return paths


async def main():
    parser = argparse.ArgumentParser(
        description="Comprehensive session capture for X-32 mixer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Captures everything needed for a mixing session:
- All channel settings (EQ, dynamics, preamp, routing)
- All bus settings (EQ, dynamics, inserts)
- All FX settings and routing
- Meter data for gain staging analysis
- Signal path analysis

Example:
    python session_capture.py --duration 10 --output captures/sunday.json
        """
    )
    parser.add_argument(
        "--duration", "-d",
        type=float,
        default=5,
        help="Meter capture duration in seconds (default: 5)"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path (default: captures/session_TIMESTAMP.json)"
    )

    args = parser.parse_args()

    config = load_config()

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_path = Path(__file__).parent.parent / "captures" / f"session_{timestamp}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("Connecting to mixer...", file=sys.stderr)

    try:
        mixer = await get_mixer(config)
    except Exception as e:
        print(f"Error: Cannot connect to mixer at {config['mixer_ip']}", file=sys.stderr)
        print(json.dumps({"success": False, "error": "connection_failed"}))
        sys.exit(1)

    try:
        await warmup_connection(mixer)

        result = {
            "metadata": {
                "capture_time": datetime.now().isoformat(),
                "mixer_ip": config["mixer_ip"],
                "meter_duration": args.duration,
            },
            "channels": {},
            "buses": {},
            "fx": {},
            "main": {},
            "analysis": {},
        }

        # Capture all channels
        print("Capturing channel settings...", file=sys.stderr)
        for ch_num in range(1, 33):
            result["channels"][f"ch{ch_num:02d}"] = await capture_channel_settings(mixer, ch_num)
            if ch_num % 8 == 0:
                print(f"  Channels 1-{ch_num} done", file=sys.stderr)

        # Fix stereo linked pairs: even (right) channel returns stale/default
        # values for processing settings. Copy from odd (left/master) channel.
        for ch_num in range(1, 32, 2):
            odd_key = f"ch{ch_num:02d}"
            even_key = f"ch{ch_num+1:02d}"
            odd_ch = result["channels"][odd_key]
            even_ch = result["channels"][even_key]
            if odd_ch.get("stereo_linked") and even_ch.get("stereo_linked"):
                for key in ("preamp", "eq", "gate", "compressor", "insert", "sends"):
                    even_ch[key] = odd_ch[key]

        # Capture all buses
        print("Capturing bus settings...", file=sys.stderr)
        for bus_num in range(1, 17):
            result["buses"][f"bus{bus_num:02d}"] = await capture_bus_settings(mixer, bus_num)
        print("  Buses 1-16 done", file=sys.stderr)

        # Capture all FX slots
        print("Capturing FX settings...", file=sys.stderr)
        for fx_num in range(1, 9):
            result["fx"][f"fx{fx_num}"] = await capture_fx_settings(mixer, fx_num)
        print("  FX 1-8 done", file=sys.stderr)

        # Capture main bus
        print("Capturing main bus settings...", file=sys.stderr)
        result["main"] = await capture_main_settings(mixer)

        # Capture meters
        channel_peaks = await capture_meters(
            config["mixer_ip"], config["mixer_port"], args.duration
        )

        # Build channel name lookup
        channel_names = {
            ch_key: ch_data.get("name", ch_key)
            for ch_key, ch_data in result["channels"].items()
        }

        # Analyze gain staging
        print("Analyzing gain staging...", file=sys.stderr)
        result["analysis"]["gain_staging"] = analyze_gain_staging(channel_peaks, channel_names)

        # Build signal paths
        print("Building signal paths...", file=sys.stderr)
        result["analysis"]["signal_paths"] = build_signal_paths(
            result["channels"], result["buses"]
        )

        # Add FX routing summary
        fx_routing = {}
        for fx_key, fx_data in result["fx"].items():
            fx_num = int(fx_key.replace('fx', ''))
            # Find what uses this FX as insert
            used_by = []
            for ch_key, ch_data in result["channels"].items():
                if ch_data.get("insert", {}).get("fx_slot") == fx_num:
                    used_by.append({"type": "channel", "id": ch_key, "name": ch_data.get("name")})
            for bus_key, bus_data in result["buses"].items():
                if bus_data.get("insert", {}).get("fx_slot") == fx_num:
                    used_by.append({"type": "bus", "id": bus_key, "name": bus_data.get("name")})

            if used_by or fx_data.get("type_id", 0) != 0:
                fx_routing[fx_key] = {
                    "type": fx_data.get("type_name"),
                    "inserted_on": used_by if used_by else None,
                }
        result["analysis"]["fx_routing"] = fx_routing

        # Write output
        with open(output_path, 'w') as f:
            json.dump(result, f, indent=2)

        # Summary
        active_count = len(result["analysis"]["gain_staging"]["active_channels"])
        issue_count = len(result["analysis"]["gain_staging"]["issues"])

        print(f"\nSession capture complete!", file=sys.stderr)
        print(f"  Active channels: {active_count}", file=sys.stderr)
        print(f"  Gain issues: {issue_count}", file=sys.stderr)
        print(f"  Output: {output_path}", file=sys.stderr)

        # Output JSON summary
        summary = {
            "success": True,
            "path": str(output_path),
            "active_channels": result["analysis"]["gain_staging"]["active_channels"],
            "gain_issues": result["analysis"]["gain_staging"]["issues"],
        }
        print(json.dumps(summary, indent=2))

    finally:
        await mixer.stop()


if __name__ == "__main__":
    asyncio.run(main())
