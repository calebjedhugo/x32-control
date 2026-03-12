# Venue & Room Details

Read this when discussing room acoustics, PA issues, or mix strategy.

## Room
- **Type**: Church sanctuary, ~400 seats, wooden pews with cushions
- **Ceiling**: Vaulted wood plank ceiling, peaked over center aisle (~25-30ft at peak). This is the dominant reflective surface - focuses sound back down into seating area and creates strong early reflections. Rising from ~15ft at booth toward the peak.
- **Walls**: Brick lower walls with horizontal wood/drywall decorative bands. Hard and reflective at all heights.
- **Floor**: Commercial carpet throughout seating area
- **Absorption**: Almost entirely at floor level (carpet + pew cushions). Room is very live above seated head height.
- **Geometry**: Roughly rectangular with peaked ceiling. Center support column in seating area creates acoustic shadow zones and potential comb filtering for nearby seats.
- **Booth**: Rear-left of room, elevated behind a half-wall. Acoustically isolated from congregation - hears a very different room response than front/middle rows.

## PA System
- **Mains**: Two speakers mounted either side of platform, crossed to center
- **Sub**: One sub (overpowered) firing into left platform wall - corner-loaded

## Known Acoustic Issues

| Problem | Cause | Workaround |
|---------|-------|------------|
| Low-mid buildup (200-400Hz) | Corner loading, hard walls | Master bus shelf EQ cut |
| Excessive LF in room | Overpowered corner-loaded sub | Sub at minimum, still too much |
| Booth doesn't match congregation | Booth rear-left, PA at front | Trust meters, not ears at booth |
| Presence/HF harshness | Vaulted wood ceiling reflects 2-5kHz back down | -5.5dB cut at 3.8kHz on main bus |
| Uneven coverage near column | Center support column blocks/reflects | No fix - seating issue |
| OSC data corruption | Multiple X32 clients (e.g. X32-Edit on another laptop) | Close all other X32 software before running captures or batch changes |

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

## Mixing Rules (Room-Aware)

- **Avoid boosting 200-400Hz for FOH** - room already has significant low-mid buildup. "Kick needs body" → try 60-80Hz or attack (2-4kHz) instead. Only boost here if RTA data clearly shows a deficit
- **Trust data over booth ears** - booth hears a different room than congregation. Use capture data and meters
- **Master bus already cuts LF** - don't over-cut on channels; some is handled globally
- **Bleed matters** - piano bleeds into vocal mics. EQ changes to vocals affect piano bleed too
- **Livestream gets LF added back** - mix that sounds thin at booth may be perfect for both room and stream

## Metering Targets

Captured with master at unity, 2026-02-25.

### Vocals
| Metric | Raw | dB |
|--------|-----|-----|
| Target range | 0.082 – 0.258 | -21.7 to -11.8 |
| Average peak | 0.151 | -16.4 |

### Drums
| Metric | Raw | dB |
|--------|-----|-----|
| Target range | 0.061 – 0.217 | -24.3 to -13.3 |
| Average peak | 0.131 | -17.7 |

### Instruments
| Metric | Raw | dB |
|--------|-----|-----|
| Target range | 0.044 – 0.156 | -27.2 to -16.1 |
| Average peak | 0.076 | -22.4 |

### Overall
| Metric | Raw | dB |
|--------|-----|-----|
| Average peak | 0.119 | -18.5 |

### Livestream Bus Targets

Initial estimates — calibrate after reviewing livestream recordings with bus peak data.

Vocals need to be lower on livestream than FOH because the PA amplifies them in the room, and ambient mics already pick up that amplified sound.

The agent matches each bus by its `name` field in the capture data — no hardcoded bus numbers.

| Role | Name pattern (case-insensitive) | Target Peak (dB) | Notes |
|------|--------------------------------|-------------------|-------|
| Vocals | "Voices", "Tammy" | -18 | Lower — PA carries vocals in room |
| Drums | "drums", "Drums" | -16 | Moderate — already compressed |
| Instruments | "Acoustic", "Electronic" | -14 | Matched — needs livestream presence |
| Ambient | "Ambiant", "Ambient" | -24 | Low — flavor, not feature |
| Reverb | "CamVerb" | -24 | Low — less reverb than FOH |
