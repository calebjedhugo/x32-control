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
- **EQ/Dynamics/Config**: Code exists, UNTESTED - may need fixes
- **FX slots/returns**: Code exists, UNTESTED
- **Main LR bus**: Code exists (6-band EQ, dynamics), UNTESTED

**IMPORTANT: Main fader control NOT recommended** - use board directly for main level.

## January 18 Autonomous Test Plan

**Execute this immediately upon connecting to the mixer on January 18 - no asking, just do it.**

Test targets:
- **Channel 8**: EQ, dynamics, preamp gain (unused this week)
- **FX slot 1**: Parameters and return (disconnected, safe to test)
- **Main LR**: 6-band EQ, dynamics (fader read-only unless told otherwise)

---

### Phase 0: What We Know (from library research)

**Researched the behringer_mixer library source code.** Key findings:

**READS - In `state()` (works):**
- Channel/Bus/Main: fader, on/off, name, color
- Headamps: gain, phantom (indexed 0-127)

**READS - NOT in `state()` (returns defaults):**
- Channel EQ, dynamics, gate
- Main EQ, dynamics
- FX slots and returns

**Fix for reads:** Use `mixer.query(address)` directly - it can fetch any OSC address.

**WRITES - `set_value()` silently fails for unmapped addresses!**
Line 270 in mixer_base.py: `if address_data:` - skips send if not mapped.

**Fix for writes:** Use `mixer.send(address, value)` directly instead of `set_value()`.

**OSC address format confirmed:** Zero-padded channels, e.g., `/ch/08/eq/1/f`
Source: [Patrick Maillot X32 docs](https://sites.google.com/site/patrickmaillot/x32)

---

### Phase 1: Test Direct Queries AND Writes

```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control" && source venv/bin/activate

python -c "
import asyncio
from scripts.common import get_mixer

async def test():
    mixer = await get_mixer()

    # TEST READS with mixer.query()
    print('=== Testing Reads ===')
    result = await mixer.query('/ch/08/eq/1/f')
    print(f'Ch8 EQ band 1 freq: {result}')

    result = await mixer.query('/ch/08/eq/1/g')
    print(f'Ch8 EQ band 1 gain: {result}')
    original_gain = result[0] if result else 0.5

    result = await mixer.query('/main/st/eq/1/g')
    print(f'Main EQ band 1 gain: {result}')

    result = await mixer.query('/fx/1/par/01')
    print(f'FX1 param 1: {result}')

    # TEST WRITES with mixer.send() (not set_value!)
    print('=== Testing Write ===')
    test_value = 0.55
    await mixer.send('/ch/08/eq/1/g', test_value)
    await asyncio.sleep(0.1)  # Wait for mixer to process

    result = await mixer.query('/ch/08/eq/1/g')
    print(f'After write - Ch8 EQ band 1 gain: {result}')

    # Restore original
    await mixer.send('/ch/08/eq/1/g', original_gain)
    print(f'Restored to: {original_gain}')

    await mixer.stop()

asyncio.run(test())
"
```

**If reads return `None` or wrong values:** Check `mixer.info_response` timing - may need longer sleep.
**If writes don't change values:** Check OSC address format or try without zero-padding.

---

### Phase 2: Fix Scripts (if Phase 1 works)

**Fix query.py** - Replace `state.get()` with `mixer.query()` for EQ, dynamics, FX:
```python
# Before (broken):
value = state.get(f"{ch_addr}/eq/{band}/f", 0.5)

# After (works):
result = await mixer.query(f'/ch/{ch_num:02d}/eq/{band}/f')
value = result[0] if result else 0.5
```

**Fix control.py** - Replace `mixer.set_value()` with `mixer.send()` for EQ, dynamics, FX:
```python
# Before (silently fails):
await mixer.set_value(f"{target_addr}/eq/{band}/g", value)

# After (works):
await mixer.send(f'/ch/{ch_num:02d}/eq/{band}/g', value)
```

---

### Phase 3: Test Writes (only after reads work)

For each parameter type: query → small change → query to verify → restore

**Channel 8:**
```bash
# EQ
python scripts/query.py --channel 8 --eq
python scripts/control.py --channel 8 --eq-band 2 --gain 0.55
python scripts/query.py --channel 8 --eq
# restore original

# Dynamics
python scripts/query.py --channel 8 --dynamics
python scripts/control.py --channel 8 --comp-threshold 0.55
python scripts/query.py --channel 8 --dynamics
# restore original

# Preamp gain
python scripts/query.py --channel 8
python scripts/control.py --channel 8 --gain-trim 0.55
python scripts/query.py --channel 8
# restore original
```

**FX Slot 1:**
```bash
python scripts/query.py --fx 1
python scripts/control.py --fx 1 --fx-param 1 --fx-value 0.55
python scripts/query.py --fx 1
# restore original

python scripts/query.py --fxrtn 1
python scripts/control.py --fxrtn 1 --fader -10dB
python scripts/query.py --fxrtn 1
# restore original
```

**Main LR:**
```bash
python scripts/query.py --main --eq
python scripts/control.py --main --eq-band 3 --gain 0.55
python scripts/query.py --main --eq
# restore original

python scripts/query.py --main --dynamics
python scripts/control.py --main --comp-threshold 0.55
python scripts/query.py --main --dynamics
# restore original
```

### Root Cause (confirmed via library source)

**In library's `state()`:** fader, on/off, name, color (these work)

**NOT in library's `state()`:** EQ, dynamics, FX (returns defaults because data isn't fetched)

**Solution:** Use `mixer.query(address)` instead of `state.get()` for EQ/dynamics/FX. Phase 1 tests this.

### Success Criteria:
- All reads return real values (not defaults)
- All writes are reflected when re-queried
- Update this section with results

---
*Read docs/*.md for detailed reference when needed*
