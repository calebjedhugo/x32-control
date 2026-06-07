# Vocals Metering Worker

> Read `.claude/commands/x32-auto-awesome/_shared.md` first, then the context brief named in your
> envelope, then follow this file.

**Scope**: Preamp + dynamics + reverb sends for active vocal channels.

**Data:** `venv/bin/python scripts/extract.py --scope metering --channels <vocal_channels> <capture_file>`
(your channel list and the capture file path are in the context brief)
**Docs:** `docs/CHANNELS.md` (voice type, mic type, lead vs BGV), `docs/CORRECTIONS.md`, `docs/TECHNICAL.md`

The context brief lists your channels + labels (e.g. "ch1 Tammy, ch5 Sara, ch7 Kat"). Read
`docs/CHANNELS.md` for per-channel context — voice type (alto/tenor/baritone), mic type, lead vs BGV.

For each active vocal channel:
1. **Preamp/gain staging** — Compare the channel's current peak to the vocal target range; nudge trim
   to bring it in range. Skip channels with `meter_issue`.
2. **Gate** — Check if enabled (`on` field). If it should be active but is disabled, suggest enabling
   first. Threshold just below quietest useful signal. Gentle range for vocals (not full gate).
3. **Compressor** — Check if enabled (`on` field). Compare signal level to threshold. Always squeezing
   = threshold too low. Never engaging = too high. Ratio 2:1-5:1. Mix 100% unless parallel compression
   is intentional. Adjust makeup gain if changing threshold/ratio.
4. **Reverb sends** — Check sends to reverb buses (find by name: "AudVerb" for FOH reverb, "CamVerb"
   for livestream reverb) in the channel's `sends` data. Use the bus number from the capture data for
   OSC addresses.
   - Both should be `on: true` for vocals. If off, flag it.
   - Lead vocal typically gets moderate reverb. BGVs can have slightly more to push them back.
   - AudVerb and CamVerb send levels should be similar per channel unless intentionally different.
   - Compare across all vocal channels — levels should be relatively consistent unless a voice needs
     to sit further forward/back.
   - OSC address: `/ch/XX/mix/NN/level` where NN is the bus number from capture data.

Write your changes to the output file (JSON, per `_shared.md`). Return one line:
`vocals-metering: N changes` / `vocals-metering: clean` / `vocals-metering: error <reason>`.
