#!/usr/bin/env python3
"""
Capture real-time meter data from all channels simultaneously.

This script uses raw OSC to subscribe to meter data directly from the X-32,
capturing truly simultaneous readings across all channels in the same
musical moment.

Usage:
    python capture.py --duration 30
    python capture.py --duration 10 --output captures/soundcheck.json

Meter data is pushed by the mixer at ~50Hz, giving synchronized snapshots
of all channel levels in each packet.

For RTA frequency analysis, use rta_listen.py instead (on-demand, single channel).
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

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from common import load_config, get_mixer, fader_to_db, format_db, get_state_value

# X-32 meter indices
METER_CHANNEL_PRE = 0   # Ch 1-32 pre-fader + Aux 1-8 (70 values)
METER_CHANNEL_POST = 1  # Ch 1-32 post-fader + Aux 1-8 (70 values)
METER_BUS = 2           # Bus 1-16 + Main L/R + Mono (34 values)

# Activity detection thresholds (raw int16 values, not dB)
# Raw meter values: 0 = silence, ~32767 = max, negative = treat as no signal
INACTIVE_THRESHOLD_RAW = 500  # Below this = completely inactive (ignore channel)


def meter_int_to_db(value: int) -> float:
    """
    Convert X-32 meter int16 value to dB (APPROXIMATE - NOT CALIBRATED).

    WARNING: This formula is a rough approximation and has NOT been calibrated
    against actual signal levels. Use only for rough human-readable output,
    never for thresholds or comparisons. Use raw values for all logic.

    User's dB scale: 0 = unity, +10 = max, -70 = almost silent

    X-32 meters use int16 values where:
    - 0 = -inf (silence)
    - ~16384 = ~0 dB (approximate)
    - Higher values = positive dB (clipping)
    """
    if value <= 0:
        return float('-inf')

    # X-32 uses a specific log mapping - THIS NEEDS CALIBRATION
    # Values are roughly: 10^((value/16384 - 1) * 4) for the main range
    normalized = value / 32768.0  # 0.0 to 1.0

    if normalized <= 0:
        return float('-inf')
    elif normalized < 0.0625:  # Very low levels
        return -90 + (normalized / 0.0625) * 60  # -90 to -30
    elif normalized < 0.25:  # Low to mid levels
        return -30 + ((normalized - 0.0625) / 0.1875) * 30  # -30 to 0
    else:  # Mid to high levels
        return ((normalized - 0.25) / 0.75) * 18  # 0 to +18


def parse_meter_blob(data: bytes, meter_type: int) -> Dict[str, Any]:
    """
    Parse meter blob data from X-32.

    Meter data comes as a blob of int16 values (big-endian).

    X32 meter blob structure for /meters/0 and /meters/1 (channels):
    - Index 0: Header (constant ~17920)
    - Index 1: Header (constant 0)
    - Index 2-17: Channels 1-16
    - Index 18: Header (constant ~28603)
    - Index 19-34: Channels 17-32
    - Index 35+: Aux inputs and other meters
    """
    result = {}

    try:
        # Number of int16 values
        num_values = len(data) // 2
        values = struct.unpack(f'>{num_values}h', data[:num_values * 2])

        if meter_type == METER_CHANNEL_PRE or meter_type == METER_CHANNEL_POST:
            # X32 meter blob structure (empirically determined from live data):
            # - Index 0: Header (constant ~17920)
            # - Index 1: Header (constant 0)
            # - Index 2-17: ch01-ch16
            # - Index 18: Header (constant ~28603)
            # - Index 19-34: ch17-ch32
            result['channels'] = {}

            # Channels 1-16 (indices 2-17)
            for i in range(16):
                if i + 2 < len(values):
                    ch_num = i + 1
                    result['channels'][f'ch{ch_num:02d}'] = values[i + 2]

            # Channels 17-32 (indices 19-34, skip header at 18)
            for i in range(16):
                if i + 19 < len(values):
                    ch_num = i + 17
                    result['channels'][f'ch{ch_num:02d}'] = values[i + 19]

            # Aux inputs (after index 35: 2 headers + 16ch + 1 header + 16ch = 35)
            result['aux'] = {}
            aux_start = 35
            for i in range(8):
                if aux_start + i < len(values):
                    result['aux'][f'aux{i + 1}'] = values[aux_start + i]

        elif meter_type == METER_BUS:
            # Bus meters - skip header at index 0
            result['buses'] = {}
            for i in range(min(16, len(values) - 1)):
                bus_num = i + 1
                result['buses'][f'bus{bus_num:02d}'] = values[i + 1]

            main_start = 17
            if len(values) > main_start:
                result['main'] = {
                    'L': values[main_start],
                    'R': values[main_start + 1] if len(values) > main_start + 1 else 0
                }

    except Exception as e:
        result['error'] = str(e)
        result['raw_length'] = len(data)

    return result


class MeterCapture:
    """Handles real-time meter capture via raw OSC UDP."""

    def __init__(self, mixer_ip: str, mixer_port: int = 10023):
        self.mixer_ip = mixer_ip
        self.mixer_port = mixer_port
        self.sock: Optional[socket.socket] = None
        self.running = False
        self.samples: List[Dict] = []

        # Activity tracking
        self.channel_peak_raw: Dict[int, int] = {}  # Track peak raw value seen per channel
        self.active_channels: set = set()  # Channels with meaningful signal

    def connect(self):
        """Create UDP socket for OSC communication."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.1)  # 100ms timeout for non-blocking reads
        self.sock.bind(('', 0))  # Bind to any available port
        print(f"Connected to {self.mixer_ip}:{self.mixer_port}", file=sys.stderr)

    def disconnect(self):
        """Close UDP socket."""
        if self.sock:
            self.sock.close()
            self.sock = None

    def send_osc(self, address: str, *args):
        """Send an OSC message."""
        if not self.sock:
            return

        # Build OSC message manually
        msg = self._build_osc_message(address, *args)
        try:
            self.sock.sendto(msg, (self.mixer_ip, self.mixer_port))
        except OSError as e:
            if e.errno == 64:  # Host is down
                raise ConnectionError(f"Cannot reach mixer at {self.mixer_ip}:{self.mixer_port}") from e
            raise

    def _build_osc_message(self, address: str, *args) -> bytes:
        """Build an OSC message from address and arguments."""
        # Pad address to 4-byte boundary
        address_bytes = address.encode('utf-8') + b'\x00'
        while len(address_bytes) % 4 != 0:
            address_bytes += b'\x00'

        # Build type tag
        type_tag = ','
        arg_data = b''

        for arg in args:
            if isinstance(arg, int):
                type_tag += 'i'
                arg_data += struct.pack('>i', arg)
            elif isinstance(arg, float):
                type_tag += 'f'
                arg_data += struct.pack('>f', arg)
            elif isinstance(arg, str):
                type_tag += 's'
                s_bytes = arg.encode('utf-8') + b'\x00'
                while len(s_bytes) % 4 != 0:
                    s_bytes += b'\x00'
                arg_data += s_bytes

        # Pad type tag
        type_tag_bytes = type_tag.encode('utf-8') + b'\x00'
        while len(type_tag_bytes) % 4 != 0:
            type_tag_bytes += b'\x00'

        return address_bytes + type_tag_bytes + arg_data

    def send_xremote(self):
        """Send keep-alive to maintain connection."""
        self.send_osc('/xremote')

    def subscribe_meters(self):
        """Subscribe to meter data streams."""
        # X-32 uses /batchsubscribe to subscribe to meter updates
        # Format: /batchsubscribe ,ssiiii [alias] [address] [start] [end] [interval]
        # Interval in frames (1 = every frame, higher = less frequent)
        self.send_osc('/batchsubscribe', '/meters/0', '/meters/0', 0, 0, 2)  # Channel pre-fader
        self.send_osc('/batchsubscribe', '/meters/1', '/meters/1', 0, 0, 2)  # Channel post-fader
        self.send_osc('/batchsubscribe', '/meters/2', '/meters/2', 0, 0, 2)  # Buses + mains

    def receive_data(self) -> Optional[tuple]:
        """
        Receive OSC data from mixer.

        Returns:
            Tuple of (address, data) or None if no data
        """
        if not self.sock:
            return None

        try:
            data, addr = self.sock.recvfrom(4096)
            return self._parse_osc_response(data)
        except socket.timeout:
            return None
        except Exception as e:
            print(f"Receive error: {e}", file=sys.stderr)
            return None

    def _parse_osc_response(self, data: bytes) -> Optional[tuple]:
        """Parse raw OSC response."""
        try:
            # Find end of address string
            addr_end = data.find(b'\x00')
            if addr_end == -1:
                return None

            address = data[:addr_end].decode('utf-8')

            # Skip to type tag (aligned to 4 bytes)
            type_tag_start = addr_end + 1
            while type_tag_start % 4 != 0:
                type_tag_start += 1

            # Find type tag
            type_tag_end = data.find(b'\x00', type_tag_start)
            if type_tag_end == -1:
                return (address, None)

            type_tag = data[type_tag_start:type_tag_end].decode('utf-8')

            # Skip to arguments (aligned to 4 bytes)
            args_start = type_tag_end + 1
            while args_start % 4 != 0:
                args_start += 1

            # For meter data, the argument is usually a blob
            if 'b' in type_tag:
                # Blob: first 4 bytes are length
                blob_len = struct.unpack('>i', data[args_start:args_start+4])[0]
                blob_data = data[args_start+4:args_start+4+blob_len]
                return (address, blob_data)
            else:
                return (address, data[args_start:])

        except Exception as e:
            return None

    def update_channel_activity(self, meter_data: Dict):
        """Track channel activity from meter readings."""
        if 'channels' not in meter_data:
            return

        for ch_key, raw_value in meter_data['channels'].items():
            # Extract channel number
            ch_num = int(ch_key.replace('ch', ''))

            # Use absolute value - audio oscillates positive AND negative
            abs_value = abs(raw_value)

            # Update peak tracking
            current_peak = self.channel_peak_raw.get(ch_num, 0)
            if abs_value > current_peak:
                self.channel_peak_raw[ch_num] = abs_value

            # Mark as active if above threshold
            if abs_value > INACTIVE_THRESHOLD_RAW:
                self.active_channels.add(ch_num)

    async def capture(self, duration: float) -> Dict:
        """
        Capture meter data for specified duration.

        - Tracks which channels have signal
        - Excludes inactive channels from output

        Args:
            duration: Capture duration in seconds

        Returns:
            Dictionary with all captured data (inactive channels excluded)
        """
        self.samples = []
        self.channel_peak_raw = {}
        self.active_channels = set()

        start_time = time.time()
        last_xremote = start_time
        last_meter_request = start_time
        sample_count = 0

        print(f"Capturing for {duration} seconds...", file=sys.stderr)

        while time.time() - start_time < duration:
            current_time = time.time()
            elapsed = current_time - start_time

            # Send keep-alive every 8 seconds
            if current_time - last_xremote > 8:
                self.send_xremote()
                last_xremote = current_time

            # Re-request meters every 100ms (keeps subscription alive)
            if current_time - last_meter_request > 0.1:
                self.subscribe_meters()
                last_meter_request = current_time

            # Receive and process data
            result = self.receive_data()
            if result:
                address, data = result
                if data and address.startswith('/meters'):
                    sample = {
                        'timestamp_ms': int((current_time - start_time) * 1000),
                        'address': address,
                    }

                    # Determine meter type from address (more reliable than data length)
                    num_values = len(data) // 2

                    if address in ['/meters/0', '/meters/1'] and num_values >= 70:  # Channel meters
                        sample['type'] = 'channels'
                        parsed = parse_meter_blob(data, METER_CHANNEL_PRE)
                        sample['data'] = parsed
                        # Update activity tracking
                        self.update_channel_activity(parsed)
                    elif address == '/meters/2' and num_values >= 34:  # Bus meters
                        sample['type'] = 'buses'
                        sample['data'] = parse_meter_blob(data, METER_BUS)
                    else:
                        sample['type'] = 'unknown'
                        sample['raw_values'] = num_values

                    self.samples.append(sample)
                    sample_count += 1

            # Progress update
            if sample_count > 0 and sample_count % 100 == 0:
                progress = (elapsed / duration) * 100
                print(f"Progress: {progress:.0f}% ({sample_count} samples, {len(self.active_channels)} active)", file=sys.stderr)

            await asyncio.sleep(0.001)

        # Final summary
        print(f"Capture complete: {sample_count} samples", file=sys.stderr)
        print(f"  Active channels: {sorted(self.active_channels)}", file=sys.stderr)

        return {
            'sample_count': sample_count,
            'duration_ms': int(duration * 1000),
            'active_channels': sorted(self.active_channels),
            'samples': self.samples
        }


