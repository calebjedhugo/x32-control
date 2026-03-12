# Channel & Equipment Reference

Read this when you need detailed info about personnel, equipment, or stage layout.

**Note:** Channel assignments are dynamic — agents classify channels by their mixer label at runtime, never by channel number. This document provides contextual information (voice types, mic details, drum sizes, etc.) that agents look up by name.

## Personnel

### Vocalists
Generally quiet singers with low-output mics = high preamp gains needed.

| Name | Voice Type | HPF Range | Mic | Notes |
|------|-----------|-----------|-----|-------|
| Tammy | Alto | 120-150Hz | Sennheiser e945 | Lead vocalist, also plays piano and guitar |
| Randy | Tenor | 100-120Hz | CPG XD2 | High preamp needed — quiet mic |
| John | Baritone | 80-100Hz | CPG XD2 | High preamp needed. Also speaks (pastor rotation) |
| Jen | Alto | 120-150Hz | CPG XD2 | High preamp needed. Also plays flute |
| Sara | Alto | 120-150Hz | CPG XD2 | High preamp needed — quiet mic |
| Bart | Baritone | 80-100Hz | Shure SM58 | |
| Kat | Alto | 120-150Hz | Shure SM58 | Also plays keys |
| Jill | Alto | 120-150Hz | (substitute) | Occasional, rotates onto available channel |

### Other Inputs

| Label Pattern | Source | Notes |
|---------------|--------|-------|
| Pastor / John / Brian | Speaking | Headset mic, rotates weekly |
| Announcements | Speaking | |
| Aux / Phone | Phone/Zoom | Usually muted |
| Ambient / Room | Room mics | Livestream only, not FOH |
| Computer | Playback | |

## Equipment

### Drums
Classically trained drummer, masterful restraint. No cage needed. Gentle playing style requires close mics to capture transients. NADY kit mics (budget, but captures transients).

| Type | Size | Notes |
|------|------|-------|
| Kick | 24" | |
| Snare | 14" | |
| Floor Tom | 18" | |
| Mid Tom | 14" rack | |
| Mid High Tom | 12" rack | |
| Overheads | Spaced pair | L near hi-hats, R near ride |

### Instruments

| Instrument | Mic / DI | Notes |
|------------|----------|-------|
| Piano | AKG C02 pencil condensers | 6ft grand, stereo low/high string split |
| Acoustic Guitar | Mic | Tammy's primary, or front guitar (not always used) |
| Flute | C02 condenser | Shares channel with violin or other instrument (rotates weekly) |
| Electric Keyboard | DI | Stereo (L/R) |
| Bass | DI | → Ultimo compressor (intentional fuzz, not dynamics) |
| Electric Guitar | DI | → amp sim plugin |

## Bus Roles (by name)

Agents find buses by their `name` field in capture data — never by bus number.

### FOH Processing Buses

Non-lead vocals and drums do NOT go directly to main LR. They route through stereo processing buses with FX inserts first. **Exception:** The lead vocal (Tammy) routes directly to main LR (`st=1`) with her own exciter (FX4 channel insert) — she is NOT in the Voices bus.

| Name Pattern | Sources | FX Insert | Feeds |
|-------------|---------|-----------|-------|
| "Voices" | Non-lead vocals | Stereo Exciter (FX8) | Main LR + Cam L/R matrices |
| "drums" / "Drums" | Drum channels | Ultimo Compressor (FX5) + Precision Limiter (FX6) | Main LR + Cam L/R matrices |

These buses feed both FOH (main LR) and livestream (Cam L/R matrices). Adjusting bus faders, EQ, or FX inserts affects both audiences.

### Livestream Buses

These feed the livestream matrices (Cam L / Cam R) only, not mains.

| Name Pattern | Source | Notes |
|-------------|--------|-------|
| "Tammy" | Lead vocal only | Independent lead vocal level for livestream |
| "Acoustic" | Acoustic instruments | Subgroup — on/off routing, no adjustable send levels |
| "Electronic" | Electronic instruments | Subgroup — on/off routing, no adjustable send levels |

Drums reach the livestream via the FOH processing drums bus, not a separate livestream bus. Any bus named "Not used" is decommissioned — skip it.

### Other Buses

| Name Pattern | Purpose |
|-------------|---------|
| "Pres" | Presentation (speaking mics → matrices) |
| "Ambiant" / "Ambient" | Ambient room mics → livestream matrices |
| "AudVerb" | Auditorium reverb → main LR (FOH) |
| "CamVerb" | Livestream reverb → Cam L/R matrices |

## DCA Groups

DCA names are stable board config. Membership is dynamic — read from capture.

| Name | Purpose |
|------|---------|
| Vox | All singing vocals |
| Speaking | Pastor, announcements |
| Inst | All instruments |
| Aux | Auxiliary inputs |
| Monitors | Monitor sends |

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
- Flute/violin condenser mic is sensitive — shares channel, picks up nearby sources

## Known Problem Areas
- **Low G on bass** (~49Hz or 98Hz) hits room resonance hard
- **Keyboard**: Difficult to sit in mix — frequency masking with piano/guitars

## Monitors
- All in-ear monitors (IEMs) - no wedges
