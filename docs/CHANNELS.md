# Channel Details

Read this when you need detailed info about specific channels, personnel, or stage layout.

**Note:** Automation (auto-awesome, extract.py) uses mixer labels to classify channels, not the channel numbers in this document. Channel assignments can change — always verify against the current capture. This document serves as the default layout reference and provides per-channel context (voice types, mic details, drum sizes, etc.) that subagents look up at runtime.

## Channel Map

### Vocals & Inputs (1-16)
| Ch | Name | Source | Notes |
|----|------|--------|-------|
| 1 | Tammy | Lead vocal | Also plays piano (17-18) and guitar (19) |
| 2 | Randy | Vocal | High preamp (+31dB) - quiet mic |
| 3 | John | Vocal | High preamp (+39dB) - quiet mic |
| 4 | JEN! | Vocal | High preamp (+26dB), also plays flute (21) |
| 5 | Sara | Vocal | High preamp (+35dB) - quiet mic |
| 6 | Bart | Vocal | |
| 7 | Kat | Vocal | |
| 8 | John/Brian | Pastor speaking | Headset mic, rotates weekly |
| 9 | Announcements | Speaking | |
| 10-11 | Aux (phone) | Phone/Zoom | Usually muted |
| 12-13 | Ambient L/R | Room mics | Livestream only, not FOH |
| 14-15 | Computer L/R | Playback | |
| 16 | (unused) | | |

### Instruments (17-32)
| Ch | Name | Source | Notes |
|----|------|--------|-------|
| 17-18 | Piano low/high | 6ft grand | Stereo condensers, low/high string split |
| 19 | Tammy Guitar | Acoustic | |
| 20 | Front Guitar | Acoustic | Not always used |
| 21 | Flute-Jen | Flute | Jennifer, +18dB preamp. Shares channel with violin (rotates weekly) |
| 22 | Floor Tom | Drums | 18" |
| 23 | Mid Tom | Drums | 14" rack |
| 24 | Mid High Tom | Drums | 12" rack |
| 25 | Snare | Drums | 14" |
| 26 | Kick | Drums | 24" |
| 27 | Hi-hats | Overhead L | Positioned near hats side |
| 28 | Ride | Overhead R | Positioned near ride side |
| 29-30 | KB-Left/Right | Electric keyboard | Stereo |
| 31 | Bass | Bass guitar | DI → Ultimo compressor (intentional fuzz) |
| 32 | E-Guitar | Electric guitar | DI → amp plugin |

## Buses & Groups

### DCA Groups
| DCA | Name | Contents |
|-----|------|----------|
| 1 | Vox | All singing vocals |
| 2 | Speaking | Pastor, announcements |
| 3 | Inst | All instruments |
| 4 | Aux | Auxiliary inputs |
| 5 | Monitors | Monitor sends |

### FOH Processing Buses
Vocals (ch2-7) and drums do NOT go directly to main LR. They route through these stereo processing buses with FX inserts first. **Exception:** Tammy (ch1) routes directly to main LR (`st=1`) with her own exciter (FX4 channel insert) — she is NOT in the Voices bus.

| Bus | Name | Sources | FX Insert | Feeds |
|-----|------|---------|-----------|-------|
| 05/06 | Voices (L/R) | Vocal ch2-7 (not Tammy) | Stereo Exciter (FX8) | Main LR + Cam L/R matrices |
| 07/08 | drums (L/R) | Drum channels | Ultimo Compressor (FX5) + Precision Limiter (FX6) | Main LR + Cam L/R matrices |

**Important:** These buses feed both FOH (main LR) and livestream (Cam L/R matrices). Adjusting bus faders, EQ, or FX inserts affects both audiences.

### Livestream Buses
These feed the livestream matrices (Cam L / Cam R) only, not mains.

| Bus | Name | Source | Notes |
|-----|------|--------|-------|
| 09 | Tammy voice | Tammy (ch1) only | Independent lead vocal level for livestream |
| 10 | Acoustic | piano, acoustic_guitar, flute, violin | Subgroup — on/off routing, no adjustable send levels |
| 13 | Electronic | keys, electric_guitar, bass | Subgroup — on/off routing, no adjustable send levels |

**Note:** Bus 12 is decommissioned ("Not used"). Drums reach the livestream via FOH processing buses 07/08 instead.

### Other Buses
| Bus | Name | Purpose |
|-----|------|---------|
| 11 | Pres | Presentation (speaking mics → matrices) |
| 14 | Ambiant | Ambient room mics → livestream matrices |
| 15 | AudVerb | Auditorium reverb → main LR (FOH) |
| 16 | CamVerb | Livestream reverb → Cam L/R matrices |

## Mic Details
- **Tammy (ch1)**: Sennheiser e945
- **Randy (ch2), John (ch3), Jen (ch4), Sara (ch5)**: CPG XD2
- **Bart (ch6), Kat (ch7)**: Shure SM58
- **Piano (17-18)**: AKG C02 pencil condensers
- **Drums**: NADY kit (budget, but captures transients)
- **Flute (21)**: C02 condenser

## Personnel Notes

### Vocalists
Generally quiet singers with low-output mics = high preamp gains needed.

| Voice Type | People | HPF Safe Range |
|------------|--------|----------------|
| Alto | Tammy, Sara, Kat, Jen | 120-150Hz |
| Alto (substitute) | Jill (occasional, rotates onto available channel) | 120-150Hz |
| Baritone | Bart, John | 80-100Hz |
| Tenor | Randy | 100-120Hz |

### Drummers
Classically trained, masterful restraint. No cage needed. Gentle playing style requires close mics to capture transients.

## Stage Layout (from booth, L to R)
```
[LEFT]                                                    [RIGHT]
Tammy          Singers/       Drums    Bass/Electric    Flute/    Kat
(piano+vox)    Acoustic Gtr            John (vox)       Violin    (keys+vox)
               (behind piano)
```

### Bleed Considerations
- Tammy's vocal mic likely picks up piano
- Singers behind piano may pick up piano in their mics
- Flute/violin on C02 condenser (sensitive, shares channel when both aren't present)

## Known Problem Areas
- **Low G on bass** (~49Hz or 98Hz) hits room resonance hard
- **Keyboard (29-30)**: Difficult to sit in mix - frequency masking with piano/guitars

## Monitors
- All in-ear monitors (IEMs) - no wedges
