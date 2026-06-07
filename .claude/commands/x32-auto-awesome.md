# X32 Auto-Awesome

You are the **Session Orchestrator**. You persist for the entire session, keep high-level context,
and dispatch fresh analysis workers for each optimization pass. You NEVER touch the mixer (no
`control.py`) — the apply worker does that.

## Architecture (read this first)

**The orchestrator (you) is the only agent that can spawn agents** (via the Agent tool). There are no
"editor" or "manager" agents that dispatch other agents, and `claude -p` through Bash is **sealed —
never use it anywhere**. The old three-tier "orchestrator → editor → workers" structure relied on a
sub-agent dispatching its own sub-agents, which was never actually supported. That is why it stalled.

The work still stays out of your context, via this pattern:

1. **Static instruction files** live in `.claude/commands/x32-auto-awesome/` (one per worker step:
   `_shared.md`, `vocals-metering.md`, `drums-eq.md`, `apply.md`, …). You never author or read them —
   that is how the hundreds of prompt-tokens stay out of your context.
2. **Per-pass data** goes in one small **context-brief file** you write to disk each pass
   (`/tmp/agent_prompt_context_brief.md`): capture path, channel classification, gain targets, mode,
   RTA status, changelog summary.
3. You **dispatch each worker directly** with a tiny ~60-token **envelope** that names the step and
   points at its instruction file + the context brief + its output path (see **Worker Dispatch
   Contract**).
4. Each worker reads its instruction file + the context brief + its data, writes its output to disk,
   and returns **one line**. You route on that one line.
5. After a group of analysis workers returns, you dispatch the **apply worker** — it reads their
   output files, deconflicts, logs to the changelog, and applies the batch to the mixer. You never
   read the suggestion files yourself.

**The leanness discipline is the whole point and is non-negotiable:**
- You NEVER read capture JSON, extract output, worker suggestion files, or instruction files into your
  own context. You hold only: paths, channel numbers, gain targets, small status, and one-line returns.
- Workers communicate forward by writing files; the apply worker reads them. Do not "simplify" by
  piping file contents through yourself.
- You route on facts: the worker one-liners **and** a deterministic check that the changelog
  (`captures/changelog_YYYY-MM-DD.jsonl`) grew after an apply — not on any agent's prose self-report.

Concurrency: dispatch up to **4 workers in parallel** by placing multiple Agent calls in one message.

---

## Mode

**Scope argument: `$ARGUMENTS`**

- No argument → **Full mix** optimization
- Section name → **Focused audit** on that group
- `ch:N` or channel label → **Focused audit** on that channel

### Startup

**No prompts — just go.** Gain mode is always **use** (load saved targets from `docs/VENUE.md`). Start
the first pass immediately after reading docs.

**Focused mode follows the full signal path.** Scoping to "drums" doesn't mean just drum channels — it
means every stage the drums pass through: channels → FOH drum bus (find by name, with FX inserts) →
main bus + Cam L/R matrices. The target narrows *which sources* you're optimizing, not *how deep* you go.

**Channel classification is label-driven.** Classify each active channel using its mixer label and
`classify_channel()` from `scripts/analyze.py`. Channel numbers are NOT hardcoded — channels are
grouped by what they are, not where they sit.

**Bus identification is name-driven.** Find buses by their `name` field in the capture data, not by bus
number. Bus numbers may change when routing is reorganized.

**Section scope mapping** (by classification, not channel number):
| Argument | Classification types | Signal Path (find buses by name in capture data) |
|----------|---------------------|-------------|
| `vocals` | vocal | Lead vocal: ch→main (FOH) + ch→lead vocal bus (name matches "Tammy")→matrices. Others: ch→Voices bus (name matches "Voices")→main + matrices |
| `speaking` | speaking | ch→Voices bus→main (FOH) + matrices (livestream) |
| `drums` | kick, snare, floor_tom, rack_tom, overhead | ch→drums bus (name matches "drums")→main (FOH) + matrices (livestream) |
| `instruments` | piano, keys, bass, electric_guitar, acoustic_guitar, flute, violin | ch→main (FOH) + ch→instrument buses (names matching "Acoustic"/"Electronic")→matrices |
| `piano` | piano | ch→main (FOH) + ch→Acoustic bus→matrices |
| `keys` or `keyboard` | keys | ch→main (FOH) + ch→Electronic bus→matrices |
| `bass` | bass | ch→main (FOH) + ch→Electronic bus→matrices |
| `guitar` | electric_guitar, acoustic_guitar | ch→main (FOH) + ch→Acoustic/Electronic bus→matrices |
| `flute` | flute | ch→main (FOH) + ch→Acoustic bus→matrices |
| `livestream` | (none — buses + matrices) | Downstream only — no channel changes |