async def capture_channel_settings(mixer) -> Dict:
    """Capture all channel settings using behringer-mixer library."""
    state = mixer.state()
    settings = {'channels': {}, 'buses': {}, 'dcas': {}, 'main': {}}

    # Channels 1-32
    for ch_num in range(1, 33):
        ch_addr = f"/ch/{ch_num:02d}"
        try:
            fader = get_state_value(state, ch_addr, "mix_fader", 0.0)
            fader_db = get_state_value(state, ch_addr, "mix_fader_db", None)
            ch_data = {
                'name': get_state_value(state, ch_addr, "config_name", ""),
                'fader': round(fader, 3),
                'fader_db': f"{fader_db} dB" if fader_db is not None else format_db(fader),
                'mute': get_state_value(state, ch_addr, "mix_on", True) == False,
                'pan': round(get_state_value(state, ch_addr, "mix_pan", 0.5) or 0.5, 3),
                'color': get_state_value(state, ch_addr, "config_color", 0),
            }

            # EQ settings (library doesn't load these by default)
            eq_on = get_state_value(state, ch_addr, "eq_on", False)
            eq_bands = []
            for band in range(1, 5):
                eq_bands.append({
                    'freq': round(get_state_value(state, ch_addr, f"eq_{band}_f", 0.5) or 0.5, 3),
                    'gain': round(get_state_value(state, ch_addr, f"eq_{band}_g", 0.5) or 0.5, 3),
                    'q': round(get_state_value(state, ch_addr, f"eq_{band}_q", 0.5) or 0.5, 3),
                    'type': get_state_value(state, ch_addr, f"eq_{band}_type", 0),
                })
            ch_data['eq'] = {'on': eq_on, 'bands': eq_bands}

            # Dynamics (library doesn't load these by default)
            ch_data['gate'] = {
                'on': get_state_value(state, ch_addr, "gate_on", False),
                'threshold': round(get_state_value(state, ch_addr, "gate_thr", 0.5) or 0.5, 3),
                'range': round(get_state_value(state, ch_addr, "gate_range", 0.5) or 0.5, 3),
                'attack': round(get_state_value(state, ch_addr, "gate_attack", 0.5) or 0.5, 3),
                'hold': round(get_state_value(state, ch_addr, "gate_hold", 0.5) or 0.5, 3),
                'release': round(get_state_value(state, ch_addr, "gate_release", 0.5) or 0.5, 3),
            }
            ch_data['compressor'] = {
                'on': get_state_value(state, ch_addr, "dyn_on", False),
                'threshold': round(get_state_value(state, ch_addr, "dyn_thr", 0.5) or 0.5, 3),
                'ratio': round(get_state_value(state, ch_addr, "dyn_ratio", 0.5) or 0.5, 3),
                'attack': round(get_state_value(state, ch_addr, "dyn_attack", 0.5) or 0.5, 3),
                'hold': round(get_state_value(state, ch_addr, "dyn_hold", 0.5) or 0.5, 3),
                'release': round(get_state_value(state, ch_addr, "dyn_release", 0.5) or 0.5, 3),
                'knee': round(get_state_value(state, ch_addr, "dyn_knee", 0.5) or 0.5, 3),
                'mix': round(get_state_value(state, ch_addr, "dyn_mix", 1.0) or 1.0, 3),
            }

            # Preamp (library doesn't load these by default)
            ch_data['preamp'] = {
                'gain': round(get_state_value(state, ch_addr, "preamp_trim", 0.5) or 0.5, 3),
                'phantom': get_state_value(state, ch_addr, "preamp_48v", False),
                'hpf_on': get_state_value(state, ch_addr, "preamp_hpon", False),
                'hpf_freq': round(get_state_value(state, ch_addr, "preamp_hpf", 0.0) or 0.0, 3),
            }

            settings['channels'][f'ch{ch_num:02d}'] = ch_data

        except Exception as e:
            print(f"Warning: Could not read {ch_addr}: {e}", file=sys.stderr)

    # Buses 1-16
    for bus_num in range(1, 17):
        bus_addr = f"/bus/{bus_num:02d}"
        try:
            fader = get_state_value(state, bus_addr, "mix_fader", 0.0)
            fader_db = get_state_value(state, bus_addr, "mix_fader_db", None)
            settings['buses'][f'bus{bus_num:02d}'] = {
                'name': get_state_value(state, bus_addr, "config_name", ""),
                'fader': round(fader, 3),
                'fader_db': f"{fader_db} dB" if fader_db is not None else format_db(fader),
                'mute': get_state_value(state, bus_addr, "mix_on", True) == False,
            }
        except:
            pass

    # Main
    try:
        fader = get_state_value(state, "/main/st", "mix_fader", 0.0)
        fader_db = get_state_value(state, "/main/st", "mix_fader_db", None)
        settings['main'] = {
            'fader': round(fader, 3),
            'fader_db': f"{fader_db} dB" if fader_db is not None else format_db(fader),
        }
    except:
        pass

    # DCAs - library uses /dca/{num}/mix_fader format
    for dca_num in range(1, 9):
        try:
            fader = state.get(f"/dca/{dca_num}/mix_fader", 0.0)
            fader_db = state.get(f"/dca/{dca_num}/mix_fader_db", None)
            settings['dcas'][f'dca{dca_num}'] = {
                'name': state.get(f"/dca/{dca_num}/config_name", f"DCA {dca_num}"),
                'fader': round(fader, 3),
                'fader_db': f"{fader_db} dB" if fader_db is not None else format_db(fader),
                'mute': state.get(f"/dca/{dca_num}/mix_on", True) == False,
            }
        except:
            pass

    return settings


