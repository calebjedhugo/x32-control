# X-32 Mixer Control

**CRITICAL: Users are sound engineers, not developers. Speak plain English about music and sound. YOU run all commands - never ask users to run scripts.**

## Quick Reference Docs
- `docs/VENUE.md` - Room acoustics, PA, known issues
- `docs/CHANNELS.md` - Detailed channel info, personnel, stage layout
- `docs/TECHNICAL.md` - Developer/debug notes (OSC addresses, library workarounds)

## People
*Channel assignments vary - check most recent capture*

| Person | Role |
|--------|------|
| Tammy | Lead vocalist, guitar |
| John | Vocals, sometimes electric guitar |
| Sara | Vocals |
| Bart | Vocals |
| Kat | Vocals |
| Jen | Flute, sometimes vocals |
| Zach | Electric guitar |

## FX Routing

| FX Slot | Effect | Routed to |
|---------|--------|-----------|
| FX 4 | Exciter | Tammy only |
| FX 7 | Amp Sim | Electric guitar (ch32) |
| FX 8 | Exciter | Background vocals |

**Exciter Timbre**: -48 to +48 scale (0 = neutral)
- Tammy: +10 to +15 (brighter to cut through)
- Background vocals: 0 to +5 (warm, blends)

## Natural Language → Actions

| User says | You do |
|-----------|--------|
| "capture the mix" | Run capture --rta-sweep |
| "turn up the kick" | Raise fader ch26 |
| "Tammy's too loud" | Lower fader ch1 |
| "snare needs more snap" | Boost EQ 2-5kHz on ch25 |
| "bass is muddy" | Cut EQ 200-400Hz on ch31 |
| "piano is boxy" | Cut EQ 300-500Hz on ch17-18 |

## Safety Rules

- **NEVER change during live service** unless told "we're live, go ahead"
- **Small moves** - 2-3dB at a time
- **Always confirm** before executing
- **NEVER save scenes** - user manages one scene manually

## Commands

```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control" && source venv/bin/activate

# Capture
python scripts/capture.py --duration 30 --rta-sweep

# Query
python scripts/query.py --channel 26 --eq
python scripts/query.py --channel 26 --dynamics
python scripts/query.py --fx 1

# Control (always confirm first)
python scripts/control.py --channel 26 --fader -5dB
python scripts/control.py --channel 26 --eq-band 2 --gain 0.6
python scripts/control.py --fx 1 --fx-param 1 --fx-value 0.5
```

## Room Issues
- Low-mid buildup (200-400Hz) from corner loading
- Overpowered sub
- Master bus has LF shelf cut for house

## Current Mix Approach (Jan 2026)

**Frequency lanes** to reduce fighting:
- Piano: warm mids, presence (2-4kHz)
- Keyboard: sparkle (5kHz+), cut mids
- Electric guitar: low-end warmth via amp sim, cut mids

**Vocals**: gentle presence boosts only - aggressive boosts stack when everyone sings.

---
*See docs/*.md for detailed reference*
