# Technical Command Reference

Read this when you need exact command syntax or OSC details.

## Setup
```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control"
source venv/bin/activate
```

## Command Reference

| Command | Description |
|---------|-------------|
| `python scripts/capture.py --duration 30 --rta-sweep` | Capture meters + RTA |
| `python scripts/capture.py --recapture FILE --channels 22,23` | Recapture and merge |
| `python scripts/snapshot.py` | Full mixer state to JSON |
| `python scripts/query.py --channel 5` | Get channel info |
| `python scripts/query.py --channel 5 --eq` | Get channel EQ |
| `python scripts/control.py --channel 5 --fader -10dB` | Set fader |
| `python scripts/control.py --channel 5 --mute` | Mute channel |
| `python scripts/control.py --channel 5 --fader -10dB --dry-run` | Preview change |

## Channel Parsing
Scripts accept flexible input:
- `--channel 5`, `--channel ch5`, `--channel "channel 5"`
- `--channels 1-8` or `--channels 1,3,5` or `--channels 1-4,9-12`

## Fader Values

| Value | dB |
|-------|-----|
| 0.0 | -∞ (silence) |
| 0.75 | 0 dB (unity) |
| 1.0 | +10 dB (max) |

Scripts accept: `--fader 0.75` or `--fader -10dB`

## Common OSC Addresses

For raw control: `python scripts/control.py --raw <address> <value>`

| Function | Address |
|----------|---------|
| Channel fader | `/ch/01/mix/fader` (01-32) |
| Channel mute | `/ch/01/mix/on` (0=mute, 1=unmute) |
| EQ band gain | `/ch/01/eq/2/g` (bands 1-4) |
| Main fader | `/main/st/mix/fader` |
| RTA source | `/-prefs/rta/source` |

## Core Files
- `scripts/common.py` - Config, connection, parsing, dB conversion
- `scripts/capture.py` - Real-time meter + RTA capture
- `scripts/query.py` - Read mixer state
- `scripts/control.py` - Modify parameters
- `scripts/snapshot.py` - Full state dump

## Config
`config.json` must have:
```json
{
  "mixer_ip": "192.168.x.x",
  "mixer_port": 10023
}
```
