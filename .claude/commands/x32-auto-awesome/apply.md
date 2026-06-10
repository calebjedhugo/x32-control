# Apply Worker (deconflict + apply one stage)

> Dispatched by the orchestrator after a group of analysis workers returns. You read their output
> files, deconflict, log, and apply ONE stage's changes to the mixer. You do NOT dispatch any agents
> and you do NOT run analysis yourself — you only merge and apply what the analysis workers wrote.

You are the apply worker for a Behringer X-32 mixer. Your dispatch envelope tells you:
- **stage**: `metering` | `eq` | `upstream`
- **input files**: the analysis workers' output JSON files to merge (e.g.
  `/tmp/agent_output_vocals_metering.json`, ...)
- **capture file**: the current capture path (for `update_peaks.py`)
- **changelog**: the changelog path (e.g. `captures/changelog_2026-06-10.jsonl`)
- **iter**: the iteration number (for the changelog)

## Setup

Run each command as a separate Bash call — never chain with `&&`. Working directory persists.
```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control"
```

## Safety

- **Small moves.** 2-3dB at a time. NEVER drastic changes. If an analysis worker suggested something
  drastic, clamp it.
- **NEVER touch mute.** **NEVER save scenes.**
- **Respect existing room corrections** (main bus LF shelf cuts, HF presence cut stay).

## Steps

1. **Read each input file** with the Read tool. Each is a JSON object with a `changes` array (full
   change objects — `address`, `value`, `old_value`, `human`, `ch`, `label`, `reason`, `trim_db`)
   and `notes`. (Format defined in `_shared.md`.) **If an input file named in your envelope is
   missing**, do not guess — return `apply <stage>: error missing <file>`.

2. **Deconflict** across the merged changes:
   - **metering stage**: contradictory suggestions for overlapping channels — pick the more
     conservative move.
   - **eq stage**: stacked EQ boosts across sections (e.g. vocals and instruments both boosted at
     3kHz) — reduce or drop the duplicate. Cross-section interactions (e.g. kick and bass both boosted
     in the sub range) — keep the lanes separate.
   - **upstream stage**: bus-dynamics vs livestream-send suggestions for the same bus — apply both
     only if they don't fight (dynamics shapes the bus; sends are pre-fader matrix levels).
   - Drop any change whose `address` is a duplicate of one you're already applying (last-writer or
     more-conservative wins).

3. **Write the batch file** with the Write tool to `/tmp/agent_output_<stage>_changes.json` — a JSON
   array of the surviving change objects, **keeping all their fields** (`old_value`, `human`, `ch`,
   `label`, `reason`, `trim_db` — control.py writes the changelog from them). Values raw OSC as-is;
   compressor ratio = index 0-11, knee = index 0-5; see `docs/TECHNICAL.md`.

4. **Apply the batch** (this is the only mixer-touching step):
   ```bash
   venv/bin/python scripts/control.py --batch /tmp/agent_output_<stage>_changes.json --changelog <changelog_path> --phase <stage> --iter <N>
   ```
   control.py validates every command first (address allowlist, value ranges, integer indices;
   mute/scene/routing changes are refused), appends one changelog line per applied change, deletes
   the batch file on completion, and prints a final `BATCH_RESULT {...}` JSON line. Exit codes:
   - **0** — all applied.
   - **2** — validation failed, nothing applied, batch file kept. Read the listed errors, fix the
     offending values in the batch file (or drop those changes), and run it once more. If it fails
     validation again, return an error line.
   - **3** — partial failure; the unapplied commands are in `<batch>.failed.json`. Report the
     applied/failed counts from `BATCH_RESULT` — do not retry automatically.

5. **metering stage only — update meter peaks** if any `/ch/XX/preamp/trim` change had a non-null
   `trim_db`: so subsequent iterations see accurate signal levels, run
   ```bash
   venv/bin/python scripts/update_peaks.py <capture_file> <ch:dB> [ch:dB ...]
   ```
   passing each channel's `trim_db` (e.g. `update_peaks.py captures/session_XXX.json 5:+3.0 17:-2.0`).

## One-line return

Return exactly one line, with N taken from `BATCH_RESULT.applied` (not your own count):
- `apply <stage>: N changes applied`
- `apply <stage>: 0 changes (clean)` if nothing to apply after deconflict
- `apply <stage>: N applied, M failed (see .failed.json)` on partial failure
- `apply <stage>: error <short reason>` if validation failed twice, an input file was missing, or
  the batch errored

The orchestrator routes on this line and independently confirms by checking the changelog grew.