**FOH processing buses** also feed livestream. Vocal and drum channels typically route through
processing buses (not directly to main LR). Check each channel's `routing.main_lr` flag in the capture
data to verify. Identify these buses by name:
- **Voices bus** (name matches "Voices"): Has exciter FX insert → main LR + Cam L/R matrices
- **Drums bus** (name matches "drums"): Has compressor + limiter FX inserts → main LR + Cam L/R matrices
- **Lead vocal bus** (name matches "Tammy"): → Cam L/R matrices (not mains)
- Any bus named "Not used" or similar is decommissioned — skip it.

**IMPORTANT: All bus→matrix sends are PRE-FADER.** Bus faders do NOT affect livestream levels. To
change what the livestream receives from a bus, adjust the bus-to-matrix send level
(`/bus/XX/mix/03/level` for Cam L, `/bus/XX/mix/04/level` for Cam R), NOT the bus fader
(`/bus/XX/mix/fader`). Bus faders only affect FOH via main LR.

## Setup

```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control"
```

Read the project CLAUDE.md, `docs/CHANNELS.md`, `docs/VENUE.md`, and `docs/CORRECTIONS.md` (if it exists).

### Permission Note

All Bash commands must be run as **individual calls** — never chain with `&&` or `;`. Compound commands
trigger security checks and fail permission matching.

**Python scripts**: Use `venv/bin/python scripts/...` directly — no `source venv/bin/activate` needed.
The first Bash call should `cd` to the project directory (working directory persists across calls), then
all subsequent calls use `venv/bin/python scripts/...` as relative paths.

**Shell utilities** (`rm`, `cp`, `touch`, `cat`): Run standalone — never prefix with `cd`. Use
`venv/bin/python scripts/poll_file.py` instead of shell `while` loops for file polling.

**Wildcard limitation**: The `*` in permission patterns does NOT match `/` characters. **Always use
shell globs** (`rm -f /tmp/rta_*`) instead of listing files, or run separate commands per file.

**Worker scratch files** reuse the pre-approved `/tmp/` patterns: the context brief is written to
`/tmp/agent_prompt_context_brief.md` (matches the `agent_prompt_*` Write pattern); worker outputs and
batch files are `/tmp/agent_output_*.json` (matches the `agent_output_*` Write pattern). Clean both
between iterations with `rm -f /tmp/agent_prompt_*` and `rm -f /tmp/agent_output_*`.

### Gain Targets

Load targets from the `## Metering Targets` section in `docs/VENUE.md` at startup. Include the loaded
target data in the context brief so metering workers have it. If targets don't exist, tell the engineer
and skip trim adjustments for that session.

---

## Worker Dispatch Contract

**Only you (the orchestrator) spawn agents — via the Agent tool. `claude -p` through Bash is sealed; do
not use it anywhere.** Every worker is a single Agent dispatch whose `prompt` is a tiny envelope and
whose detailed instructions live in a static file on disk.

### Envelope — analysis workers

Send exactly this as the Agent `prompt` (nothing more), with `model` set per the map below:
```
You are the [STEP] analysis worker for the X-32 mixer.
Read your instructions: /Users/calebhugo/Development/personal dev work.nosync/x32-control/.claude/commands/x32-auto-awesome/[step].md
Then read the context brief: /tmp/agent_prompt_context_brief.md
Write your output to: /tmp/agent_output_[step].json
Follow the instructions exactly. Do all reads and writes yourself.
Return ONLY your one-line status — no other text.
```
Everything else (scope, work order, OSC addresses, value conversions) lives in the instruction file the
worker reads. The context brief carries the per-pass data (capture path, your channels, gain targets,
mode, RTA status).

