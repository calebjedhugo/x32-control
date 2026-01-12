# X-32 Mixer Control

Python scripts for autonomous control of Behringer X-32 digital mixer via OSC protocol.

**IMPORTANT: Run `pip install -r requirements.txt` on first use**
**IMPORTANT: Configure `config.json` with mixer IP before running any scripts**

## Bash Commands

Always run from project directory:
```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control"
```

| Command | Description |
|---------|-------------|
| `python scripts/snapshot.py` | Dump full mixer state to JSON |
| `python scripts/monitor.py --channels 1-16 --duration 10` | Monitor channel levels for 10 seconds |
| `python scripts/query.py --channel 5` | Get channel info (fader, mute, name) |
| `python scripts/query.py --channel 5 --eq` | Get channel EQ settings |
| `python scripts/control.py --channel 5 --fader -10dB` | Set channel fader to -10dB |
| `python scripts/control.py --channel 5 --mute` | Mute channel |
| `python scripts/control.py --channel 5 --fader -10dB --dry-run` | Preview change without executing |
| `python scripts/scenes.py --list` | List available mixer scenes |

## Core Files

- `scripts/common.py` - Shared utilities: config loading, mixer connection, channel parsing, dB conversions
- `scripts/query.py` - Read mixer state (channels, EQ, dynamics, sends)
- `scripts/control.py` - Modify mixer parameters (faders, mutes, EQ, dynamics)
- `scripts/monitor.py` - Sample levels over time, output statistics
- `scripts/snapshot.py` - Capture complete mixer state to JSON
- `scripts/scenes.py` - Scene management (list, load)

## Workflow

**YOU MUST follow this workflow when controlling the mixer:**

1. **Always read state first** before making changes:
   ```bash
   python scripts/query.py --channel 5
   ```

2. **Use --dry-run** to preview changes:
   ```bash
   python scripts/control.py --channel 5 --fader -10dB --dry-run
   ```

3. **Take snapshot** before significant changes:
   ```bash
   python scripts/snapshot.py --output snapshots/before_changes.json
   ```

4. **Confirm with user** before executing control commands

5. **Never make changes during live sound** without explicit user instruction

## Channel Parsing

Scripts accept flexible channel input:
- `--channel 5`, `--channel ch5`, `--channel "channel 5"` all work
- Range format: `--channels 1-8` or `--channels 1,3,5` or `--channels 1-4,9-12`

## Fader Values

X-32 fader mapping (critical for control.py):
- 0.0 = -∞ dB (silence)
- 0.75 = 0 dB (unity gain)
- 1.0 = +10 dB (maximum)

Scripts accept both: `--fader 0.75` or `--fader -10dB`

## Common OSC Addresses

For raw control: `python scripts/control.py --raw <address> <value>`
- Channel fader: `/ch/01/mix/fader` (channels 01-32)
- Channel mute: `/ch/01/mix/on` (0=mute, 1=unmute)
- EQ band gain: `/ch/01/eq/2/g` (bands 1-4)
- Main fader: `/main/st/mix/fader`

---

*Last Updated: 2026-01-11*
