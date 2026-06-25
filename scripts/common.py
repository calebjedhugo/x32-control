"""
Common utilities for X-32 mixer control scripts.
"""

import asyncio
import json
import math
import os
import re
import struct
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# X32 compressor ratio values (index -> actual ratio)
# The X32 stores ratio as an index into this array
COMP_RATIO_VALUES = [1.1, 1.3, 1.5, 2, 2.5, 3, 4, 5, 7, 10, 20, 100]

def ratio_index_to_value(index: int) -> float:
    """Convert X32 ratio index to actual ratio value."""
    if 0 <= index < len(COMP_RATIO_VALUES):
        return COMP_RATIO_VALUES[index]
    return index  # Return raw if out of range

def ratio_value_to_index(ratio: float) -> int:
    """Convert ratio value to X32 index (finds closest match)."""
    closest_idx = 0
    closest_diff = abs(COMP_RATIO_VALUES[0] - ratio)
    for idx, val in enumerate(COMP_RATIO_VALUES):
        diff = abs(val - ratio)
        if diff < closest_diff:
            closest_diff = diff
            closest_idx = idx
    return closest_idx

# Get project root (parent of scripts directory)
PROJECT_ROOT = Path(__file__).parent.parent


def load_config() -> Dict[str, Any]:
    """Load configuration from config.json."""
    config_path = PROJECT_ROOT / "config.json"

    if not config_path.exists():
        print(f"Error: config.json not found at {config_path}", file=sys.stderr)
        print("Copy config.example.json to config.json and set your mixer IP", file=sys.stderr)
        sys.exit(1)

    try:
        with open(config_path) as f:
            config = json.load(f)

        # Validate required fields
        if "mixer_ip" not in config:
            print("Error: mixer_ip not found in config.json", file=sys.stderr)
            sys.exit(1)

        if config["mixer_ip"] == "192.168.0.XXX":
            print("Error: Please set a valid mixer_ip in config.json", file=sys.stderr)
            sys.exit(1)

        # Set defaults
        config.setdefault("mixer_port", 10023)
        config.setdefault("mixer_type", "X32")
        config.setdefault("timeout_seconds", 5)
        config.setdefault("default_output_format", "json")
        config.setdefault("snapshot_dir", "snapshots")

        return config

    except json.JSONDecodeError as e:
        print(f"Error parsing config.json: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error loading config: {e}", file=sys.stderr)
        sys.exit(1)


async def get_mixer(config: Optional[Dict[str, Any]] = None):
    """
    Create and return a connected mixer instance.

    Args:
        config: Configuration dict (loads from file if not provided)

    Returns:
        Connected mixer instance from behringer_mixer
    """
    sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
    from behringer_mixer import mixer_api

    if config is None:
        config = load_config()

    mixer = mixer_api.create(
        config["mixer_type"],
        ip=config["mixer_ip"],
        port=config["mixer_port"]
    )

    try:
        await mixer.start()
        await mixer.validate_connection()
        await mixer.reload()  # Load initial state from mixer
        # Poll until state is fully populated (last channel responds)
        # instead of a fixed sleep that may be too short
        max_wait = 10.0
        poll_interval = 0.2
        elapsed = 0.0
        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
            state = mixer.state()
            # Check if the last channel's name has arrived
            if state.get('/ch/32/config_name') is not None:
                break
        if elapsed >= max_wait:
            print(f"Warning: mixer state not fully populated after {max_wait}s", file=sys.stderr)
        return mixer
    except Exception as e:
        print(f"Error connecting to mixer at {config['mixer_ip']}:{config['mixer_port']}", file=sys.stderr)
        print(f"Details: {e}", file=sys.stderr)
        sys.exit(1)


def fader_to_db(fader_value: float) -> float:
    """
    Convert fader value (0.0-1.0) to decibels.

    X32 fader mapping (piecewise linear, verified against mixer):
    - 0.0  = -inf dB
    - 0.25 = -30 dB
    - 0.5  = -10 dB
    - 0.75 =   0 dB (unity)
    - 1.0  = +10 dB
    """
    if fader_value <= 0.0:
        return float('-inf')
    elif fader_value <= 0.25:
        # -90 dB to -30 dB
        return 240 * fader_value - 90
    elif fader_value <= 0.5:
        # -30 dB to -10 dB
        return 80 * fader_value - 50
    else:
        # -10 dB to +10 dB
        return 40 * fader_value - 30


def db_to_fader(db: float) -> float:
    """
    Convert decibels to fader value (0.0-1.0).

    Inverse of fader_to_db().
    """
    if db <= -90:
        return 0.0
    elif db <= -30:
        return (db + 90) / 240
    elif db <= -10:
        return (db + 50) / 80
    elif db <= 10:
        return (db + 30) / 40
    else:
        return 1.0


