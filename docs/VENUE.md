# Venue & Room Details

Read this when discussing room acoustics, PA issues, or mix strategy.

## Room
- **Type**: Church sanctuary, ~400 seats
- **Ceiling**: ~20ft at booth, rising toward platform
- **Surfaces**: Pew cushions, commercial carpet, all hard walls
- **Geometry**: Complex with parallel walls (flutter echo risk)

## PA System
- **Mains**: Two speakers mounted either side of platform, crossed to center
- **Sub**: One sub (overpowered) firing into left platform wall - corner-loaded

## Known Acoustic Issues

| Problem | Cause | Workaround |
|---------|-------|------------|
| Low-mid buildup (200-400Hz) | Corner loading, hard walls | Master bus shelf EQ cut |
| Excessive LF in room | Overpowered corner-loaded sub | Sub at minimum, still too much |
| Booth doesn't match congregation | Booth in opposite corner from PA | Trust meters, not ears at booth |

## Mix Strategy
- Master bus has shelf EQ cutting LF for house
- Livestream matrix has inverse compensation (adds LF back)
- This affects how I suggest EQ changes - cuts may already be in place on master

## Typical Use
- Contemporary Christian worship (Phil Wickham, Hillsong style)
- Target aesthetic: Modern/polished - present vocals, full but controlled low end
- Full band: acoustic drums (no cage), grand piano, guitars, keyboard, vocalists
- Bleed consideration: Grand piano + many open vocal mics = significant bleed

---

## What This Means for Mixing

### Be Careful With Low Frequencies
- Room already has too much LF and low-mid energy
- **Don't boost 200-400Hz** unless absolutely necessary - it's a problem area
- If user says "kick needs more body" → try 60-80Hz or attack (2-4kHz), not 200Hz
- If user says "bass sounds weak at the booth" → it's probably fine in the room

### Trust Data Over Booth Ears
- What engineer hears at booth ≠ what congregation hears
- Booth is far from PA, different angle
- Use capture data and meters to guide decisions, not just "it sounds thin here"

### Remember the Master Bus
- There's already a global LF shelf cut on the master
- Channel EQ + master EQ = total effect
- Don't over-cut LF on individual channels - some is already handled globally

### Bleed Changes Everything
- Piano bleeds into vocal mics
- EQ changes to vocals may affect how piano bleed sounds
- Cutting 300Hz on a vocal might thin out the piano bleed too (could be good or bad)
- When suggesting EQ, consider what else that mic is picking up

### Livestream Is Different
- Livestream matrix adds LF back (inverse of house cut)
- A mix that sounds good in room may sound bass-heavy on stream
- A mix that sounds thin at booth may be perfect for both
