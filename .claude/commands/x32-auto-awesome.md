# X32 Auto-Awesome

Intelligent mix optimization. Capture the current state, analyze every channel in context, and make targeted fixes — minimal changes unless something is obviously wrong.

**YOU MUST** run `/x32-debug` first if this is the first time using auto-awesome. You need verified control over all parameter types before making real changes.

## Setup

```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control" && source venv/bin/activate
```

Read the project CLAUDE.md, `docs/CHANNELS.md`, and `docs/VENUE.md` before starting. You need to know the room, the people, and the channel assignments.

## Safety

- **Always confirm before applying changes.** Present your findings and proposed changes first, then ask.
- **Small moves.** 2-3dB at a time. Never make drastic changes.
- **Never touch mute.** Read-only — report it, don't change it.
- **Respect existing room corrections.** The main bus has LF shelf cuts and a HF presence cut for the reflective ceiling. Don't flatten these.

## Step 1: Full Capture

Run a session capture with meter data:
```bash
python scripts/session_capture.py --duration 5
```

Read the full capture JSON. You need all of it — channels, buses, mains, matrices, routing, FX, meter data.

## Step 2: Identify Active Channels

Use the meter data to determine which channels have active signal (someone is playing/singing). Skip inactive channels — don't optimize a channel nobody's using today.

## Step 3: Channel-by-Channel (Bottom Up)

Go through each **active** channel. For every decision, consider the context — what are the other channels doing? Don't boost 3kHz on every vocal.

### For each channel:

**3a. Gain staging** — Compare peak level to peers of the same type. Adjust preamp trim so fader sits near unity. Fader near max = needs more preamp; near floor = too much.

**3b. HPF** — On for everything except bass and kick. Frequency per voice type (see `docs/CHANNELS.md`).

**3c. Pan** — Match stage layout (see `docs/CHANNELS.md`). Stereo pairs (keyboards 29-30, overheads 27-28) balanced L/R. **Piano low/high (17-18) is NOT a stereo pair** — string split, treat independently.

**3d. Gate** — Threshold just below quietest useful signal. Range: full gate for drums, gentler for vocals.

**3e. Compressor** — Compare actual signal level to threshold. Always squeezing = threshold too low. Never engaging = threshold too high. Adjust ratio, knee, attack/release per source type. Mix should be 100% unless parallel compression is intentional. Compensate makeup gain if you changed threshold/ratio.

**3f. EQ (RTA-informed)**
```bash
python scripts/rta_listen.py --channel N --update-session
```
- Subtractive first — cut problems, don't boost solutions
- **NEVER boost 200-400Hz** — known room buildup
- Cross-channel awareness: stacked presence boosts cause harshness. Spread or keep gentle.
- Piano low vs piano high need different EQ

## Step 4: FX Processing

Review each active FX in context of what's routed through it:

- **Exciters** (Tammy, background vocals): Timbre settings should add clarity without shrillness. Tammy's can be brighter (+10 to +15), background vocals warmer (0 to +5).
- **Drum bus compressor** (Ultimo on bus07/08): Settings should glue the kit together without squashing transients.
- **Amp sim** (electric guitar ch32): Should complement the guitar's role in the frequency lanes.
- **Reverb sends** (bus15 AudVerb, bus16 CamVerb): Keep send levels in check — each channel's send should make sense relative to the others. Lead vocal gets more reverb than piano, drums get less than vocals.

## Step 5: Bus Processing

For each active bus, check:
- **Bus EQ**: Should complement the channel EQ, not duplicate it. Bus EQ is for shaping the group as a whole.
- **Bus compressor**: Glue the group together. Threshold should engage on peaks, not constantly squeeze.
- **Bus fader levels**: These matter enormously for the livestream mix. More on this in Step 7.

## Step 6: Main Bus (FOH)

- **Look at signal strength and RTA data** for the main output
- **Compressor**: Should be gentle bus compression, catching peaks. Not slamming.
- **EQ**: Respect the existing room corrections (LF cuts, HF presence cut). Only adjust if RTA data shows a problem the current corrections aren't handling.
- **Don't touch the main fader** unless asked.

## Step 7: Livestream Mix

This is where Claude adds the most value. The engineer can't hear the livestream from the room — Claude optimizes it by the numbers.

### Signal Path
Trace every path to the livestream matrices (Cam L / Cam R):
- Channels → subgroup buses (Vocal, Drums, Acoustic, Electronic) → matrices
- Channels → main LR → matrices
- Ambient mics (ch12-13) → matrices (room feel for the stream)
- Reverb return (CamVerb bus16) → matrices

### Balance for Two Audiences
Optimize for both phone speakers and home theaters. Prioritize vocal intelligibility and clarity. Keep low end controlled but present — phone speakers can't reproduce sub-bass, so lean on upper harmonics (80-200Hz). Less reverb than FOH.

### Group Fader Levels
Calculate target levels from actual signal data. Balance vocal bus vs drum bus vs instruments vs ambient mics vs CamVerb. This is math, not guesswork.

### Matrix Processing
- **Matrix EQ**: May need different corrections than the room. The livestream doesn't have the room's acoustic problems, but it has its own (phone speaker limitations, codec artifacts).
- **Matrix compressor**: Tighter than FOH. Broadcast needs consistent levels — viewers reach for the volume less if the dynamics are controlled.

## Step 8: Verification

After all changes:
1. Run a fresh capture: `python scripts/session_capture.py --duration 5`
2. Compare before/after: `python scripts/diff_sessions.py --text`
3. Present the summary: what changed, by how much, and why
4. Ask the engineer to listen and verify
