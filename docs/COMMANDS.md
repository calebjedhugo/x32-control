# Technical Command Reference

Read this when you need exact command syntax or OSC details.

## Setup
```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control"
source venv/bin/activate
```

## Command Reference

### Session Capture (Start of Session)
```bash
python scripts/session_capture.py --duration 5
```
Captures EVERYTHING: all channels, buses, FX, routing, gain staging. This is what `/x32-capture` runs.

### RTA Frequency Analysis (On-Demand)
```bash
python scripts/rta_listen.py --channel 26 --update-session                    # 15 seconds
python scripts/rta_listen.py --channel 26 --until-confident --update-session  # Auto-stop when stable
```
**IMPORTANT: ALWAYS use `--update-session`** to splice results back into session capture.

### Mix Analysis (Offline - No Mixer Needed)
```bash
python scripts/analyze.py                                    # Analyze latest session (JSON)
python scripts/analyze.py captures/session_2026-01-25.json   # Specific file
python scripts/analyze.py --text                             # Human-readable report
python scripts/analyze.py -p warning                         # Warnings only
```
JSON output includes `fix` field with ready-to-run `control.py` commands where applicable. Checks HPF, EQ boosts, room-aware rules, cross-channel masking, main bus correction.

### Session Comparison (Offline)
```bash
python scripts/diff_sessions.py                              # Compare two most recent (JSON)
python scripts/diff_sessions.py old.json new.json            # Specific files
python scripts/diff_sessions.py --text                       # Human-readable report
```
Shows fader, EQ, mute, dynamics, and FX changes between sessions.

### Data Extraction (Offline - No Mixer Needed)
```bash
python scripts/extract.py --scope metering-vocals captures/session_XXX.json   # Vocal preamp+dynamics
python scripts/extract.py --scope metering-drums captures/session_XXX.json    # Drum preamp+dynamics
python scripts/extract.py --scope metering-instruments captures/session_XXX.json  # Instrument preamp+dynamics
python scripts/extract.py --scope eq captures/session_XXX.json                # All EQ+HPF+FX tone
python scripts/extract.py --scope editor captures/session_XXX.json            # Routing+faders+DCAs overview
python scripts/extract.py --scope dynamics captures/session_XXX.json          # Bus/main/matrix compressors
python scripts/extract.py --scope livestream captures/session_XXX.json        # Bus→matrix sends+levels
```
Extracts targeted subsets from a session capture. Used by auto-awesome subagents to get only the data they need. Omits capture file arg to use latest.

### Batch Control (Single Connection)
```bash
python scripts/control.py --batch changes.json
python scripts/control.py --batch changes.json --dry-run
```
Executes all changes in one mixer connection. File format: `[{"address": "/ch/01/mix/fader", "value": 0.75}, ...]`. Deletes the batch file after execution.

### RTA Batch Collection
```bash
python scripts/rta_listen.py --channel 5 --until-confident --append-to /tmp/rta_batch.jsonl
python scripts/splice_rta.py /tmp/rta_batch.jsonl captures/session_XXX.json
```
`--append-to` collects RTA results to a JSONL file (one line per channel). `splice_rta.py` merges all results into a capture file and deletes the JSONL temp file.

### Stream Guard (Livestream Mode)
```bash
# Full auto — detect stream, monitor peaks, adjust matrix faders:
python scripts/stream_guard.py --setup-limiter

# Dry-run with any YouTube video (validates pipeline without touching mixer):
python scripts/stream_guard.py --video-id dQw4w9WgXcQ --dry-run --start-db -20 --interval 5

# Monitor a specific video (skip stream detection):
python scripts/stream_guard.py --video-id VIDEO_ID --setup-limiter

# Watch status in another terminal:
watch -n 1 'cat /tmp/stream_guard_status.json | python3 -m json.tool'
```

