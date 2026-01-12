# X-32 Mixer Control

Python scripts for controlling Behringer X-32 digital mixer via OSC (Open Sound Control) protocol.

## Features

- **Real-time control**: Direct OSC communication with X-32 hardware
- **Complete mixer state capture**: Snapshot all settings to JSON
- **Level monitoring**: Sample and analyze channel levels over time
- **Flexible querying**: Read any parameter (faders, EQ, dynamics, routing)
- **Safe modifications**: Dry-run mode to preview changes before executing
- **Scene management**: List and load mixer scenes programmatically

## Quick Start

### 1. Install Dependencies

A virtual environment is already set up with dependencies installed. To use it:

```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control"
source venv/bin/activate
```

If you need to reinstall dependencies:
```bash
pip install -r requirements.txt
```

This installs:
- `behringer-mixer` - High-level async X32 API
- `python-osc` - Raw OSC protocol for fallback operations

### 2. Configure Mixer IP

```bash
cp config.example.json config.json
# Edit config.json and set "mixer_ip" to your X-32's IP address
```

**Finding your X-32's IP address:**
1. On the X-32, go to Setup → Network
2. Look for IP address under network settings
3. Or check your router's DHCP client list

**Example config.json:**
```json
{
  "mixer_ip": "192.168.0.100",
  "mixer_port": 10023,
  "mixer_type": "X32",
  "timeout_seconds": 5,
  "default_output_format": "json",
  "snapshot_dir": "snapshots"
}
```

### 3. Test Connection

```bash
python scripts/query.py --channel 1
```

If successful, you'll see channel 1's current settings in JSON format.

## Usage

### Snapshot - Capture Full Mixer State

```bash
# Full snapshot
python scripts/snapshot.py

# Save to specific file
python scripts/snapshot.py --output snapshots/soundcheck.json

# Capture only specific sections
python scripts/snapshot.py --sections channels,buses

# Compact JSON (no pretty-print)
python scripts/snapshot.py --compact
```

### Monitor - Sample Channel Levels

```bash
# Monitor all channels for 10 seconds
python scripts/monitor.py --duration 10

# Monitor specific channels
python scripts/monitor.py --channels 1-8 --duration 30

# Monitor with clip threshold alert
python scripts/monitor.py --channels 1-16 --clip-threshold -3 --duration 60

# Table format output
python scripts/monitor.py --channels 1-8 --format table
```

### Query - Read Mixer Parameters

```bash
# Get channel overview (fader, mute, name)
python scripts/query.py --channel 5

# Get EQ settings
python scripts/query.py --channel 5 --eq

# Get dynamics (gate, compressor)
python scripts/query.py --channel 5 --dynamics

# Get bus sends
python scripts/query.py --channel 5 --sends

# Query bus overview
python scripts/query.py --bus 3

# Query raw OSC address
python scripts/query.py /ch/05/mix/fader

# Multiple addresses
python scripts/query.py /ch/05/mix/fader /ch/05/mix/on
```

### Control - Modify Mixer Parameters

```bash
# Set fader by dB
python scripts/control.py --channel 5 --fader -10dB

# Set fader by float (0.0-1.0)
python scripts/control.py --channel 5 --fader 0.75

# Mute/unmute
python scripts/control.py --channel 5 --mute
python scripts/control.py --channel 5 --unmute

# Set channel name
python scripts/control.py --channel 5 --name "Vocals"

# Adjust EQ band
python scripts/control.py --channel 5 --eq-band 2 --freq 2500 --gain 3.0 --q 1.5

# Toggle EQ on/off
python scripts/control.py --channel 5 --eq-on
python scripts/control.py --channel 5 --eq-off

# Set compressor threshold
python scripts/control.py --channel 5 --comp-threshold -20

# Set bus send level
python scripts/control.py --channel 5 --send-bus 1 --level 0.5

# Preview changes without executing (dry run)
python scripts/control.py --channel 5 --fader -10dB --dry-run

# Raw OSC command
python scripts/control.py --raw /ch/05/eq/1/g 0.65
```

### Scenes - Manage Mixer Scenes

