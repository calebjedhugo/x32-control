# Technical Notes (Developer Reference)

## Library Limitations

The `behringer_mixer` library has limitations:
- `state()` only returns fader, on/off, name, color - not EQ/dynamics/FX
- `set_value()` silently fails for addresses not in its internal mapping

**Workarounds applied:**
- `common.py` - `reliable_query()` uses `mixer.query()` directly with retries
- `query.py` - EQ, dynamics, FX queries use `reliable_query()` instead of `state.get()`
- `control.py` - Uses `mixer.send()` directly instead of `mixer.set_value()`

## OSC Address Notes

- Zero-padded channels required: `/ch/08/`, not `/ch/8/`
- First query after connection often returns None; `reliable_query()` handles this with retries
- FX parameters have internal scaling (e.g., 0.65 → 0.646)

## Value Conversions

### Compressor Ratio
X32 returns index into array, not actual ratio:
```
Index: 0    1    2   3   4   5  6  7  8   9  10   11
Ratio: 1.1  1.3  1.5  2  2.5  3  4  5  7  10  20  100
```
Use `ratio_index_to_value()` in common.py.

### HPF Frequency
- Address: `/ch/XX/preamp/hpf` (frequency), `/ch/XX/preamp/hpon` (on/off)
- Value 0.0-1.0 maps logarithmically to 20-400Hz
- Use `hpf_value_to_hz()` in common.py

### Insert Selector
- Address: `/ch/XX/insert/sel`
- Value 0-7 maps to FX1-4 in pairs (L/R):
```
sel: 0  1  2  3  4  5  6  7
FX:  1  1  2  2  3  3  4  4
```
- Formula: `fx_slot = (insert_sel // 2) + 1`

## Meter Blob Structure

X32 meter blob parsing (capture.py):
- Index 0: Header (~17920)
- Index 1: Header (0)
- Index 2-17: Channels 1-16
- Index 18: Header (~28603)
- Index 19-34: Channels 17-32
- Index 35+: Aux inputs

Activity detection uses `abs(raw_value)` since audio oscillates positive and negative.

## FX Parameter Mappings

FX parameters are at `/fx/N/par/XX` (01-64). Values are 0.0-1.0 normalized.

### Hall Reverb (Type 0)

Versatile reverb with 6 type presets (Hall, Ambience, Plate, Room, Chamber, Concert).
**Verified 2026-01-25**.

| Param | Name | Notes |
|-------|------|-------|
| 01 | Pre Delay | |
| 02 | Decay | |
| 03 | Size | |
| 04 | Damp | High frequency damping |
| 05 | Diff | Diffusion |
| 06 | Level | Output level |
| 07 | Lo Cut | Low frequency filter |
| 08 | Hi Cut | High frequency filter |
| 09 | Bassmult | Bass multiplier |
| 10 | Spread | Stereo spread |
| 11 | Shape | Early reflection shape |
| 12 | Mod Speed | Modulation speed |

### Dual Exciter (Type 50)

Dual-band exciter with separate low and high frequency processing.
**Verified 2026-01-25** by comparing UI changes to parameter reads.

| Param | Name | Range | Notes |
|-------|------|-------|-------|
| 01 | Tune Low | 1-10 kHz | Low band center frequency |
| 02 | Tune High | 1-10 kHz | High band center frequency |
| 03 | Peak Low | 0-100 | |
| 04 | Peak High | 0-100 | |
| 05 | Zero Fill Low | 0-100 | |
| 06 | Zero Fill High | 0-100 | |
| 07 | Timbre Low | -50 to +50 | 0.0=-50, 0.5=0, 1.0=+50 |
| 08 | Timbre High | -50 to +50 | **Key shrillness control** |
| 09 | Harmonics Low | 0-100 | |
| 10 | Harmonics High | 0-100 | |
| 11 | Mix Low | 0-100 | |
| 12 | Mix High | 0-100 | |

