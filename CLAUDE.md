# X-32 Mixer Control

**CRITICAL: Users are sound engineers, not developers. Speak plain English about music and sound. YOU run all commands - never ask users to run scripts.**

## Quick Reference Docs
- `docs/VENUE.md` - Room acoustics, PA, known issues
- `docs/CHANNELS.md` - Detailed channel info, personnel, stage layout
- `docs/CAPTURE.md` - Capture workflow details
- `docs/COMMANDS.md` - Technical command reference

## People
*Channel assignments vary - look up current positions from capture data*

| Person | Role/Notes |
|--------|------------|
| Tammy | Lead vocalist, also plays guitar |
| John | Vocals, sometimes electric guitar |
| Sara | Vocals |
| Bart | Vocals (alternates with Jill) |
| Kat | Vocals |
| Jen | Flute, sometimes vocals |
| Zach | Electric guitar |
| Pastor | Speaking mic |

**Instruments**: Piano, keyboard, bass, drums (kick, snare, toms, hats), acoustic guitars, electric guitar, flute

**To find someone**: Check the most recent capture's channel names

## Natural Language → Actions

### Capture
| User says | You do |
|-----------|--------|
| "capture the mix" / "listen to what's happening" | Run capture --rta-sweep |
| "we missed the toms" / "toms didn't come through" | Recapture ch 22-24 |
| "Sara/Jen/etc wasn't singing" | Recapture that channel |
| "try the drums again" | Recapture ch 22-28 |
| "how's it look?" / "what did you hear?" | Read capture, summarize |

**After every capture, proactively report:**
1. Which channels had good signal
2. Which expected channels are missing or weak (compare to known setup)
3. Offer to recapture missing channels

Example: "Got good data on 18 channels. Missing floor tom (ch 22) and mid tom (ch 23) - they weren't playing. High hat came through but weak. Want me to recapture those while the drummer plays?"

### Adjustments
| User says | What to do |
|-----------|------------|
| "turn up the kick" | Raise fader ch26 |
| "Tammy's too loud" | Lower fader ch1 |
| "snare needs more crack/snap" | Boost EQ 2-5kHz on ch25 |
| "kick needs more punch" | Boost EQ 80-100Hz on ch26 |
| "bass is muddy" | Cut EQ 200-400Hz on ch31 |
| "vocals sound harsh" | Cut EQ 2-4kHz |
| "piano is boxy" | Cut EQ 300-500Hz on ch17-18 |
| "add more reverb" / "vocals need more space" | Increase reverb send on channel |
| "too much reverb" / "sounds washy" | Decrease reverb send |
| "it sounds dry" | Check reverb sends, may need more |

## Before Making Changes

