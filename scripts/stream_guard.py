#!/usr/bin/env python3
"""
YouTube Stream Guard — monitors livestream true-peak and autonomously
adjusts matrix faders to approach 0 dBTP without clipping.

Usage:
    python scripts/stream_guard.py [OPTIONS]

    --channel-url URL      YouTube streams page URL (default: from config.json)
    --video-id ID          Skip detection, monitor this specific video
    --start-db DB          Fallback fader level in dB if mixer can't be read (default: -30)
    --target-dbtp DB       Target peak ceiling (default: -1.0)
    --step-db DB           Creep increment (default: 1.0)
    --interval SECS        Seconds between adjustments (default: 30)
    --poll-interval SECS   Stream detection poll interval (default: 60)
    --status-file PATH     Status output (default: /tmp/stream_guard_status.json)
    --pause-file PATH      Pause signal file (default: /tmp/stream_guard_pause)
    --dry-run              Monitor YouTube but don't touch the mixer
    --setup-limiter        Configure mtx 03/04 compressor as limiter at startup
"""

import argparse
import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from collections import deque
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from common import load_config, db_to_fader, fader_to_db


# --- State Machine ---

class State(Enum):
    WAITING_FOR_STREAM = "waiting"
    CONNECTING = "connecting"
    MONITORING = "monitoring"
    SETTLED = "settled"
    BACKING_OFF = "backing_off"
    STREAM_ENDED = "stream_ended"


# --- Status File ---

class StatusWriter:
    """Writes status JSON atomically (write-to-temp-then-rename)."""

    def __init__(self, path: str):
        self.path = path
        self._dir = os.path.dirname(path) or "/tmp"

    def write(self, data: dict):
        data["timestamp"] = datetime.now(timezone.utc).isoformat()
        try:
            fd, tmp_path = tempfile.mkstemp(dir=self._dir, suffix=".json")
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self.path)
        except OSError as e:
            print(f"[status] Failed to write {self.path}: {e}", file=sys.stderr)


# --- Fader Controller ---

class FaderController:
    """Manages matrix fader level based on measured YouTube true-peak."""

    def __init__(self, start_db: float, target_dbtp: float, step_db: float,
                 interval: float):
        self.current_db = start_db
        self.target_dbtp = target_dbtp
        self.step_db = step_db
        self.interval = interval

        # Rolling window of ~30 readings (~3 sec at 10 Hz)
        self.peak_history: deque = deque(maxlen=30)
        self.settled = False
        self.adjustments_made = 0
        self.last_adjustment_time = 0.0
        self.cooldown_until = 0.0

    @property
    def recent_peak(self) -> float:
        """Max peak over the rolling window."""
        if not self.peak_history:
            return -100.0
        return max(self.peak_history)

    def add_peak(self, left_dbtp: float, right_dbtp: float):
        """Record a true-peak reading."""
        self.peak_history.append(max(left_dbtp, right_dbtp))

    def evaluate(self) -> tuple:
        """
        Decide whether to adjust fader.

        Returns:
            (new_db or None, reason_string)
        """
        now = time.monotonic()

        # Respect cooldown
        if now < self.cooldown_until:
            return None, "cooldown"

        # Need enough readings
        if len(self.peak_history) < 5:
            return None, "insufficient data"

        # Time gate — only adjust every `interval` seconds
        if now - self.last_adjustment_time < self.interval:
            return None, "waiting"

        peak = self.recent_peak

        # When settled: only respond to actual clipping
        if self.settled:
            if peak >= 0.0:
                new_db = max(self.current_db - 0.5, -90.0)
                self.cooldown_until = now + 60.0
                return new_db, f"CLIP GUARD -0.5dB (peak {peak:+.1f} dBTP)"
            return None, "settled"

        # BACK OFF: clipping
        if peak >= 0.0:
            new_db = max(self.current_db - 2.0, -90.0)
            self.cooldown_until = now + 60.0
            self.settled = False
            return new_db, f"BACK OFF 2dB (peak {peak:+.1f} dBTP >= 0)"

        # BACK OFF: too hot
        if peak > self.target_dbtp:
            new_db = max(self.current_db - 1.0, -90.0)
            self.cooldown_until = now + 45.0
            self.settled = False
            return new_db, f"back off 1dB (peak {peak:+.1f} dBTP > {self.target_dbtp})"

        # SETTLE: in the sweet spot
        if -3.0 <= peak <= self.target_dbtp:
            if not self.settled:
                self.settled = True
                return None, f"SETTLED (peak {peak:+.1f} dBTP in sweet spot)"
            return None, "settled"

        # UNSETTLE: signal dropped significantly while settled
        if peak < -6.0 and self.settled:
            self.settled = False
            return None, f"UNSETTLED (peak {peak:+.1f} dBTP dropped below -6)"

        # CREEP UP: signal too quiet
        if peak < -3.0:
            new_db = min(self.current_db + self.step_db, 0.0)  # cap at 0 dB (unity)
            if new_db == self.current_db:
                return None, "at unity cap"
            return new_db, f"creep up {self.step_db}dB (peak {peak:+.1f} dBTP)"

        return None, "no action"

    def apply(self, new_db: float):
        """Record that a fader adjustment was applied."""
        self.current_db = new_db
        self.adjustments_made += 1
        self.last_adjustment_time = time.monotonic()


