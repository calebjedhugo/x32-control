# Session Corrections Log

## 2026-06-28 — RTA "lock" was a wrong-bank parse bug. FIXED. (supersedes all 2026-06-24 RTA notes)

**Root cause, proven by raw-blob inspection on the live desk:** `scripts/rta_listen.py` was reading
the **wrong meter bank in the wrong format**. It subscribed to `/meters/4` and parsed it as 82 ×
float32. `/meters/4` is a **channel/bus LEVEL-METER bank, not a spectrum** — so the "frozen corrupt
template" (peaks pinned at bins 50/74/75 = ~1350 Hz + a duplicated 10.2/11.1 kHz pair, with b74==b75
exactly) was just always-hot meter slots and a stereo pair, not audio. That is the entire "lock."

**Therefore the whole 2026-06-24 entry below is WRONG and is retained only as history:** there was no
corrupt-lock, no subscription-pile-up corruption, no "second X32 client," and the cooldown/`--retry-
on-lock` remedy never did anything. Cooldowns appeared to "not clear" the lock because there was
nothing to clear — the parser produced the same phantom every time by construction.

**The real RTA** is `/meters/15`: int32 count (=50 words), then **100 signed int16** where
`value ÷ 256 = dB`. Parsed that way (→ linear amplitude) it yields a clean, believable spectrum. Bank
probe confirmed `/meters/0,4,13` are all level-meter banks (shared `[0.072, 0.211, …]` channel
prefix); only `/meters/15` is the 100-band analyzer.

**Fix applied to `scripts/rta_listen.py` (unit-tested offline against a captured `/meters/15` blob;
NOT yet live-verified end-to-end because that needs board writes):**
- `parse_rta_blob` → 100 × int16 (dB÷256) → linear; `NUM_RTA_BINS` 82→100; `bin_to_freq` uses N−1 so
  bin 99 = 20 kHz; `FREQUENCY_BANDS` and the hardcoded analysis bin ranges (mud/resonance/tilt/
  transient) all recomputed for 100 bins.
- subscribe/renew/parse use `/meters/15`; `_detect_lock` neutralized to a no-op; `_validate_data`'s
  lock branch replaced with an **honest source-select guard** (silent channel meter + live RTA →
  `valid:false`, "RTA source-select is not tracking this channel").

**Still OPEN — verify next session with signal (needs a live board write):** even on `/meters/15`,
the tap did not follow `/-stat/rtasource` in passive testing (two reads of the same channel differed
MORE than two different channels). The script now sets **both** `/-stat/selidx` and `/-stat/rtasource`
as a best guess, but **which one actually steers `/meters/15` is unconfirmed.** Confirm with a
bright-vs-low both-playing scan (see the one-time block in the x32-board skill). If it doesn't switch,
the remaining fix is the source-select address — block per-channel EQ until then.

Code follow-up: `.claude/commands/x32-auto-awesome/rta-gather.md` and any docs still describing the
"lock"/cooldown can be simplified; they're chasing a bug that no longer exists.

## TODO

### Open
1. **De-esser for Brian (ch9, speaking/headset) — deferred to a future session (2026-06-14).**
   Diagnosis done: sibilance energy peaks at **10–11 kHz** (his voice is very top-heavy, −23 dB
   slope). Engineer already (a) eased the heavy 5:1 comp and (b) moved his ~8 kHz EQ cut up to
   ~10 kHz — helped but not enough. A real de-esser is wanted. Blocker: **all 8 FX slots are in
   use**, and only FX1–4 can be channel inserts (bass Ultimo / CamVerb / AudVerb / Tammy exciter) —
   no free home for a de-esser without sacrificing one. No-slot stock alternative to try first:
   the channel **compressor sidechain key filter** keyed to ~6–9 kHz (ducks on the "s"; pumps the
   whole channel slightly). Decide between that vs. freeing an FX slot next session.