```bash
# List all available scenes
python scripts/scenes.py --list

# Get current scene
python scripts/scenes.py --current

# Load scene by number
python scripts/scenes.py --load 5

# Load scene by name (partial match)
python scripts/scenes.py --load "Sunday Service"
```

## OSC Address Reference

### Channel Addresses (01-32)
- Fader: `/ch/XX/mix/fader` (0.0-1.0, where 0.75 = 0dB unity)
- Mute: `/ch/XX/mix/on` (0=mute, 1=on)
- Name: `/ch/XX/config/name`
- Color: `/ch/XX/config/color` (0-15)

### EQ (4 bands per channel)
- Enable: `/ch/XX/eq/on` (0=off, 1=on)
- Frequency: `/ch/XX/eq/N/f` (0.0-1.0, band N = 1-4)
- Gain: `/ch/XX/eq/N/g` (0.0-1.0, 0.5 = 0dB)
- Q factor: `/ch/XX/eq/N/q` (0.0-1.0)

### Dynamics
- Gate on: `/ch/XX/gate/on`
- Gate threshold: `/ch/XX/gate/thr`
- Compressor on: `/ch/XX/dyn/on`
- Compressor threshold: `/ch/XX/dyn/thr`
- Compressor ratio: `/ch/XX/dyn/ratio`

### Routing
- Bus send: `/ch/XX/mix/YY/level` (channel XX to bus YY)
- Main LR fader: `/main/st/mix/fader`

### Scenes
- Current scene index: `/-snap/index`
- Scene name: `/-snap/XXX/name` (scene XXX = 000-099)
- Load scene: `/-snap/load` with scene number

## Technical Details

### Fader Mapping

X-32 uses a non-linear fader curve:
- `0.0` = -∞ dB (silence)
- `0.75` = 0 dB (unity gain)
- `1.0` = +10 dB (maximum)

The `common.py` utilities handle conversions between float values and dB.

### Protocol

- **Protocol**: OSC (Open Sound Control) over UDP
- **Port**: 10023 (default)
- **Keepalive**: X-32 requires `/xremote` command every 10 seconds to maintain connection (handled automatically by `behringer-mixer` library)

### Network Setup

The X-32 must be on the same network as your computer. Options:
1. Connect X-32's Ethernet port to your main router (recommended)
2. Connect to X-32's built-in WiFi (no internet access)
3. Use a WiFi bridge to connect X-32 to main network

## Project Structure

```
x32-control/
├── CLAUDE.md              # Claude Code integration docs
├── README.md              # This file
├── requirements.txt       # Python dependencies
├── config.json            # Your mixer configuration (gitignored)
├── config.example.json    # Configuration template
├── .gitignore
├── scripts/
│   ├── common.py          # Shared utilities
│   ├── snapshot.py        # Full state capture
│   ├── monitor.py         # Level monitoring
│   ├── query.py           # Parameter queries
│   ├── control.py         # Parameter modifications
│   └── scenes.py          # Scene management
└── snapshots/             # Saved mixer states
```

## Troubleshooting

### Cannot connect to mixer

1. Verify `mixer_ip` in `config.json` is correct
2. Check that mixer is powered on and connected to network
3. Verify your computer is on the same network as the mixer
4. Try pinging the mixer: `ping <mixer_ip>`
5. Check firewall settings (UDP port 10023 must be open)

### Permission denied

Make scripts executable:
```bash
chmod +x scripts/*.py
```

### Module not found

Install dependencies:
```bash
pip install -r requirements.txt
```

### Changes not appearing on mixer

1. Check that you're connected to the actual hardware (not just X32-Edit)
2. Verify the OSC address is correct
3. Try a simple test: `python scripts/control.py --channel 1 --mute`

## License

MIT License - See LICENSE file for details

## Contributing

Contributions welcome! Please open an issue or pull request.

## Resources

- [X-32 OSC Protocol Documentation](https://sites.google.com/site/patrickmaillot/x32)
- [behringer-mixer Python Library](https://github.com/wrodie/behringer-mixer)
- [Behringer X32 Product Page](https://www.behringer.com/product.html?modelCode=P0ASF)