# --- Mixer Interface ---

class MixerInterface:
    """Sends fader commands to X-32 via behringer_mixer."""

    def __init__(self, config: dict, dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run
        self.mixer = None
        self._keepalive_task = None

    async def connect(self):
        if self.dry_run:
            print("[mixer] Dry-run mode — not connecting", file=sys.stderr)
            return

        from behringer_mixer import mixer_api

        self.mixer = mixer_api.create(
            self.config["mixer_type"],
            ip=self.config["mixer_ip"],
            port=self.config["mixer_port"]
        )
        await self.mixer.start()
        await self.mixer.validate_connection()
        print(f"[mixer] Connected to {self.config['mixer_ip']}", file=sys.stderr)

        # Start keepalive
        self._keepalive_task = asyncio.create_task(self._keepalive())

    async def _keepalive(self):
        """Send /xremote every 8 seconds to keep connection alive."""
        while True:
            try:
                await asyncio.sleep(8)
                if self.mixer:
                    await self.mixer.send("/xremote", None)
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def disconnect(self):
        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
        if self.mixer:
            try:
                await self.mixer.stop()
            except Exception:
                pass

    async def set_matrix_fader(self, matrix: int, fader_value: float):
        """Set a matrix fader. matrix is 3 or 4."""
        address = f"/mtx/{matrix:02d}/mix/fader"
        if self.dry_run:
            db = fader_to_db(fader_value)
            print(f"[dry-run] Would set {address} = {fader_value:.4f} ({db:+.1f} dB)",
                  file=sys.stderr)
            return
        # No readback on matrix faders (known unreliable per control.py)
        await self.mixer.send(address, fader_value)

    async def set_both_matrix_faders(self, db: float):
        """Set mtx 03 and 04 to the same dB level."""
        fader_val = db_to_fader(db)
        await self.set_matrix_fader(3, fader_val)
        await asyncio.sleep(0.05)
        await self.set_matrix_fader(4, fader_val)

    async def read_matrix_fader_db(self) -> float | None:
        """Read current matrix 03 fader level in dB. Returns None in dry-run."""
        if self.dry_run or not self.mixer:
            return None
        result = await self.mixer.query("/mtx/03/mix/fader")
        if result is None:
            return None
        fader_val = result[0] if isinstance(result, (list, tuple)) else result
        return fader_to_db(float(fader_val))

    async def setup_limiter(self):
        """Configure mtx 03/04 compressors as brick-wall limiters."""
        if self.dry_run:
            print("[dry-run] Would configure mtx 03/04 limiters", file=sys.stderr)
            return

        for mtx in [3, 4]:
            prefix = f"/mtx/{mtx:02d}/dyn"
            commands = [
                (f"{prefix}/on", 1),        # Enable
                (f"{prefix}/ratio", 11),     # Index 11 = 100:1
                (f"{prefix}/attack", 0.0),   # Fastest (0.05ms)
                (f"{prefix}/release", 0.5),  # Medium release
                (f"{prefix}/knee", 0),       # Hard knee
                (f"{prefix}/mix", 1.0),      # 100% wet
                (f"{prefix}/mgain", 0.0),    # No makeup gain
            ]
            for address, value in commands:
                await self.mixer.send(address, value)
                await asyncio.sleep(0.05)
            print(f"[mixer] Configured mtx {mtx:02d} compressor as limiter",
                  file=sys.stderr)


# --- Stream Detection ---

async def detect_live_stream(channel_url: str, timeout: int = 30) -> str | None:
    """
    Detect a live stream on the channel's /streams page.

    Returns video ID if live, None if not live.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp", "--print", "id",
            "--match-filter", "live_status = is_live",
            "--playlist-items", "1:5",
            channel_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )

        if proc.returncode != 0:
            err = stderr.decode().strip()
            if err:
                print(f"[detect] yt-dlp error: {err}", file=sys.stderr)
            return None

        video_id = stdout.decode().strip().split("\n")[0].strip()
        return video_id if video_id else None

    except asyncio.TimeoutError:
        print("[detect] yt-dlp timed out", file=sys.stderr)
        return None
    except FileNotFoundError:
        print("[detect] yt-dlp not found", file=sys.stderr)
        return None


# --- Audio Pipeline ---

FTPK_PATTERN = re.compile(r"FTPK:\s+([-\d.]+)\s+([-\d.]+)\s+dBFS")


async def run_audio_pipeline(video_id: str, peak_callback, stop_event: asyncio.Event):
    """
    Run yt-dlp | ffmpeg pipeline and parse true-peak values.

    Uses subprocess.Popen for the OS-level pipe between yt-dlp stdout and
    ffmpeg stdin, then wraps ffmpeg's stderr with asyncio for non-blocking reads.

    Calls peak_callback(left_dbtp, right_dbtp) for each FTPK line.
    Returns when stop_event is set or pipeline exits.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"

    # Use subprocess.Popen so OS-level pipe connects yt-dlp stdout → ffmpeg stdin
    ytdlp_proc = subprocess.Popen(
        ["yt-dlp", "-f", "bestaudio", "--no-warnings", "-o", "-", url],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    ffmpeg_proc = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "verbose",
         "-i", "pipe:0",
         "-af", "ebur128=peak=true:framelog=verbose",
         "-f", "null", "-"],
        stdin=ytdlp_proc.stdout,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    # Allow yt-dlp stdout to be consumed by ffmpeg
    ytdlp_proc.stdout.close()

    # Wrap ffmpeg stderr in an asyncio StreamReader for non-blocking reads
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    transport, _ = await loop.connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader),
        ffmpeg_proc.stderr
    )

    try:
        while not stop_event.is_set():
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=2.0)
            except asyncio.TimeoutError:
                if ffmpeg_proc.poll() is not None:
                    break
                continue

            if not line:
                break

            text = line.decode("utf-8", errors="replace")
            match = FTPK_PATTERN.search(text)
            if match:
                left = float(match.group(1))
                right = float(match.group(2))
                peak_callback(left, right)

    finally:
        transport.close()
        for proc in [ffmpeg_proc, ytdlp_proc]:
            if proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except (subprocess.TimeoutExpired, OSError):
                    try:
                        proc.kill()
                    except OSError:
                        pass


