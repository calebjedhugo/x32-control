# Instruments Metering Worker

> Read `.claude/commands/x32-auto-awesome/_shared.md` first, then the context brief named in your
> envelope, then follow this file.

**Scope**: Preamp + dynamics + reverb sends for active instrument channels.

**Data:** `venv/bin/python scripts/extract.py --scope metering --channels <instrument_channels> <capture_file>`
(your channel list and the capture file path are in the context brief)
**Docs:** `docs/CHANNELS.md` (instrument details, mic type, DI vs mic), `docs/CORRECTIONS.md`, `docs/TECHNICAL.md`

The context brief lists your channels + labels (e.g. "ch17 Piano Lo, ch18 Piano Hi, ch31 Bass,
ch32 E-Guitar"). Read `docs/CHANNELS.md` for per-channel context — instrument details, mic/DI info,
stereo pairs vs splits.

For each active instrument channel:
1. **Preamp/gain staging** — Compare current peak to the instrument target range; nudge trim to bring
   it in range. Skip channels with `meter_issue`.
2. **Gate** — Check if enabled (`on` field). Generally not needed. Only if bleed is a problem.
3. **Compressor** — Check if enabled (`on` field). Ratio 2:1-5:1 most instruments. Bass 3:1-10:1.
   Piano 2:1-4:1.
4. **Bass fuzz tone (FX1 — Ultimo Compressor)** — The bass channel uses an Ultimo Compressor as a
   channel insert for **tonal effect, not dynamics**. Identify the bass channel by label. Check the
   `insert` field — it should show `on: true, fx_slot: 1`. If the insert is off or on the wrong
   channel, flag it. Evaluate FX1 parameters in the `fx` section of the extract (see `docs/TECHNICAL.md`
   for Ultimo parameter mapping). Use the bass `meter_peak` to judge how hard the signal is driving
   the Ultimo (more level = more saturation/fuzz). Does it give the bass presence and grit without
   muddying the low end? Complement the bass channel EQ and respect the bass/kick frequency lane
   separation. OSC: `/fx/1/par/XX`.
5. **Reverb sends** — Check sends to reverb buses (find by name: "AudVerb" for FOH, "CamVerb" for
   livestream) in the channel's `sends` data. Use the bus number from the capture data for OSC.
   - Piano: moderate reverb (adds space and sustain, especially for grand piano).
   - Acoustic guitar: light-to-moderate reverb.
   - Flute: moderate reverb (helps blend and adds air).
   - Keys: light reverb (often has built-in effects already).
   - Bass: little to no reverb (keeps low end tight and defined).
   - Electric guitar: light reverb (amp sim already adds character).
   - CamVerb sends may differ from AudVerb since the livestream has no natural room sound.
   - OSC address: `/ch/XX/mix/NN/level` where NN is the bus number from capture data.

Write your changes to the output file (JSON, per `_shared.md`). Return one line:
`instruments-metering: N changes` / `instruments-metering: clean` / `instruments-metering: error <reason>`.
