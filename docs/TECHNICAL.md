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
- FX parameters have internal scaling (e.g., 0.65 → 0.646). Need nudge >= 0.05 to register
- Bus/matrix parameters respond slower than channels; use 8+ retries with 0.25s delay
- Matrix faders: direct `query()` is unreliable for readback after send; use `state()` instead (`/mtx/N/mix_fader`)
- Send levels (`/ch/XX/mix/YY/level`): initial query works but readback after send is unreliable

## Value Conversions

### Compressor Ratio
X32 returns index into array, not actual ratio:
```
Index: 0    1    2   3   4   5  6  7  8   9  10   11
Ratio: 1.1  1.3  1.5  2  2.5  3  4  5  7  10  20  100
```
Use `ratio_index_to_value()` / `ratio_value_to_index()` in common.py.

### Compressor Knee
Stepped parameter, index 0-5. Sending intermediate floats gets snapped:
```
Index: 0    1    2    3    4    5
Float: 0.0  0.2  0.4  0.6  0.8  1.0
```
Send integer 0-5 or exact float values. **Verified 2026-02-15**.

### Compressor Mix / Makeup Gain
Quantized — nudge of 0.01 is too small. Use 0.05+ for mix, 0.1+ for mgain.

### HPF Frequency
- Address: `/ch/XX/preamp/hpf` (frequency), `/ch/XX/preamp/hpon` (on/off)
- Value 0.0-1.0 maps logarithmically to 20-400Hz
- Use `hpf_value_to_hz()` in common.py

### Phantom Power (48V)
- **NOT at** `/ch/XX/preamp/48v` (does not respond)
- Phantom lives on the headamp, indexed by physical input
- Get channel's physical input: `/ch/XX/config/source` (returns 0-31 for local inputs)
- Query phantom: `/headamp/NNN/phantom` where NNN = source value, zero-padded to 3 digits
- Example: ch17 source=9 → `/headamp/009/phantom`

### Insert Selector
- Address: `/ch/XX/insert/sel`
- Value 0-7 maps to FX1-4 in pairs (L/R):
```
sel: 0  1  2  3  4  5  6  7
FX:  1  1  2  2  3  3  4  4
```
- Formula: `fx_slot = (insert_sel // 2) + 1`

## Routing OSC Addresses

**Verified 2026-02-15**. These addresses control signal routing.

### Channel → Main LR
- `/ch/XX/mix/st` — 1=routes to main LR, 0=does not
- Subgroup channels (drums, some vocals) set st=0 and route only via bus sends

### Bus → Main LR
- `/bus/XX/mix/st` — 1=bus feeds main LR, 0=does not
- Subgroup buses (09 Vocal, 10 Acoustic, 12 Drums, 13 Electronic) all have st=0

### Bus → Matrix Sends
- `/bus/XX/mix/YY/level` — send level from bus XX to matrix YY (1-6)
- `/bus/XX/mix/YY/on` — send on/off
- **All bus→matrix sends are PRE-FADER.** Bus faders (`/bus/XX/mix/fader`) do NOT affect matrix output. Only the send level (`/bus/XX/mix/YY/level`) controls what reaches the matrix.

### Main → Matrix Sends
- `/main/st/mix/YY/level` — send level from main to matrix YY
- `/main/st/mix/YY/on` — send on/off

### Matrix Outputs (1-6)
- `/mtx/XX/mix/fader` — matrix output fader
- `/mtx/XX/eq/N/f|g|q` — 6-band EQ (same as buses)
- `/mtx/XX/dyn/on|thr` — compressor
- `/mtx/XX/insert/on|sel` — insert routing
- `/mtx/XX/config/name` — matrix name

### Current Matrix Map
```
mtx01: Mono House (fed from main)
mtx02: Foyer
mtx03: Cam L (livestream left)
mtx04: Cam R (livestream right)
mtx05: Assisted Listening (inactive, ignore)
mtx06: Computer
```

## DCA Groups

### Reading DCA Settings
- `/dca/N/config/name` — DCA name (query works)
- `/dca/N/mix_fader` — DCA fader (read via `state()`, NOT `query()`)
- `/dca/N/mix_on` — DCA mute (read via `state()`)

### DCA Membership (Bitmask)
- `/ch/XX/grp/dca` — bitmask of DCA assignments for channel XX
- `/bus/XX/grp/dca` — bitmask of DCA assignments for bus XX
- Bit 0 = DCA1, Bit 1 = DCA2, ..., Bit 7 = DCA8
- Example: value 4 = binary 100 = DCA3 only
- Example: value 5 = binary 101 = DCA1 + DCA3

