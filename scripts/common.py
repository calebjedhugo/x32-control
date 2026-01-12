"""
Common utilities for X-32 mixer control scripts.
"""

import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

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
        return mixer
    except Exception as e:
        print(f"Error connecting to mixer at {config['mixer_ip']}:{config['mixer_port']}", file=sys.stderr)
        print(f"Details: {e}", file=sys.stderr)
        sys.exit(1)


def fader_to_db(fader_value: float) -> float:
    """
    Convert fader value (0.0-1.0) to decibels.

    X32 fader mapping:
    - 0.0 = -inf dB
    - 0.75 = 0 dB (unity)
    - 1.0 = +10 dB

    Formula based on X32 documentation.
    """
    if fader_value <= 0.0:
        return float('-inf')
    elif fader_value < 0.5:
        # -90 dB to -30 dB
        return 40 * fader_value - 90
    elif fader_value < 0.75:
        # -30 dB to 0 dB
        return 120 * fader_value - 90
    else:
        # 0 dB to +10 dB
        return 40 * fader_value


def db_to_fader(db: float) -> float:
    """
    Convert decibels to fader value (0.0-1.0).

    Inverse of fader_to_db().
    """
    if db <= -90:
        return 0.0
    elif db < -30:
        return (db + 90) / 40
    elif db < 0:
        return (db + 90) / 120
    elif db <= 10:
        return db / 40
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
