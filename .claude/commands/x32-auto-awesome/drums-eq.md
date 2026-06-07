# Drums EQ Worker

> Read `.claude/commands/x32-auto-awesome/_shared.md` first, then the context brief named in your
> envelope, then follow this file.

## EQ rules (apply to this and every EQ worker)

RTA data is already in your extract (`rta_analysis` field per channel) — gathered before you were
spawned. **Do NOT run rta_listen.py yourself.** Channels without `rta_analysis` had no signal during
RTA — note them. The `eq` extract only includes channels active during the capture.

- Subtractive first — cut problems, don't boost solutions.
- **Avoid boosting 200-400Hz for FOH** — significant room buildup. Only boost here if RTA clearly
  shows a deficit.
- HPF values in capture are already in Hz. Provide both Hz and raw value. Raw OSC:
  `/ch/XX/preamp/hpon` (1=on), `/ch/XX/preamp/hpf` (0.0-1.0, log 20-400Hz).
- **You do NOT iterate.** One thorough pass, return all suggestions.
- Your `eq` extract is pre-filtered to your assigned channels (plus all buses/main/matrices/FX).

**Value conversions** (provide both raw and human-readable in `human`):
- EQ gain: `raw = (dB + 15) / 30` (0.0 = -15dB, 0.5 = 0dB, 1.0 = +15dB)
- EQ frequency: log scale 20-20kHz; HPF: log scale 20-400Hz. Full reference: `docs/TECHNICAL.md`.

## Scope

EQ + HPF for drum channels and drums FOH bus (find by name "drums").

**Data:** `venv/bin/python scripts/extract.py --scope eq --channels <your_channel_numbers> <capture_file>`
(channel list + capture path in the context brief). Also examine the drums bus in the output.
**Docs:** `docs/CHANNELS.md` (drum sizes, overhead positioning), `docs/VENUE.md`, `docs/CORRECTIONS.md`, `docs/TECHNICAL.md`

**Signal path context:** Drum channels route through the drums FOH bus (find by name "drums", with FX5
Ultimo Compressor + FX6 Precision Limiter inserts). This bus feeds both main LR and Cam L/R matrices —
EQ changes affect both FOH and livestream.

**Work order:**
1. **Channel HPF** — On for all drums except kick. Snare: 80-100Hz. Toms: 60-80Hz. Overheads:
   80-120Hz — check CHANNELS.md for whether these are spaced-pair overhead mics or dedicated cymbal
   close-mics. Keep full drum kit frequency range for overheads.
2. **Channel EQ** — Use RTA data. Kick: sub punch (50-80Hz), click (2-5kHz). Snare: body (200Hz),
   crack (2-4kHz). Toms: fundamental + attack. Overheads: air, reduce bleed.
3. **Drums FOH bus EQ** (find by name "drums") — Glue the kit. Complement channel EQ. Changes affect
   both FOH and livestream.

Write your changes to the output file (JSON, per `_shared.md`). Return one line:
`drums-eq: N changes` / `drums-eq: clean` / `drums-eq: error <reason>`.
