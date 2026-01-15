#!/usr/bin/env python3
"""
Capture real-time meter data and RTA from all channels simultaneously.

This script uses raw OSC to subscribe to meter data directly from the X-32,
capturing truly simultaneous readings across all channels in the same
musical moment.

Usage:
    python capture.py --duration 30
    python capture.py --duration 30 --rta-sweep
    python capture.py --duration 10 --output captures/soundcheck.json

Meter data is pushed by the mixer at ~50Hz, giving synchronized snapshots
of all channel levels in each packet.
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
METER_MATRIX = 3        # Matrix 1-6 + Mono (18 values)
METER_RTA = 4           # 100 frequency bins (20Hz - 20kHz)

# Activity detection thresholds
INACTIVE_THRESHOLD_DB = -70  # Below this = completely inactive (ignore channel)
WEAK_SIGNAL_THRESHOLD_DB = -40  # Below this during RTA = retry later
RTA_MEANINGFUL_THRESHOLD_DB = -60  # RTA bins below this aren't meaningful

# Drum channels get special treatment (transient sources need more capture time)
DRUM_CHANNELS = {22, 23, 24, 25, 26, 27, 28}  # Floor tom, mid tom, mid-high tom, snare, kick, OH L, OH R
DRUM_RTA_DWELL_SECONDS = 3.0  # Give drums 3 seconds to catch a hit
DEFAULT_RTA_DWELL_SECONDS = 0.5  # Other sources get 500ms

# RTA frequency bins (100 bins, roughly 1/3 octave spacing)
RTA_FREQUENCIES = [
    20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160,
    200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600,
    2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000,
    20000
]  # Approximate center frequencies for display (actual bins are finer)


def meter_int_to_db(value: int) -> float:
    """
    Convert X-32 meter int16 value to dB.

    X-32 meters use int16 values where:
    - 0 = -inf (silence)
    - ~16384 = ~0 dB
    - Higher values = positive dB (clipping)

    The exact mapping follows a log scale.
    """
    if value <= 0:
        return float('-inf')

    # X-32 uses a specific log mapping
    # Values are roughly: 10^((value/16384 - 1) * 4) for the main range
    # This is an approximation - exact mapping may need calibration
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
    """
    # Skip first 4 bytes (blob length header if present)
    # X-32 meter blobs are arrays of int16

    result = {}

    try:
        # Number of int16 values
        num_values = len(data) // 2
        values = struct.unpack(f'>{num_values}h', data[:num_values * 2])

        if meter_type == METER_CHANNEL_PRE or meter_type == METER_CHANNEL_POST:
            # Channels 1-32, then Aux 1-8
            result['channels'] = {}
            for i in range(min(32, len(values))):
                ch_num = i + 1
                result['channels'][f'ch{ch_num:02d}'] = {
                    'raw': values[i],
                    'db': round(meter_int_to_db(values[i]), 1)
                }

            # Aux inputs (if present)
            result['aux'] = {}
            for i in range(32, min(40, len(values))):
                aux_num = i - 31
                result['aux'][f'aux{aux_num}'] = {
                    'raw': values[i],
                    'db': round(meter_int_to_db(values[i]), 1)
                }

        elif meter_type == METER_BUS:
            # Bus 1-16, Main L, Main R, Mono
            result['buses'] = {}
            for i in range(min(16, len(values))):
                bus_num = i + 1
                result['buses'][f'bus{bus_num:02d}'] = {
                    'raw': values[i],
                    'db': round(meter_int_to_db(values[i]), 1)
                }

            if len(values) > 16:
                result['main'] = {
                    'L': {'raw': values[16], 'db': round(meter_int_to_db(values[16]), 1)},
                    'R': {'raw': values[17] if len(values) > 17 else 0,
                          'db': round(meter_int_to_db(values[17] if len(values) > 17 else 0), 1)}
                }

        elif meter_type == METER_RTA:
            # 100 frequency bins
            result['rta'] = []
            for i in range(min(100, len(values))):
                result['rta'].append({
                    'bin': i,
                    'raw': values[i],
                    'db': round(meter_int_to_db(values[i]), 1)
                })

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
        self.rta_source: int = 0  # Current RTA source channel

        # Activity tracking
        self.channel_peak_db: Dict[int, float] = {}  # Track peak level seen per channel
        self.active_channels: set = set()  # Channels with meaningful signal
        self.rta_captures: Dict[int, Dict] = {}  # Best RTA capture per channel
        self.rta_retry_queue: List[int] = []  # Channels to retry for RTA

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
        self.sock.sendto(msg, (self.mixer_ip, self.mixer_port))

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

    def subscribe_rta(self, source_channel: int = 0):
        """
        Subscribe to RTA data.

        Args:
            source_channel: Channel to analyze (0 = main LR)
        """
        # Set RTA source
        self.send_osc('/-prefs/rta/source', source_channel)
        self.rta_source = source_channel
        # Subscribe to RTA meters
        self.send_osc('/batchsubscribe', '/meters/4', '/meters/4', 0, 0, 2)

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

        for ch_key, ch_data in meter_data['channels'].items():
            # Extract channel number
            ch_num = int(ch_key.replace('ch', ''))
            db_level = ch_data.get('db', float('-inf'))

            # Skip -inf
            if db_level == float('-inf'):
                continue

            # Update peak tracking
            current_peak = self.channel_peak_db.get(ch_num, float('-inf'))
            if db_level > current_peak:
                self.channel_peak_db[ch_num] = db_level

            # Mark as active if above threshold
            if db_level > INACTIVE_THRESHOLD_DB:
                self.active_channels.add(ch_num)

    def evaluate_rta_capture(self, rta_data: Dict, channel: int, timestamp_ms: int) -> bool:
        """
        Evaluate if RTA capture is good enough or needs retry.

        Returns True if capture is acceptable, False if should retry.
        """
        if 'rta' not in rta_data:
            return False

        # Calculate peak RTA level
        peak_rta_db = max(
            (bin_data.get('db', float('-inf')) for bin_data in rta_data['rta']),
            default=float('-inf')
        )

        # Check if we have an existing capture for this channel
        existing = self.rta_captures.get(channel)

        # Store if better than existing or no existing
        if existing is None or peak_rta_db > existing.get('peak_db', float('-inf')):
            self.rta_captures[channel] = {
                'timestamp_ms': timestamp_ms,
                'peak_db': peak_rta_db,
                'data': rta_data
            }

        # Return whether this is a good capture
        return peak_rta_db > WEAK_SIGNAL_THRESHOLD_DB

    async def capture(self, duration: float, rta_sweep: bool = False) -> Dict:
        """
        Capture meter data for specified duration.

        Smart capture mode:
        - Tracks which channels have signal
        - Only captures RTA for active channels
        - Retries weak RTA captures
        - Excludes inactive channels from output

        Args:
            duration: Capture duration in seconds
            rta_sweep: If True, cycle RTA through active channels only

        Returns:
            Dictionary with all captured data (inactive channels excluded)
        """
        self.samples = []
        self.channel_peak_db = {}
        self.active_channels = set()
        self.rta_captures = {}
        self.rta_retry_queue = []

        start_time = time.time()
        last_xremote = start_time
        last_meter_request = start_time
        last_rta_switch = start_time
        current_rta_dwell = DEFAULT_RTA_DWELL_SECONDS  # Adjusted per channel

        # RTA sweep state
        rta_sweep_list: List[int] = []  # Channels to sweep (populated after initial scan)
        rta_sweep_index = 0
        initial_scan_duration = min(3.0, duration * 0.2)  # First 3 sec or 20% to identify active channels
        initial_scan_complete = False
        retry_phase = False

        sample_count = 0

        print(f"Capturing for {duration} seconds...", file=sys.stderr)
        if rta_sweep:
            print(f"  Initial scan: {initial_scan_duration:.1f}s to identify active channels", file=sys.stderr)

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
                if not rta_sweep or initial_scan_complete:
                    self.send_osc('/batchsubscribe', '/meters/4', '/meters/4', 0, 0, 2)  # RTA
                last_meter_request = current_time

            # Initial scan phase - just collect meter data to find active channels
            if rta_sweep and not initial_scan_complete:
                if elapsed >= initial_scan_duration:
                    initial_scan_complete = True
                    # Sort channels: non-drums first, drums last (drums need more time)
                    non_drums = sorted([ch for ch in self.active_channels if ch not in DRUM_CHANNELS])
                    drums = sorted([ch for ch in self.active_channels if ch in DRUM_CHANNELS])
                    rta_sweep_list = non_drums + drums

                    if rta_sweep_list:
                        active_drums = [ch for ch in drums]
                        print(f"  Found {len(rta_sweep_list)} active channels: {rta_sweep_list}", file=sys.stderr)
                        if active_drums:
                            print(f"  Drums ({active_drums}) will be captured last with {DRUM_RTA_DWELL_SECONDS}s dwell time", file=sys.stderr)
                        # Start RTA on first active channel
                        first_ch = rta_sweep_list[0]
                        current_rta_dwell = DRUM_RTA_DWELL_SECONDS if first_ch in DRUM_CHANNELS else DEFAULT_RTA_DWELL_SECONDS
                        self.subscribe_rta(first_ch)
                    else:
                        print(f"  No active channels found during initial scan", file=sys.stderr)

            # RTA sweep mode - cycle through active channels only
            elif rta_sweep and rta_sweep_list and current_time - last_rta_switch > current_rta_dwell:
                # Move to next channel
                rta_sweep_index = (rta_sweep_index + 1) % len(rta_sweep_list)

                # Check if we've completed a full sweep and have retries
                if rta_sweep_index == 0 and self.rta_retry_queue and not retry_phase:
                    retry_phase = True
                    # Sort retries: non-drums first, drums last
                    non_drums = sorted([ch for ch in self.rta_retry_queue if ch not in DRUM_CHANNELS])
                    drums = sorted([ch for ch in self.rta_retry_queue if ch in DRUM_CHANNELS])
                    rta_sweep_list = non_drums + drums
                    self.rta_retry_queue = []
                    print(f"  Retrying {len(rta_sweep_list)} channels with weak signal", file=sys.stderr)

                if rta_sweep_index < len(rta_sweep_list):
                    next_channel = rta_sweep_list[rta_sweep_index]
                    # Set dwell time based on whether this is a drum channel
                    current_rta_dwell = DRUM_RTA_DWELL_SECONDS if next_channel in DRUM_CHANNELS else DEFAULT_RTA_DWELL_SECONDS
                    self.subscribe_rta(next_channel)
                    last_rta_switch = current_time

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

                    if address == '/meters/4':  # RTA
                        sample['type'] = 'rta'
                        sample['rta_source'] = self.rta_source
                        parsed = parse_meter_blob(data, METER_RTA)
                        sample['data'] = parsed
                    elif address in ['/meters/0', '/meters/1'] and num_values >= 70:  # Channel meters
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

                    # Evaluate RTA quality for sweep mode (after RTA sample)
                    if sample.get('type') == 'rta' and rta_sweep and self.rta_source > 0:
                        is_good = self.evaluate_rta_capture(
                            sample['data'], self.rta_source, sample['timestamp_ms']
                        )
                        if not is_good and not retry_phase:
                            # Queue for retry if not already queued
                            if self.rta_source not in self.rta_retry_queue:
                                self.rta_retry_queue.append(self.rta_source)

                    self.samples.append(sample)
                    sample_count += 1

            # Progress update
            if sample_count > 0 and sample_count % 100 == 0:
                progress = (elapsed / duration) * 100
                active_str = f", {len(self.active_channels)} active" if rta_sweep else ""
                print(f"Progress: {progress:.0f}% ({sample_count} samples{active_str})", file=sys.stderr)

            await asyncio.sleep(0.001)

        # Final summary
        print(f"Capture complete: {sample_count} samples", file=sys.stderr)
        print(f"  Active channels: {sorted(self.active_channels)}", file=sys.stderr)
        if rta_sweep:
            print(f"  RTA captured for: {sorted(self.rta_captures.keys())}", file=sys.stderr)

        return {
            'sample_count': sample_count,
            'duration_ms': int(duration * 1000),
            'active_channels': sorted(self.active_channels),
            'rta_captures': {
                ch: {'peak_db': data['peak_db'], 'timestamp_ms': data['timestamp_ms']}
                for ch, data in self.rta_captures.items()
            },
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


async def recapture_channels(config: Dict, channels: List[int], duration: float) -> Dict:
    """
    Recapture RTA data for specific channels only.

    Used when initial capture missed channels (e.g., drummer wasn't hitting toms).
    """
    print(f"Recapturing RTA for channels: {channels}", file=sys.stderr)
    print(f"Duration: {duration}s per channel", file=sys.stderr)

    capture = MeterCapture(config['mixer_ip'], config['mixer_port'])
    rta_results = {}

    try:
        capture.connect()
        capture.send_xremote()

        for ch_num in channels:
            # Use drum timing for all recaptures (we want good data)
            dwell_time = max(DRUM_RTA_DWELL_SECONDS, duration)

            print(f"  Capturing channel {ch_num} for {dwell_time}s...", file=sys.stderr)
            capture.subscribe_rta(ch_num)

            start_time = time.time()
            best_capture = None
            best_peak = float('-inf')

            while time.time() - start_time < dwell_time:
                # Keep-alive
                if time.time() - start_time > 8:
                    capture.send_xremote()

                # Request meters
                capture.send_osc('/batchsubscribe', '/meters/4', '/meters/4', 0, 0, 2)

                result = capture.receive_data()
                if result:
                    address, data = result
                    if data and len(data) // 2 == 100:  # RTA data
                        parsed = parse_meter_blob(data, METER_RTA)
                        if 'rta' in parsed:
                            peak = max(
                                (b.get('db', float('-inf')) for b in parsed['rta']),
                                default=float('-inf')
                            )
                            if peak > best_peak:
                                best_peak = peak
                                best_capture = {
                                    'timestamp_ms': int((time.time() - start_time) * 1000),
                                    'peak_db': peak,
                                    'data': parsed
                                }

                await asyncio.sleep(0.01)

            if best_capture:
                rta_results[ch_num] = best_capture
                print(f"    Got capture with peak {best_peak:.1f} dB", file=sys.stderr)
            else:
                print(f"    No RTA data received for channel {ch_num}", file=sys.stderr)

    finally:
        capture.disconnect()

    return rta_results


def merge_recapture(original_path: Path, recapture_data: Dict, channels: List[int]) -> None:
    """Merge recaptured RTA data into existing capture file."""

    # Load original
    with open(original_path, 'r') as f:
        original = json.load(f)

    # Add recapture metadata
    if 'recaptures' not in original['metadata']:
        original['metadata']['recaptures'] = []

    original['metadata']['recaptures'].append({
        'timestamp': datetime.now().isoformat(),
        'channels': channels,
        'reason': 'manual_recapture'
    })

    # Update active channels if needed
    active = set(original['metadata'].get('active_channels', []))
    active.update(channels)
    original['metadata']['active_channels'] = sorted(active)

    # Merge RTA captures into meters section
    if 'rta_captures' not in original['meters']:
        original['meters']['rta_captures'] = {}

    for ch_num, rta_data in recapture_data.items():
        ch_key = str(ch_num)
        original['meters']['rta_captures'][ch_key] = {
            'peak_db': rta_data['peak_db'],
            'timestamp_ms': rta_data['timestamp_ms'],
            'recaptured': True
        }

        # Also add as a sample
        original['meters']['samples'].append({
            'timestamp_ms': rta_data['timestamp_ms'],
            'type': 'rta',
            'rta_source': ch_num,
            'recaptured': True,
            'data': rta_data['data']
        })

    # Write back
    with open(original_path, 'w') as f:
        json.dump(original, f, indent=2)

    print(f"Merged recapture data into {original_path}", file=sys.stderr)


async def main():
    parser = argparse.ArgumentParser(
        description="Capture real-time meter and RTA data from X-32",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python capture.py --duration 30
    python capture.py --duration 30 --rta-sweep
    python capture.py --duration 10 --output captures/soundcheck.json

    # Recapture missed channels and merge into existing file:
    python capture.py --recapture captures/worship.json --channels 22,23,24

The RTA can only analyze one source at a time. Use --rta-sweep to cycle
through channels (loses perfect simultaneity but captures frequency data
for each channel).

RECAPTURE MODE:
If you missed channels (e.g., toms weren't being played), use --recapture
to capture just those channels and merge into the original file. Have the
musician play while capturing.
        """
    )
    parser.add_argument(
        "--duration", "-d",
        type=float,
        default=30,
        help="Capture duration in seconds (default: 30, or per-channel for recapture)"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path (default: captures/YYYY-MM-DD_HHMMSS.json)"
    )
    parser.add_argument(
        "--rta-sweep",
        action="store_true",
        help="Cycle RTA through all channels (captures frequency data per channel)"
    )
    parser.add_argument(
        "--rta-source",
        type=int,
        default=0,
        help="Fixed RTA source channel (0=main LR, 1-32=channel, ignored if --rta-sweep)"
    )
    parser.add_argument(
        "--skip-settings",
        action="store_true",
        help="Skip capturing channel settings (faster, meters only)"
    )
    parser.add_argument(
        "--recapture",
        type=str,
        metavar="FILE",
        help="Recapture mode: path to existing capture file to merge into"
    )
    parser.add_argument(
        "--channels", "-c",
        type=str,
        help="Channels to recapture (e.g., '22,23,24' for toms). Required with --recapture"
    )

    args = parser.parse_args()

    # Load config
    config = load_config()

    # Handle recapture mode
    if args.recapture:
        if not args.channels:
            print("Error: --channels required with --recapture", file=sys.stderr)
            print("Example: --recapture captures/file.json --channels 22,23,24", file=sys.stderr)
            sys.exit(1)

        recapture_path = Path(args.recapture)
        if not recapture_path.exists():
            print(f"Error: Capture file not found: {recapture_path}", file=sys.stderr)
            sys.exit(1)

        # Parse channel list
        try:
            channels = [int(ch.strip()) for ch in args.channels.split(',')]
        except ValueError:
            print(f"Error: Invalid channel list: {args.channels}", file=sys.stderr)
            print("Expected format: 22,23,24", file=sys.stderr)
            sys.exit(1)

        # Do recapture
        recapture_data = await recapture_channels(config, channels, args.duration)

        if recapture_data:
            merge_recapture(recapture_path, recapture_data, channels)
            print(f"\nRecapture complete!", file=sys.stderr)
            print(f"  Channels: {list(recapture_data.keys())}", file=sys.stderr)
            print(f"  Merged into: {recapture_path}", file=sys.stderr)
            print(json.dumps({'success': True, 'path': str(recapture_path), 'channels': channels}))
        else:
            print("No data captured", file=sys.stderr)
            print(json.dumps({'success': False, 'error': 'no_data'}))

        return  # Exit after recapture

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

        # Set initial RTA source
        if not args.rta_sweep:
            capture.subscribe_rta(args.rta_source)

        # Subscribe to meters
        capture.subscribe_meters()

        # Capture data
        meter_data = await capture.capture(args.duration, args.rta_sweep)

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
            'rta_sweep': args.rta_sweep,
            'rta_source': args.rta_source if not args.rta_sweep else 'sweep',
            'active_channels': sorted(active_channels),
            'inactive_threshold_db': INACTIVE_THRESHOLD_DB,
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
