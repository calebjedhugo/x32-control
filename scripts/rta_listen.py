#!/usr/bin/env python3
"""
On-demand RTA frequency analysis for a single channel.

Listens to RTA data for a specified channel and provides aggregated
frequency analysis useful for EQ decisions. Also captures peak meter
level for gain staging.

Usage:
    python rta_listen.py --channel 26                    # 15 seconds (default)
    python rta_listen.py --channel 26 --duration 30      # Custom duration
    python rta_listen.py --channel 26 --until-confident  # Auto-stop when stable
    python rta_listen.py --channel 26 --update-session   # Splice into session capture
"""

import argparse
import asyncio
import glob as globlib
import json
import math
import socket
import struct
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from common import load_config, get_mixer, get_state_value

# X-32 meter index for RTA
METER_RTA = 4  # 100 frequency bins (20Hz - 20kHz)

# Frequency band definitions (bin index ranges)
# X-32 RTA has 100 bins spanning ~20Hz to 20kHz (logarithmic spacing)
# Bin n ≈ 20 * 10^(3n/100) Hz
FREQUENCY_BANDS = {
    'sub':        {'range': '20-60Hz',   'bins': (0, 16),   'desc': 'Rumble, kick fundamental'},
    'bass':       {'range': '60-120Hz',  'bins': (16, 26),  'desc': 'Punch, bass fundamental'},
    'low':        {'range': '120-250Hz', 'bins': (26, 37),  'desc': 'Warmth, fullness'},
    'low_mid':    {'range': '250-500Hz', 'bins': (37, 47),  'desc': 'Mud, boxiness'},
    'mid':        {'range': '500-1kHz',  'bins': (47, 57),  'desc': 'Honk, nasal, body'},
    'upper_mid':  {'range': '1-2kHz',    'bins': (57, 67),  'desc': 'Presence, attack'},
    'presence':   {'range': '2-4kHz',    'bins': (67, 77),  'desc': 'Bite, clarity, intelligibility'},
    'brilliance': {'range': '4-8kHz',    'bins': (77, 87),  'desc': 'Air, sibilance, shimmer'},
    'high':       {'range': '8-20kHz',   'bins': (87, 100), 'desc': 'Sparkle, extreme air'},
}

# Variance thresholds for --until-confident mode
VARIANCE_STABLE_THRESHOLD = 0.15  # Coefficient of variation below this = stable
MIN_SAMPLES_FOR_CONFIDENCE = 50   # Need at least this many samples
MIN_DURATION_SECONDS = 5          # Always capture at least this long

# Signal thresholds
MIN_SIGNAL_THRESHOLD = 500  # Raw RTA value below this = no meaningful signal


def parse_rta_blob(data: bytes) -> Optional[List[int]]:
    """Parse RTA meter blob from X-32."""
    try:
        num_values = len(data) // 2
        if num_values < 100:
            return None
        values = struct.unpack(f'>{num_values}h', data[:num_values * 2])
        # Skip header at index 0, return 100 RTA bins
        return list(values[1:101])
    except Exception:
        return None


