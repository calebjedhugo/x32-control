# X32 Board Session

Drop into a **fully-loaded, context-resident board session** for on-the-fly tweaks — the same
"agent already knows everything" state you get *after* an `x32-auto-awesome` run, but without the
optimization passes. Invoke it, it primes itself once, then you chat naturally ("Bart's harsh,"
"audit the bass and fix it," "turn up the kick") and it does the right thing.

**Audience: sound engineers, not developers. Speak plain English about music and sound. NEVER show
raw commands or JSON to the user. YOU run everything.**

---

## What this skill is

A **session primer + interactive companion**, NOT a one-shot command. On invoke you load the board
once; then you stay in an interactive loop handling ad-hoc requests with full context and all
guardrails — until the user is done. This is a single persistent agent (no worker dispatch); the
context is *supposed* to be resident — that's the whole point.

## ⚠️ ONE-TIME: confirm per-channel RTA source-switching (added 2026-06-28 — remove once confirmed)

The RTA parser was rewritten 2026-06-28 to read the **correct** bank/format (`/meters/15`, 100 ×
int16 dB) — the old code read `/meters/4` level-meters as float32, which is what produced the bogus
"corrupt lock" template. The spectrum is now real. **One thing still needs a live confirm:** that the
analyzer actually follows the channel you pick. The script now sets BOTH `/-stat/selidx` and
`/-stat/rtasource`, but which one truly steers `/meters/15` wasn't confirmable off a live board.

Next time you have musicians playing, before deep requests:

1. With a **bass** (low) and a **bright** source (vocal/cymbal/piano-high) both playing, scan each:
   `venv/bin/python scripts/rta_listen.py --channel <N> --update-session`. Bass should read
   low-frequency-dominant; the bright one should have real `presence`/`brilliance`. **Different
   shapes = source-switching works.** Identical shapes = the tap isn't following the channel (it's
   stuck on the main mix) — say so and don't trust per-channel EQ until it's sorted.
2. Scan a channel you KNOW is silent. The script should return `valid:false` with
   "channel meter silent but RTA shows signal …" — that guard means it correctly noticed the tap
   isn't on that (silent) channel.

Tell the engineer the result in plain English ("per-channel RTA is switching correctly"), then delete
this block. If switching is broken, the fix is the source-select address — leave a note in
`docs/CORRECTIONS.md`.

---

## Setup

```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control"
```
Run Python as `venv/bin/python scripts/...` (no activate needed). Run Bash commands as **individual
calls** — never chain with `&&` or `;` (breaks permission matching).

---

## Startup — prime once (do this immediately, no prompts)

1. **Read the docs**: project `CLAUDE.md`, `docs/CHANNELS.md`, `docs/VENUE.md`, `docs/CORRECTIONS.md`.
   These give you the FX-routing source of truth, personnel, room rules, and prior session learnings.
2. **Fresh live capture** (state only — RTA is gathered per-tweak, not now):
   ```bash
   venv/bin/python scripts/session_capture.py --duration 5
   ```
3. **Classify channels by label**:
   ```bash
   venv/bin/python scripts/prepare_pass.py <capture_file> --mode full --rta-status pending
   ```
   Route on its summary line. Flag any `UNKNOWN=` labels to the engineer (fix on the board — don't
   tweak them). Note `NO-GAIN-TARGETS` if present.
4. **Verify routing/FX** against the FX Routing table in the project `CLAUDE.md` (lead vocal `st=1`
   direct to main; other vocals `st=0` via Voices bus; drums via drums bus; bass/guitar/lead-vocal
   FX inserts on the right channels). **If anything mismatches, STOP and tell the engineer** before
   taking requests.
5. **RTA** — gathered per-EQ-tweak, not at boot (see the dedicated section). Don't scan a quiet
   pre-service board — RTA needs the source actually playing. A quiet board ≠ broken RTA.
6. **Present the loaded summary** in plain English and hand over:
   > "Board's loaded. 20 active channels — vocals: Tammy, Randy, Bart, Kat, Jen; drums: kick/snare/
   > toms/hats/ride; instruments: bass, piano, keys, e-guitar. Routing checks out, gain targets
   > loaded, RTA healthy. Heads up: ch10 label is UNKNOWN. What do you want to tweak?"

After this, you're in the **interactive loop**. Do NOT re-read docs or re-capture each request —
the context is resident. Re-capture only when state goes stale (below).

---

## ⚠️ The intent gate (read every request through this)

**Decide: did the engineer authorize the change, or just ask you to look?**

