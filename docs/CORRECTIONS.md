# Session Corrections Log

## TODO (next session — read this first)

1. **Restore FX7 amp sim (targeted guitar session planned).** A worker's fabricated old_value left
   the amp sim degraded on 2026-06-10: par07 (Low) is 0.55, should be ~0.725; par08 (High) is 0.35,
   was 0.4 before the bad write. The engineer wants a dedicated guitar session — restore these as
   the starting point, then tune by ear with him. Don't "fix" FX7 in a general pass.
2. **Live-verify the new write safeguards (added 2026-06-10, untested against the board):**
   pre-write verification in `control.py --batch` (refuses old_value mismatches vs live reads) and
   `query.py` null-on-failure (failed reads now return null, never 0.5-style defaults). First time
   at the board: run a no-op batch (set a param to its current value) and confirm it applies, then
   one with a deliberately wrong old_value and confirm it's refused.
3. **session_capture.py still writes plausible defaults on failed reads** (~60 sites, e.g. EQ gain
   defaults to 0.5) — failures are counted in `metadata.query_failures` but the capture body shows
   fake values. Refactoring to nulls cascades into analyze/extract/diff and needs board time to
   verify. Until then: treat any capture with `query_failures.count > 0` with suspicion; the
   pre-write check in control.py is the backstop.

*Wiped 2026-03-15: All prior entries (2026-02-25 through 2026-03-15) were recorded with a buggy capture script that produced corrupted EQ/parameter readbacks. Patterns derived from that data are unreliable. Fresh start with fixed capture script.*

## Known issues (carried forward, verified independently of capture data)
- **FX1 (bass Ultimo) insert on ch31**: `/ch/31/insert/on` query consistently returns 0 when insert is actually on. Known false readback — do NOT flag in sessions.
- **bus01 "2 TmyInst"**: In-ear monitor bus. Not relevant to mix.
- **RTA requires `/-prefs/rta/mode=1` AND `/-stat/rtasource=channel-1`**: Two separate gotchas, both needed. (1) Without `/-prefs/rta/mode=1`, `/meters/4` returns stale/default data. (2) The active RTA tap is driven by `/-stat/rtasource` (0-indexed: ch26 → value 25), NOT by `/-prefs/rta/source`. The `prefs` address is just the UI dropdown — the desk happily stores writes there but never reads from it. Symptom of the prefs mistake: every channel's RTA looks like Main L (or whatever the desk was last looking at). Mode-only fix landed 2026-04-12; the source-address fix landed 2026-05-24 after the prefs-vs-stat confusion was caught empirically (writing to `/-prefs/rta/source` while reading back `/-stat/rtasource` showed they don't track). `subscribe_rta()` sets both, and the re-subscribe loop re-asserts `/-stat/rtasource` every 100ms so a stray tap on the desk's RTA picker can't silently steal the source.
- **RTA blob format is LE float32**: 4-byte LE int32 count (82) + 82 LE float32 values (0.0-1.0). NOT big-endian int16. The original BE int16 parser produced plausible-looking but wrong data by misinterpreting float bytes as integers.
- **EQ without RTA makes things worse**: 2026-04-12 session applied uniform -3 to -4.5dB cuts at 2.1kHz on every channel without per-channel data. Engineer had to revert most of them. Rule: if RTA data is unavailable, skip EQ agents entirely — metering-only changes are safe.

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
