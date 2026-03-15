# Session Corrections Log

*Wiped 2026-03-15: All prior entries (2026-02-25 through 2026-03-15) were recorded with a buggy capture script that produced corrupted EQ/parameter readbacks. Patterns derived from that data are unreliable. Fresh start with fixed capture script.*

## Known issues (carried forward, verified independently of capture data)
- **FX1 (bass Ultimo) insert on ch31**: `/ch/31/insert/on` query consistently returns 0 when insert is actually on. Known false readback — do NOT flag in sessions.
- **bus01 "2 TmyInst"**: In-ear monitor bus. Not relevant to mix.
