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
    python rta_listen.py --channel 1 --until-confident --silence-timeout 3  # Quick scan, exit early if silent
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
METER_RTA = 4  # 82 frequency bins (20Hz - 20kHz), LE float32 format

# Number of RTA bins the X32 returns via /meters/4
NUM_RTA_BINS = 82

# Frequency band definitions (bin index ranges)
# X-32 RTA has 82 bins spanning ~20Hz to 20kHz (logarithmic spacing)
# Bin n ≈ 20 * 10^(3n/82) Hz
FREQUENCY_BANDS = {
    'sub':        {'range': '20-60Hz',   'bins': (0, 13),   'desc': 'Rumble, kick fundamental'},
    'bass':       {'range': '60-120Hz',  'bins': (13, 21),  'desc': 'Punch, bass fundamental'},
    'low':        {'range': '120-250Hz', 'bins': (21, 30),  'desc': 'Warmth, fullness'},
    'low_mid':    {'range': '250-500Hz', 'bins': (30, 38),  'desc': 'Mud, boxiness'},
    'mid':        {'range': '500-1kHz',  'bins': (38, 47),  'desc': 'Honk, nasal, body'},
    'upper_mid':  {'range': '1-2kHz',    'bins': (47, 55),  'desc': 'Presence, attack'},
    'presence':   {'range': '2-4kHz',    'bins': (55, 63),  'desc': 'Bite, clarity, intelligibility'},
    'brilliance': {'range': '4-8kHz',    'bins': (63, 71),  'desc': 'Air, sibilance, shimmer'},
    'high':       {'range': '8-20kHz',   'bins': (71, 82),  'desc': 'Sparkle, extreme air'},
}

# Variance thresholds for --until-confident mode
VARIANCE_STABLE_THRESHOLD = 0.15  # Coefficient of variation below this = stable
MIN_SAMPLES_FOR_CONFIDENCE = 50   # Need at least this many samples
MIN_DURATION_SECONDS = 5          # Always capture at least this long

# Signal thresholds
MIN_SIGNAL_THRESHOLD = 0.001  # LE float32 RTA value below this = no meaningful signal


