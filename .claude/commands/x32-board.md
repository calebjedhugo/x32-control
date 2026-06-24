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

## ⚠️ ONE-TIME: verify the RTA lock fix (added 2026-06-24 — remove once confirmed)

The RTA `/meters/4` corrupt-lock fix (renew-not-hammer + cooldown + lock detection in
`scripts/rta_listen.py`) was merged but **never verified on a live board with signal**. Next time
you're at the desk with musicians playing, before the engineer gets deep into requests:

1. With a low source (bass) and a bright source (vocal/piano-high) both playing, scan each
   repeatedly back-to-back and confirm their **absolute** band spectra (`bands[*].peak`) stay
   distinct — the lock no longer reproduces under scan load.
2. Scan a silent channel and confirm it reads near-zero (not a loud "locked" blob).
3. If a scan ever returns `"RTA feed corrupt — cool down and rescan"`, that's the new detector
   working — `--retry-on-lock` should auto-recover after ~18s.

Tell the engineer the result in plain English ("RTA's holding up under repeated scans"), then delete
this block from the skill.

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
5. **RTA** — assume healthy (it is; see the dedicated section). Do NOT run a pin-check at boot off a
   quiet board — the check needs two channels actually producing signal, which often don't exist
   pre-service. Run it only when an EQ tweak is requested and you have two active, spectrally-distinct
   channels to compare. A quiet board ≠ broken RTA.
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

**RTA WORKS. Default assumption: RTA is healthy.** Verified end-to-end on 2026-06-24 (bass ch31
returned `valid:true`, real low-frequency spectrum; piano returned distinct presence/brilliance
content; the tap demonstrably follows `/-stat/rtasource`). Earlier sessions repeatedly declared RTA
"pinned/blocked" and skipped all EQ — **those were almost all FALSE alarms from a broken sanity
check.** Do not inherit that pessimism. Trust the script's own per-channel `valid` field: `valid:true`
with a source-appropriate shape = good data, proceed.

**The real failure mode is SELF-INFLICTED, not an external client (proven 2026-06-24).** The old
docs blamed "a second X32 controller pinning the tap." That is a **myth** — it was investigated live
with no other software running and nobody at the desk, and the tap still locked. The actual cause:
**hammering the desk with rapid, piled-up `/meters/4` subscriptions.** `rta_listen` opens a fresh UDP
socket per run and re-subscribes every 100 ms; do enough of that in quick succession (e.g. scanning
many channels back-to-back) and the X32's meter feed corrupts and **locks onto a fixed spectrum that
no source pointer can move.** Confirmed signatures of the locked/corrupt state:
- A **silent channel** (`peak_meter` ≈ 0) returns a **loud** spectrum — impossible if it were real.
- Two spectrally-different channels return **identical absolute spectra** regardless of which you select.
- The blob is **structurally broken**: many bins pinned to exactly `0.0000` wedged between strong
  ones, a fixed peak template that doesn't change with the source.
- Setting `/-stat/rtasource`, `/-prefs/rta/source`, `/-stat/selidx`, clearing solo, or toggling
  `/-prefs/rta/mode` does **nothing**. (If you're reaching for these, you're already locked.)

**The FIRST scan in a fresh session is the trustworthy one.** RTA works correctly when you haven't
been pounding it (startup: bass→low, piano→bright, hats→silent, all correct). It degrades under load.

**Detecting the lock (compare ABSOLUTE magnitudes, never normalized peak Hz):** pick a low source
(bass/kick) and a bright one (vocal/cymbal/piano-high), both with `peak_meter` off the floor
(> ~0.02), and compare `bands[*].peak` raw values. Healthy = the bright channel has real
`presence`/`brilliance` the low one lacks. Locked = identical spectra, or a silent channel reading
loud. (The OLD check compared `peaks[].freq_hz`, normalized per channel — a silent channel's
noise-floor peaks coincidentally match anything, which is what produced years of false "pinned"
alarms. Don't use it.)

**The remedy is a COOLDOWN, not closing phantom software:**
> Go quiet. Stop all scanning for ~15–20 s so the stale meter subscriptions expire, then do **one**
> clean scan. Don't pile on more subscriptions trying to "force" it — that's what locked it.

Do **not** tell the engineer to close X32-Edit unless you have independent evidence it's actually
open. The default explanation is your own scan load.

**Never diagnose a lock from a silent channel alone.** If your comparator reads near zero, the band
just isn't playing — a quiet board is not a broken RTA.

**Scan hygiene (avoid the lock in the first place):** scan sparingly — one channel at a time, only
when a tweak needs it, and don't loop over many channels rapidly. If you must scan several, space
them out. (Code follow-up tracked in `docs/CORRECTIONS.md` 2026-06-24: `rta_listen.py` should reuse
one socket / use `/renew` instead of re-`/batchsubscribe` at 100 ms, and the auto-awesome
`rta-gather` worker's all-channels loop is the prime trigger.)

> Note: running RTA moves the desk's RTA-source picker and selected channel. Harmless (display
> only), but mention it if the engineer cares, and offer to set it back.

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
