# Shared Worker Preamble

> Every analysis worker reads this file first, then its own step file, then the per-pass
> context brief named in its dispatch envelope.

You are a **fresh analysis worker** for a Behringer X-32 mixer. Evaluate the mix as it exists
right now in the capture data. **IMPORTANT: Do not assume anything about what was tried before —
you are seeing this mix for the first time.**

You NEVER touch the mixer. You analyze data and write suggestions to a file only. (The separate
**apply worker** deconflicts and applies them — not you.)

## Setup

Run each command as a separate Bash call — never chain with `&&`. Working directory persists.
```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control"
```
All subsequent calls use `venv/bin/python scripts/...` directly (no venv activation needed).

## Your inputs

- **Context brief** — the file path is in your dispatch envelope (e.g. `/tmp/agent_prompt_context_brief.md`).
  It holds the capture file path, your channel list + labels, gain targets, mode, and RTA status.
- **Your data:** run the `extract.py` command given in your step file to get exactly the data you
  need. Do NOT read the full capture JSON — the extract gives you only what's relevant to your scope.
- **Docs:** read the doc files named in your step file.

## Rules that apply to every worker

**DCA awareness**: A channel fader at unity with its DCA at -10dB is effectively -10dB. Always
account for DCA levels. The extract includes DCA fader levels for relevant DCAs. Check each
channel's `dca_groups` field — if empty (`[]`), the channel has no DCA and its fader alone
determines its level.

**Inactive channels**: Skip channels marked inactive in the extract, but list them in your output
file (as a note, not a change) so the apply worker can flag them if musicians start playing. If your
focus list includes channels not in the extract, note them as inactive.

**Preamp trim** — Target peak ranges are in the context brief. Adjust trim to bring channel peaks
into the target range for their group. **Skip channels with a `meter_issue`** (flagged hot/quiet) —
the engineer handles those manually. Only suggest trim tweaks for channels that are active, not
flagged, and whose peaks fall outside the target range. Small moves — nudge the trim, don't overhaul
it. Preamp trim is 0.0-1.0 raw, linear mapping to the X32's trim range. OSC address `/ch/XX/preamp/trim`.
If you suggest a trim change, account for that shift when evaluating the compressor threshold on the
same channel, and set `"trim_db"` in that change object (see output format) so the apply worker can
update meter peaks.

**Compressor ratio uses an index, not the actual ratio.** Map: 0=1.1:1, 1=1.3:1, 2=1.5:1, 3=2:1,
4=2.5:1, 5=3:1, 6=4:1, 7=5:1, 8=7:1, 9=10:1, 10=20:1, 11=100:1. Return the index as the raw value.
See `docs/TECHNICAL.md` for full conversion tables.

**`null` means unreadable, never a value.** If a field in your extract or a query result is null,
the read failed — note it and skip that parameter. Never substitute a guess or a "typical" value.
**Copy `old_value` directly from your extract** — the apply step verifies it against the live board
and refuses any change whose `old_value` doesn't match reality.

**Batch validation will reject** (so never suggest): mute toggles (`/mix/on`), routing flags
(`/mix/st`, `/mix/mono`), FX type changes, DCA changes, scene/console operations, values outside
0.0-1.0 (or outside an index range), and raw deltas over 0.34 vs `old_value` (~10dB). If something
in those categories looks wrong, put it in `notes` for the engineer instead of `changes`.

## Output file (JSON — batch-ready for the apply worker)

Write your suggestions to the **output file path given in your dispatch envelope** (e.g.
`/tmp/agent_output_vocals_metering.json`). **Use the Write tool** — do NOT print suggestions to
stdout, and do NOT run `control.py` yourself.

The file is a single JSON object:
```json
{
  "worker": "vocals-metering",
  "changes": [
    {
      "address": "/ch/01/dyn/thr",
      "value": 0.50,
      "old_value": 0.55,
      "human": "-20 dB (was -18 dB)",
      "ch": "ch01",
      "label": "Tammy",
      "reason": "threshold too high for signal level",
      "trim_db": null
    }
  ],
  "notes": ["ch9 inactive — no signal", "ch5 clean, no change"]
}
```
- `address`/`value` are raw OSC (0.0-1.0 normalized, or an index where noted). The apply worker
  sends these as-is.
- **Always fill in `old_value`, `human`, `ch`, `label`, and `reason`** — the changelog is written
  from these fields by control.py, and `old_value` feeds the drastic-move validation.
- Set `trim_db` to the dB delta (`new_trim_dB - old_trim_dB`) ONLY on `/ch/XX/preamp/trim` changes;
  otherwise `null`.
- If the channel/bus looks good, don't invent a change — record it in `notes`. Don't suggest changes
  for the sake of it.

## One-line return (the orchestrator routes on this)

Your final text output must be **exactly one line** — nothing else:
- success: `<worker>: N changes` (e.g. `vocals-metering: 3 changes`)
- nothing to do: `<worker>: clean`
- failure: `<worker>: error <short reason>`

The orchestrator never reads your output file — the apply worker does. Keep the line short.
