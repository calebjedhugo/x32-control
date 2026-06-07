# Bus Dynamics Worker

> Read `.claude/commands/x32-auto-awesome/_shared.md` first, then the context brief named in your
> envelope, then follow this file.

**Scope**: Bus compressors, FOH bus FX insert dynamics (Ultimo/Limiter), and master compressor. No
channel-level or EQ work.

**Data:** `venv/bin/python scripts/extract.py --scope dynamics <capture_file>` (capture path in the
context brief)
**Also query:** `venv/bin/python scripts/query.py --fx 5 --fx 6` for drum FOH bus insert parameters
**Docs:** `docs/CHANNELS.md`, `docs/CORRECTIONS.md`, `docs/TECHNICAL.md`

**Work order:**

Identify buses by their `name` field in the dynamics extract — do not rely on bus numbers.

1. **Drum FOH bus FX inserts** (find the bus named "drums" or "Drums"):
   - **FX5 — Ultimo Compressor** (type 17): Insert on drums bus L. Primary drum dynamics for FOH.
     Evaluate input gain, attack, release, output gain, ratio. See TECHNICAL.md for Ultimo mapping.
     Tame transients without killing punch — drums need attack to cut through.
   - **FX6 — Precision Limiter** (type 11): Insert on drums bus R. Evaluate input/output gain, squeeze,
     knee, attack, release. Should catch peaks, not constantly limiting.
   - These two should work together coherently (one compresses, one limits). If the built-in bus
     compressor is also enabled, check for over-processing — three stages of dynamics is likely too much.
2. **FOH processing bus compressors** (find buses named "Voices" and "drums"):
   - Voices bus: last dynamics stage before mains for vocals. Has Stereo Exciter (FX8) insert but
     that's tonal, not dynamics — the compressor here is independent.
   - Drums bus: already has Ultimo + Limiter inserts (step 1). Built-in bus compressor may not be
     needed. Only enable if the FX inserts aren't providing enough control.
3. **Livestream bus compressors** (find buses matching Vocals/Instruments roles by name — e.g.
   "Tammy", "Acoustic", "Electronic"):
   - Glue each group. Threshold should engage on peaks, not constant squeeze.
   - The lead vocal bus (e.g. "Tammy") shapes her livestream dynamics independently.
   - Check ratio, attack, release, knee, makeup gain.
4. **Master compressor**:
   - Gentle, catching peaks. Not slamming.
   - If gain reduction would be constant (threshold well below expected signal), threshold is too low.

**Focused mode**: Only evaluate the target's bus compressor and relevant FX inserts. Note main
compressor state but only suggest changes if clearly wrong.

Write your changes to the output file (JSON, per `_shared.md`). Return one line:
`bus-dynamics: N changes` / `bus-dynamics: clean` / `bus-dynamics: error <reason>`.
