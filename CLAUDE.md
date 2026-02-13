# X-32 Mixer Control

**CRITICAL: Users are sound engineers, not developers. Speak plain English about music and sound. YOU run all commands - never ask users to run scripts.**

## Safety Rules

- **NEVER change during live service** unless told "we're live, go ahead"
- **NEVER save scenes** - user manages one scene manually
- **Small moves** - 2-3dB at a time
- **Always confirm** before executing

## First Run / Debugging

**Scripts were developed without live mixer testing (Jan 2026).** If something fails or data looks wrong:

1. **Fix it yourself** - Don't ask the user to debug
2. **The user is a sound engineer** - They can tell you "that's not right" but they shouldn't have to read code
3. **See `docs/TECHNICAL.md`** for OSC addresses, known quirks, and debugging details

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

### 1. Start of Session (Capture → Analyze → Suggest)
Run `/x32-capture` when the user says "let's get started" or similar. This:
1. **Captures** everything (32 channels, 16 buses, 8 FX, routing, gain staging)
2. **Analyzes** the capture automatically (EQ issues, HPF, masking, gain staging, room rules)
3. **Presents findings** in plain English with available fixes

Output is saved to `captures/session_YYYY-MM-DD_HH-MM-SS.json`.

### 2. Applying Fixes
Findings from analyze.py include a `fix` field with ready-to-run `control.py` commands:
- Present fixes in plain English (never show raw commands to the user)
- Ask "Want me to apply any of these?" and wait for approval
- Run the fix command, confirm what changed, ask them to listen
- Findings without `fix` (HPF, compressor ratio, preamp gain) require manual adjustment on the board

### 3. Answering Questions
**Use the session capture data.** Don't re-query the mixer unless you need fresh real-time info.

- "What's Tammy's EQ?" → Look up ch01 in session capture
- "Where does the kick go?" → Check ch26 routing/sends in session capture
- "What's on FX4?" → Look up fx4 in session capture

### 4. RTA (Frequency Analysis)
When user asks about frequencies ("what's the kick hitting?"), run RTA:
```bash
python scripts/rta_listen.py --channel 26 --update-session
```

**ALWAYS use `--update-session`** - this splices RTA results back into the session capture so you don't have to re-listen later.

### 5. Data Freshness
- Session capture >24 hours old? Suggest running `/x32-capture` for today
- The rta_listen script warns automatically if capture is stale

## Natural Language → Actions

| User says | You do |
|-----------|--------|
| "let's get started" | Run `/x32-capture` (captures + analyzes + suggests fixes) |
| "check Ryan's signal path" | Look up in session capture |
| "what frequencies is the kick hitting?" | Run rta_listen.py --channel 26 --update-session |
| "turn up the kick" | Raise fader ch26 |
| "Tammy's too loud" | Lower fader ch1 |
| "snare needs more snap" | Boost EQ 2-5kHz on ch25 |
| "bass is muddy" | Cut EQ 200-400Hz on ch31 |
| "piano is boxy" | Cut EQ 300-500Hz on ch17-18 |

## Quick Commands

```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control" && source venv/bin/activate
```

| Task | Command |
|------|---------|
| Session capture | `python scripts/session_capture.py --duration 5` |
| Analyze mix | `python scripts/analyze.py` (add `--text` for readable output) |
| Compare sessions | `python scripts/diff_sessions.py` (add `--text` for readable) |
| RTA frequency | `python scripts/rta_listen.py --channel 26 --update-session` |
| Query channel | `python scripts/query.py --channel 26 --eq` |
| Control | `python scripts/control.py --channel 26 --fader -5dB` |

**IMPORTANT: ALWAYS use `--update-session` with rta_listen.py.** Full syntax in `docs/COMMANDS.md`.

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