# --- Main Guard Loop ---

class StreamGuard:
    """Main state machine coordinating detection, monitoring, and fader control."""

    def __init__(self, args):
        self.args = args
        self.config = load_config()
        self.channel_url = args.channel_url or self.config.get("youtube_channel_url", "")
        self.state = State.WAITING_FOR_STREAM
        self.video_id = None
        self.stop_event = asyncio.Event()
        self.errors: list = []
        self.consecutive_failures = 0

        self.fader = FaderController(
            start_db=args.start_db,
            target_dbtp=args.target_dbtp,
            step_db=args.step_db,
            interval=args.interval,
        )
        self.mixer = MixerInterface(self.config, dry_run=args.dry_run)
        self.status = StatusWriter(args.status_file)

    def _status_dict(self) -> dict:
        return {
            "state": self.state.value,
            "video_id": self.video_id,
            "fader_db": round(self.fader.current_db, 1),
            "recent_peak_dbtp": round(self.fader.recent_peak, 1),
            "settled": self.fader.settled,
            "last_adjustment": (
                datetime.fromtimestamp(
                    self.fader.last_adjustment_time + time.time() - time.monotonic(),
                    tz=timezone.utc
                ).isoformat()
                if self.fader.last_adjustment_time > 0 else None
            ),
            "adjustments_made": self.fader.adjustments_made,
            "errors": self.errors[-5:],
        }

    def _write_status(self):
        self.status.write(self._status_dict())

    def _transition(self, new_state: State):
        old = self.state
        self.state = new_state
        print(f"[guard] {old.value} -> {new_state.value}", file=sys.stderr)
        self._write_status()

    def _is_paused(self) -> bool:
        return os.path.exists(self.args.pause_file)

    async def run(self):
        """Main loop."""
        # Handle signals
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.stop_event.set)

        try:
            # Connect mixer
            await self.mixer.connect()

            # Setup limiter if requested
            if self.args.setup_limiter:
                await self.mixer.setup_limiter()

            # Read current fader position from mixer
            actual_db = await self.mixer.read_matrix_fader_db()
            if actual_db is not None:
                self.fader.current_db = actual_db
                print(f"[guard] Read fader from mixer: {actual_db:+.1f} dB",
                      file=sys.stderr)
            else:
                print(f"[guard] Using start-db: {self.fader.current_db:+.1f} dB",
                      file=sys.stderr)

            # Set fader to confirmed position (ensures both mtx 03/04 match)
            await self.mixer.set_both_matrix_faders(self.fader.current_db)
            print(f"[guard] Initial fader: {self.fader.current_db:+.1f} dB",
                  file=sys.stderr)

            self._write_status()

            # If video ID provided, skip detection
            if self.args.video_id:
                self.video_id = self.args.video_id
                self._transition(State.CONNECTING)
                await self._monitor_loop()
            else:
                await self._detection_loop()

        except Exception as e:
            self.errors.append(str(e))
            self._write_status()
            print(f"[guard] Fatal error: {e}", file=sys.stderr)
            raise
        finally:
            await self.mixer.disconnect()

    async def _detection_loop(self):
        """Poll for live streams, then monitor when found."""
        if not self.channel_url:
            print("[guard] No channel URL configured", file=sys.stderr)
            self.errors.append("No youtube_channel_url in config.json")
            self._write_status()
            return

        self._transition(State.WAITING_FOR_STREAM)
        detect_failures = 0

        while not self.stop_event.is_set():
            video_id = await detect_live_stream(self.channel_url)

            if video_id:
                self.video_id = video_id
                detect_failures = 0
                self._transition(State.CONNECTING)
                await self._monitor_loop()

                # Stream ended — wait before re-detecting
                if self.stop_event.is_set():
                    break
                self._transition(State.WAITING_FOR_STREAM)
                await asyncio.sleep(30)
            else:
                detect_failures += 1
                if detect_failures >= 5:
                    self.errors.append(f"{detect_failures} consecutive detection failures")
                    self._write_status()

                # Wait before next poll
                try:
                    await asyncio.wait_for(
                        self.stop_event.wait(),
                        timeout=self.args.poll_interval
                    )
                    if self.stop_event.is_set():
                        break
                except asyncio.TimeoutError:
                    pass

    async def _monitor_loop(self):
        """Monitor a live stream and adjust faders."""
        self._transition(State.MONITORING)
        self.fader.peak_history.clear()
        self.consecutive_failures = 0

        # Heartbeat + adjustment task
        adjust_task = asyncio.create_task(self._adjustment_loop())

        try:
            while not self.stop_event.is_set():
                print(f"[guard] Connecting to video {self.video_id}",
                      file=sys.stderr)

                try:
                    await run_audio_pipeline(
                        self.video_id,
                        peak_callback=self.fader.add_peak,
                        stop_event=self.stop_event,
                    )
                except Exception as e:
                    print(f"[guard] Pipeline error: {e}", file=sys.stderr)
                    self.errors.append(f"pipeline: {e}")

                # Pipeline exited
                self.consecutive_failures += 1

                if self.stop_event.is_set():
                    break

                if self.consecutive_failures >= 3:
                    self.errors.append("3 consecutive pipeline failures")
                    self._write_status()
                    print("[guard] Too many failures, exiting", file=sys.stderr)
                    break

                # Stream may have ended — re-detect
                self._transition(State.STREAM_ENDED)
                await asyncio.sleep(10)

                # Quick re-check: is the same video still live?
                vid = await detect_live_stream(
                    f"https://www.youtube.com/watch?v={self.video_id}",
                    timeout=15
                )
                if vid == self.video_id:
                    # Still live, reconnect
                    self._transition(State.MONITORING)
                    continue
                else:
                    # Stream truly ended
                    break

        finally:
            adjust_task.cancel()
            try:
                await adjust_task
            except asyncio.CancelledError:
                pass

        self._transition(State.STREAM_ENDED)

    async def _adjustment_loop(self):
        """Periodically evaluate peaks and adjust faders."""
        last_heartbeat = time.monotonic()

        try:
            while True:
                await asyncio.sleep(1.0)

                # Heartbeat status every 30 seconds
                now = time.monotonic()
                if now - last_heartbeat >= 30:
                    self._write_status()
                    last_heartbeat = now

                # Skip adjustments if paused
                if self._is_paused():
                    continue

                new_db, reason = self.fader.evaluate()

                if new_db is not None:
                    # Safety cap
                    new_db = min(new_db, 0.0)

                    print(f"[guard] {reason} -> {new_db:+.1f} dB", file=sys.stderr)

                    # Retry with exponential backoff on mixer failure
                    applied = False
                    for attempt in range(3):
                        try:
                            await self.mixer.set_both_matrix_faders(new_db)
                            self.fader.apply(new_db)
                            applied = True
                            break
                        except Exception as e:
                            delay = 2 ** (attempt + 1)
                            print(f"[guard] Mixer send failed (attempt {attempt+1}): {e}",
                                  file=sys.stderr)
                            if attempt < 2:
                                await asyncio.sleep(delay)
                            else:
                                self.errors.append(f"mixer send failed: {e}")

                    # Update state only if fader change was applied
                    if applied:
                        if "BACK OFF" in reason or "back off" in reason:
                            self._transition(State.BACKING_OFF)
                        elif self.fader.settled:
                            self._transition(State.SETTLED)
                        else:
                            if self.state != State.MONITORING:
                                self._transition(State.MONITORING)

                    self._write_status()

                elif "SETTLED" in reason:
                    self._transition(State.SETTLED)
                elif "UNSETTLED" in reason:
                    self._transition(State.MONITORING)

        except asyncio.CancelledError:
            pass


