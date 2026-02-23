# Corrections Log

End-of-session observations: what Claude suggested vs. what the engineer actually kept. Used to calibrate future suggestions.

## Format

```
## YYYY-MM-DD
- Parameter: Claude set X, engineer changed to Y (pattern note if applicable)
- Parameter: Claude set X, engineer left as-is
```

## 2026-02-18

### Changes engineer kept (approved)
- FX4 Tammy exciter Timbre High: 0.84 → 0.62 (+34 → +12), engineer left as-is
- FX8 BGV exciter Timbre: 0.56 → 0.52 (+6 → +2), engineer left as-is
- Drum gates enabled (ch22-25 close mics), engineer left as-is
- Snare/Kick comp ratio: 3:1 → 5:1, engineer left as-is
- Ch18 Piano high HPF: 120Hz → 79Hz, engineer left as-is
- Ch19 Tammy Guitar HPF: 39Hz → 79Hz, engineer left as-is
- Ch21 Flute-Jen, Ch22 Floor Tom, Ch28 Ride HPF enabled, engineer left as-is
- Drum EQ presence reductions (~1dB each on toms), engineer left as-is
- Hi-hats/Ride air EQ reduced ~1.5dB each, engineer left as-is
- KB-Left/Right EQ band 4: +3.5dB → +1.5dB, engineer left as-is

### Changes engineer modified
- Ch4 JEN! EQ band 3: Claude set +3.5dB, engineer lowered to +3.0dB (pattern: prefers less presence on BGVs)
- Ch3 John comp threshold: Claude set 0.45, engineer raised to 0.525 (pattern: prefers less compression on vocals)
- Ch5 Jill comp threshold: Claude set ~0.5, engineer raised to 0.575 (same pattern)

### Changes engineer undid or fixed
- Ch7 Kat: Claude made buggy EQ change (band 3 showed +7dB at 632Hz). Engineer disabled Kat's compressor — likely cleaned up the channel
- Bus16 CamVerb fader: 0.2dB → -8.6dB (engineer significantly reduced livestream reverb)
- Bus14 Ambient fader: -0.8dB → -8.5dB (engineer significantly lowered ambient mics)

### Engineer's own adjustments
- Ch3 John fader: 3.4dB → 2.3dB
- Ch4 JEN! fader: -6.3dB → -0.9dB (significant raise)
- Ch31 Bass fader: -2.9dB → 0.3dB (raised)
- Ch9 John (pastor) compressor: disabled
- Ch20 Violin EQ band 1: removed -2.3dB cut

### Flags
- Auto-awesome Pass 1 took 20+ min — editor didn't spawn subagents as designed
- Ch17 Piano low: preamp gain and EQ band 1 changes — source unclear (Claude or engineer)
- Capture read inconsistencies on some channels (Ch2 Randy, Ch7 Kat EQ freq shifts)

## 2026-02-22

### Changes engineer kept (approved)
- Vocal EQ: Randy 497Hz cut (-1.5dB), Kat 480Hz cut (-1.0dB), JEN! 678Hz reduction — all room-zone corrections kept
- Drum HPF fixes: Snare 148→89Hz, Hi-hats 183→110Hz, Floor Tom 49→58Hz, Mid Tom 58→70Hz — all kept
- Drum EQ: Tom presence reductions (+5dB→+2dB), kick sub boost halved (+6→+3dB), overhead air reduced — all kept
- Piano high brightness reduced, KB mid boost reduced, electric guitar super-air reduced — all kept
- Amp sim retuned: Punch 0.6→0.4, Buzz 0.45→0.55 — kept
- Bass comp tightened: ratio 3:1→5:1, threshold lowered — kept
- Snare fader +2dB — kept
- Randy gate enabled — kept
- Livestream send balance: vocal bus up +2.5dB, drums down -1.4dB, acoustic down -0.7dB — kept
- Cam L/R EQ: harmonic bass boost, sibilance cut, presence lift, R asymmetry fix — kept
- Cam L/R compressor tightened: 3:1→5:1, threshold lowered, +3dB makeup — kept

### Changes engineer modified
- Ch27 Hi-hats compressor disabled (was on in initial capture, Claude didn't change it)
- Ch22 Floor Tom EQ band 4 at 9kHz: -3dB cut flattened to 0dB by engineer
- Main LR fader: -0.8→-1.3dB (engineer pulled down slightly)

### Engineer's own adjustments
- Panning: 8 channels re-panned to match stage positions (Tammy, Randy, John, JEN!, Jill, Kat, Flute-Jen, Zach-John). Auto-awesome doesn't evaluate panning.
- Ch31 Bass panning: 12%L→center (on Claude's recommendation — low freq should be centered)
- CamVerb routing: Connected bus 16 sends to Cam L/R (mtx03/04) at 0.75, lowered bus fader from -8.6dB to -14.3dB. Livestream was completely dry before — engineer fixed it after Claude identified the gap.
- Ch9 renamed John→Brian (different speaker this week)
- Ch9 Brian EQ completely reworked (4 bands repositioned — new speaker profile)
- Voices bus (05/06) faders raised from -0.4dB to +0.3dB
- drums bus (07/08) faders raised from -5.6dB to 0.0dB (significant +5.6dB raise)
- Various BGV faders pulled down (John -2.5dB, JEN! -0.7dB, Jill -1.2dB, Kat -2.1dB)

### Bugs identified
- Ch1 Tammy compressor: capture showed dyn/on=0 but engineer confirmed comp was already enabled. Same type of capture read bug as Ch2/Ch7 from 2026-02-18. (TECHNICAL.md already documents this under Known Issues)
- HPF readback bug: final capture showed HPF changes (several channels at 20Hz, one disabled) that the engineer did NOT make. Capture is reading HPF values incorrectly on some channels. Needs code investigation.

### Documentation gaps fixed this session
- FOH processing buses (05/06 Voices, 07/08 drums) were completely undocumented — added to CHANNELS.md and auto-awesome skill
- FX5 (Ultimo Compressor) and FX6 (Precision Limiter) as drum bus inserts — added to CLAUDE.md FX table, Bus Dynamics agent scope
- FX8 role corrected: not just "BGV exciter" but Voices FOH bus insert processing ALL vocals to mains — updated in Vocals EQ agent
- Reverb sends (AudVerb/CamVerb) per channel — assigned to metering agents
- CamVerb bus 16 had zero matrix sends — engineer connected after Claude identified routing gap
- Assisted Listening (mtx05) marked inactive

### Flags
- Editor agent still can't spawn nested subagents (Task within Task). Orchestrator dispatched EQ agents directly — worked but adds complexity.
- HPF readback is unreliable — do NOT draw conclusions from HPF diffs until the capture bug is fixed.
- KB fader swings are musician-driven (volume changes at the keyboard), not corrections to Claude's suggestions. Don't over-interpret KB fader diffs.
- Bass EQ is experimental — engineer is actively exploring. Keep suggestions flexible, don't anchor on a target.
- FOH processing buses (05/06, 07/08) faders were significantly raised by engineer. Agents didn't know these buses existed until docs were updated mid-session.
