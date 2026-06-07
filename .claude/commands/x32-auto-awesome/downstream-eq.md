# Downstream EQ Worker

> Read `.claude/commands/x32-auto-awesome/_shared.md` first, then the context brief named in your
> envelope, then follow this file.

## EQ rules (apply to this and every EQ worker)

RTA data is already in your extract (`rta_analysis` field per channel) — gathered before you were
spawned. **Do NOT run rta_listen.py yourself.**

- Subtractive first — cut problems, don't boost solutions.
- **Avoid boosting 200-400Hz for FOH** — significant room buildup. Only boost here if RTA clearly
  shows a deficit.
- **You do NOT iterate.** One thorough pass, return all suggestions.

**Value conversions** (provide both raw and human-readable in `human`):
- EQ gain: `raw = (dB + 15) / 30` (0.0 = -15dB, 0.5 = 0dB, 1.0 = +15dB)
- EQ frequency: log scale 20-20kHz. Full reference: `docs/TECHNICAL.md`.

## Scope

Main bus EQ, matrix EQ (livestream + house), remaining buses not covered by section workers (ambient,
CamVerb, AudVerb, Acoustic, Electronic), and **reverb FX engine parameters** (FX2 CamVerb, FX3 AudVerb).

**Data:** `venv/bin/python scripts/extract.py --scope eq <capture_file>` (no --channels — needs full
board; capture path in the context brief) — focus on main, all matrices, buses not owned by Vocals/
Drums EQ workers (i.e. not Voices, drums, or lead vocal buses).
**Docs:** `docs/CHANNELS.md`, `docs/VENUE.md`, `docs/CORRECTIONS.md`, `docs/TECHNICAL.md`

**Note:** FOH processing bus EQ (Voices bus, drums bus) is handled by the Vocals EQ and Drums EQ
workers respectively. Lead vocal bus (e.g. "Tammy") is handled by the Vocals EQ worker. Any bus named
"Not used" is decommissioned — skip it.

**Work order:**
1. **Main bus EQ** — Respect existing room corrections (LF shelf cuts, HF presence cut). Only suggest
   changes if something is clearly wrong or fighting upstream corrections. Check VENUE.md for known
   room problems.
2. **Matrix EQ** — Optimize for each output's audience:
   - Cam L/R (mtx03/04): livestream. Phone speakers can't reproduce sub-bass — boost upper harmonics
     (80-200Hz) instead. Tame sibilance (5-8kHz). Slight presence lift for vocal intelligibility.
   - Mono House (mtx01): room PA supplement. Similar to main but mono-compatible.
   - Foyer (mtx02): background listening. Roll off lows, gentle presence.
   - Assisted Listening (mtx05): inactive, skip.
3. **Livestream bus EQ** — Acoustic bus, Electronic bus (find by name). Shape for livestream matrices.
4. **Remaining bus EQ** — Ambient bus, CamVerb, AudVerb. Shape for their purpose (reverb return EQ
   should complement, not duplicate, channel reverb sends).
5. **Reverb FX parameters** — Evaluate the Hall Reverb engine settings for both reverb FX slots.
   Parameters are in the `fx` section of the extract. See `docs/TECHNICAL.md` for Hall Reverb
   parameter mapping (par/01-12).
   - **FX3 — AudVerb** (AudVerb bus → FX3, fxrtn03 → main LR): FOH reverb. Should complement the room
     acoustics — check VENUE.md for room character. Decay and size should match the room (too long
     washes out speech intelligibility, too short sounds dry). Damping should tame high-frequency
     buildup. Pre-delay helps preserve vocal clarity.
   - **FX2 — CamVerb** (CamVerb bus → FX2, fxrtn02 → livestream matrices): Livestream reverb.
     Livestream has NO natural room sound, so this reverb creates the entire sense of space. Can be
     slightly longer/wetter than AudVerb. Higher diffusion smooths the tail for headphone/speaker
     listeners. Hi-cut can be lower than AudVerb since livestream doesn't need air to fill a room.
   - **Relationship**: CamVerb and AudVerb serve different audiences. Don't assume they should match —
     the room already adds reverb to FOH, so AudVerb supplements while CamVerb creates from scratch.
   - OSC addresses: `/fx/2/par/XX` (CamVerb), `/fx/3/par/XX` (AudVerb). Values are 0.0-1.0 normalized.

Write your changes to the output file (JSON, per `_shared.md`). Return one line:
`downstream-eq: N changes` / `downstream-eq: clean` / `downstream-eq: error <reason>`.
