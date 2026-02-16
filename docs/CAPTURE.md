# Capture & RTA Workflow

Read this when doing captures or analyzing frequency data.

## Quick Commands
```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control" && source venv/bin/activate

# Capture meter data (levels, activity detection)
python scripts/capture.py --duration 30
python scripts/capture.py --duration 30 --output captures/2026-01-12_sunday-worship.json

# RTA frequency analysis (on-demand, single channel)
# Use --update-session to splice results back into session capture
python scripts/rta_listen.py --channel 26 --update-session                    # 15 seconds default
python scripts/rta_listen.py --channel 26 --duration 30 --update-session      # Custom duration
python scripts/rta_listen.py --channel 26 --until-confident --update-session  # Auto-stop when stable
```

## Capture (capture.py)

Captures simultaneous meter data for all channels.

### What Gets Captured

**Smart Filtering (automatic)**
- Only channels with signal above threshold included
- Inactive channels excluded entirely
- Reduces file size, focuses on what matters

**Meter Data (simultaneous)**
- Pre-fader levels for all active channels
- Bus 1-16 levels
- Main L/R levels
- ~50 samples/second with timestamps

**Channel Settings (snapshot at start)**
- Fader positions, mutes, pans
- Full EQ (4 bands)
- Gate settings
- Compressor settings
- Preamp settings (gain, phantom, HPF)

### Data Volume
- 30 seconds ≈ 1500 meter samples
- ~500KB-1MB JSON file

### Capture Naming Convention
Suggest meaningful names for later comparison:
- `2026-01-12_sunday-worship.json`
- `2026-01-12_soundcheck.json`

## RTA Listen (rta_listen.py)

On-demand frequency analysis for a single channel. Use when you need to understand what frequencies a source contains.

### Usage
```bash
# Kick drum - needs time to catch hits
python scripts/rta_listen.py --channel 26 --duration 15 --update-session

# Vocal - use until-confident for sustained sources
python scripts/rta_listen.py --channel 1 --until-confident --update-session
```

### Session Splicing (--update-session)

When you use `--update-session`, the RTA results are spliced back into the most recent session capture file. This keeps all data in one place and avoids re-listening to the same channel.

**What happens:**
- Finds the most recent `session_*.json` in `captures/`
- Adds `rta_analysis` to that channel's data
- Updates `rta_last_updated` timestamp on the session

**Data freshness:**
- If session capture is >24 hours old, you'll see a warning
- Consider running a fresh `/x32-capture` for today's session
- RTA data still gets spliced (better than nothing)

### Frequency Bands
Output aggregates 100 RTA bins into 9 practical bands:

| Band | Range | What it represents |
|------|-------|-------------------|
| sub | 20-60Hz | Rumble, kick fundamental |
| bass | 60-120Hz | Punch, bass fundamental |
| low | 120-250Hz | Warmth, fullness |
| low_mid | 250-500Hz | Mud, boxiness |
| mid | 500-1kHz | Honk, nasal, body |
| upper_mid | 1-2kHz | Presence, attack |
| presence | 2-4kHz | Bite, clarity, intelligibility |
| brilliance | 4-8kHz | Air, sibilance, shimmer |
| high | 8-20kHz | Sparkle, extreme air |

### Output Metrics
- `avg`: Average energy (mean of absolute values)
- `peak`: Maximum value seen
- `variance`: How much it fluctuates
  - `high` = transient (drums)
  - `low` = sustained (vocals, keys)

### Example Output
```json
{
  "timestamp": "2026-01-19T10:30:45.123456",
  "channel": 26,
  "channel_name": "Kick",
  "samples_collected": 750,
  "peak_meter": 18500,
  "bands": {
    "sub": {"avg": 12500, "peak": 28000, "variance": "high"},
    "bass": {"avg": 9800, "peak": 22000, "variance": "high"},
    "low": {"avg": 5200, "peak": 14000, "variance": "medium"},
    "low_mid": {"avg": 4100, "peak": 11000, "variance": "medium"},
    "mid": {"avg": 1800, "peak": 5500, "variance": "low"},
    "upper_mid": {"avg": 1200, "peak": 4500, "variance": "low"},
    "presence": {"avg": 800, "peak": 2100, "variance": "low"},
    "brilliance": {"avg": 400, "peak": 1200, "variance": "low"},
    "high": {"avg": 200, "peak": 600, "variance": "low"}
  },
  "interpretation": {
    "dominant_band": "sub",
    "energy_balance": "bottom-heavy",
    "transient_character": "punchy (high variance in low end)"
  },
  "session_updated": true,
  "session_file": "session_2026-01-19_10-15-30.json"
}
```

## Understanding RTA vs EQ

| RTA | EQ Settings |
|-----|-------------|
| What frequencies the signal CONTAINS | What processing is APPLIED |
| Measurement | Modification |
| "Kick has energy at 60Hz" | "I'm cutting 400Hz by 3dB" |

### What Comparing Reveals
- Is a cut addressing an actual problem frequency?
- Are boosts adding frequencies not naturally there?
- What's each source's natural frequency footprint?

## Protocol Reference
- [X32 OSC Protocol PDF](https://x32ram.com/wp-content/uploads/download-files/X32-OSC.pdf)
- [pmaillot/X32-Behringer](https://github.com/pmaillot/X32-Behringer)
