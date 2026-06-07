# Drums Metering Worker

> Read `.claude/commands/x32-auto-awesome/_shared.md` first, then the context brief named in your
> envelope, then follow this file.

**Scope**: Preamp + dynamics + reverb sends for active drum channels.

**Data:** `venv/bin/python scripts/extract.py --scope metering --channels <drum_channels> <capture_file>`
(your channel list and the capture file path are in the context brief)
**Docs:** `docs/CHANNELS.md` (drum sizes, mic details), `docs/CORRECTIONS.md`, `docs/TECHNICAL.md`

The context brief lists your channels + labels (e.g. "ch22 Floor Tom, ch25 Snare, ch26 Kick"). Read
`docs/CHANNELS.md` for per-channel context — drum sizes, overhead positioning, etc.

**Targets by drum type:**
- Floor tom: comp 3:1-7:1, full gate
- Rack toms: comp 3:1-7:1, full gate
- Snare: comp 3:1-7:1, full gate
- Kick: comp 3:1-7:1, full gate
- Overheads (spaced pair — L near hi-hats, R near ride): comp 2:1-5:1, NO gate

For each active drum channel:
1. **Preamp/gain staging** — Compare current peak to the drum target range; nudge trim to bring it in
   range. Skip channels with `meter_issue`.
2. **Gate** — Check if enabled (`on` field). Enable for close mics if disabled. Full gate for close
   mics. Threshold below quietest hit. No gate on overheads.
3. **Compressor** — Check if enabled (`on` field). Tame transients without killing punch. Faster
   attack for toms/kick, medium snare, gentler overheads.
4. **Reverb sends** — Check sends to reverb buses (find by name: "AudVerb" for FOH, "CamVerb" for
   livestream) in the channel's `sends` data. Use the bus number from the capture data for OSC.
   - Drums generally need less reverb than vocals. Too much muddies transients.
   - Kick: little to no reverb (keeps it tight and punchy).
   - Snare: moderate reverb (adds body and sustain).
   - Toms: light-to-moderate reverb (helps sustain without washing out).
   - Overheads: little to no direct send — they already capture room ambience.
   - CamVerb sends may differ from AudVerb since the livestream has no natural room sound.
   - OSC address: `/ch/XX/mix/NN/level` where NN is the bus number from capture data.

Write your changes to the output file (JSON, per `_shared.md`). Return one line:
`drums-metering: N changes` / `drums-metering: clean` / `drums-metering: error <reason>`.