**Options:**
| Flag | Default | Description |
|------|---------|-------------|
| `--channel-url URL` | config.json | YouTube `/streams` page URL |
| `--video-id ID` | (auto-detect) | Skip detection, monitor specific video |
| `--start-db DB` | -30 | Starting fader level in dB |
| `--target-dbtp DB` | -1.0 | Target peak ceiling |
| `--step-db DB` | 1.0 | Creep increment |
| `--interval SECS` | 30 | Seconds between adjustments |
| `--poll-interval SECS` | 60 | Stream detection poll interval |
| `--status-file PATH` | /tmp/stream_guard_status.json | Status output |
| `--pause-file PATH` | /tmp/stream_guard_pause | Pause signal file |
| `--dry-run` | — | Monitor YouTube without touching mixer |
| `--setup-limiter` | — | Configure mtx 03/04 compressor as brick-wall limiter |

**Owns**: `/mtx/03/mix/fader`, `/mtx/04/mix/fader` (exclusively during operation).
**Pause/resume**: Create `/tmp/stream_guard_pause` to pause fader adjustments (continues reading peaks). Remove file to resume.
**Dependencies**: `yt-dlp`, `ffmpeg` (system-wide).

### Other Commands
| Command | Description |
|---------|-------------|
| `python scripts/capture.py --duration 30` | Capture meter data only |
| `python scripts/snapshot.py` | Full mixer state to JSON |
| `python scripts/query.py --channel 5` | Get channel info |
| `python scripts/query.py --channel 5 --eq` | Get channel EQ |
| `python scripts/control.py --channel 5 --fader -10dB` | Set fader |
| `python scripts/control.py --channel 5 --gate-threshold 0.4` | Set gate threshold |
| `python scripts/control.py --channel 5 --fader -10dB --dry-run` | Preview change |

## Channel Parsing
Scripts accept flexible input:
- `--channel 5`, `--channel ch5`, `--channel "channel 5"`
- `--channels 1-8` or `--channels 1,3,5` or `--channels 1-4,9-12`

## Fader Values

Always use dB values when communicating:
- **0** = unity (0 dB)
- **-inf** = silence
- **+10** = max

Scripts accept: `--fader 0dB` or `--fader -10dB`

## Common OSC Addresses

For raw control: `python scripts/control.py <address> <value>` (positional args, no flag needed)

| Function | Address |
|----------|---------|
| Channel fader | `/ch/01/mix/fader` (01-32) |
| Channel mute | `/ch/01/mix/on` (0=mute, 1=unmute) |
| EQ band gain | `/ch/01/eq/2/g` (bands 1-4) |
| Main fader | `/main/st/mix/fader` |
| RTA source | `/-prefs/rta/source` |

## Core Files
- `scripts/common.py` - Config, connection, parsing, dB conversion
- `scripts/session_capture.py` - **Primary capture**: all settings, routing, FX, gain staging
- `scripts/rta_listen.py` - On-demand RTA analysis, splices into session capture
- `scripts/analyze.py` - **Mix analysis**: reads session JSON, produces recommendations (offline)
- `scripts/diff_sessions.py` - **Session diff**: compares two captures (offline)
- `scripts/capture.py` - Meter-only capture (rarely needed directly)
- `scripts/query.py` - Read mixer state
- `scripts/control.py` - Modify parameters (supports `--batch` for bulk changes)
- `scripts/extract.py` - Extract scoped data from session captures
- `scripts/splice_rta.py` - Merge batch RTA data into session capture
- `scripts/stream_guard.py` - YouTube livestream true-peak monitor + matrix fader control
- `scripts/snapshot.py` - Full state dump

## Config
`config.json` must have:
```json
{
  "mixer_ip": "192.168.x.x",
  "mixer_port": 10023,
  "youtube_channel_url": "https://www.youtube.com/@channel/streams"
}
```

## Technical Notes

See `docs/TECHNICAL.md` for library quirks, OSC details, and debugging.
