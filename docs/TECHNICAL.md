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

## Meter Blob Structure

X32 meter blob parsing (capture.py):
- Index 0: Header (~17920)
- Index 1: Header (0)
- Index 2-17: Channels 1-16
- Index 18: Header (~28603)
- Index 19-34: Channels 17-32
- Index 35+: Aux inputs

Activity detection uses `abs(raw_value)` since audio oscillates positive and negative.

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