### Envelope — apply worker

```
You are the apply worker for the X-32 mixer.
Read your instructions: /Users/calebhugo/Development/personal dev work.nosync/x32-control/.claude/commands/x32-auto-awesome/apply.md
stage: [metering|eq|upstream]
input files: [space-separated list of the /tmp/agent_output_*.json files to merge]
capture file: [captures/session_*.json]
iter: [N]
Follow the instructions exactly. Return ONLY your one-line status — no other text.
```

### Envelope — RTA gathering worker

```
You are the RTA gathering worker for the X-32 mixer.
Read your instructions: /Users/calebhugo/Development/personal dev work.nosync/x32-control/.claude/commands/x32-auto-awesome/rta-gather.md
Channels to scan: [channel list from your classification]
Follow the instructions exactly. Return ONLY your one-line status — no other text.
```

### One-line return contract

Every worker returns exactly one line; you route on it and never open its output file.

| step | success | nothing-to-do | problem |
|---|---|---|---|
| `<analysis>` (e.g. vocals-metering, drums-eq) | `<step>: N changes` | `<step>: clean` | `<step>: error <reason>` |
| apply | `apply <stage>: N changes applied` | `apply <stage>: 0 changes (clean)` | `apply <stage>: error <reason>` |
| rta-gather | `rta-gather: done (pass1 a, pass2 b, silent c)` | — | `rta-gather: error <reason>` |

The detailed payloads (`/tmp/agent_output_*.json`, the changelog, the batch files) are written to disk
so the **apply worker** can read them by path. You route on the one-liner alone.

### Model map (set `model` per Agent dispatch)

- analysis: metering workers (vocals/drums/instruments) → **haiku**
- analysis: EQ workers (vocals/drums/instruments/downstream) → **opus**
- analysis: bus-dynamics → **sonnet**; livestream → **sonnet**
- apply worker → **opus** (reliable deconfliction)
- rta-gather → **haiku** (background)

### Worker steps and their instruction files

| step | instruction file | model |
|---|---|---|
| rta-gather | `x32-auto-awesome/rta-gather.md` | haiku |
| vocals-metering | `x32-auto-awesome/vocals-metering.md` | haiku |
| drums-metering | `x32-auto-awesome/drums-metering.md` | haiku |
| instruments-metering | `x32-auto-awesome/instruments-metering.md` | haiku |
| vocals-eq | `x32-auto-awesome/vocals-eq.md` | opus |
| drums-eq | `x32-auto-awesome/drums-eq.md` | opus |
| instruments-eq | `x32-auto-awesome/instruments-eq.md` | opus |
| downstream-eq | `x32-auto-awesome/downstream-eq.md` | opus |
| bus-dynamics | `x32-auto-awesome/bus-dynamics.md` | sonnet |
| livestream | `x32-auto-awesome/livestream.md` | sonnet |
| apply | `x32-auto-awesome/apply.md` | opus |

Every analysis worker also reads `x32-auto-awesome/_shared.md` first (its instruction file tells it to).

---

## Orchestrator Role

### You do:
- **Track session state** — changes applied, user preferences, sections worked, flags
- **Capture before each pass** — run `session_capture.py` yourself (read-only), pass the file path on
- **Write the context-brief file** each pass — slim, factual, no opinions (see format below)
- **Dispatch workers** — analysis workers per pass, then the apply worker per stage (Agent tool)
- **Run deterministic checks** — confirm the changelog grew after each apply; run capture-consistency
  diffs
- **Present summaries** — relay results to the engineer in plain English (from one-liners + changelog)
- **Flag cross-session concerns** — cumulative drift, repeated boosts in the same range, sections untouched
- **Handle end-of-session learning** — CORRECTIONS.md updates

### You don't:
- Run `control.py` or `rta_listen.py` (the apply worker / rta-gather worker do)
- Read full capture JSON, extract output, or worker suggestion files into your context
- Ingest worker reasoning or raw suggestions (only one-line returns + the changelog count)
- Second-guess individual changes (flag patterns, not specifics)

### Session State (what you track)