**Timbre** is the main tonal control:
- 0.0 = -50 (warmer/darker)
- 0.5 = 0 (neutral)
- 1.0 = +50 (brighter/edgier, can cause shrillness)

**For Tammy's shrillness**: Check par/08 (Timbre High). If >0.5, the exciter is adding brightness to high frequencies.

### Stereo Exciter (Type 22)

Single-band exciter (simpler than Dual Exciter). **Verified 2026-01-25**.

| Param | Name | Range | Notes |
|-------|------|-------|-------|
| 01 | Tune | 1-10 kHz | Center frequency |
| 02 | Peak | 0-100 | |
| 03 | Zero Fill | 0-100 | |
| 04 | Timbre | -50 to +50 | 0.0=-50, 0.5=0, 1.0=+50 |
| 05 | Harmonics | 0-100 | |
| 06 | Mix | 0-100 | |
| 07 | Solo Mode | 0/1 | On/off |

### Ultimo Compressor (Type 17, Type 47)

Vintage-style limiting amplifier. Same parameters for both type IDs. **Verified 2026-01-25**.

| Param | Name | Range | Notes |
|-------|------|-------|-------|
| 01 | ? | | (didn't change in testing) |
| 02 | Input | ∞-48 dB | Input gain |
| 03 | Attack | 1-7 | Attack time |
| 04 | Release | 1-7 | Release time |
| 05 | Output | ∞-48 dB | Output/makeup gain |
| 06 | Ratio | 4-20 | Compression ratio |
| 07-12 | Mode/other | | GR, LIMIT, ACTIVE, OFF switches |

### Precision Limiter (Type 11)

Broadcast-style limiter with knee control. **Verified 2026-01-25**.

| Param | Name | Range | Notes |
|-------|------|-------|-------|
| 01 | Input Gain | | |
| 02 | Output Gain | | |
| 03 | Squeeze | | Threshold/amount |
| 04 | Knee | | Soft to hard knee |
| 05 | Attack | | |
| 06 | Release | | |
| 07 | Stereo Link | 0/1 | On/off |
| 08 | Auto Gain | 0/1 | On/off |

### Dual Guitar Amp (Type 26)

Guitar amp simulator with cabinet modeling. **Verified 2026-01-25**.

| Param | Name | Range | Notes |
|-------|------|-------|-------|
| 01 | Preamp | 0-10 | Preamp gain |
| 02 | Buzz | 0-10 | Low-end buzz/growl |
| 03 | Punch | 0-10 | Mid punch |
| 04 | Crunch | 0-10 | Distortion character |
| 05 | Drive | 0-10 | Overdrive amount |
| 06 | Level | 0-10 | Output level |
| 07 | Low | 0-10 | Bass EQ |
| 08 | High | 0-10 | Treble EQ |
| 09 | Cabinet | 0/1 | Cabinet sim on/off |

### Other FX Types (TODO)

Add mappings as needed. Query with:
```bash
python -c "..." # see session debugging examples
```

## Known Issues

- **EQ/dynamics on/off queries occasionally wrong**: Some channels report incorrect on/off state. 5-retry approach helps but isn't perfect.

## Test History

### January 18, 2026 - Session 1
- Fixed EQ, dynamics, FX read/write
- Fixed meter blob parsing
- All core features verified working

### January 18, 2026 - Session 2
- Fixed compressor ratio display (index → actual value)
- Added HPF queries
- Increased query retries from 3 to 5

### January 25, 2026 - Session Capture Fixes
- Fixed pan not being captured (was using state dict, now uses reliable_query)
- Fixed `or 0.5` bug that converted hard-left pan (0.0) to center (0.5)
- Added stereo link detection (`/config/chlink/X-Y`)
- Removed all `or 0.5` patterns that could corrupt 0.0 values
- Added Dual Exciter (type 50) parameter mapping
- Fixed insert_sel to FX slot mapping (was +1, now //2+1 for L/R pairs)
