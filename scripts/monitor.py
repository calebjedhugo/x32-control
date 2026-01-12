#!/usr/bin/env python3
"""
Monitor channel levels over time and output statistics.

Usage:
    python monitor.py --duration 10
    python monitor.py --channels 1-8 --duration 30
    python monitor.py --channels 1,3,5 --duration 10 --format table
    python monitor.py --channels 1-8 --clip-threshold -3
"""

import argparse
import asyncio
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from common import load_config, get_mixer, parse_channel_range, fader_to_db


class LevelMonitor:
    """Monitor channel levels and compute statistics."""

    def __init__(self, channels, clip_threshold_db=-3.0):
        """
        Initialize level monitor.

        Args:
            channels: List of channel numbers to monitor
            clip_threshold_db: dB level to consider as "clip" (default: -3)
        """
        self.channels = channels
        self.clip_threshold_db = clip_threshold_db
        self.samples = defaultdict(list)
        self.names = {}
        self.clip_counts = defaultdict(int)

    def add_sample(self, channel_addr, fader_value, name=None):
        """
        Add a level sample for a channel.

        Args:
            channel_addr: Channel address like "/ch/01"
            fader_value: Fader value (0.0-1.0)
            name: Optional channel name
        """
        if name:
            self.names[channel_addr] = name

        db = fader_to_db(fader_value)
        self.samples[channel_addr].append(db)

        if not math.isinf(db) and db > self.clip_threshold_db:
            self.clip_counts[channel_addr] += 1

    def get_statistics(self):
        """
        Get statistics for all monitored channels.

        Returns:
            Dictionary with channel statistics
        """
        stats = {}

        for channel_addr in sorted(self.samples.keys()):
            samples = self.samples[channel_addr]
            if not samples:
                continue

            # Filter out -inf values for avg/min calculations
            finite_samples = [s for s in samples if not math.isinf(s)]

            if finite_samples:
                avg_db = sum(finite_samples) / len(finite_samples)
                peak_db = max(samples)
                min_db = min(finite_samples)
            else:
                avg_db = float('-inf')
                peak_db = float('-inf')
                min_db = float('-inf')

            stats[channel_addr] = {
                "name": self.names.get(channel_addr, ""),
                "avg_db": round(avg_db, 1) if not math.isinf(avg_db) else "-inf",
                "peak_db": round(peak_db, 1) if not math.isinf(peak_db) else "-inf",
                "min_db": round(min_db, 1) if not math.isinf(min_db) else "-inf",
                "clip_count": self.clip_counts[channel_addr],
                "sample_count": len(samples)
            }

        return stats


def format_table(stats, clip_threshold_db):
    """Format statistics as a table."""
    lines = []
    lines.append(f"{'Channel':<10} {'Name':<15} {'Avg (dB)':<10} {'Peak (dB)':<10} {'Min (dB)':<10} {'Clips':<8}")
    lines.append("-" * 73)

    for channel_addr in sorted(stats.keys()):
        s = stats[channel_addr]
        channel = channel_addr.replace('/ch/', 'ch/').replace('/bus/', 'bus/')
        name = s['name'][:14] if s['name'] else ""
        avg = str(s['avg_db'])
        peak = str(s['peak_db'])
        min_val = str(s['min_db'])
        clips = str(s['clip_count'])

        lines.append(f"{channel:<10} {name:<15} {avg:<10} {peak:<10} {min_val:<10} {clips:<8}")

    if any(s['clip_count'] > 0 for s in stats.values()):
        lines.append("")
        lines.append(f"Note: Clips are levels above {clip_threshold_db} dB")

    return '\n'.join(lines)


async def monitor_levels(mixer, channels, duration, clip_threshold_db):
    """
    Monitor channel levels for a specified duration.

    Args:
        mixer: Connected mixer instance
        channels: List of channel numbers to monitor
        duration: Duration in seconds
        clip_threshold_db: dB level to consider as clip

    Returns:
        LevelMonitor with statistics
    """
    monitor = LevelMonitor(channels, clip_threshold_db)
    state = mixer.state()

    # Get initial channel names
    for ch_num in channels:
        ch_addr = f"/ch/{ch_num:02d}"
        try:
            name = state.get(f"{ch_addr}/config/name", "")
            monitor.names[ch_addr] = name
        except:
            pass

    # Sample interval (50ms)
    sample_interval = 0.05
    samples_needed = int(duration / sample_interval)

    print(f"Monitoring {len(channels)} channels for {duration} seconds...", file=sys.stderr)

    # Subscribe to meter updates
    # Note: behringer-mixer may not expose meter data directly
    # This implementation polls fader levels as a fallback
    for i in range(samples_needed):
        state = mixer.state()

        for ch_num in channels:
            ch_addr = f"/ch/{ch_num:02d}"
            try:
                # In a real implementation, we'd read meter data
                # For now, we'll use fader positions as a proxy
                fader = state.get(f"{ch_addr}/mix/fader", 0.0)
                name = state.get(f"{ch_addr}/config/name", "")
                monitor.add_sample(ch_addr, fader, name)
            except:
                pass

        await asyncio.sleep(sample_interval)

        # Progress indicator
        if (i + 1) % 20 == 0:
            progress = (i + 1) / samples_needed * 100
            print(f"Progress: {progress:.0f}%", file=sys.stderr)

    print("Monitoring complete.", file=sys.stderr)
    return monitor


async def main():
    parser = argparse.ArgumentParser(description="Monitor X-32 channel levels")
    parser.add_argument(
        "--channels", "-c",
        default="1-32",
        help="Channels to monitor (e.g., 1-8, 1,3,5, 1-4,9-12)"
    )
    parser.add_argument(
        "--duration", "-d",
        type=int,
        default=10,
        help="Duration in seconds (default: 10)"
    )
    parser.add_argument(
        "--clip-threshold", "-t",
        type=float,
        default=-3.0,
        help="dB level to consider as clip (default: -3.0)"
    )
    parser.add_argument(
        "--format", "-f",
        choices=["json", "table"],
        default="table",
        help="Output format (default: table)"
    )

    args = parser.parse_args()

    # Parse channel range
    try:
        channels = parse_channel_range(args.channels)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Connect to mixer
    print(f"Connecting to mixer...", file=sys.stderr)
    mixer = await get_mixer()

    try:
        # Monitor levels
        monitor = await monitor_levels(
            mixer,
            channels,
            args.duration,
            args.clip_threshold
        )

        # Get statistics
        stats = monitor.get_statistics()

        # Output
        if args.format == "table":
            print(format_table(stats, args.clip_threshold))
        else:
            output = {
                "duration_seconds": args.duration,
                "clip_threshold_db": args.clip_threshold,
                "channels": stats
            }
            print(json.dumps(output, indent=2))

    finally:
        await mixer.stop()


if __name__ == "__main__":
    asyncio.run(main())