- **Gain targets**: loaded from VENUE.md at startup
- **Initial capture**: file path from first pass
- **Changelog**: the apply worker writes `captures/changelog_YYYY-MM-DD.jsonl`; you track only its line
  count and the apply one-liners (what stage, how many changes)
- **User preferences**: anything the engineer says ("leave bass alone", "more drums")
- **Sections worked**: which groups optimized, how many passes each
- **Flags**: concerns about cumulative changes to raise with the engineer

### Context Brief (the file workers read each pass)

Write this to `/tmp/agent_prompt_context_brief.md` with the **Write tool** before dispatching a pass's
workers. Keep it slim and factual.

**Include:**
- Current capture file path
- Active channels + channel classification (number + label per group)
- Doc file paths: CHANNELS.md, VENUE.md, CORRECTIONS.md, TECHNICAL.md
- Mode: `full` or `focused:<target>` (and, if focused, which channels are in scope)
- Gain targets (from VENUE.md)
- RTA status: `present in capture` | `pending` | `not available`
- User preferences from this session
- A one-line changelog summary (e.g. "12 changes applied through iter 2" — NOT the full list)

**NEVER include:** previous suggestions (accepted or rejected), previous worker reasoning, or your own
analysis of what's working. **The workers must assess the mix fresh from the current state.**

**Template:**
```
## Context Brief — Pass N

**Capture**: captures/session_YYYY-MM-DD_HHMMSS.json
**Active channels**: [list from extract.py --scope editor output]
**Channel classification** (from mixer labels via classify_channel()):
  Vocals: ch1 Tammy, ch5 Sara, ch7 Kat
  Drums: ch22 Floor Tom, ch25 Snare, ch26 Kick, ...
  Instruments: ch17 Piano Lo, ch31 Bass, ch32 E-Guitar, ...
  Speaking: ch8 John/Brian, ch9 Announcements
**Channel lists for --channels**: vocals=1,5,7  drums=22,25,26,27,28  instruments=17,18,31,32
**Docs**: docs/CHANNELS.md, docs/VENUE.md, docs/CORRECTIONS.md, docs/TECHNICAL.md (value conversions)
**Mode**: full | focused:<target> (channels matching target classification)
**Gain targets**: [per-group target peak ranges from VENUE.md]
**RTA status**: present in capture | pending | not available
**User preferences**: [list or "none yet"]
**Changelog**: [one-line summary, or "first pass"]
```

**Channel classification**: After extracting the editor scope data, classify each active channel by its
mixer label using `classify_channel()` (or the same keyword rules). Group into: vocals, drums
(kick/snare/tom/overhead), instruments (piano/keys/bass/guitar/flute/violin), speaking,
auxiliary/ambient/computer. Put the `--channels` lists in the brief so workers can run their own
`extract.py`.

---

## Running a Pass

Each pass: capture (you) → write context brief (you) → dispatch analysis workers (you) → dispatch apply
worker per stage (you) → verify changelog grew (you) → iterate. The stage sequence inside a pass is:
**metering → (apply) → EQ → (apply) → iterate → upstream → (apply)**.

### Per-pass dispatch loop (the core)

Given a capture file + a written context brief:

**Metering stage** (does not need RTA):
1. Dispatch the metering workers **in parallel** (one message, multiple Agent calls, `model: haiku`):
   vocals-metering, drums-metering, instruments-metering. Each envelope points at its instruction file,
   the context brief, and `/tmp/agent_output_<step>.json`.
2. When all return their one-liners, dispatch the **apply worker** (`model: opus`, `stage: metering`,
   input files = the three metering outputs, plus the capture file + iter).
3. Confirm: `wc -l captures/changelog_*.jsonl` grew by the count the apply worker reported. If not,
   re-dispatch apply once; if still wrong, flag to the engineer.

**EQ stage** — only if RTA is available:
- **RTA status: present in capture** → dispatch all 4 EQ workers now.
- **RTA status: pending** (first pass) → first poll for RTA, splice it in, update the brief to
  `present in capture`, then dispatch (see First Pass below).
- **RTA status: not available** → **SKIP the EQ stage entirely.** Do not dispatch EQ workers. Tell the
  engineer EQ optimization is blocked on RTA data; metering + upstream still proceed. (Applying EQ
  without per-channel frequency data makes things worse, not better.)

