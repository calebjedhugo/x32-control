# Instruments EQ Worker

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

EQ + HPF for instrument channels and instrument buses (find by name "Acoustic", "Electronic"). Also
evaluates amp sim FX tone.

**Data:** `venv/bin/python scripts/extract.py --scope eq --channels <your_channel_numbers> <capture_file>`
(channel list + capture path in the context brief). Also examine Acoustic + Electronic buses, FX amp
sim in the output.
**Docs:** `docs/CHANNELS.md` (instrument details, stereo pairs/splits), `docs/VENUE.md`, `docs/CORRECTIONS.md`, `docs/TECHNICAL.md`

**Work order:**
1. **Amp sim tone** — Check FX7 parameters. Identify the electric guitar channel by label. Complement
   guitar's frequency lane (low warmth, cut mids).
2. **Channel HPF** — Piano: 25-80Hz. Acoustic guitar: 60-150Hz. Flute: 150-300Hz. Keys: 40-80Hz.
   Bass: OFF. Electric guitar: 60-100Hz. Violin: 150-250Hz.
3. **Channel EQ** — Use RTA data. Frequency lanes:
   - Piano: warm mids (400Hz-2kHz), presence (2-4kHz). Low vs high need different EQ.
   - Keyboard: sparkle (3kHz+), cut mids
   - Electric guitar: low warmth via amp sim, cut mids
   - Bass: don't fight kick in sub range
   - Flute: presence (2-4kHz), air (6-8kHz)
4. **Bus EQ** — Acoustic bus (find by name): shape acoustic group. Electronic bus (find by name):
   shape electronic group.

Write your changes to the output file (JSON, per `_shared.md`). Return one line:
`instruments-eq: N changes` / `instruments-eq: clean` / `instruments-eq: error <reason>`.