### Downgraded (was item 3 — do NOT just execute it)
- **session_capture.py plausible defaults → null refactor: shelved 2026-06-14.** Rationale: failures
  are rare post-Mar-2026 fix (0 in the 2026-06-14 session), `metadata.query_failures.count` is now
  always emitted so a clean capture is provable, and `control.py` pre-write verification + `query.py`
  nulls already backstop bad data reaching the board. The ~60-site refactor cascades into
  analyze/extract/diff math (null arithmetic) for marginal gain. Revisit ONLY if failure rates climb
  again — then do it with the downstream null-tolerance changes, not in isolation.

### Done 2026-06-14 (at the board)
- ✅ Restored FX7 amp sim: par07→0.725, par08→0.4. **Live-only** — the degraded 0.55/0.35 persist in
  the saved scene; re-save the scene to make it stick (engineer's call — not done by Claude).
- ✅ Live-verified pre-write verification (matching old_value applies; gross mismatch caught by
  static validation; subtle mismatch caught by the live pre-write read — the exact Sunday scenario).
- ✅ session_capture.py now always writes `metadata.query_failures` (even count 0).
- ✅ **Fixed the `/meters/0` channel-dropout bug** (ch9/19/20 reading 0 with signal). Root cause: the
  channel meter parser used a 2-values-per-channel stride; the blob is 1-per-channel. Confirmed live
  with the announcement on ch10 (speech tracked idx9, not the 2-per idx18), fixed the stride in
  common.py, re-captured → ch10 reads correctly. **All historical per-channel gain-staging levels
  except ch1 were mis-attributed** — don't trust pre-2026-06-14 capture channel peaks. Detail in
  TECHNICAL.md. (Earlier "parser is fine, it's a tap-point issue" conclusion was wrong — it had
  trusted the bad parser's own labels; isolating one known channel exposed it.)

*Wiped 2026-03-15: All prior entries (2026-02-25 through 2026-03-15) were recorded with a buggy capture script that produced corrupted EQ/parameter readbacks. Patterns derived from that data are unreliable. Fresh start with fixed capture script.*

## Known issues (carried forward, verified independently of capture data)
- **FX1 (bass Ultimo) insert on ch31**: `/ch/31/insert/on` query consistently returns 0 when insert is actually on. Known false readback — do NOT flag in sessions.
- **bus01 "2 TmyInst"**: In-ear monitor bus. Not relevant to mix.
- **RTA requires `/-prefs/rta/mode=1` AND `/-stat/rtasource=channel-1`**: Two separate gotchas, both needed. (1) Without `/-prefs/rta/mode=1`, `/meters/4` returns stale/default data. (2) The active RTA tap is driven by `/-stat/rtasource` (0-indexed: ch26 → value 25), NOT by `/-prefs/rta/source`. The `prefs` address is just the UI dropdown — the desk happily stores writes there but never reads from it. Symptom of the prefs mistake: every channel's RTA looks like Main L (or whatever the desk was last looking at). Mode-only fix landed 2026-04-12; the source-address fix landed 2026-05-24 after the prefs-vs-stat confusion was caught empirically (writing to `/-prefs/rta/source` while reading back `/-stat/rtasource` showed they don't track). `subscribe_rta()` sets both, and the re-subscribe loop re-asserts `/-stat/rtasource` every 100ms so a stray tap on the desk's RTA picker can't silently steal the source. **⚠️ 2026-06-24: that 100 ms re-`/batchsubscribe` loop is now the prime SUSPECT for the RTA "lock" (corrupt/frozen `/meters/4`), not a protection — see the 2026-06-24 entry. Source re-assertion via `/renew` would be gentler. Don't trust this bullet's "can't steal the source" framing; the source-pointer reads turned out not to drive `/meters/4` once locked.**
- **RTA blob format is LE float32**: 4-byte LE int32 count (82) + 82 LE float32 values (0.0-1.0). NOT big-endian int16. The original BE int16 parser produced plausible-looking but wrong data by misinterpreting float bytes as integers.
- **EQ without RTA makes things worse**: 2026-04-12 session applied uniform -3 to -4.5dB cuts at 2.1kHz on every channel without per-channel data. Engineer had to revert most of them. Rule: if RTA data is unavailable, skip EQ agents entirely — metering-only changes are safe.
- **"RTA is pinned by a second X32 client" is a MYTH (corrected 2026-06-24)**: fresh RTA works. When it *does* lock, the cause is SELF-INFLICTED — hammering the desk with rapid piled-up `/meters/4` subscriptions — NOT another controller. Proven live with no other software running and nobody at the desk. Remedy is a cooldown, not closing phantom apps. Also: never declare a problem by comparing normalized peak frequencies, and never from a silent channel. See the 2026-06-24 entry.

## 2026-06-24

### RTA confirmed working — "pinned/blocked" verdicts were a broken-diagnostic artifact
Engineer flagged that the last few sessions wrongly claimed RTA was unavailable. Investigated with bass (ch31) as the test channel. **RTA returns real, valid, per-channel data** — bass came back `valid:true`, 109 samples, energy concentrated at 84/108/250 Hz with nothing above (textbook bass DI). Piano low, scanned the same way, showed distinct `presence`+`brilliance` energy the bass lacks. The tap demonstrably follows `/-stat/rtasource`; nothing was pinned.

**Root cause of the false alarms:** the board skill's pin sanity-check compared each channel's *normalized peak-frequency list* (`peaks[].freq_hz`, scaled to that channel's own loudest bin). When a comparator channel is **silent** (not being played), its normalized peaks are just noise-floor artifacts and **coincidentally match any other channel's** — here a silent hi-hat (peak_meter 0.0012) returned the same 250/108/84/77 Hz labels as the active bass, which reads as "identical spectra → pinned." It was never pinned; the hats just weren't playing. Past instances picked a silent channel as a comparator and condemned a working RTA, then skipped all EQ for the session.

**Correct pin check (now in the skill):**
- Only run it when an EQ tweak is actually requested, using **two channels that BOTH currently have signal** (`peak_meter` > ~0.02; near 0.001 = silent, not pinned) and that should differ spectrally (low source vs. bright source).
- Compare **absolute band energy** (`bands[*].peak`, raw 0.0–1.0), NOT peak-frequency labels. Healthy = bright channel has `presence`/`brilliance` the low channel lacks. Pinned = two channels with *different* `peak_meter` but *identical absolute spectra* — the only thing that warrants stopping.
- A quiet/pre-service board is NOT a broken RTA. Don't pin-check off silence at boot.

Decisive numbers from the session (absolute band peaks): Bass low_mid 0.0103 / presence 0 / brilliance 0; Piano low presence 0.0026 / brilliance 0.0015; Hi-hats (silent) all ~0.0014. Distinct absolute spectra = tap is switching correctly.

### Then we reproduced the REAL bug — and it is self-inflicted, not a second X32 client
Continuing the same session, after applying bass EQ and doing a multi-channel disambiguation scan (Randy ch2, Tammy-Guitar ch19 [silent], Acust-Guitar ch20 in a tight loop), the RTA **locked**: a silent bass (ch31, `peak_meter`=0) and the playing piano (ch17) returned **identical** bright spectra. Engineer confirmed: **no other software running, nobody at the desk, only my own OSC actions touched the board.** So the long-standing "another X32 controller pinned `/-stat/rtasource`" explanation in these docs is **wrong** — that was the misdiagnosis that made past sessions give up on RTA.

**What was verified (empirically, this session):**
- The lock ignores **every** source pointer: setting `/-stat/rtasource`, `/-prefs/rta/source`, `/-stat/selidx`, clearing solo, and toggling `/-prefs/rta/mode` 0→1 all left the same fixed spectrum. (`/-prefs/rta/source` happened to read 16 = ch17 piano = the one thing playing, which is a coincidence of what I'd last set, not the driver.)
- The locked blob is **structurally corrupt**, not channel audio: 82 bins in correct LE-float32 format, but ~40 of them pinned to exactly `0.0000` wedged between strong bins, 250 Hz (bin 30) always dead, and a fixed peak template (1350 Hz, 10.2/11.1 kHz — bins 50/74/75, with 74==75 exactly). A real spectrum never looks like this.
- Magnitude jumped ~50× vs the startup scans (0.01 range → 0.5 range) and stopped tracking the source.
- A ~18 s quiet cooldown changed the **levels** (bass total 5.5 vs piano 1.7) but not the locked **shape**, and the silent bass even read *louder* than the playing piano — still wrong.

**Leading mechanism (high confidence, exact slot-vs-parser detail not yet isolated):** meter-subscription pile-up. `rta_listen` opens a fresh UDP socket per invocation and re-`/batchsubscribe`s `/meters/4` + `/meters/0` every 100 ms; many runs in quick succession (or one all-channels loop) corrupt/saturate the X32 meter feed until it emits a locked, broken blob. The **first** scan of a fresh session is reliable; reliability degrades under scan load. This exactly matches the historical pattern where the auto-awesome `rta-gather` worker (scans ALL channels back-to-back) "found RTA pinned."

**Operational fix (now in the board skill):** scan sparingly (one channel, only when needed); on a suspected lock, **cool down ~15–20 s with zero traffic, then do ONE clean scan** — do not pile on more subscriptions or blame external software. Detect a lock by absolute magnitudes (silent channel reading loud, or identical spectra across distinct sources), never by normalized peak Hz.

**Code follow-ups (NOT yet done — band stopped playing before they could be tested live):**
1. `scripts/rta_listen.py`: reuse a single persistent socket across scans; replace the 100 ms re-`/batchsubscribe` with `/renew <alias>`; explicitly `/unsubscribe` (or let one connection's subs lapse) before the next scan. Add a cooldown/backoff between consecutive channel scans.
2. `scripts/rta_listen.py` `_validate_data()`: catch the lock signature — N bins exactly 0.0 between strong bins, or a silent `peak_meter` with a loud RTA blob → mark `valid:false` with note "RTA feed corrupt — cool down and rescan" (and stop printing the misleading "check for a second X32 client" hint).
3. `.claude/commands/x32-auto-awesome/rta-gather.md`: the all-channels back-to-back loop is the prime trigger — space scans out, reuse one connection, and treat a lock as "cool down + retry," not "abort, RTA unavailable."
These need a live board with signal to verify; do them at the start of the next session before any heavy scanning.

## 2026-06-10

First full auto-awesome session (orchestrator/worker architecture). 147 automated changes over 2 passes (18 metering, 102 EQ, 27 upstream). Per-channel RTA verified distinct (0 identical pairs of 120; clone-spectra bug confirmed fixed).

### Oscillation/creep — main lesson
- **Fresh workers re-push the same params every iteration.** FX7 amp sim Low climbed 0.45→0.55→0.65→0.72 over 3 iters; pass 2 vocal EQ bands ping-ponged ±1 step (JEN band 3 round-tripped exactly back to start). Orchestrator changelog repeat-check caught both; channel iteration stopped early both passes. **Workers need an anti-creep rule: do not re-adjust a param the changelog shows was already moved the same direction this session.**
- **FX7 "engineer override" was a worker hallucination (corrected 2026-06-10 post-session).**
  Transcript forensics: the engineer never touched the amp sim, and 0.5 never existed on the board
  (four consecutive captures read 0.725). The iter-6 instruments-eq worker's extract showed the true
  value (`"7": 0.725`) but it wrote `old_value: 0.5` in its output anyway — fabricated. Its
  "+0.05 nudge" to 0.55 was really a −0.175 cut; that's why the guitar lost clarity at the end.
  Lesson: never infer engineer intent from old-value discontinuities — verify against captures or a
  live read first. control.py --batch now pre-write-verifies every command against the live board
  and refuses old_value mismatches, so a fabricated old value can no longer reach the mixer.
- **Livestream sends chase program material**: pass 1 raised Voices→Cam send, pass 2 cut it below origin (different songs, same targets). Ambient/CamVerb cuts were consistent both passes (likely real). Calibrate VENUE.md livestream targets from an actual stream recording before trusting another upstream pass.

### What Claude changed vs what engineer kept/adjusted
- **Kept**: bass + e-guitar comp threshold raises; Jen comp release 390ms; FX5 drums slower attack; FX2 CamVerb hi-cut; FX4 Tammy exciter timbre +12.5; John gate enable + HPF 153→89Hz; tom 805Hz mud cuts and 3.9kHz ceiling-zone band-4 cuts; snare/hi-hat/bass EQ reshaping; KB band-3 flip +2.5→-3.8dB.
- **Engineer fader moves after automation** (workers never touch faders): Tammy +1.5, Kat +2.0, e-guitar +6.2, Voices bus +1.2 up; Bass -5.2, KB-L/R -3.5, Piano high -4.1, Snare -1.2 down. Pattern repeat: engineer raises vocals/Voices (Claude underestimates vocal level in this room).
- **Engineer preamp gain moves** (workers only touch trim): Randy/Kat/High Tom up, KB-L/R 0.500→0.306 down (KB was flagged hot all session — engineer fixed at the gain stage), Bass down.
- **Engineer raised piano comp thresholds** (less compression) — automation never touched piano dynamics.

### Data quality notes
- ch09 John (speaking headset) and ch21 Violin RTA invalid in every splice (peak meter 0 while RTA shows signal) — they got no EQ analysis all session. Investigate the mismatch.
- Kick ch26 never registered active in any capture window; excluded from drum worker lists all session. Verify mic/gate next time.
- Two captures landed in practice lulls (near-silent). Orchestrator caught and re-captured both. Consider a signal-level gate in session_capture.py that warns when peaks are ~30dB below targets.

## 2026-03-25
- No automation applied — session cut short before editor ran.
- **Ch21 Flute-Jen feedback fix**: Engineer raised HPF 200→262Hz and flattened 3.6kHz boost (+3.2→+0.2dB). Reverb send reduction (suggested at -1.0dB) was NOT needed — HPF + killing the presence boost was sufficient. Pattern: for condenser feedback, prioritize cutting EQ boosts in the 2-5kHz ceiling reflection zone before reducing reverb sends.
- **Ch32 e-guitar**: Engineer deepened 202Hz cut (-2.3→-4.5dB) independently.
- **Ch31 labeled "Front Guitar"** with FX1 Ultimo insert — previously documented as bass channel. Label may have changed or channel repurposed. Verify next session.

## 2026-04-12

### What Claude changed vs what engineer kept/adjusted
- **Tammy EQ**: Claude cut -4.5dB at 2.1kHz. Engineer moved band to 3.9kHz at -2.5dB instead — different frequency, different purpose. Also deepened 3.0kHz cut from -1.5 to -2.3dB. Pattern: engineer targets ceiling reflection zone (3-4kHz) more precisely.
- **Systemic 2.1kHz cuts**: Claude applied uniform -3 to -4.5dB at 2.1kHz on every channel without RTA data. Engineer reverted nearly all of them, restoring original frequencies and gains. Only kept direction (not depth) on toms (flattened +2dB boosts to 0dB).
- **Keyboard (KB-Left/Right)**: Claude cut -3dB at 2.1kHz. Engineer moved to 3.6kHz at +3.5dB — a presence boost, complete opposite. Keyboards struggle to cut through in this mix (documented issue).
- **E-guitar**: Claude cut across the board. Engineer completely reworked all 4 bands: -1dB at 189Hz, -3.2dB at 448Hz, +2dB at 1.4kHz, +1.3dB at 5.6kHz. This is expert shaping — low cut, mid scoop, presence + air boost.
- **Flute-Jen**: Engineer raised fader 3.6→5.0dB (buried), moved air boost from 11.5kHz to 7.3kHz and increased from +1 to +2.5dB.
- **Piano high**: Engineer flipped 2.3kHz from -1dB cut to +1dB boost.
- **Hi-hats**: Engineer dropped fader from +1.4 to -3.2dB (4.6dB cut). Claude's trim and HPF changes kept.
- **Brian (speaking)**: Engineer raised fader +2dB and restored original +3dB at 2.1kHz (was always there, not a resonance issue for this channel).
- **Voices bus**: Engineer pulled fader from +1.6 to +0.5dB.
- **Drums bus**: Engineer pulled fader from -0.3 to -2.4dB.
- **Randy compressor**: Engineer lowered threshold (more compression). Claude's trim boost kept.
- **Bass compressor**: Engineer raised threshold (less compression). Claude's HPF-off and 98Hz cut kept.
- **Main bus**: Engineer flattened 1.8kHz +1.3dB boost to 0dB, slightly raised 121Hz shelf cut.
- **Metering changes kept**: Trim boosts (Randy, John, Kat), trim cuts (hi-hats, ride, e-guitar), HPF changes (overheads 140→120Hz, high tom 97→75Hz, bass HPF off) — all kept.
- **Reverb changes kept**: AudVerb shorter/damper, CamVerb warmer — all kept.
- **FX changes kept**: FX5 Ultimo faster release, FX7 amp sim reduced buzz — kept.
- **Livestream sends**: All 3dB step-downs kept.

### Observations
- **No EQ without RTA**: Uniform cuts without frequency data caused more damage than they fixed. Metering-only changes (trim, gates, HPF) were safe and helpful. Rule added to skill: block EQ agents when RTA unavailable.
- **RTA was broken due to `/-prefs/rta/mode=0`**: Fixed by setting mode=1 in subscribe_rta(). Per-channel RTA confirmed working with LE float32 format.
- **Engineer's EQ is surgical**: Band-specific frequencies and gains tailored to each instrument. Automation should support this, not override it with blanket rules.

## 2026-03-29

### What Claude changed vs what engineer kept/adjusted
- **Voices bus fader**: Claude left at -0.9dB after enabling bus compressor and cutting 2kHz across all vocals. Engineer raised to +4.1dB. Pattern: systemic resonance cuts across multiple channels need compensating level increase.
- **AudVerb fader**: Claude left at +0.5dB. Engineer pulled to -6.9dB. Pattern: Claude underestimates how reverberant the room already is — be more aggressive reducing FOH reverb.
- **Main fader**: Engineer raised +0.3→+2.4dB. EQ cuts across the board reduced overall level.
- **Ch31 Front Guitar**: Claude treated as bass (wrong — it's acoustic guitar). Engineer corrected. **RESOLVED: ch31 IS an acoustic guitar. Labels are always authoritative. FX1 Ultimo on ch31 is a routing anomaly — do not reclassify.**
- **FX6 Precision Limiter**: Claude changed params thinking it was on drums bus. **It's on the MAINS.** Capture script doesn't read main bus insert — blind spot. Changes partially reverted. Engineer uncertain if plugin is even active/inserted.
- **FX5 Ultimo output**: 0.1→0.5. Engineer kept — original was likely accidental/legacy.
- **Flute fader**: Engineer raised -0.6→+3.6dB (buried). Agents didn't touch faders.
- **E-guitar fader**: Engineer raised -4.1→+4.2dB (new arrival, needed boost).
- **Sara**: Engineer fixed double-routing (was going to both Voices bus and Tammy voice bus).

### Observations
- **2kHz ceiling resonance is systemic**: RTA confirmed +7-10dB at 2-2.1kHz on nearly every channel. Vaulted wood ceiling. Both channel-level cuts and Voices bus group cut applied.
- **Muted channels are still in scope**: When polishing for next service, agents should evaluate settings against meter collector peaks regardless of mute state.
- **Tom compressor attacks are intentionally slow**: Slower attack = more punch. Not a problem.
- **Drums bus L/R imbalance is intentional**: Hi-hats overhead positioned for crash capture, turned down.
- **Acoustic guitars have no CamVerb send**: ch20/ch31 at -inf to CamVerb. Appears intentional.
- **FX5 is stereo**: Covers both L and R of the drums bus pair. FX6 is NOT on the drums bus.