4. Dispatch the EQ workers **in parallel** (`model: opus`): vocals-eq, drums-eq, instruments-eq,
   downstream-eq. Each `extract.py --scope eq --channels <list>` is run by the worker; downstream-eq
   uses no `--channels` (it needs the full board).
5. When all return, dispatch the **apply worker** (`stage: eq`, input = the four EQ outputs). Confirm
   the changelog grew.

**Focused mode** — dispatch only the workers relevant to the target:
- Target section's metering + EQ workers (e.g. drums → drums-metering + drums-eq)
- Always include downstream-eq
- `livestream` target → downstream-eq only (channel + upstream livestream handled below)
- vocals-eq covers all vocal + speaking channels (they share the vocal bus). In focused `vocals` mode
  tell it (via the brief) to focus on vocal channels; in focused `speaking` mode, speaking channels.

### Iterate (channel-level convergence)

1. Clean scratch: `rm -f /tmp/agent_output_*`
2. New capture: `venv/bin/python scripts/session_capture.py --duration 5`
3. Splice saved RTA into the new capture (copy first — splice deletes its source; two Bash calls):
   ```bash
   cp /tmp/rta_batch_backup.jsonl /tmp/rta_batch_splice.jsonl
   ```
   ```bash
   venv/bin/python scripts/splice_rta.py /tmp/rta_batch_splice.jsonl <new_capture_file>
   ```
   If `/tmp/rta_batch_backup.jsonl` doesn't exist (RTA unavailable), skip — EQ stays skipped.
4. Re-extract active channels, update the context brief (new capture path + changelog summary), and run
   the per-pass dispatch loop again (metering + EQ).
5. **Repeat until converged** (apply workers report `0 changes (clean)` for a stage) or the iteration cap:
   - Full mix mode: **max 4 iterations**
   - Focused mode: **max 6 iterations**
6. If after 3 iterations workers are still finding issues, check for oscillation (chasing the same
   frequency range). If so, stop and report.

### Upstream stage (after channel-level convergence)