### Current DCA Assignments (as of 2026-02-15)
```
DCA1 (Vox):      ch01-06 (singing vocals)
DCA2 (Speaking):  ch09, ch10, ch13, ch14
DCA3 (Inst):      ch08, ch17-22, ch28-32, bus07-08
DCA4 (Aux):       ch11, ch15, ch16
DCA5 (Monitors):  bus01-06
```
Note: ch07 (Kat), ch23-27 (drums except floor tom) have no DCA assignment.
ch08 (pastor) is in DCA3 (Inst) instead of DCA2 (Speaking) — possible misconfiguration.

## Meter Subscription

**IMPORTANT**: `/batchsubscribe` does NOT work for meters on this X32. Use request-polling instead:
```
/meters ,siii '/meters/0' 0 0 3
```
Poll every ~50ms with `/xremote` keep-alive. Responses come back as `/meters/0` with a blob.

## Meter Blob Structure

X32 meter blob format (verified 2026-02-18):
- First 4 bytes: LE int32 count (typically 70)
- Remaining: count LE float32 values (0.0-1.0 range)
- Indices 0-31: Channels 1-32
- Indices 32+: Aux inputs

Activity threshold: 0.0005 (float). Values are already positive (no abs needed).

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

Add mappings as needed. Query FX parameters with:
```bash
python scripts/query.py --fx 1
```

## Known Issues

- **EQ/dynamics on/off queries occasionally wrong**: Fixed Feb 22, 2026. Root cause: `mixer.query()` returns None ~46% of individual calls. With 5 retries, ~2% still fail — defaulting to 0 reports "off" when actually "on". Fix: `reliable_on_off_query()` uses 10 retries (<0.05% failure rate) + stderr warning on failure.

- **Query failures produce default values**: When all retries fail, `reliable_query()` returns the caller's `default` parameter. Common corrupted defaults: EQ freq → 0.5 (632Hz), comp/gate on → 0 (OFF), FX type → 0 (Hall Reverb). Mitigations added Mar 2026:
  - **Background keepalive**: `/xremote` sent every 2s during capture keeps the UDP connection hot, dramatically improving response rate.
  - **Increased retries**: `reliable_query()` defaults raised from 5/0.15s to 8/0.2s. `warmup_connection()` sends 3 throwaway queries instead of 1.
  - **Failure tracking**: All failed addresses logged in `metadata.query_failures`.
  - **Post-capture validation**: `validate_capture()` flags suspicious patterns (e.g., EQ freq at 0.5 with non-default gain).
  - **Diff suspicious flags**: `diff_sessions.py` marks changes TO/FROM default values with `[?]` prefix.

## Changelog

- **Mar 4, 2026**: Query reliability improvements — background `/xremote` keepalive during capture, raised `reliable_query()` defaults to 8 retries / 0.2s delay, 3-query warmup, failure tracking in capture metadata, `validate_capture()` post-capture validation, suspicious change detection in `diff_sessions.py`. Removed hardcoded channel-to-instrument mappings — auto-awesome now classifies channels by mixer label. Added `--channels` flag to `extract.py`. Fixed `classify_channel()` gaps: "high tom", "e-guitar"/"e-gtr", "announc".

- **Feb 22, 2026**: Fixed on/off readback reliability — `reliable_on_off_query()` with 10 retries for all toggle parameters (HPF, EQ, gate, comp, insert, routing, bus sends). Reduces false-negative rate from ~2% to <0.05%.

- **Feb 18, 2026**: Fixed meter capture — replaced broken `/batchsubscribe` with `/meters` request-polling; fixed blob parsing from BE int16 to LE float32; updated activity threshold from 500 (int) to 0.0005 (float); fixed `average_peak` int cast to round().
- **Feb 15, 2026**: Full parameter verification (29/32 pass). Added matrix capture, channel/bus routing, DCA groups, bus→matrix sends, main→matrix sends. New control.py args: --mute/--unmute, --pan, --comp-ratio, --comp-mix, --comp-mgain, --gate-range. New analyze.py checks: livestream routing, DCA coverage, matrix EQ. Documented comp knee (stepped 0-5), matrix/DCA OSC addresses.
- **Jan 25, 2026**: Fixed pan capture, stereo link detection, insert_sel mapping, added Dual Exciter params
- **Jan 18, 2026**: Fixed EQ/dynamics/FX read/write, meter blob parsing, compressor ratio display, HPF queries
