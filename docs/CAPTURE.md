# Capture Workflow Details

Read this when doing captures or analyzing capture data.

## Quick Commands
```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control" && source venv/bin/activate

# Main capture (30 seconds, all active channels)
python scripts/capture.py --duration 30 --rta-sweep

# Recapture specific channels
python scripts/capture.py --recapture captures/FILE.json --channels 22,23,24 --duration 5

# Named capture
python scripts/capture.py --duration 30 --rta-sweep --output captures/2026-01-12_sunday-worship.json
```

## What Gets Captured

### Smart Filtering (automatic)
- Only channels with signal above -70dB included
- Inactive channels excluded entirely
- Reduces file size, focuses on what matters

### Meter Data (simultaneous)
- Pre-fader levels for all active channels
- Bus 1-16 levels
- Main L/R levels
- ~50 samples/second with timestamps

### RTA Frequency Spectrum (100 bins, 20Hz-20kHz)
With `--rta-sweep`:
1. First 3 seconds: scans to identify active channels
2. Non-drum channels: 0.5 seconds each
3. Drum channels (22-28): captured LAST with 3 seconds each
4. Weak captures automatically retried
5. Keeps best capture per channel

### Channel Settings (snapshot at start)
- Fader positions, mutes, pans
- Full EQ (4 bands)
- Gate settings
- Compressor settings
- Preamp settings (gain, phantom, HPF)

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

## Recapture Workflow

If channels were missed (drummer wasn't playing toms, vocalist wasn't singing):

1. Ask them to play/sing
2. Run recapture: `python scripts/capture.py --recapture FILE --channels 22,23,24`
3. Data merges into original file
4. Marked as `"recaptured": true` in JSON

## Data Volume
- 30 seconds ≈ 1500 meter samples
- ~1-3 MB JSON file
- Keep captures focused

## Capture Naming Convention
Suggest meaningful names for later comparison:
- `2026-01-12_sunday-worship.json`
- `2026-01-12_soundcheck.json`
- `2026-01-05_sunday-worship.json`

## Protocol Reference
- [X32 OSC Protocol PDF](https://x32ram.com/wp-content/uploads/download-files/X32-OSC.pdf)
- [pmaillot/X32-Behringer](https://github.com/pmaillot/X32-Behringer)