def format_db(fader_value: float, decimal_places: int = 1) -> str:
    """
    Format fader value as dB string.

    Args:
        fader_value: Float between 0.0 and 1.0
        decimal_places: Number of decimal places (default: 1)

    Returns:
        String like "-5.2 dB" or "-inf dB"
    """
    db = fader_to_db(fader_value)
    if math.isinf(db):
        return "-inf dB"
    return f"{db:.{decimal_places}f} dB"


def parse_channel(input_str: str) -> str:
    """
    Parse channel input and return normalized OSC address.

    Accepts:
        - "5" → "/ch/05"
        - "ch5" → "/ch/05"
        - "channel 5" → "/ch/05"
        - "/ch/05" → "/ch/05"

    Args:
        input_str: Channel identifier

    Returns:
        Normalized OSC address like "/ch/05"
    """
    input_str = input_str.strip().lower()

    # Already formatted
    if input_str.startswith("/ch/"):
        return input_str

    # Extract number
    match = re.search(r'\d+', input_str)
    if not match:
        raise ValueError(f"Could not parse channel number from: {input_str}")

    channel_num = int(match.group())

    if channel_num < 1 or channel_num > 32:
        raise ValueError(f"Channel number must be 1-32, got: {channel_num}")

    return f"/ch/{channel_num:02d}"


def parse_bus(input_str: str) -> str:
    """Parse bus input and return normalized OSC address."""
    input_str = input_str.strip().lower()

    if input_str.startswith("/bus/"):
        return input_str

    match = re.search(r'\d+', input_str)
    if not match:
        raise ValueError(f"Could not parse bus number from: {input_str}")

    bus_num = int(match.group())

    if bus_num < 1 or bus_num > 16:
        raise ValueError(f"Bus number must be 1-16, got: {bus_num}")

    return f"/bus/{bus_num:02d}"


def parse_channel_range(range_str: str) -> list:
    """
    Parse channel range string and return list of channel numbers.

    Examples:
        "1-8" → [1, 2, 3, 4, 5, 6, 7, 8]
        "1,3,5" → [1, 3, 5]
        "1-4,9-12" → [1, 2, 3, 4, 9, 10, 11, 12]

    Args:
        range_str: Range specification

    Returns:
        List of channel numbers
    """
    channels = []
    parts = range_str.split(',')

    for part in parts:
        part = part.strip()
        if '-' in part:
            start, end = part.split('-')
            start = int(start.strip())
            end = int(end.strip())
            channels.extend(range(start, end + 1))
        else:
            channels.append(int(part))

    return sorted(set(channels))


def format_output(data: Any, format: str = 'json') -> str:
    """
    Format output data.

    Args:
        data: Data to format
        format: Output format ('json', 'table', 'plain')

    Returns:
        Formatted string
    """
    if format == 'json':
        return json.dumps(data, indent=2)
    elif format == 'plain':
        if isinstance(data, dict):
            return '\n'.join(f"{k}: {v}" for k, v in data.items())
        return str(data)
    elif format == 'table':
        # Basic table formatting (can be enhanced)
        if isinstance(data, dict):
            return '\n'.join(f"{k:<20} {v}" for k, v in data.items())
        return str(data)
    else:
        return str(data)


def get_snapshot_dir() -> Path:
    """Get or create snapshots directory."""
    config = load_config()
    snapshot_dir = PROJECT_ROOT / config["snapshot_dir"]
    snapshot_dir.mkdir(exist_ok=True)
    return snapshot_dir


def state_key(base_addr: str, prop: str) -> str:
    """
    Convert OSC-style address to behringer_mixer state key.

    Examples:
        state_key("/ch/01", "mix/fader") → "/ch/1/mix_fader"
        state_key("/ch/05", "config/name") → "/ch/5/config_name"
        state_key("/bus/03", "mix/on") → "/bus/3/mix_on"
    """
    # Remove zero-padding from channel/bus numbers
    base_addr = re.sub(r'/(\d+)', lambda m: f'/{int(m.group(1))}', base_addr)
    # Replace slashes in property with underscores
    prop = prop.replace('/', '_')
    return f"{base_addr}/{prop}"


def get_state_value(state: dict, base_addr: str, prop: str, default=None):
    """
    Get value from mixer state using OSC-style addressing.

    Args:
        state: Mixer state dictionary
        base_addr: Base address like "/ch/01" or "/bus/05"
        prop: Property path like "mix/fader" or "config/name"
        default: Default value if not found

    Returns:
        Value from state or default
    """
    key = state_key(base_addr, prop)
    return state.get(key, default)