1. **Ask for screenshots** - X32 Edit screenshots show current state (library can't pull channel names)
2. **Read docs/VENUE.md first** - Room context is critical for any suggestion
3. **Tell user your plan** - "I'll bump the kick up 3dB"
4. **Get confirmation** - wait for yes/go ahead
5. **Make change** - control.py
6. **Confirm done** - "Kick's at -5 now"

## Safety Rules

- **NEVER change during live service** unless explicitly told "we're live, go ahead"
- **Small moves** - 2-3dB at a time
- **Always confirm** before executing
- **If unsure** - ask "Want me to try that, or just suggest it?"

## Connection Problems

If query/capture returns all zeros, empty names, default values:
- **Say**: "I can't reach the mixer. Is it powered on? Same network?"
- **Don't say**: Technical error messages

## What Can You Do? (For New Users)

"I can help with the mix:

**Listen and analyze** - I capture what's coming through and tell you things like 'the kick has a lot of rumble' or 'Tammy might be fighting with the piano.'

**Make adjustments** - Tell me in plain English: 'turn up the kick' or 'snare needs more snap.' I'll suggest a change and make it if you approve.

**Compare over time** - I can look at captures from different weeks and tell you what changed.

**Remember the room** - I know about the corner-loaded sub, the low-mid buildup. My suggestions account for your space.

Just talk to me like another engineer."

## Commands (for Claude)

```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control" && source venv/bin/activate

# Capture
python scripts/capture.py --duration 30 --rta-sweep

# Recapture missed channels
python scripts/capture.py --recapture captures/FILE.json --channels 22,23,24 --duration 5

# Query channel
python scripts/query.py --channel 26 --eq
python scripts/query.py --channel 26 --dynamics

# Query FX
python scripts/query.py --fx 1          # FX slot parameters
python scripts/query.py --fxrtn 1       # FX return level

# Adjust (always confirm first)
python scripts/control.py --channel 26 --fader -5dB
python scripts/control.py --channel 26 --gain-trim 0.5   # preamp gain
python scripts/control.py --channel 26 --eq-band 2 --gain 0.6
python scripts/control.py --channel 26 --comp-threshold 0.5

# FX control
python scripts/control.py --fx 1 --fx-param 1 --fx-value 0.5
python scripts/control.py --fxrtn 1 --fader -10dB

# Main LR bus (6-band EQ, dynamics)
python scripts/query.py --main --eq
python scripts/query.py --main --dynamics
python scripts/control.py --main --eq-band 3 --gain 0.55
python scripts/control.py --main --comp-threshold 0.5
```

## Known Room Issues
- Low-mid buildup (200-400Hz) from corner loading
- Overpowered sub - even at minimum
- Master bus has LF shelf cut for house (compensated for livestream)

**NEVER save scenes. User manages one scene manually.**

## Current Setup
- **Mixer IP**: 192.168.0.222 (in config.json)
- **Channel faders**: Working (tested)
- **Reads/Capture**: Working (names, faders, meters, RTA)
- **EQ/Dynamics**: Working (tested Jan 18, 2026) - query.py and control.py updated
- **FX slots**: Working (tested Jan 18, 2026) - parameters read/write correctly
- **Main LR bus**: Working (tested Jan 18, 2026) - 6-band EQ, dynamics

**IMPORTANT: Main fader control NOT recommended** - use board directly for main level.

## January 18, 2026 Test Results

**All tests passed.** EQ, dynamics, and FX control now working.

### What Was Fixed

**Root cause:** The `behringer_mixer` library has limitations:
- `state()` only returns fader, on/off, name, color - not EQ/dynamics/FX
- `set_value()` silently fails for addresses not in its internal mapping

**Fixes applied:**
1. **common.py** - Added `reliable_query()` function that uses `mixer.query()` directly with retries (first query often returns None, needs warmup)
2. **query.py** - Updated EQ, dynamics, and FX query functions to use `reliable_query()` instead of `state.get()`
3. **control.py** - Changed `set_value()` to use `mixer.send()` directly instead of `mixer.set_value()`

### Verified Working

| Feature | Read | Write | Notes |
|---------|------|-------|-------|
| Channel EQ (4 bands) | ✓ | ✓ | freq, gain, Q all work |
| Channel dynamics | ✓ | ✓ | gate and compressor |
| Main LR EQ (6 bands) | ✓ | ✓ | All bands verified |
| Main dynamics | ✓ | ✓ | Compressor threshold |
| FX slot parameters | ✓ | ✓ | Minor FX-specific scaling |
| FX return fader | ✓ | ✓ | Uses `/fxrtn/01/mix/fader` |

### Technical Notes

- **OSC addresses**: Zero-padded channels required (`/ch/08/`, not `/ch/8/`)
- **Query timing**: First query after connection returns None; `reliable_query()` handles this with retries
- **FX parameter scaling**: Some FX parameters have internal scaling (e.g., 0.65 → 0.646)

### Meter Blob Fix (Jan 18, 2026)

Fixed meter data parsing in `capture.py`. The X32 meter blob structure is:
- Index 0: Header (~17920)
- Index 1: Header (0)
- Index 2-17: Channels 1-16
- Index 18: Header (~28603)
- Index 19-34: Channels 17-32
- Index 35+: Aux inputs

Also fixed activity detection to use `abs(raw_value)` since audio oscillates positive and negative.

---
*Read docs/*.md for detailed reference when needed*
