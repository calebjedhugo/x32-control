# X-32 Mixer Control

Python scripts for autonomous control of Behringer X-32 digital mixer via OSC protocol.

**IMPORTANT: Virtual environment is set up at `venv/` - dependencies already installed**
**IMPORTANT: Configure `config.json` with mixer IP before running any scripts**

**WARNING: If query results show all default/empty values (fader 0.0, empty names, no EQ), the mixer is probably not connected. The behringer_mixer library silently returns defaults instead of erroring on connection failure.**

## Bash Commands

Always run from project directory with venv activated:
```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control"
source venv/bin/activate
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

## Setup & Channel Map

### Venue
- **Type**: Church sanctuary, ~400 seats
- **Layout**: Platform corner-loaded with storage/baptismal behind (hard surfaces). Sound booth in opposite corner. Main ceiling ~20ft at booth, rising toward platform. Soffits along both side walls near booth create 10ft ceiling over edge seating with vertical faces up to main ceiling.
- **PA**: Two mains mounted either side of platform, crossed to center of room. One sub (overpowered even at min volume) firing into left platform wall - corner-loaded, causes excessive LF in room.
- **Acoustics**: Pew cushions, commercial carpet. All hard wall surfaces. Complex geometry but many parallel walls (flutter echo risk).
- **Baptismal**: Usually covered, elevated above platform for visibility.
- **Known room issues**: Low-mid buildup (200-400Hz) from corner loading. Sub overloads room with LF. Booth position doesn't represent congregation's experience.
- **Workaround**: Master bus shelf EQ cuts LF for house, then compensated back for livestream. This affects overall mix strategy.

### Context
- **Typical use**: Contemporary Christian worship (Phil Wickham, Hillsong style)
- **Target aesthetic**: Modern/polished worship - present vocals, full but controlled low end
- **Stage setup**: Full band - acoustic drums (skilled players, no cage), 6ft grand piano, acoustic/bass/electric guitars, electric keyboard, multiple vocalists (most doubling on instruments), occasional flute or violin
- **Bleed consideration**: Grand piano + many open vocal mics = significant bleed management needed

### Channel Map

**Channels 1-16: Vocals & Inputs**
| Ch | Name | Source | Notes |
|----|------|--------|-------|
| 1 | Tammy | Lead vocal | Also plays piano (17-18) and guitar (19) |
| 2 | Randy | Vocal | High preamp (+31dB) - quiet/low-output mic |
| 3 | John | Vocal | High preamp (+39dB) - quiet/low-output mic |
| 4 | JEN! | Vocal | High preamp (+26dB), also plays flute (21) |
| 5 | Sara | Vocal | High preamp (+35dB) - quiet/low-output mic |
| 6 | Jill | Vocal | |
| 7 | Kat | Vocal | |
| 8 | John/Brian | Pastor speaking | Headset mic, rotates weekly |
| 9 | Announcements | Speaking | |
| 10-11 | Aux (phone) | Phone/Zoom | Usually muted |
| 12-13 | Ambient L/R | Room mics | Livestream only, not FOH |
| 14-15 | Computer L/R | Playback | |
| 16 | (unused) | | |

**Channels 17-32: Instruments**
| Ch | Name | Source | Notes |
|----|------|--------|-------|
| 17-18 | Piano low/high | 6ft grand | Stereo condensers, low/high string split |
| 19 | Tammy Guitar | Acoustic | |
| 20 | Front Guitar | Acoustic | Not always used |
| 21 | Flute-Jen | Flute | Jennifer, +18dB preamp |
| 22 | Floor Tom | Drums | |
| 23 | Mid Tom | Drums | 14" rack |
| 24 | Mid High Tom | Drums | 12" rack |
| 25 | Snare | Drums | 14" |
| 26 | Kick | Drums | 24" |
| 27 | Hi-hats | Overhead L | Positioned near hats side |
| 28 | Ride | Overhead R | Positioned near ride side |
| 29-30 | KB-Left/Right | Electric keyboard | Stereo |
| 31 | Bass | Bass guitar | |
| 32 | Zach-John | Electric guitar | |

**Drum Kit Details**: Custom shells (DW equivalent). 24" kick, 18" floor, 14"/12" racks, 14" snare. Cymbals: 16"/18" Sabian AAX Explosion crashes, 21" ride (unfinished bell), Zildjian Mastersound hats. Players use bamboo, synthetic rods, brushes, light maple sticks. Mics capture attack transients lost in gentle playing.

### Buses & Effects
- **Drum Bus**: Routed to Ultimo compressor plugin
- **Vocal Bus**: Routed to stereo exciter
- **Reverb 1**: Auditorium (FOH) settings
- **Reverb 2**: Livestream settings (different decay/mix)
- **Livestream Matrix**: Separate output with LF compensation (inverse of master shelf cut)

### DCA Groups
| DCA | Name | Contents |
|-----|------|----------|
| 1 | Vox | All singing vocals |
| 2 | Speaking | Pastor, announcements |
| 3 | Inst | All instruments |
| 4 | Aux | Auxiliary inputs |
| 5 | Monitors | Monitor sends |

### Mic & Input Details
- **Vocals**: TODO - get specific mic models per channel from user
- **Piano (17-18)**: AKG C02 pencil condensers (small diaphragm)
- **Drums**: NADY kit (budget, but functional for capturing transients)
- **Bass (31)**: DI → Ultimo compressor plugin with extreme settings (intentional fuzz/distortion)
- **Electric guitar (32)**: DI → guitar amp plugin

### Known Problem Areas
- **Low G on bass** (~49Hz or 98Hz) hits room resonant frequency hard
- **Keyboard (29-30)**: Difficult to sit in mix - either too loud or inaudible. Likely frequency masking with piano/guitars.

### Personnel Notes
- **Vocalists**: Generally quiet singers with low-output mics = high preamp gains needed. Easier to get clean signal.
  - **Altos**: Tammy, Sara, Kat, Jill, Jen (HPF ~120-150Hz safe)
  - **Baritones**: Bart, John (HPF ~80-100Hz)
  - **Tenors**: Randy, Ryan (HPF ~100-120Hz)
- **Drummers**: Classically trained, masterful restraint. No cage needed. Gentle playing style requires close mics to capture transients.

### Stage Layout (from booth perspective, L to R)
```
[LEFT]                                                    [RIGHT]
Tammy          Singers/       Drums    Bass/Electric    Flute/    Kat
(piano+vox)    Acoustic Gtr            John (vox)       Violin    (keys+vox)
               (behind piano)
