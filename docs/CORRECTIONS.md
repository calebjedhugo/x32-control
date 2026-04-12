# Session Corrections Log

*Wiped 2026-03-15: All prior entries (2026-02-25 through 2026-03-15) were recorded with a buggy capture script that produced corrupted EQ/parameter readbacks. Patterns derived from that data are unreliable. Fresh start with fixed capture script.*

## Known issues (carried forward, verified independently of capture data)
- **FX1 (bass Ultimo) insert on ch31**: `/ch/31/insert/on` query consistently returns 0 when insert is actually on. Known false readback — do NOT flag in sessions.
- **bus01 "2 TmyInst"**: In-ear monitor bus. Not relevant to mix.
- **RTA requires `/-prefs/rta/mode=1`**: Without this, `/meters/4` returns stale/default data regardless of source. With mode=1, per-channel RTA works correctly via `/-prefs/rta/source`. Fixed 2026-04-12. The `subscribe_rta()` method now sets mode=1 automatically.
- **RTA blob format is LE float32**: 4-byte LE int32 count (82) + 82 LE float32 values (0.0-1.0). NOT big-endian int16. The original BE int16 parser produced plausible-looking but wrong data by misinterpreting float bytes as integers.
- **EQ without RTA makes things worse**: 2026-04-12 session applied uniform -3 to -4.5dB cuts at 2.1kHz on every channel without per-channel data. Engineer had to revert most of them. Rule: if RTA data is unavailable, skip EQ agents entirely — metering-only changes are safe.

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
