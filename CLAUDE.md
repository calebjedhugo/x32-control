# X-32 Mixer Control

Python scripts for controlling Behringer X-32 digital mixer via OSC (Open Sound Control).

**IMPORTANT: Mixer IP must be configured in `config.json` before use**

## Quick Setup

1. Install dependencies:
   ```bash
   cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control"
   pip install -r requirements.txt
   ```

2. Configure mixer IP:
   ```bash
   cp config.example.json config.json
   # Edit config.json and set "mixer_ip" to your X-32's IP address
   ```

## Quick Commands

| Task | Command |
|------|---------|
| Get full mixer state | `python scripts/snapshot.py` |
| Monitor levels (10s) | `python scripts/monitor.py --duration 10` |
| Get channel info | `python scripts/query.py --channel 5` |
| Set fader to -10dB | `python scripts/control.py --channel 5 --fader -10dB` |
| Mute channel | `python scripts/control.py --channel 5 --mute` |
| Get EQ settings | `python scripts/query.py --channel 5 --eq` |
| Load scene | `python scripts/scenes.py --load 5` |

## Common Workflows

### Check Sound Levels
```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control"
python scripts/monitor.py --channels 1-16 --duration 10 --format table
```

### Get Channel Details
```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control"
# Basic info (fader, mute, name)
python scripts/query.py --channel 5

# EQ settings
python scripts/query.py --channel 5 --eq

# Dynamics (gate, comp)
python scripts/query.py --channel 5 --dynamics
```

### Adjust Channel Settings
```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control"
# Set fader level
python scripts/control.py --channel 5 --fader -10dB

# Adjust EQ (band 3 to 2.5kHz, +3dB gain)
python scripts/control.py --channel 5 --eq-band 3 --freq 2500 --gain 3.0

# Mute/unmute
python scripts/control.py --channel 5 --mute
python scripts/control.py --channel 5 --unmute

# Preview changes first
python scripts/control.py --channel 5 --fader -10dB --dry-run
```

### Save Current Mix State
```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control"
python scripts/snapshot.py --output "snapshots/$(date +%Y-%m-%d)_current.json"
```

### Scene Management
```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control"
# List available scenes
python scripts/scenes.py --list

# Get current scene
python scripts/scenes.py --current

# Load scene by number
python scripts/scenes.py --load 5

# Load scene by name (partial match)
python scripts/scenes.py --load "Sunday"
```

## OSC Address Reference

Common X-32 OSC addresses for raw queries/control:

### Channel Addresses (replace XX with 01-32)
- Fader: `/ch/XX/mix/fader` (0.0-1.0, 0.75 = 0dB unity)
- Mute: `/ch/XX/mix/on` (0=mute, 1=on)
- Name: `/ch/XX/config/name`
- Color: `/ch/XX/config/color` (0-15)

### EQ (replace XX with channel, N with band 1-4)
- Enable: `/ch/XX/eq/on` (0=off, 1=on)
- Frequency: `/ch/XX/eq/N/f` (0.0-1.0)
- Gain: `/ch/XX/eq/N/g` (0.0-1.0, 0.5 = 0dB)
- Q: `/ch/XX/eq/N/q` (0.0-1.0)

### Dynamics (replace XX with channel)
- Gate on: `/ch/XX/gate/on`
- Gate threshold: `/ch/XX/gate/thr`
- Comp on: `/ch/XX/dyn/on`
- Comp threshold: `/ch/XX/dyn/thr`
- Comp ratio: `/ch/XX/dyn/ratio`

### Bus/Routing (replace XX with channel, YY with bus 01-16)
- Bus send: `/ch/XX/mix/YY/level` (0.0-1.0)
- Main fader: `/main/st/mix/fader`

### Scenes
- Current scene: `/-snap/index`
- Load scene: `/-snap/load` with scene number

## Project Structure

```
x32-control/
├── CLAUDE.md           # This file
├── config.json         # Mixer IP and settings (not in git)
├── config.example.json # Configuration template
├── requirements.txt    # Python dependencies
├── scripts/
│   ├── common.py       # Shared utilities (config, connection, parsing)
│   ├── snapshot.py     # Dump full mixer state to JSON
│   ├── monitor.py      # Sample levels over time, output statistics
│   ├── query.py        # Get specific parameter values
│   ├── control.py      # Set parameters (faders, EQ, mutes, etc.)
│   └── scenes.py       # List/load mixer scenes
└── snapshots/          # Saved mixer states (JSON files)
```

## Configuration

Edit `config.json`:
```json
{
  "mixer_ip": "192.168.0.XXX",    // Your X-32's IP address
  "mixer_port": 10023,             // OSC port (default: 10023)
  "mixer_type": "X32",             // Mixer model
  "timeout_seconds": 5,
  "default_output_format": "json",
  "snapshot_dir": "snapshots"
}
```

To find your X-32's IP:
1. On the X-32, go to Setup → Network
2. Look for IP address under network settings
3. Or check your router's DHCP client list

## Claude Usage Guidelines

When Claude assists with the X-32 mixer:

1. **Always navigate first**:
   ```bash
   cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control"
   ```

2. **Read before write**: Check current state before making changes
   ```bash
   python scripts/query.py --channel 5
   ```

3. **Use --dry-run**: Preview changes for safety
   ```bash
   python scripts/control.py --channel 5 --fader -10dB --dry-run
   ```

4. **Confirm with user**: Always confirm before making changes

5. **Take snapshots**: Save state before significant changes
   ```bash
   python scripts/snapshot.py --output snapshots/before_changes.json
   ```

## Technical Notes

- **Protocol**: OSC (Open Sound Control) over UDP port 10023
- **Keepalive**: X-32 requires `/xremote` command every 10 seconds (handled automatically by behringer-mixer library)
- **Fader mapping**:
  - 0.0 = -∞ dB (silence)
  - 0.75 = 0 dB (unity gain)
  - 1.0 = +10 dB (maximum)
- **Meter data**: Comes as binary blobs requiring unpacking (not yet implemented in monitor.py)

## Dependencies

- **behringer-mixer** (0.4.11+): High-level async X32 API
- **python-osc** (1.8.3+): Raw OSC protocol for fallback operations

Install with:
```bash
pip install -r requirements.txt
```

## Troubleshooting

**Cannot connect to mixer:**
1. Verify mixer IP in `config.json` is correct
2. Check that mixer is on and connected to network
3. Verify your computer is on same network as mixer
4. Try pinging the mixer: `ping <mixer_ip>`

**Permission denied:**
1. Make scripts executable: `chmod +x scripts/*.py`

**Module not found:**
1. Install dependencies: `pip install -r requirements.txt`

---

*Last Updated: 2026-01-11*
*Mixer: Behringer X-32*