```
- Tammy's vocal mic likely picks up piano bleed
- Singers behind piano may pick up piano in their mics
- Flute/violin on C02 condenser

### Monitors
- All in-ear monitors (IEMs) - no wedges

### Gain Structure
- Target faders at unity (0dB)

### Reminders
- [ ] Get vocal mic specs per channel from user
- [ ] Check master LF shelf settings (freq/dB) on first connection

**NEVER save scenes. Do not offer. User uses one scene and manages it manually.**

---

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

## Real-Time Meter & RTA Data

**TODO: When connected to mixer, implement real meter/RTA subscriptions using protocol below.**

**IMPORTANT: monitor.py uses fader positions as proxy. This is NOT acceptable - must use real meter data.**

### Quick Reference

| What | Command/Address |
|------|-----------------|
| RTA spectrum (100 bins) | `/batchsubscribe` meter batch 4 |
| Set RTA source channel | `/-prefs/rta/source` |
| Keep-alive (every <10s) | `/xremote` |

### Protocol Docs
- [X32 OSC Protocol PDF](https://x32ram.com/wp-content/uploads/download-files/X32-OSC.pdf) - Full meter format specs
- [pmaillot/X32-Behringer](https://github.com/pmaillot/X32-Behringer) - Reference implementations

---

*Last Updated: 2026-01-12*