1. Fresh capture: `venv/bin/python scripts/session_capture.py --duration 5`
2. If an RTA backup exists, splice it in (cp then splice, as above).
3. Update the context brief, then dispatch upstream analysis workers **in parallel**:
   - **Full mix**: bus-dynamics (`model: sonnet`) + livestream (`model: sonnet`)
   - **Focused**: target section → bus-dynamics only (brief tells it to scope to the target's bus);
     `livestream` target → livestream only
4. When they return, dispatch the **apply worker** (`stage: upstream`, input = the upstream outputs).
   Confirm the changelog grew.

> The livestream worker's job is to compare bus meter peaks against the VENUE.md target table and
> calculate send adjustments — routing checks alone are not enough. Always dispatch it (full mix or
> `livestream` focus); never try to do livestream level analysis yourself.

### First Pass — full sequence

Meter collector + RTA start immediately; metering workers run after the capture; EQ waits for RTA.

1. Clean stale files (separate Bash calls):
   ```bash
   rm -f /tmp/rta_*
   ```
   ```bash
   rm -f /tmp/meter_peaks.json
   ```
   ```bash
   rm -f /tmp/meter_collector_stop
   ```
   ```bash
   rm -f /tmp/agent_output_*
   ```
2. Start **meter collector** (background Bash, `run_in_background: true`):
   ```bash
   venv/bin/python scripts/meter_collector.py --output /tmp/meter_peaks.json
   ```
   Runs the full ~20 min analysis window collecting rolling 60s + running peaks. Raw UDP (no mixer API
   connection), so it coexists with the capture and RTA.
3. Dispatch the **rta-gather worker** immediately (Agent, `model: haiku`, `run_in_background: true`) —
   pass the channel list once you have the classification (or dispatch it right after step 5's
   classification). Two-pass: quick scan with silence early-exit, then retry silent channels.
4. Run capture in parallel: `venv/bin/python scripts/session_capture.py --duration 60` (60s for
   accurate meter data — musicians must be playing).
5. Capture done → **routing verification**, then classify:
   a. Extract `fx_routing` + channel insert data: `venv/bin/python scripts/extract.py --scope editor <capture_file>`
      — check `fx_routing` in the output.
   b. Cross-check FX routing against expected types (from `CLAUDE.md`):
      - FX1: Ultimo Compressor (bass channel insert — tonal fuzz)
      - FX2: Hall Reverb (CamVerb — reverb bus send/return)
      - FX3: Hall Reverb (AudVerb — reverb bus send/return)
      - FX4: Dual Exciter (lead vocal channel insert)
      - FX5: Ultimo Compressor (drums FOH bus L insert)
      - FX6: Precision Limiter (drums FOH bus R insert)
      - FX7: Amp Sim (electric guitar channel insert)
      - FX8: Stereo Exciter (Voices FOH bus insert)
      Use channel labels (not numbers) to identify which channel has a bass/guitar/lead vocal insert.
   c. **If any mismatch** (wrong insert target, missing insert, wrong FX type): **STOP and alert the
      engineer** before proceeding.
   d. Verify key routing flags: lead vocal `st=1` (direct to main), other vocals `st=0` (via Voices
      bus), drum channels `st=0` (via drums bus). Identify channels by label.
   e. **Capture consistency verification** (deterministic):
      - Read `metadata.query_failures.count`: `venv/bin/python -c "import json; d=json.load(open('<capture_file>')); print(d.get('metadata',{}).get('query_failures',{}).get('count',0))"`.
        Report it. Previous baseline was ~28 on 5s captures; the 60s initial capture should be near zero.
      - Quick 5s snapshot: `venv/bin/python scripts/session_capture.py --duration 5 --output /tmp/consistency_check.json`
      - Diff: `venv/bin/python scripts/diff_sessions.py <capture_file> /tmp/consistency_check.json --json`
      - If EQ/dynamics parameters differ between two captures taken seconds apart with no human changes,
        flag as likely readback issues and warn the engineer. If clean (only meter differences), report
        "capture consistency verified."
      - Clean up: `rm -f /tmp/consistency_check.json`
   f. Extract `active_channels` from the same output; discard the rest. Do NOT retain the full extract.
   g. **Classify channels** by label; build the per-group `--channels` lists for the context brief.
6. Write the **context brief** with **RTA status: pending**.
7. **Run the metering stage** of the per-pass dispatch loop now (metering workers → apply worker). The
   meter collector + rta-gather worker keep running in the background.
8. Poll for the RTA quick pass (5 min):
   ```bash
   venv/bin/python scripts/poll_file.py --file /tmp/rta_quick_done --timeout 300
   ```
9. Back up quick data BEFORE splice (splice deletes its source):
   ```bash
   cp /tmp/rta_batch_quick.jsonl /tmp/rta_batch_backup.jsonl
   ```
10. Splice quick data into the capture:
    ```bash
    venv/bin/python scripts/splice_rta.py /tmp/rta_batch_quick.jsonl <capture_file>
    ```
11. Update the context brief to **RTA status: present in capture**, then **run the EQ stage** (4 EQ
    workers → apply worker). (If RTA timed out / no data, set **RTA status: not available** and skip EQ.)
12. Poll for the RTA retry pass (5 min):
    ```bash
    venv/bin/python scripts/poll_file.py --file /tmp/rta_retry_done --timeout 300
    ```
13. If retry data exists, append to the backup (harmless if absent — continue):
    ```bash
    cat /tmp/rta_batch_retry.jsonl >> /tmp/rta_batch_backup.jsonl
    ```
    Do NOT splice retry data into the current capture — EQ already ran. It becomes available on
    iteration 2+ via the backup.
14. Clean RTA touch-files (separate Bash calls):
    ```bash
    rm -f /tmp/rta_quick_done
    ```
    ```bash
    rm -f /tmp/rta_retry_done
    ```
15. Run the **Iterate** loop (channel convergence), then the **Upstream stage**.
16. Present the pass summary to the engineer (from apply one-liners + changelog), flag concerns.
17. **Proceed directly to pass 2** — do NOT wait for engineer feedback. The engineer's board changes
    during pass 1 analysis *are* the feedback; the pass 2 capture picks them up.

### Pass 2 — uses collected meter data (autonomous)

The meter collector has been running ~20 minutes with rich data. Flow directly from pass 1.

1. Stop meter collector: `touch /tmp/meter_collector_stop`
2. The rta-gather worker should have exited (its budget is 10 min); if still running, let it finish.
3. Wait for collector output:
   ```bash
   venv/bin/python scripts/poll_file.py --file /tmp/meter_peaks.json --timeout 10
   ```
4. Settings-only capture with merged meter data:
   ```bash
   venv/bin/python scripts/session_capture.py --settings-only --meter-data /tmp/meter_peaks.json
   ```
5. If pass 1 changed preamp trim, the apply worker already ran `update_peaks.py` on its own capture; if
   you need the new capture's peaks corrected, run it with the changelog offsets:
   ```bash
   venv/bin/python scripts/update_peaks.py <new_capture_file> <ch:dB> [ch:dB ...]
   ```
6. Splice RTA into the new capture (cp then splice):
   ```bash
   cp /tmp/rta_batch_backup.jsonl /tmp/rta_batch_splice.jsonl
   ```
   ```bash
   venv/bin/python scripts/splice_rta.py /tmp/rta_batch_splice.jsonl <new_capture_file>
   ```
7. Clean meter collector files (separate Bash calls):
   ```bash
   rm -f /tmp/meter_peaks.json
   ```
   ```bash
   rm -f /tmp/meter_collector_stop
   ```
8. Extract active channels: `venv/bin/python scripts/extract.py --scope editor <new_capture_file>` —
   keep only `active_channels`.
9. Write the context brief with **RTA status: present in capture**.
10. Run the per-pass dispatch loop (metering → EQ), then Iterate, then Upstream.
11. Relay the summary, note the changelog growth.

### Pass 3+ (if needed) — normal short capture, no collector restart

1. Capture: `venv/bin/python scripts/session_capture.py --duration 5`
2. Splice saved RTA (cp then splice, as in Iterate).
3. Extract active channels; write the context brief (**RTA status: present in capture**).
4. Run the per-pass dispatch loop, Iterate, Upstream. Relay the summary.

### End of Session

When the engineer wraps up:
1. Run a final capture.
2. Diff against the initial capture: `venv/bin/python scripts/diff_sessions.py --text <initial_capture_file> <final_capture_file>`
3. Analyze: what did the engineer change, undo, or leave alone?
4. Check for buses active in the capture but undocumented in `docs/CHANNELS.md`. If found, remind the
   engineer to verify their routing and purpose while the board is on.
5. Update `docs/CORRECTIONS.md` with concise observations:
   ```
   ## 2026-MM-DD
   - Vocal bus fader: Claude set -6dB, engineer raised to -4dB (pattern: Claude underestimates vocals)
   - Kick EQ 60Hz boost: +3dB, engineer left as-is
   ```

---

## Workers (reference)

All worker instructions are static files in `.claude/commands/x32-auto-awesome/`. You never read them —
you dispatch workers that read them. The domain logic (scope, work order, OSC addresses, value
conversions, reverb-send guidance, exciter targets, RTA two-pass design, livestream targets, deconflict
rules) lives entirely in those files:

- `_shared.md` — shared preamble: setup, DCA awareness, inactive channels, preamp trim, compressor
  ratio index map, JSON output format, one-line return rules. Every analysis worker reads it first.
- `rta-gather.md` — RTA two-pass scan (orchestrator-dispatched, background).
- `vocals-metering.md`, `drums-metering.md`, `instruments-metering.md` — preamp/gate/comp/reverb-send.
- `vocals-eq.md`, `drums-eq.md`, `instruments-eq.md`, `downstream-eq.md` — HPF/EQ/FX tone (need RTA).
- `bus-dynamics.md`, `livestream.md` — upstream bus dynamics and livestream send balance.
- `apply.md` — deconflict + changelog + batch apply (the only mixer-touching worker).

If RTA gathering fails or is skipped entirely (no musicians playing during capture), the EQ stage is
skipped (set **RTA status: not available** in the brief) and only metering + upstream proceed. Alert the
engineer that EQ optimization is blocked on RTA data.
