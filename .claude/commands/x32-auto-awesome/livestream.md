# Livestream Worker

> Read `.claude/commands/x32-auto-awesome/_shared.md` first, then the context brief named in your
> envelope, then follow this file.

**Scope**: Livestream send level balance and matrix compressors. No channel-level, bus EQ, or bus
compressor work.

**Primary job: Compare actual bus meter peaks against VENUE.md target levels and suggest send
adjustments.** Routing assessment alone is NOT sufficient — you must produce (in your output file's
`notes`) a table showing each bus's actual peak vs. its target and the delta.

**Data:** `venv/bin/python scripts/extract.py --scope livestream <capture_file>` (capture path in the
context brief) — bus→matrix sends, matrix compressors/EQ, bus meter peaks.
**Docs:** `docs/CHANNELS.md`, `docs/VENUE.md` (YOU MUST read the Livestream Bus Targets table), `docs/TECHNICAL.md`

The engineer can't hear the livestream from the room — optimize by the numbers.

**Signal path** — The extract includes every bus with its `name` field and `matrix_sends`. Classify
each bus by name and match to role targets in `docs/VENUE.md`:
- Read all buses in the extract that have non-zero matrix sends to Cam L (mtx03) or Cam R (mtx04).
- Match each bus name to a role using the name patterns in VENUE.md (e.g. a bus named "Voices"
  matches the Vocals role).
- Buses with no name match are unknown — report them but do not adjust.
- Main LR → matrices: **OFF** (main does not feed livestream).

**Work order:**
1. **Read bus meter peaks and classify by name** — Each bus in the livestream extract has a `name`
   and `meter_peak` field. Classify each bus by matching its name to the role/name patterns in
   `docs/VENUE.md`. Compare meter peaks against the target dB for the matched role. **Produce a
   comparison table** in your output `notes` like:
   ```
   Bus Name | Role   | Actual Peak | Target | Delta
   Voices   | Vocals | -15.2dB     | -18dB  | +2.8dB (hot)
   Drums    | Drums  | -18.1dB     | -16dB  | -2.1dB (quiet)
   ```
   If `meter_peak` is missing (old capture without bus metering), fall back to estimating signal
   strength from channel data in the full capture.
2. **Set matrix send levels** — Read each bus's `matrix_sends` for mtx03 (Cam L) and mtx04 (Cam R).
   **Bus→matrix sends are PRE-FADER — bus faders have zero effect on livestream levels. NEVER adjust
   bus faders for livestream purposes.** Adjust only the bus-to-matrix send levels:
   `/bus/XX/mix/03/level` (Cam L) and `/bus/XX/mix/04/level` (Cam R). Calculate adjustments based on
   how far each bus meter peak is from its target in VENUE.md. Buses running hot get lower sends;
   quiet buses get higher sends. Use 2-3dB increments, cap at 5dB per pass.
3. **Matrix compressors / limiters** — Tighter than FOH. Broadcast needs consistent levels. Evaluate
   matrix compressors freely.
4. **Balance for two audiences** — phone speakers AND home theaters:
   - Vocal intelligibility first
   - Low end via upper harmonics (80-200Hz) — phones can't do sub-bass
   - Less reverb than FOH

Matrix EQ is handled by the Downstream EQ worker. Do not duplicate.

Write your changes to the output file (JSON, per `_shared.md`). Return one line:
`livestream: N changes` / `livestream: clean` / `livestream: error <reason>`.
