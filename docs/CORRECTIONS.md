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
