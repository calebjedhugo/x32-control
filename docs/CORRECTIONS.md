# Session Corrections Log

## 2026-02-25
- First auto-awesome session. 21 changes applied in pass 1, board powered off before pass 2.
- No engineer corrections to evaluate (board lost all changes on power-off).
- Routing issues found: FX1 on ch09+bus05/06 (should be ch31), FX8 not inserted (should be bus05/06), ch31 insert off. Engineer acknowledged, chose to proceed.
- Stream guard fix: changed yt-dlp format from `bestaudio` to `bestaudio/best` — livestream HLS has no audio-only formats.
- Stream guard still has pipeline stability issues — pipeline dies after running for a while, needs further debugging.
- Note: X32 software running on another machine causes OSC packet drops during captures.

## 2026-03-04
- 30 changes applied (14 metering, 6 EQ, 10 upstream). Converged in 2 iterations.
- **Livestream buses were all at -inf**: Bus 09 (Tammy voice), 10 (Acoustic), 13 (Electronic), 14 (Ambient) all had faders at -90dB. Claude raised to -2dB/-5dB. Engineer kept these (adjusted Ambient to -6dB).
- **Sara (ch5) had extreme EQ**: +12dB at 1.8kHz, +6.9dB at 316Hz. Claude reduced both to +1.5dB. Engineer kept the reductions and also raised her fader from -1.0 to -0.5dB.
- **Sara had no gate or compressor**: Claude enabled both. Engineer kept.
- **Drum reverb sends were excessive**: Toms at -1dB AudVerb, kick at -1dB. Claude reduced to -7dB (toms) and -14dB (kick). Engineer kept.
- **Engineer manual changes observed**:
  - Piano faders raised: low -0.4→+0.2dB, high -0.5→+0.7dB (pattern: Claude may underestimate piano)
  - Main LR fader pulled down 0→-0.8dB after Claude's changes
  - Ch20 (Violin this session): preamp halved 1.0→0.5, fader lowered +0.1→-2.6dB. Engineer-initiated reduction.
  - Sara fader raised -1.0→-0.5dB
  - Bus14 Ambient adjusted from Claude's -5dB to -6dB
- **DATA BUGS in final capture diff** (need investigation):
  - FX return faders all reported as -inf — almost certainly a readback bug, not real.
  - Cam L/R matrix faders reported at -35.3dB — engineer confirmed they were at unity by session end. Capture not reading matrix faders correctly.
  - Randy (ch2) compressor reported as disabled — not real. Capture warned "ch02 comp on returned None after 10 retries" → defaulted to OFF.
  - FX1 reported as Hall Reverb, FX7 reported type change — Hall Reverb is the default when FX type query fails. Neither was touched.
  - Multiple EQ frequency/gain changes across channels (John, Jen, Bart, Kat, KB, Hi-hats, Computer, Aux) — no human EQ changes were made. These are false diffs from unreliable EQ parameter readback.
  - TODO: Investigate why final capture has significantly more data corruption than initial 60s capture. Possible causes: shorter capture duration (5s vs 60s), mixer busy, or cumulative OSC connection issues.
- **Routing issues persisted**: FX1 insert on ch31 still needs connecting (someday).
