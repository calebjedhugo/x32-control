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
- **FX1 insert on ch31**: Reported as disconnected but was actually connected. Query failure — insert status reads as OFF/null consistently.

## 2026-03-08
- 28 changes applied (25 metering, 3 EQ). Stopped after 1 iteration — engineer was happy with sound.
- **Drum reverb sends still excessive**: CamVerb too hot on toms (-3dB), kick (+2dB!), overheads (-1.5dB). Claude reduced all. Pattern confirmed from 2026-03-04 — drum reverb sends drift high between sessions.
- **Floor Tom + Ride compressors were OFF**: Claude enabled with appropriate settings. Engineer kept.
- **Violin compressor threshold too low**: 0.242 (-23dB) always squeezing. Claude raised to 0.4 (-12dB). Engineer kept.
- **Engineer manual changes observed**:
  - Drums bus faders raised +2dB (-6.4→-4.6dB) — **pattern: Claude sets drum bus too low for FOH**
  - Violin fader pulled down further (-2.6→-5.8dB) — continuing pattern from 2026-03-04, violin still too loud
  - Mid Tom fader raised +1.2dB (1.6→2.8dB)
  - Tammy EQ band 3 at 6.6kHz: removed -1.5dB cut (wanted her brighter at FOH)
  - Ch4 JEN! brought online: compressor enabled, fader -4.7→+0.7dB
  - Computer faders raised 0.5→2.9dB for playback
- **FX1 routing**: Still on wrong channel. Diff shows ch28 Ride insert went from FX1→none (possibly disconnected during session). Ch1 Tammy insert reported as FX1 instead of FX4 — likely query failure, not real.
- **DATA BUGS in final capture diff**:
  - FX4 par/08 (Tammy exciter timbre) reported as 0 instead of 0.6 — query failure
  - Ch19 Tammy Guitar comp reported disabled — query failure (was ON with tuned params)
  - Ch25 Snare EQ freq shift 632→296Hz — possible query failure (marked suspicious)
  - 60s final capture with muted channels: only 3 active channels detected. Settings data complete but metering sparse.
- **Patterns confirmed across sessions**:
  - Drum reverb sends consistently too hot (3 sessions now)
  - Violin consistently needs to be pulled down
  - Engineer prefers brighter Tammy at FOH (removed presence cut)
  - Drum bus faders need to be higher than Claude sets them

## 2026-03-11
- 15 changes applied (9 metering, 4 EQ, 2 iteration-2 fixes). Converged in 2 iterations.
- **Livestream agent not properly dispatched**: Editor analyzed livestream inline instead of spawning a dedicated subagent. Did NOT compare bus meter peaks against VENUE.md target table. Send levels were left unchanged without proper validation.
- **Tammy CamVerb send enabled**: Was at -inf (no livestream reverb). Set to -10dB. Engineer kept.
- **Snare CamVerb send reduced**: -2.8dB → -7dB (excessive livestream reverb). Engineer kept.
- **Front Guitar HPF enabled**: Was OFF. Set to ~80Hz. Engineer kept HPF but completely reworked all 4 EQ bands and raised compressor threshold. Channel renamed Violin → Front Guitar.
- **Engineer manual changes observed**:
  - Vocal faders: Randy +4.2dB, Jen +1.8dB, Bart +1.7dB (raised). Sara -3.9dB, Kat -4.3dB (lowered). **Pattern confirmed: Claude underestimates vocal levels (4th session)**
  - Bart EQ band 4 HF shelf: Claude set +3dB, engineer lowered to +1.5dB. SM58 baritone needs less HF.
  - Kat EQ band 4: Engineer added +10.3dB at 2.3kHz (aggressive presence boost Claude missed)
  - Piano faders raised ~1-2dB — **pattern continues from 2026-03-04: Claude underestimates piano**
  - Bass fader dropped -6.4dB by engineer
  - Main LR band 5: -3.2dB → 0dB at 3.8kHz (HF presence cut removed or query corruption — verify next session)
  - FX1 par/03 adjusted despite insert being OFF
- **FX1 (bass Ultimo) insert**: Capture reported OFF but engineer confirms it is both routed (insert/sel=1 → FX1) AND active. The `/ch/31/insert/on` query consistently returns 0 when the insert is actually on. Known false readback — do NOT flag this in future sessions.
- **DATA BUGS**: 28 query failures in final capture. mtx04 Cam R EQ band 3 flagged suspicious. Known pattern — 5s captures less reliable than 60s.
- **Patterns confirmed/updated**:
  - Claude underestimates vocal faders (4 sessions — should bias vocals +2dB higher)
  - Claude underestimates piano faders (3 sessions — should bias piano +1dB higher)
  - Drum reverb sends still need monitoring (corrected again this session)
  - Kat may need dedicated presence boost that Claude doesn't suggest
  - Main LR HF cut status uncertain — verify at next session start