def parse_rta_blob(data: bytes) -> Optional[List[float]]:
    """Parse RTA meter blob from X-32.

    Format: 4-byte LE int32 count, then count LE float32 values.
    Returns list of float values (0.0-1.0 linear amplitude per frequency bin).
    """
    try:
        if len(data) < 4:
            return None
        count = struct.unpack('<i', data[:4])[0]
        num_floats = min(count, (len(data) - 4) // 4)
        if num_floats < 10:
            return None
        values = struct.unpack(f'<{num_floats}f', data[4:4 + num_floats * 4])
        return list(values)
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
        self.peak_meter: float = 0.0  # Peak meter level for this channel (0.0-1.0)

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
        self.channel = channel
        # Enable RTA processing (mode=1) and set source
        self.send_osc('/-prefs/rta/mode', 1)
        self.send_osc('/-prefs/rta/source', channel)
        # Subscribe to RTA meters
        self.send_osc('/batchsubscribe', '/meters/4', '/meters/4', 0, 0, 2)
        # Also subscribe to channel meters for peak level
        self.send_osc('/batchsubscribe', '/meters/0', '/meters/0', 0, 0, 2)

    def _parse_channel_meter(self, data: bytes) -> Optional[float]:
        """Parse channel meter blob and return level for our channel.

        Format: 4-byte LE int32 count (70), then 70 LE float32 values.
        Layout: 2 values per channel (input level + gate), 32 channels = 64,
        plus 6 aux values. Channel N meter is at index (N-1)*2.
        """
        try:
            if len(data) < 4:
                return None
            count = struct.unpack('<i', data[:4])[0]
            num_floats = min(count, (len(data) - 4) // 4)
            values = struct.unpack(f'<{num_floats}f', data[4:4 + num_floats * 4])
            idx = (self.channel - 1) * 2
            if idx < len(values):
                return values[idx]
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

        for bin_idx in range(len(recent[0])):
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

    async def listen(self, duration: float, until_confident: bool = False,
                     silence_timeout: Optional[float] = None) -> Dict:
        """
        Listen to RTA and meter data for specified duration.

        Args:
            duration: Maximum capture duration in seconds
            until_confident: If True, stop early when data stabilizes
            silence_timeout: If set, exit early after this many seconds if
                no meaningful signal detected (all samples below MIN_SIGNAL_THRESHOLD)

        Returns:
            Dictionary with aggregated frequency band analysis and peak level.
            Includes 'silence_exit: true' if exited due to silence timeout.
        """
        self.samples = []
        self.peak_meter = 0.0
        silence_exit = False
        has_signal = False
        start_time = time.time()
        last_xremote = start_time
        last_subscribe = start_time

        print(f"Listening for RTA data...", file=sys.stderr)
        if until_confident:
            print(f"  Will stop when data stabilizes (max {duration}s)", file=sys.stderr)
        if silence_timeout is not None:
            print(f"  Silence timeout: {silence_timeout}s", file=sys.stderr)

        while time.time() - start_time < duration:
            current_time = time.time()
            elapsed = current_time - start_time

            # Keep-alive every 8 seconds
            if current_time - last_xremote > 8:
                self.send_osc('/xremote')
                last_xremote = current_time

            # Re-subscribe every 100ms
            # NOTE: /-prefs/rta/source does NOT change /meters/4 blob over OSC.
            # The X32 always sends the same RTA data regardless of source setting.
            # Per-channel RTA is not possible via OSC on this firmware. See CORRECTIONS.md.
            if current_time - last_subscribe > 0.1:
                self.send_osc('/batchsubscribe', '/meters/4', '/meters/4', 0, 0, 2)
                self.send_osc('/batchsubscribe', '/meters/0', '/meters/0', 0, 0, 2)
                last_subscribe = current_time

            # Receive data (RTA and/or meter)
            rta_data, meter_level = self.receive_data()
            if rta_data:
                self.samples.append(rta_data)
                if not has_signal and max(rta_data) >= MIN_SIGNAL_THRESHOLD:
                    has_signal = True
            if meter_level is not None and meter_level > self.peak_meter:
                self.peak_meter = meter_level

            # Check for confidence (after minimum time)
            if until_confident and elapsed >= MIN_DURATION_SECONDS:
                if len(self.samples) >= MIN_SAMPLES_FOR_CONFIDENCE:
                    stability = self.calculate_variance_stability()
                    if stability < VARIANCE_STABLE_THRESHOLD:
                        print(f"  Data stabilized after {elapsed:.1f}s ({len(self.samples)} samples)", file=sys.stderr)
                        break

            # Check for silence timeout
            if silence_timeout is not None and elapsed >= silence_timeout and not has_signal:
                silence_exit = True
                print(f"  No signal after {elapsed:.1f}s — silence timeout", file=sys.stderr)
                break

            # Progress update
            if len(self.samples) > 0 and len(self.samples) % 50 == 0:
                print(f"  {len(self.samples)} samples collected...", file=sys.stderr)

            await asyncio.sleep(0.001)

        actual_duration = time.time() - start_time
        print(f"Capture complete: {len(self.samples)} samples in {actual_duration:.1f}s", file=sys.stderr)
        print(f"  Peak meter level: {self.peak_meter}", file=sys.stderr)

        result = self.analyze()
        if silence_exit:
            result['silence_exit'] = True
        return result

    @staticmethod
    def bin_to_freq(n: int) -> float:
        """Convert RTA bin index to approximate frequency in Hz."""
        return 20.0 * (10.0 ** (3.0 * n / NUM_RTA_BINS))

    @staticmethod
    def freq_to_band(freq_hz: float) -> str:
        """Map a frequency to its band name."""
        for band_name, band_info in FREQUENCY_BANDS.items():
            start_bin, end_bin = band_info['bins']
            low_freq = RTAListener.bin_to_freq(start_bin)
            high_freq = RTAListener.bin_to_freq(end_bin)
            if low_freq <= freq_hz < high_freq:
                return band_name
        return 'high'  # Above all defined bands

    @staticmethod
    def raw_to_db(value: float, reference: float) -> float:
        """Convert raw RTA value to dB relative to reference. Returns -inf for zero."""
        if value <= 0 or reference <= 0:
            return -100.0
        return round(20.0 * math.log10(value / reference), 1)

    def _validate_data(self, avg_bins: List[float]) -> tuple:
        """
        Validate RTA data quality.

        Returns:
            (valid: bool, notes: str or None)
        """
        if len(self.samples) < 10:
            return False, "insufficient samples (need at least 10)"

        max_raw = 1.0
        # Check if >80% of bins are within 5% of max
        near_max_count = sum(1 for v in avg_bins if v > max_raw * 0.95)
        if near_max_count > len(avg_bins) * 0.8:
            return False, "all bins near maximum — likely corrupt data (check for second X32 client)"

        # Check if all band peaks are identical (±2%)
        band_peaks = []
        for band_name, band_info in FREQUENCY_BANDS.items():
            start_bin, end_bin = band_info['bins']
            band_vals = avg_bins[start_bin:end_bin]
            if band_vals:
                band_peaks.append(max(band_vals))
        if band_peaks and all(p > 0 for p in band_peaks):
            ref = band_peaks[0]
            if all(abs(p - ref) / ref < 0.02 for p in band_peaks):
                return False, "uniform frequency response — likely corrupt"

        # Check for unnaturally flat spectrum (real instruments have uneven frequency distribution)
        signal_bins = [v for v in avg_bins if v >= MIN_SIGNAL_THRESHOLD]
        if len(signal_bins) > 20:
            mean_signal = sum(signal_bins) / len(signal_bins)
            if mean_signal > 0:
                variance = sum((v - mean_signal) ** 2 for v in signal_bins) / len(signal_bins)
                cv = math.sqrt(variance) / mean_signal
                if cv < 0.15:
                    return False, f"unnaturally flat spectrum (CV={cv:.2f}) — likely corrupt data (check for second X32 client)"

        # Check meter/RTA mismatch
        has_rta_signal = max(avg_bins) >= MIN_SIGNAL_THRESHOLD
        if self.peak_meter < 0.0001 and has_rta_signal:
            return False, "meter/RTA mismatch — peak meter is 0 but RTA shows signal"

        return True, None

    def _find_peaks(self, avg_bins: List[float], db_bins: List[float]) -> List[Dict]:
        """
        Find spectral peaks — bins significantly above their neighbors.

        Returns list of peak dicts sorted by relative_db descending.
        """
        peaks = []
        # Need at least 3 bins to find peaks
        if len(avg_bins) < 3:
            return peaks

        for i in range(1, len(avg_bins) - 1):
            if avg_bins[i] < MIN_SIGNAL_THRESHOLD:
                continue
            # Compare to neighbors (wider window for smoother detection)
            left_start = max(0, i - 3)
            right_end = min(len(avg_bins), i + 4)
            neighbors = [avg_bins[j] for j in range(left_start, right_end) if j != i]
            if not neighbors:
                continue
            neighbor_avg = sum(neighbors) / len(neighbors)
            if neighbor_avg <= 0:
                continue

            prominence_db = 20.0 * math.log10(avg_bins[i] / neighbor_avg) if neighbor_avg > 0 else 0
            # A peak needs at least 3dB prominence above neighbors
            if prominence_db >= 3.0:
                freq = self.bin_to_freq(i)
                peaks.append({
                    'freq_hz': int(round(freq)),
                    'band': self.freq_to_band(freq),
                    'relative_db': db_bins[i],
                    'prominence_db': round(prominence_db, 1),
                })

        # Sort by relative_db descending (loudest first), take top 5
        peaks.sort(key=lambda p: p['relative_db'], reverse=True)
        return peaks[:5]

    def _find_problems(self, avg_bins: List[float], db_bins: List[float],
                       cv_bins: List[float]) -> List[Dict]:
        """
        Identify potential EQ problems: buildups, thin regions, resonances.
        """
        problems = []
        if len(avg_bins) < 3:
            return problems

        # 1. Buildup detection: bins in 200-500Hz that are within 6dB of peak
        #    (common mud zone)
        for i in range(25, 38):  # ~200Hz to ~500Hz (82-bin mapping)
            if avg_bins[i] < MIN_SIGNAL_THRESHOLD:
                continue
            if db_bins[i] > -6.0:
                freq = self.bin_to_freq(i)
                # Check if it's actually prominent vs neighbors
                left = max(0, i - 3)
                right = min(len(avg_bins), i + 4)
                neighbors = [avg_bins[j] for j in range(left, right) if j != i]
                neighbor_avg = sum(neighbors) / len(neighbors) if neighbors else 0
                if neighbor_avg > 0 and avg_bins[i] / neighbor_avg > 1.3:
                    problems.append({
                        'type': 'buildup',
                        'freq_hz': int(round(freq)),
                        'band': self.freq_to_band(freq),
                        'relative_db': db_bins[i],
                        'note': 'potential mud',
                    })

        # 2. Thinness: if average of bins above 8kHz is more than 20dB below peak
        high_bins = [db_bins[i] for i in range(71, len(avg_bins)) if avg_bins[i] >= MIN_SIGNAL_THRESHOLD]
        if high_bins:
            high_avg = sum(high_bins) / len(high_bins)
            if high_avg < -20.0:
                problems.append({
                    'type': 'thin_highs',
                    'freq_hz': 8000,
                    'band': 'high',
                    'relative_db': round(high_avg, 1),
                    'note': f'thin above 8kHz ({round(high_avg, 1)}dB below peak)',
                })

        # 3. Harsh resonance: narrow peak in 2-5kHz with high prominence
        for i in range(55, 66):  # ~2kHz to ~5kHz (82-bin mapping)
            if avg_bins[i] < MIN_SIGNAL_THRESHOLD:
                continue
            left = max(0, i - 2)
            right = min(len(avg_bins), i + 3)
            neighbors = [avg_bins[j] for j in range(left, right) if j != i]
            neighbor_avg = sum(neighbors) / len(neighbors) if neighbors else 0
            if neighbor_avg > 0:
                prominence = 20.0 * math.log10(avg_bins[i] / neighbor_avg)
                if prominence >= 5.0:
                    freq = self.bin_to_freq(i)
                    problems.append({
                        'type': 'harsh_resonance',
                        'freq_hz': int(round(freq)),
                        'band': self.freq_to_band(freq),
                        'relative_db': db_bins[i],
                        'note': f'resonance (+{round(prominence, 1)}dB above neighbors)',
                    })

        # Deduplicate: keep only the worst problem per type+band
        seen = {}
        deduped = []
        for p in problems:
            key = (p['type'], p['band'])
            if key not in seen or p['relative_db'] > seen[key]['relative_db']:
                seen[key] = p
        deduped = list(seen.values())

        return deduped[:5]

    def _compute_spectral_tilt(self, avg_bins: List[float]) -> str:
        """Compute spectral tilt as dB difference between low and high energy."""
        # Average dB of sub+bass bins (0-26) vs brilliance+high bins (77-100)
        low_vals = [v for v in avg_bins[0:21] if v >= MIN_SIGNAL_THRESHOLD]
        high_vals = [v for v in avg_bins[63:] if v >= MIN_SIGNAL_THRESHOLD]

        if not low_vals or not high_vals:
            return "insufficient signal for tilt measurement"

        low_avg = sum(low_vals) / len(low_vals)
        high_avg = sum(high_vals) / len(high_vals)

        if low_avg <= 0 or high_avg <= 0:
            return "insufficient signal for tilt measurement"

        tilt_db = round(20.0 * math.log10(low_avg / high_avg), 1)

        if tilt_db > 6:
            return f"bottom-heavy ({tilt_db:+.0f}dB sub-to-high slope)"
        elif tilt_db < -6:
            return f"top-heavy ({tilt_db:+.0f}dB sub-to-high slope)"
        elif tilt_db > 2:
            return f"slightly warm ({tilt_db:+.0f}dB sub-to-high slope)"
        elif tilt_db < -2:
            return f"slightly bright ({tilt_db:+.0f}dB sub-to-high slope)"
        else:
            return f"balanced ({tilt_db:+.0f}dB sub-to-high slope)"

    def _compute_transient_character(self, cv_bins: List[float]) -> str:
        """Determine transient character from coefficient of variation in low end."""
        low_cvs = [cv_bins[i] for i in range(0, 21) if cv_bins[i] is not None]
        if not low_cvs:
            return "unknown (no low-end signal)"

        avg_cv = sum(low_cvs) / len(low_cvs)
        if avg_cv > 0.8:
            return "punchy (high low-end variance)"
        elif avg_cv > 0.4:
            return "moderate transients"
        else:
            return "sustained (steady low end)"

    def _build_spectral_summary(self, peaks: List[Dict], problems: List[Dict],
                                 tilt: str, avg_bins: List[float]) -> str:
        """Build a one-sentence spectral summary for LLM consumption."""
        parts = []

        # Describe peaks
        for p in peaks[:3]:
            freq = p['freq_hz']
            if freq < 100:
                parts.append(f"strong at {freq}Hz")
            elif freq < 1000:
                parts.append(f"energy at {freq}Hz")
            else:
                parts.append(f"presence at {freq/1000:.1f}kHz")

        # Describe problems
        for prob in problems[:2]:
            if prob['type'] == 'buildup':
                parts.append(f"buildup at {prob['freq_hz']}Hz")
            elif prob['type'] == 'thin_highs':
                parts.append("thin above 8kHz")
            elif prob['type'] == 'harsh_resonance':
                freq = prob['freq_hz']
                if freq >= 1000:
                    parts.append(f"resonance at {freq/1000:.1f}kHz")
                else:
                    parts.append(f"resonance at {freq}Hz")

        # Check for no signal
        max_signal = max(avg_bins) if avg_bins else 0
        if max_signal < MIN_SIGNAL_THRESHOLD:
            return "No meaningful signal detected."

        if not parts:
            return "Even spectrum, no notable peaks or problems."

        # Add tilt info if notable
        if "bottom-heavy" in tilt or "top-heavy" in tilt:
            parts.append(tilt.split("(")[0].strip())

        return ". ".join(p.capitalize() if i == 0 else p for i, p in enumerate(parts)) + "."

    def analyze(self) -> Dict:
        """
        Analyze collected RTA samples with full frequency resolution.

        Produces actionable output: specific peak frequencies, problems,
        spectral tilt, and a summary sentence — all in dB relative to
        the loudest bin (0dB = peak).
        """
        if not self.samples:
            return {
                'valid': False,
                'validation_notes': 'no RTA data collected',
                'error': 'No RTA data collected',
            }

        num_bins = len(self.samples[0])
        num_samples = len(self.samples)

        # Compute per-bin averages
        avg_bins = [0.0] * num_bins
        for i in range(num_bins):
            vals = [s[i] for s in self.samples]
            avg_bins[i] = sum(vals) / len(vals)

        # Compute per-bin coefficient of variation
        cv_bins = [None] * num_bins
        for i in range(num_bins):
            vals = [s[i] for s in self.samples if s[i] > MIN_SIGNAL_THRESHOLD]
            if len(vals) >= 5:
                mean = sum(vals) / len(vals)
                if mean > MIN_SIGNAL_THRESHOLD:
                    variance = sum((v - mean) ** 2 for v in vals) / len(vals)
                    cv_bins[i] = math.sqrt(variance) / mean

        # Find global peak for dB reference (values are 0.0-1.0 float)
        global_peak = max(avg_bins) if avg_bins else 0.001
        if global_peak < MIN_SIGNAL_THRESHOLD:
            global_peak = MIN_SIGNAL_THRESHOLD

        # Convert to dB relative to peak (0dB = loudest bin)
        db_bins = [self.raw_to_db(v, global_peak) for v in avg_bins]

        # Validate
        valid, validation_notes = self._validate_data(avg_bins)

        # Find peaks and problems
        peaks = self._find_peaks(avg_bins, db_bins)
        problems = self._find_problems(avg_bins, db_bins, cv_bins)

        # Spectral tilt and transient character
        spectral_tilt = self._compute_spectral_tilt(avg_bins)
        transient_character = self._compute_transient_character(cv_bins)

        # Build summary
        spectral_summary = self._build_spectral_summary(peaks, problems, spectral_tilt, avg_bins)

        # Add contextual notes to peaks
        for p in peaks:
            if p['band'] in ('sub', 'bass') and p['relative_db'] > -3:
                p['note'] = 'fundamental'
            elif p['band'] in ('presence', 'upper_mid') and p['relative_db'] > -10:
                p['note'] = 'attack/clarity'
            elif p['band'] == 'brilliance':
                p['note'] = 'air/shimmer'
            else:
                p['note'] = ''
            # Keep prominence_db — tells agents how much this peak sticks
            # out above neighbors (useful for EQ cut decisions)

        # Compute per-band statistics (avg/peak/variance) for downstream tools
        bands = {}
        for band_name, band_info in FREQUENCY_BANDS.items():
            start_bin, end_bin = band_info['bins']
            band_vals = [abs(avg_bins[i]) for i in range(start_bin, min(end_bin, len(avg_bins)))]
            if not band_vals or max(band_vals) < MIN_SIGNAL_THRESHOLD:
                bands[band_name] = {'avg': 0, 'peak': 0, 'variance': 'none'}
                continue
            avg = sum(band_vals) / len(band_vals)
            peak = max(band_vals)
            # Variance from per-sample data
            all_values = []
            for sample in self.samples:
                all_values.extend(abs(sample[i]) for i in range(start_bin, min(end_bin, len(sample))))
            if avg < MIN_SIGNAL_THRESHOLD:
                variance_class = 'none'
            else:
                variance = sum((v - avg) ** 2 for v in all_values) / len(all_values) if all_values else 0
                std_dev = math.sqrt(variance)
                cv = std_dev / avg if avg > 0 else 0
                if cv > 0.8:
                    variance_class = 'high'
                elif cv > 0.4:
                    variance_class = 'medium'
                else:
                    variance_class = 'low'
            bands[band_name] = {
                'avg': round(avg, 6),
                'peak': round(peak, 6),
                'variance': variance_class,
            }

        result = {
            'timestamp': datetime.now().isoformat(),
            'valid': valid,
            'validation_notes': validation_notes,
            'samples_collected': num_samples,
            'peak_meter': self.peak_meter,
            'bands': bands,
            'spectral_summary': spectral_summary,
            'peaks': peaks,
            'problems': problems,
            'spectral_tilt': spectral_tilt,
            'transient_character': transient_character,
        }

        return result


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
            'timestamp': rta_result.get('timestamp'),
            'valid': rta_result.get('valid', False),
            'validation_notes': rta_result.get('validation_notes'),
            'samples_collected': rta_result.get('samples_collected'),
            'peak_meter': rta_result.get('peak_meter'),
            'bands': rta_result.get('bands', {}),
            'spectral_summary': rta_result.get('spectral_summary'),
            'peaks': rta_result.get('peaks', []),
            'problems': rta_result.get('problems', []),
            'spectral_tilt': rta_result.get('spectral_tilt'),
            'transient_character': rta_result.get('transient_character'),
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
    python rta_listen.py --channel 1 --until-confident --silence-timeout 3  # Quick scan

Output provides actionable spectral analysis at full frequency resolution:
  - spectral_summary: one-sentence description for quick EQ decisions
  - peaks: specific frequencies with dB relative to loudest bin (0dB)
  - problems: buildups, resonances, thin regions with frequencies
  - spectral_tilt: low-to-high energy balance in dB
  - transient_character: punchy vs sustained based on low-end variance
  - valid/validation_notes: data quality check (catches corrupt data)
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
        "--silence-timeout",
        type=float,
        metavar="N",
        help="Exit early if no meaningful signal after N seconds (useful for quick scans)"
    )
    parser.add_argument(
        "--append-to",
        type=str,
        metavar="FILE",
        help="Append compact JSON result to FILE (one line per channel, for batch collection)"
    )
    parser.add_argument(
        "--name",
        type=str,
        metavar="NAME",
        help="Channel name (avoids extra mixer connection to look it up)"
    )

    args = parser.parse_args()

    if args.channel < 1 or args.channel > 32:
        print("Error: Channel must be between 1 and 32", file=sys.stderr)
        sys.exit(1)

    # Load config
    config = load_config()

    # Get channel name — use CLI arg if provided, otherwise query mixer
    if args.name:
        channel_name = args.name
    else:
        channel_name = await get_channel_name(config, args.channel)
    print(f"Analyzing channel {args.channel}: {channel_name}", file=sys.stderr)

    # Create listener and capture
    listener = RTAListener(config['mixer_ip'], config['mixer_port'])

    try:
        listener.connect()
        listener.send_osc('/xremote')
        listener.subscribe_rta(args.channel)

        # Let the mixer settle on the new RTA source before collecting
        # Without this, early packets still carry the previous source's data
        await asyncio.sleep(0.3)

        result = await listener.listen(
            duration=args.duration,
            until_confident=args.until_confident,
            silence_timeout=args.silence_timeout
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