- **APPLY NOW** — phrases like "update it," "fix it," "and apply," "immediately," "on the fly,"
  "go ahead," "do it," or a direct imperative move ("bump Bart 2 dB," "cut 300 on the bass," "turn
  up the kick"). → Audit *and* apply end-to-end. **No clarifying questions.**
  "Audit the bass EQ and update it immediately" runs start to finish on its own.
- **PROPOSE** — "audit," "look at," "check," "what's…," "how does … sound." → Audit and **propose**
  in plain English, then wait for the nod. This is the cautious default.

When unsure which mode, **err to PROPOSE.**

---

## Guardrails — these hold even in APPLY-NOW mode (they don't slow you down)

1. **RTA gates EQ. ALWAYS.** Never propose or apply an EQ move without trustworthy per-channel RTA
   for that channel. Auditing EQ off a static capture is what produces confidently-wrong changes.
   If RTA is blocked (see pre-flight), do the non-EQ parts and tell the engineer EQ is blocked —
   don't guess.
2. **Every change goes through the logged batch path** (below) — never raw single-flag `control.py`.
   "Update immediately" means *fast*, not *untracked*. The batch path gives you old→new logging,
   live-board verification, a drastic-move backstop, and one-command revert.
3. **Locate channels by live label**, not by a remembered channel number. Assignments vary.
4. **Small moves (2–3 dB)** by default. Honor a larger move only if the engineer specifies the
   magnitude.
5. **"Update immediately" IS explicit go-ahead for live service** — it overrides the "never change
   during live service" rule by design. Without that authorization, propose first.
6. **NEVER save scenes.** The engineer manages one scene manually.

---

## RTA — how to gather and how to TRUST it

Gather per-channel, on demand, when a tweak touches EQ:
```bash
venv/bin/python scripts/rta_listen.py --channel <N> --update-session
```

**There is no "RTA lock." That whole saga was a parse bug (root-caused 2026-06-28).** The old
`rta_listen.py` read the wrong meter bank in the wrong format — `/meters/4` (a channel/bus
**level-meter** bank) parsed as 82 × float32. That produced a fixed phantom "spectrum" (always-hot
meter slots at ~1350 Hz + a duplicated 10.2/11.1 kHz pair) that every past session mistook for a
"corrupt lock," then blamed on a "second X32 client" and tried to fix with cooldowns. None of that
was real. The script now reads the **actual 100-band RTA on `/meters/15`** (100 × int16, value÷256 =
dB → linear), which gives a true spectrum. Cooldown / `--retry-on-lock` / "second client" guidance is
**dead — ignore it.**

**Trust the script's `valid` field, and read the `validation_notes`.** `valid:true` with a
source-appropriate shape = good data, proceed. The one real failure it now flags honestly:
> `valid:false` — "channel meter silent but RTA shows signal — RTA source-select is not tracking this
> channel." This means the analyzer is tapping something other than the channel you asked for (or the
> channel just isn't playing). Either way: **do not** base EQ on it. Get the channel playing and
> rescan; if a clearly-playing channel still trips this, source-switching is broken (see the one-time
> confirm block above) and EQ is blocked until it's fixed.

**Sanity-check per-channel switching when it matters** (a bright vs a low source, both playing):
their spectra should differ — the bright one has real `presence`/`brilliance` the bass lacks. If two
genuinely different, both-playing sources come back with the **same** shape, the tap isn't following
the channel — stop and say so. (Compare absolute `bands[*].peak`, never normalized peak-frequency
labels — a silent channel's noise-floor peaks coincidentally match anything.)

**A quiet board is not a broken RTA.** Don't diagnose anything off a silent channel; it just isn't
playing. Scan sparingly — one channel at a time, only when a tweak needs it.

> Note: running RTA moves the desk's RTA-source picker AND the selected channel (`/-stat/selidx`).
> Display-only, but it will jump the engineer's selected-channel view — mention it if they care, and
> offer to set it back.

---

## Applying a change (logged + revertible)

Use **batch mode** — never raw single-flag writes.

1. Read the channel's current raw value for the parameter you're changing (this is your `old_value`):
   ```bash
   venv/bin/python scripts/query.py --channel <N> --eq
   ```
2. Write a batch file to `/tmp/agent_output_board.json` — a JSON array of change objects:
   ```json
   [{"address": "/ch/06/eq/3/g", "value": 0.55, "old_value": 0.417,
     "ch": 6, "label": "Bart", "human": "+1.5 dB at 3.4 kHz",
     "reason": "presence lift per RTA"}]
   ```
   - `value`/`old_value` are **raw 0.0–1.0**. Convert from human units with the verified helpers in
     `control.py`: gain `db/30 + 0.5`, freq `log(hz/20)/log(1000)`. **Q raw mapping is unverified —**
     avoid Q changes unless necessary, and read back in human units to confirm.
   - The validator **refuses** raw deltas > 0.34 (~10 dB) — keep moves small or split them.
3. Apply with the changelog so it's revertible:
   ```bash
   venv/bin/python scripts/control.py --batch /tmp/agent_output_board.json --changelog captures/changelog_$(date +%Y-%m-%d).jsonl --phase eq --iter 1
   ```
   (`--phase metering` / `upstream` for non-EQ moves.) Exit 0 = applied; 2 = validation failed
   (nothing applied); 3 = partial/refused (do NOT blindly retry refused items — the old_value
   didn't match the live board, so re-read first).
4. **Confirm in plain English** — state old → new, ask them to listen, offer to revert:
   > "Done — Bart's presence is up 1.5 dB at 3.4 kHz (was a 2.5 dB cut at 2.35 kHz). Give him a
   > listen. Want it backed off or reverted?"

## Reverting

Every change is logged with its `old_value`, so "undo that" / "put it back" = read the last
matching entry in today's changelog and apply a batch that restores `old_raw`. Confirm what you
reverted.

---

## Freshness

- The loaded capture is good for the immediate session. **Re-capture** (`--duration 5`) if it's been
  ~15–20 min, if the engineer says they changed the board, or before a change if you're unsure the
  state is current.
- **RTA is always gathered fresh per EQ tweak** — never reuse an old spectrum for a new decision.

## Deeper EQ logic

For source-specific EQ heuristics (vocal presence stacking, drum lanes, instrument ranges), the
domain rules live in `docs/VENUE.md` (already read) and, if you want the detailed worker logic, in
`.claude/commands/x32-auto-awesome/*-eq.md`. Don't blindly load them every request — reach for them
only when a tweak needs the depth.
