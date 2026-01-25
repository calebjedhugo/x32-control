# X-32 Mixer Control

**CRITICAL: Users are sound engineers, not developers. Speak plain English about music and sound. YOU run all commands - never ask users to run scripts.**

## First Run / Debugging

**Scripts were developed without live mixer testing (Jan 2026).** If something fails or data looks wrong:

1. **Fix it yourself** - Don't ask the user to debug. Read the script, fix the issue, re-run
2. **The user is a sound engineer** - They can tell you "that's not right, the compressor threshold is actually -20" but they shouldn't have to read code

**Known risk areas** (likely to need debugging):
- **EQ/dynamics values wrong or all defaults**: The behringer-mixer library doesn't load these. We query via raw OSC in session_capture.py. OSC addresses or response parsing may be wrong. Cross-reference with `docs/TECHNICAL.md` and the [X32 OSC spec](https://behringer.world/wiki/doku.php?id=x32:osc-protocol:ch)
- **Channel/bus indexing off-by-one**: X32 uses 01-32, code might use 0-31 or 1-32 inconsistently
- **Compressor/gate values not matching mixer**: Check the OSC address format (e.g., `/ch/01/dyn/thr` vs `/ch/01/dynamics/threshold`)
- **RTA data empty or garbage**: Meter blob parsing in rta_listen.py might have wrong offsets

**How to debug**:
1. Run `python scripts/query.py --channel X --eq` and compare to what the mixer actually shows
2. If wrong, read session_capture.py's `capture_channel_settings()` function
3. Check OSC addresses against the spec, fix, re-run
4. Same approach for dynamics, routing, FX

## Quick Reference Docs
- `docs/CAPTURE.md` - Session capture and RTA workflow details
- `docs/COMMANDS.md` - Command reference and technical syntax
- `docs/VENUE.md` - Room acoustics, PA, known issues
- `docs/CHANNELS.md` - Detailed channel info, personnel, stage layout
- `docs/TECHNICAL.md` - Developer/debug notes (OSC addresses, library workarounds)
- `notes/2026-01-21-session.md` - Latest session notes (bugs found, EQ changes, channel assignments)

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

## Session Workflow

### 1. Start of Session
Run `/x32-capture` when the user says "let's get started" or similar. This captures EVERYTHING:
- All 32 channel settings (EQ, dynamics, preamp, routing)
- All 16 bus settings
- All 8 FX slots (type, parameters, routing)
- Gain staging analysis (who's hot, who's quiet)
- Signal paths (e.g., vocals → vocal bus → exciter → main)

Output is saved to `captures/session_YYYY-MM-DD_HH-MM-SS.json`. **Read this file** to have full context.

### 2. Answering Questions
**Use the session capture data.** Don't re-query the mixer unless you need fresh real-time info.

- "What's Tammy's EQ?" → Look up ch01 in session capture
- "Where does the kick go?" → Check ch26 routing/sends in session capture
- "What's on FX4?" → Look up fx4 in session capture

### 3. RTA (Frequency Analysis)
When user asks about frequencies ("what's the kick hitting?"), run RTA:
```bash
python scripts/rta_listen.py --channel 26 --update-session
```

**ALWAYS use `--update-session`** - this splices RTA results back into the session capture so you don't have to re-listen later.

### 4. Data Freshness
- Session capture >24 hours old? Suggest running `/x32-capture` for today
- The rta_listen script warns automatically if capture is stale
- RTA data still gets spliced even into old captures (better than nothing)

## Natural Language → Actions

| User says | You do |
|-----------|--------|
| "let's get started" | Run `/x32-capture` |
| "check Ryan's signal path" | Look up in session capture |
| "what frequencies is the kick hitting?" | Run rta_listen.py --channel 26 --update-session |
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

# Session capture (EVERYTHING - settings, routing, gain staging)
python scripts/session_capture.py --duration 5

# RTA frequency analysis (on-demand, single channel)
# ALWAYS use --update-session to splice results into session capture
python scripts/rta_listen.py --channel 26 --update-session                    # 15 seconds
python scripts/rta_listen.py --channel 26 --until-confident --update-session  # Auto-stop when stable

# Query (if you need fresh data mid-session)
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