async def reliable_query(mixer, address: str, retries: int = 3, delay: float = 0.05,
                         default=None, failures: list = None):
    """
    Query a mixer address with retries.

    The vendored behringer_mixer library now uses per-address response matching,
    so responses are correctly attributed even when queries overlap. Retries
    only cover UDP packet loss (not response misattribution).

    Args:
        mixer: Connected mixer instance
        address: OSC address like "/ch/08/eq/1/g"
        retries: Number of retry attempts (default 3)
        delay: Delay between retries in seconds (default 0.05)
        default: Default value if all retries fail
        failures: Optional list to append failed addresses to

    Returns:
        First value from query result, or default
    """
    for attempt in range(retries):
        result = await mixer.query(address)
        if result is not None:
            return result[0] if isinstance(result, tuple) else result
        if attempt < retries - 1:
            await asyncio.sleep(delay)
    if failures is not None:
        failures.append(address)
    return default


async def warmup_connection(mixer):
    """
    Send a throwaway query to warm up the mixer connection.

    First query after connection often returns None due to UDP setup.
    With per-address response matching, a single warmup is sufficient.
    """
    await mixer.query('/ch/01/mix/fader')
    await asyncio.sleep(0.1)


# HPF (High-Pass Filter) frequency values in Hz
# The X32 stores HPF freq as a 0.0-1.0 value that maps to 20Hz-400Hz
def hpf_value_to_hz(value: float) -> int:
    """Convert X32 HPF value (0.0-1.0) to frequency in Hz (20-400)."""
    # Logarithmic scale: 20Hz to 400Hz
    if value <= 0:
        return 20
    if value >= 1:
        return 400
    # Log scale mapping
    return int(20 * (400/20) ** value)

def hpf_hz_to_value(hz: int) -> float:
    """Convert frequency in Hz to X32 HPF value (0.0-1.0)."""
    if hz <= 20:
        return 0.0
    if hz >= 400:
        return 1.0
    return math.log(hz/20) / math.log(400/20)


# Meter constants
METER_CHANNEL_PRE = 0  # /meters/0 = pre-fader channel meters
INACTIVE_THRESHOLD_RAW = 0.0005  # Below this raw peak, channel is considered inactive


def parse_meter_blob(data: bytes) -> Dict[str, float]:
    """Parse meter blob to get channel peak values.

    X32 meter blob format: 4-byte LE int32 count (70), then 70 LE float32 values.
    Layout: ONE value per channel — channel N meter is at index N-1 (indices
    0-31 = ch1-32; indices 32+ are aux/fx/bus/main meters, which is why an
    announcement routed to the mains also lights some high indices).

    NOTE (verified 2026-06-14, live): the earlier "2 values per channel
    (level + gate), index (N-1)*2" interpretation was WRONG. With a known live
    source on ch10 (someone talking), the speech tracked index 9 — not index 18
    — and index 18 was dead. The 2-per stride read every channel's level from
    the wrong slot (except ch1 at idx0, identical either way), so some channels
    showed a flat 0.0 despite carrying signal. The bus parser
    (parse_bus_meter_blob) already used 1-per; the channel parser was the outlier.
    """
    result = {}
    try:
        if len(data) < 4:
            return result
        count = struct.unpack('<i', data[:4])[0]
        num_floats = min(count, (len(data) - 4) // 4)
        values = struct.unpack(f'<{num_floats}f', data[4:4 + num_floats * 4])

        # Channels 1-32: one value per channel at index N-1
        for i in range(32):
            idx = i
            if idx < num_floats:
                result[f'ch{i + 1:02d}'] = values[idx]
    except Exception:
        pass
    return result


def parse_bus_meter_blob(data: bytes) -> Dict[str, float]:
    """Parse /meters/2 blob to get bus and main peak values.

    Same LE float32 format as channel meters. Layout:
    - Index 0: header (skip)
    - Indices 1-16: Bus 1-16
    - Indices 17-18: Main L/R
    """
    result = {}
    try:
        if len(data) < 4:
            return result
        count = struct.unpack('<i', data[:4])[0]
        num_floats = min(count, (len(data) - 4) // 4)
        values = struct.unpack(f'<{num_floats}f', data[4:4 + num_floats * 4])

        # Buses 1-16 at indices 1-16
        for i in range(min(16, num_floats - 1)):
            result[f'bus{i + 1:02d}'] = values[i + 1]

        # Main L/R at indices 17-18
        if num_floats > 17:
            result['main_L'] = values[17]
        if num_floats > 18:
            result['main_R'] = values[18]
    except Exception:
        pass
    return result


def extract_blob(data: bytes) -> Optional[bytes]:
    """Extract blob data from an OSC meter response."""
    blob_start = data.find(b',b')
    if blob_start <= 0:
        return None
    len_start = blob_start + 4
    while len_start % 4 != 0:
        len_start += 1
    blob_len = struct.unpack('>i', data[len_start:len_start+4])[0]
    return data[len_start+4:len_start+4+blob_len]
