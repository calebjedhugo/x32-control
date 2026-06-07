# Vocals EQ Worker

> Read `.claude/commands/x32-auto-awesome/_shared.md` first, then the context brief named in your
> envelope, then follow this file.

## EQ rules (apply to this and every EQ worker)

RTA data is already in your extract (`rta_analysis` field per channel) — gathered before you were
spawned. **Do NOT run rta_listen.py yourself.** Channels without `rta_analysis` had no signal during
RTA — note them so the apply worker can flag for a future pass. The `eq` extract only includes
channels that were active during the capture; if a musician played during RTA but not the capture,
their RTA data won't appear.

- Subtractive first — cut problems, don't boost solutions.
- **Avoid boosting 200-400Hz for FOH** — significant room buildup. Only boost here if RTA clearly
  shows a deficit.
- HPF values in capture are already in Hz. For suggestions, provide both Hz and raw value. Raw OSC:
  `/ch/XX/preamp/hpon` (1=on), `/ch/XX/preamp/hpf` (0.0-1.0, log 20-400Hz).
- **You do NOT iterate.** One thorough pass, return all suggestions. The orchestrator handles iteration.
- Your `eq` extract is pre-filtered to your assigned channels (plus all buses/main/matrices/FX).
  Analyze all channels in the output. The Downstream worker handles main/bus/matrix EQ.

**Value conversions** (provide both raw and human-readable in `human`):
- EQ gain: `raw = (dB + 15) / 30` (0.0 = -15dB, 0.5 = 0dB, 1.0 = +15dB)
- EQ frequency: log scale 20-20kHz (see `docs/TECHNICAL.md`)
- HPF: log scale 20-400Hz
- Full reference: `docs/TECHNICAL.md`

## Scope

EQ + HPF for vocal channels, lead vocal livestream bus (find by name, e.g. "Tammy"), and Voices FOH
bus (find by name "Voices"). Also evaluates exciter FX tone.

**Data:** `venv/bin/python scripts/extract.py --scope eq --channels <your_channel_numbers> <capture_file>`
(channel list + capture path in the context brief). Also examine Voices bus, lead vocal bus, FX
exciters in the output.
**Docs:** `docs/CHANNELS.md` (voice types, lead vs BGV), `docs/VENUE.md`, `docs/CORRECTIONS.md`, `docs/TECHNICAL.md`

**Signal path context:** The lead vocal routes directly to main LR (`st=1`) with FX4 exciter as
channel insert — NOT in the Voices bus. Other vocals route through the Voices bus (find by name) with
FX8 exciter to both main LR and Cam L/R matrices. The lead vocal has a dedicated livestream bus (find
by name, e.g. "Tammy") for independent matrix send level. Identify the lead vocal by checking which
vocal channel has `routing.main_lr = true` and a channel insert (FX4).

**Work order:**
1. **Exciter tone** — Two exciters affect vocals:
   - **FX4 (lead vocal exciter)**: Insert on lead vocal channel. Affects both FOH and livestream.
     Dual Exciter. Target Timbre High (par/08) +10 to +15. OSC 0.6-0.65.
   - **FX8 (Voices FOH bus insert)**: Insert on Voices bus — processes non-lead vocals to FOH AND
     livestream. Check `type_name` in extract: if "Dual Exciter" use par/08 (Timbre High), if "Stereo
     Exciter" use par/04 (Timbre). Target 0 to +5 (warm — it affects every voice except lead).
     OSC 0.5-0.55.
   - Formula: `osc_value = (timbre + 50) / 100`
2. **Channel HPF** — On for all vocals. Alto: 120-150Hz. Baritone: 80-100Hz. Tenor: 100-120Hz. Look
   up voice type in CHANNELS.md.
3. **Channel EQ** — Use RTA data. Gentle presence boosts only (stacked boosts across singers cause
   harshness). Lead vocal gets priority for presence range.
4. **Lead vocal livestream bus EQ** (find by name, e.g. "Tammy") — Shapes lead vocal for livestream
   only. Complement channel EQ and FX4 exciter.
5. **Voices FOH bus EQ** (find by name "Voices") — Shapes non-lead vocals for both FOH and livestream.
   Complement channel EQ and FX8 exciter — don't duplicate.

Write your changes to the output file (JSON, per `_shared.md`). Return one line:
`vocals-eq: N changes` / `vocals-eq: clean` / `vocals-eq: error <reason>`.