class RTAListener:
    """Handles RTA capture for a single channel via raw OSC UDP."""

    def __init__(self, mixer_ip: str, mixer_port: int = 10023, channel: int = 1):
        self.mixer_ip = mixer_ip
        self.mixer_port = mixer_port
        self.channel = channel
        self.sock: Optional[socket.socket] = None
        self.samples: List[List[int]] = []  # List of 100-bin arrays
        self.peak_meter: int = 0  # Peak meter level for this channel

    def connect(self):
        """Create UDP socket for OSC communication."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.1)
        self.sock.bind(('', 0))

    def disconnect(self):
        """Close UDP socket."""
        if self.sock:
            self.sock.close()
            self.sock = None

    def send_osc(self, address: str, *args):
        """Send an OSC message."""
        if not self.sock:
            return

        msg = self._build_osc_message(address, *args)
        try:
            self.sock.sendto(msg, (self.mixer_ip, self.mixer_port))
        except OSError as e:
            if e.errno == 64:  # Host is down
                raise ConnectionError(f"Cannot reach mixer at {self.mixer_ip}:{self.mixer_port}") from e
            raise

    def _build_osc_message(self, address: str, *args) -> bytes:
        """Build an OSC message from address and arguments."""
        address_bytes = address.encode('utf-8') + b'\x00'
        while len(address_bytes) % 4 != 0:
            address_bytes += b'\x00'

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

        type_tag_bytes = type_tag.encode('utf-8') + b'\x00'
        while len(type_tag_bytes) % 4 != 0:
            type_tag_bytes += b'\x00'

        return address_bytes + type_tag_bytes + arg_data

    def subscribe_rta(self, channel: int):
        """Subscribe to RTA data for a specific channel."""
        # Set RTA source (0 = main LR, 1-32 = channel)
        self.send_osc('/-prefs/rta/source', channel)
        # Subscribe to RTA meters
        self.send_osc('/batchsubscribe', '/meters/4', '/meters/4', 0, 0, 2)
        # Also subscribe to channel meters for peak level
        self.send_osc('/batchsubscribe', '/meters/0', '/meters/0', 0, 0, 2)

    def _parse_channel_meter(self, data: bytes) -> Optional[int]:
        """Parse channel meter blob and return level for our channel."""
        try:
            num_values = len(data) // 2
            if num_values < 35:
                return None
            values = struct.unpack(f'>{num_values}h', data[:num_values * 2])

            # Channel 1-16 at indices 2-17, Channel 17-32 at indices 19-34
            if self.channel <= 16:
                idx = self.channel + 1  # +1 for header, channel 1 at index 2
            else:
                idx = self.channel + 2  # +2 for two headers, channel 17 at index 19

            if idx < len(values):
                return abs(values[idx])
            return None
        except Exception:
            return None

    def receive_data(self) -> tuple:
        """
        Receive data from mixer.

        Returns:
            Tuple of (rta_data, meter_level) - either can be None
        """
        if not self.sock:
            return (None, None)

        try:
            data, addr = self.sock.recvfrom(4096)
            return self._parse_response(data)
        except socket.timeout:
            return (None, None)
        except Exception:
            return (None, None)

    def _parse_response(self, data: bytes) -> tuple:
        """Parse OSC response, extracting RTA or meter data."""
        try:
            addr_end = data.find(b'\x00')
            if addr_end == -1:
                return (None, None)

            address = data[:addr_end].decode('utf-8')

            # Find type tag
            type_tag_start = addr_end + 1
            while type_tag_start % 4 != 0:
                type_tag_start += 1

            type_tag_end = data.find(b'\x00', type_tag_start)
            if type_tag_end == -1:
                return (None, None)

            type_tag = data[type_tag_start:type_tag_end].decode('utf-8')

            # Skip to arguments
            args_start = type_tag_end + 1
            while args_start % 4 != 0:
                args_start += 1

            # Extract blob
            if 'b' in type_tag:
                blob_len = struct.unpack('>i', data[args_start:args_start+4])[0]
                blob_data = data[args_start+4:args_start+4+blob_len]

                if address == '/meters/4':
                    # RTA data
                    return (parse_rta_blob(blob_data), None)
                elif address == '/meters/0':
                    # Channel meter data
                    meter_level = self._parse_channel_meter(blob_data)
                    return (None, meter_level)

            return (None, None)
        except Exception:
            return (None, None)

    def calculate_variance_stability(self) -> float:
        """
        Calculate how stable the RTA readings are.

        Returns coefficient of variation (lower = more stable).
        """
        if len(self.samples) < 10:
            return float('inf')

        # Use last 50 samples or all if fewer
        recent = self.samples[-50:]

        # Calculate variance across all bins
        total_cv = 0
        valid_bins = 0

        for bin_idx in range(100):
            values = [s[bin_idx] for s in recent if s[bin_idx] > MIN_SIGNAL_THRESHOLD]
            if len(values) < 5:
                continue

            mean = sum(values) / len(values)
            if mean < MIN_SIGNAL_THRESHOLD:
                continue

            variance = sum((v - mean) ** 2 for v in values) / len(values)
            std_dev = math.sqrt(variance)
            cv = std_dev / mean if mean > 0 else 0
            total_cv += cv
            valid_bins += 1

        return total_cv / valid_bins if valid_bins > 0 else float('inf')

    async def listen(self, duration: float, until_confident: bool = False) -> Dict:
        """
        Listen to RTA and meter data for specified duration.

        Args:
            duration: Maximum capture duration in seconds
            until_confident: If True, stop early when data stabilizes

        Returns:
            Dictionary with aggregated frequency band analysis and peak level
        """
        self.samples = []
        self.peak_meter = 0
        start_time = time.time()
        last_xremote = start_time
        last_subscribe = start_time

        print(f"Listening for RTA data...", file=sys.stderr)
        if until_confident:
            print(f"  Will stop when data stabilizes (max {duration}s)", file=sys.stderr)

        while time.time() - start_time < duration:
            current_time = time.time()
            elapsed = current_time - start_time

            # Keep-alive every 8 seconds
            if current_time - last_xremote > 8:
                self.send_osc('/xremote')
                last_xremote = current_time

            # Re-subscribe every 100ms
            if current_time - last_subscribe > 0.1:
                self.send_osc('/batchsubscribe', '/meters/4', '/meters/4', 0, 0, 2)
                self.send_osc('/batchsubscribe', '/meters/0', '/meters/0', 0, 0, 2)
                last_subscribe = current_time

            # Receive data (RTA and/or meter)
            rta_data, meter_level = self.receive_data()
            if rta_data:
                self.samples.append(rta_data)
            if meter_level is not None and meter_level > self.peak_meter:
                self.peak_meter = meter_level

            # Check for confidence (after minimum time)
            if until_confident and elapsed >= MIN_DURATION_SECONDS:
                if len(self.samples) >= MIN_SAMPLES_FOR_CONFIDENCE:
                    stability = self.calculate_variance_stability()
                    if stability < VARIANCE_STABLE_THRESHOLD:
                        print(f"  Data stabilized after {elapsed:.1f}s ({len(self.samples)} samples)", file=sys.stderr)
                        break

            # Progress update
            if len(self.samples) > 0 and len(self.samples) % 50 == 0:
                print(f"  {len(self.samples)} samples collected...", file=sys.stderr)

            await asyncio.sleep(0.001)

        actual_duration = time.time() - start_time
        print(f"Capture complete: {len(self.samples)} samples in {actual_duration:.1f}s", file=sys.stderr)
        print(f"  Peak meter level: {self.peak_meter}", file=sys.stderr)

        return self.analyze()

    def analyze(self) -> Dict:
        """Analyze collected RTA samples and return band-aggregated results."""
        if not self.samples:
            return {'error': 'No RTA data collected'}

        result = {
            'timestamp': datetime.now().isoformat(),
            'samples_collected': len(self.samples),
            'peak_meter': self.peak_meter,
            'bands': {},
        }

        # Calculate per-band statistics
        for band_name, band_info in FREQUENCY_BANDS.items():
            start_bin, end_bin = band_info['bins']

            # Collect all values for this band across all samples
            all_values = []
            for sample in self.samples:
                band_values = [abs(sample[i]) for i in range(start_bin, min(end_bin, len(sample)))]
                all_values.extend(band_values)

            if not all_values:
                result['bands'][band_name] = {'avg': 0, 'peak': 0, 'variance': 'none'}
                continue

            # Calculate statistics
            avg = sum(all_values) / len(all_values)
            peak = max(all_values)

            # Calculate variance classification
            if avg < MIN_SIGNAL_THRESHOLD:
                variance_class = 'none'
            else:
                variance = sum((v - avg) ** 2 for v in all_values) / len(all_values)
                std_dev = math.sqrt(variance)
                cv = std_dev / avg if avg > 0 else 0

                if cv > 0.8:
                    variance_class = 'high'  # Very transient (drums)
                elif cv > 0.4:
                    variance_class = 'medium'
                else:
                    variance_class = 'low'  # Sustained (vocals, keys)

            result['bands'][band_name] = {
                'avg': int(avg),
                'peak': int(peak),
                'variance': variance_class,
            }

        # Add interpretation
        result['interpretation'] = self._interpret(result['bands'])

        return result

    def _interpret(self, bands: Dict) -> Dict:
        """Generate human-readable interpretation of frequency analysis."""
        interpretation = {}

        # Find dominant band
        max_avg = 0
        dominant = None
        for band_name, stats in bands.items():
            if stats['avg'] > max_avg:
                max_avg = stats['avg']
                dominant = band_name

        interpretation['dominant_band'] = dominant or 'none'

        # Determine energy balance (low = sub+bass+low, high = brilliance+high)
        low_energy = (bands.get('sub', {}).get('avg', 0) +
                     bands.get('bass', {}).get('avg', 0) +
                     bands.get('low', {}).get('avg', 0))
        high_energy = (bands.get('brilliance', {}).get('avg', 0) +
                      bands.get('high', {}).get('avg', 0))

        if low_energy > high_energy * 2:
            interpretation['energy_balance'] = 'bottom-heavy'
        elif high_energy > low_energy * 2:
            interpretation['energy_balance'] = 'top-heavy'
        else:
            interpretation['energy_balance'] = 'balanced'

        # Determine transient character based on low-end variance
        sub_var = bands.get('sub', {}).get('variance', 'none')
        bass_var = bands.get('bass', {}).get('variance', 'none')

        if sub_var == 'high' or bass_var == 'high':
            interpretation['transient_character'] = 'punchy (high variance in low end)'
        elif sub_var == 'low' and bass_var == 'low':
            interpretation['transient_character'] = 'sustained (steady low end)'
        else:
            interpretation['transient_character'] = 'moderate'

        return interpretation


async def get_channel_name(config: Dict, channel: int) -> str:
    """Get the channel name from the mixer."""
    try:
        mixer = await get_mixer(config)
        state = mixer.state()
        name = get_state_value(state, f"/ch/{channel:02d}", "config_name", "")
        await mixer.stop()
        return name or f"Channel {channel}"
    except Exception:
        return f"Channel {channel}"


def find_latest_session_capture() -> Optional[Path]:
    """Find the most recent session capture file."""
    captures_dir = Path(__file__).parent.parent / "captures"
    if not captures_dir.exists():
        return None

    # Look for session_*.json files
    session_files = list(captures_dir.glob("session_*.json"))
    if not session_files:
        return None

    # Return most recent by modification time
    return max(session_files, key=lambda f: f.stat().st_mtime)


def get_capture_age_hours(capture_path: Path) -> float:
    """Get the age of a capture file in hours."""
    mtime = capture_path.stat().st_mtime
    age_seconds = time.time() - mtime
    return age_seconds / 3600


def splice_rta_into_session(capture_path: Path, channel: int, rta_result: Dict) -> bool:
    """
    Splice RTA results into an existing session capture file.

    Updates the channel's rta_analysis field with new data.
    """
    try:
        with open(capture_path, 'r') as f:
            session_data = json.load(f)

        # Find the channel in the session data
        channels = session_data.get('channels', {})
        channel_key = f"ch{channel:02d}"

        if channel_key not in channels:
            print(f"Warning: Channel {channel} not found in session capture", file=sys.stderr)
            return False

        # Add RTA analysis to the channel
        channels[channel_key]['rta_analysis'] = {
            'timestamp': rta_result['timestamp'],
            'samples_collected': rta_result['samples_collected'],
            'peak_meter': rta_result['peak_meter'],
            'bands': rta_result['bands'],
            'interpretation': rta_result['interpretation'],
        }

        # Update the session's last_updated timestamp
        session_data['rta_last_updated'] = datetime.now().isoformat()

        # Write back
        with open(capture_path, 'w') as f:
            json.dump(session_data, f, indent=2)

        return True
    except Exception as e:
        print(f"Error splicing RTA data: {e}", file=sys.stderr)
        return False


async def main():
    parser = argparse.ArgumentParser(
        description="On-demand RTA frequency analysis for a single channel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python rta_listen.py --channel 26                    # Kick drum, 15s
    python rta_listen.py --channel 1 --duration 30       # Vocal, 30s
    python rta_listen.py --channel 26 --until-confident  # Auto-stop when stable

Output shows 9 frequency bands for practical EQ decisions:
  sub (20-60Hz)        - Rumble, kick fundamental
  bass (60-120Hz)      - Punch, bass fundamental
  low (120-250Hz)      - Warmth, fullness
  low_mid (250-500Hz)  - Mud, boxiness
  mid (500-1kHz)       - Honk, nasal, body
  upper_mid (1-2kHz)   - Presence, attack
  presence (2-4kHz)    - Bite, clarity, intelligibility
  brilliance (4-8kHz)  - Air, sibilance, shimmer
  high (8-20kHz)       - Sparkle, extreme air
        """
    )
    parser.add_argument(
        "--channel", "-c",
        type=int,
        required=True,
        help="Channel number to analyze (1-32)"
    )
    parser.add_argument(
        "--duration", "-d",
        type=float,
        default=15,
        help="Capture duration in seconds (default: 15)"
    )
    parser.add_argument(
        "--until-confident",
        action="store_true",
        help="Auto-stop when readings stabilize (ignores --duration as max)"
    )
    parser.add_argument(
        "--update-session",
        action="store_true",
        help="Splice RTA results into the most recent session capture"
    )
    parser.add_argument(
        "--append-to",
        type=str,
        metavar="FILE",
        help="Append compact JSON result to FILE (one line per channel, for batch collection)"
    )

    args = parser.parse_args()

    if args.channel < 1 or args.channel > 32:
        print("Error: Channel must be between 1 and 32", file=sys.stderr)
        sys.exit(1)

    # Load config
    config = load_config()

    # Get channel name
    channel_name = await get_channel_name(config, args.channel)
    print(f"Analyzing channel {args.channel}: {channel_name}", file=sys.stderr)

    # Create listener and capture
    listener = RTAListener(config['mixer_ip'], config['mixer_port'])

    try:
        listener.connect()
        listener.send_osc('/xremote')
        listener.subscribe_rta(args.channel)

        result = await listener.listen(
            duration=args.duration,
            until_confident=args.until_confident
        )
    except ConnectionError as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Make sure the mixer is powered on and reachable.", file=sys.stderr)
        print(json.dumps({'success': False, 'error': 'connection_failed'}))
        sys.exit(1)
    finally:
        listener.disconnect()

    # Add channel info to result
    result['channel'] = args.channel
    result['channel_name'] = channel_name
    result['duration_seconds'] = args.duration

    # Handle session capture splicing
    if args.update_session:
        capture_path = find_latest_session_capture()

        if capture_path is None:
            print("\nNo session capture found.", file=sys.stderr)
            print("Consider running a fresh capture: python scripts/session_capture.py --duration 5", file=sys.stderr)
            result['session_updated'] = False
            result['session_warning'] = 'no_capture_found'
        else:
            age_hours = get_capture_age_hours(capture_path)

            if age_hours > 24:
                print(f"\nWarning: Session capture is {age_hours:.1f} hours old.", file=sys.stderr)
                print("Consider running a fresh capture for today's session:", file=sys.stderr)
                print("  python scripts/session_capture.py --duration 5", file=sys.stderr)
                result['session_warning'] = f'capture_stale_{age_hours:.1f}h'

            # Still splice into it (better than nothing)
            success = splice_rta_into_session(capture_path, args.channel, result)

            if success:
                print(f"\nRTA data spliced into: {capture_path.name}", file=sys.stderr)
                result['session_updated'] = True
                result['session_file'] = capture_path.name
            else:
                result['session_updated'] = False
                result['session_warning'] = 'splice_failed'

    # Append to batch collection file if requested
    if args.append_to:
        with open(args.append_to, 'a') as f:
            f.write(json.dumps(result) + '\n')
        print(f"Result appended to {args.append_to}", file=sys.stderr)

    # Output JSON to stdout (skip if appending to file)
    if not args.append_to:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