async def main():
    parser = argparse.ArgumentParser(
        description="Capture real-time meter data from X-32",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python capture.py --duration 30
    python capture.py --duration 10 --output captures/soundcheck.json

For RTA frequency analysis of individual channels, use rta_listen.py instead.
        """
    )
    parser.add_argument(
        "--duration", "-d",
        type=float,
        default=30,
        help="Capture duration in seconds (default: 30)"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path (default: captures/YYYY-MM-DD_HHMMSS.json)"
    )
    parser.add_argument(
        "--skip-settings",
        action="store_true",
        help="Skip capturing channel settings (faster, meters only)"
    )

    args = parser.parse_args()

    # Load config
    config = load_config()

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_path = Path(__file__).parent.parent / "captures" / f"{timestamp}.json"

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Capture channel settings first (using behringer-mixer for reliability)
    settings = {}
    if not args.skip_settings:
        print("Capturing channel settings...", file=sys.stderr)
        try:
            mixer = await get_mixer(config)
            settings = await capture_channel_settings(mixer)
            await mixer.stop()
            print(f"Captured settings for {len(settings.get('channels', {}))} channels", file=sys.stderr)
        except Exception as e:
            print(f"Warning: Could not capture settings: {e}", file=sys.stderr)

    # Capture meter data
    print("Starting meter capture...", file=sys.stderr)
    capture = MeterCapture(config['mixer_ip'], config['mixer_port'])

    try:
        capture.connect()
        capture.send_xremote()
        capture.subscribe_meters()
        meter_data = await capture.capture(args.duration)
    except ConnectionError as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Make sure the mixer is powered on and reachable.", file=sys.stderr)
        print(json.dumps({'success': False, 'error': 'connection_failed'}))
        sys.exit(1)
    finally:
        capture.disconnect()

    # Filter to active channels only
    active_channels = set(meter_data.get('active_channels', []))

    if active_channels:
        # Filter settings to only active channels
        if settings.get('channels'):
            filtered_channels = {}
            for ch_key, ch_data in settings['channels'].items():
                ch_num = int(ch_key.replace('ch', ''))
                if ch_num in active_channels:
                    filtered_channels[ch_key] = ch_data
            settings['channels'] = filtered_channels
            print(f"Filtered settings to {len(filtered_channels)} active channels", file=sys.stderr)

        # Filter meter samples to only include active channel data
        filtered_samples = []
        for sample in meter_data.get('samples', []):
            if sample.get('type') == 'channels' and 'data' in sample:
                # Filter channel data within the sample
                if 'channels' in sample['data']:
                    filtered_ch = {}
                    for ch_key, ch_data in sample['data']['channels'].items():
                        ch_num = int(ch_key.replace('ch', ''))
                        if ch_num in active_channels:
                            filtered_ch[ch_key] = ch_data
                    sample['data']['channels'] = filtered_ch
            filtered_samples.append(sample)
        meter_data['samples'] = filtered_samples

    # Build final output
    output = {
        'metadata': {
            'capture_time': datetime.now().isoformat(),
            'duration_seconds': args.duration,
            'mixer_ip': config['mixer_ip'],
            'active_channels': sorted(active_channels),
            'inactive_threshold_raw': INACTIVE_THRESHOLD_RAW,
        },
        'settings': settings,
        'meters': meter_data,
    }

    # Write output
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nCapture saved to: {output_path}", file=sys.stderr)

    # Summary
    print(f"\nSummary:", file=sys.stderr)
    print(f"  Duration: {args.duration}s", file=sys.stderr)
    print(f"  Samples: {meter_data.get('sample_count', 0)}", file=sys.stderr)
    print(f"  Active channels: {len(active_channels)} of 32", file=sys.stderr)
    print(f"  Settings captured: {len(settings.get('channels', {}))} channels", file=sys.stderr)
    print(f"  File size: {output_path.stat().st_size / 1024:.1f} KB", file=sys.stderr)

    # Output path for scripting
    print(json.dumps({'success': True, 'path': str(output_path)}))


if __name__ == "__main__":
    asyncio.run(main())