# --- CLI ---

def main():
    parser = argparse.ArgumentParser(
        description="YouTube Stream Guard — monitor true-peak and adjust matrix faders"
    )
    parser.add_argument(
        "--channel-url",
        help="YouTube channel streams page URL (default: from config.json)"
    )
    parser.add_argument(
        "--video-id",
        help="Skip detection, monitor this specific video ID"
    )
    parser.add_argument(
        "--start-db", type=float, default=-30.0,
        help="Fallback fader level in dB if mixer can't be read (default: -30)"
    )
    parser.add_argument(
        "--target-dbtp", type=float, default=-1.0,
        help="Target peak ceiling in dBTP (default: -1.0)"
    )
    parser.add_argument(
        "--step-db", type=float, default=1.0,
        help="Creep increment in dB (default: 1.0)"
    )
    parser.add_argument(
        "--interval", type=float, default=30.0,
        help="Seconds between adjustments (default: 30)"
    )
    parser.add_argument(
        "--poll-interval", type=float, default=60.0,
        help="Stream detection poll interval in seconds (default: 60)"
    )
    parser.add_argument(
        "--status-file", default="/tmp/stream_guard_status.json",
        help="Status output file path (default: /tmp/stream_guard_status.json)"
    )
    parser.add_argument(
        "--pause-file", default="/tmp/stream_guard_pause",
        help="Pause signal file path (default: /tmp/stream_guard_pause)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Monitor YouTube but don't touch the mixer"
    )
    parser.add_argument(
        "--setup-limiter", action="store_true",
        help="Configure mtx 03/04 compressor as limiter at startup"
    )

    args = parser.parse_args()
    guard = StreamGuard(args)
    asyncio.run(guard.run())


if __name__ == "__main__":
    main()
