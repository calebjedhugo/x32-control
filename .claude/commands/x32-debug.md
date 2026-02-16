# X32 Debug - Hardware Verification & Capture Gaps

Connect to the mixer. Verify Claude can control every parameter type. Fix capture gaps. Debug autonomously.

## Setup

```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control" && source venv/bin/activate
```

Read `docs/TECHNICAL.md`, `scripts/common.py`, and `docs/CHANNELS.md` before starting. You'll need them for OSC addresses, value conversions, and routing context.

**You have full authority to modify**: `session_capture.py`, `control.py`, `common.py`, `analyze.py`, and `docs/TECHNICAL.md`. Fix bugs, add missing features, update docs — don't ask permission for code changes.

## Part 1: Parameter Control Verification

For each parameter, run this cycle on a test channel:
1. **Read** current value
2. **Nudge** by a tiny amount (e.g., +0.01)
3. **Read back** to verify change took
4. **Restore** original value
5. **Read back** to confirm restoration

Use `control.py` (raw OSC mode is fine: `control.py /ch/01/dyn/thr 0.61`).

### Channel EQ (test on ch01, 4-band)
- [ ] EQ on/off (`/ch/01/eq/on`)
- [ ] Band frequency (`/ch/01/eq/1/f`)
- [ ] Band gain (`/ch/01/eq/1/g`)
- [ ] Band Q (`/ch/01/eq/1/q`)

### Channel Compressor (test on ch01)
- [ ] On/off (`/ch/01/dyn/on`)
- [ ] Threshold (`/ch/01/dyn/thr`)
- [ ] Ratio (`/ch/01/dyn/ratio`) — **uses index, not value** (see common.py COMP_RATIO_VALUES)
- [ ] Knee (`/ch/01/dyn/knee`)
- [ ] Attack (`/ch/01/dyn/attack`)
- [ ] Release (`/ch/01/dyn/release`)
- [ ] Mix (`/ch/01/dyn/mix`)
- [ ] Makeup gain (`/ch/01/dyn/mgain`)

### Channel Gate (test on ch01)
- [ ] On/off (`/ch/01/gate/on`)
- [ ] Threshold (`/ch/01/gate/thr`)
- [ ] Range (`/ch/01/gate/range`)

### Channel Preamp (test on ch01)
- [ ] Gain trim (`/ch/01/preamp/trim`)
- [ ] HPF on/off (`/ch/01/preamp/hpon`)
- [ ] HPF frequency (`/ch/01/preamp/hpf`)

### Channel Mix
- [ ] Fader (`/ch/01/mix/fader`)
- [ ] Pan (`/ch/01/mix/pan`)

### Bus Parameters (test on bus01, 6-band EQ)
- [ ] Bus fader (`/bus/01/mix/fader`)
- [ ] Bus EQ band gain (`/bus/01/eq/1/g`)
- [ ] Bus compressor threshold (`/bus/01/dyn/thr`)

### Main Bus (6-band EQ)
- [ ] Main fader (`/main/st/mix/fader`)
- [ ] Main EQ band gain (`/main/st/eq/1/g`)
- [ ] Main compressor threshold (`/main/st/dyn/thr`)

### FX Parameters (test on FX1)
- [ ] FX parameter (`/fx/1/par/02`)

### Matrix (test on livestream matrices)
Find Cam L / Cam R matrices — check `docs/CHANNELS.md` or query mixer for matrix names. Test on whichever matrix feeds the livestream.
- [ ] Matrix fader (`/mtx/01/mix/fader` — adjust index for correct matrix)
- [ ] Matrix EQ band gain
- [ ] Matrix compressor threshold (if available)

### Bus Sends (test on ch01 → bus15)
- [ ] Send level (`/ch/01/mix/15/level`)
- [ ] Send on/off (`/ch/01/mix/15/on`)

## Part 2: Capture Gap Fixes (Status)

All capture gaps from the original list have been implemented. Verify correctness if issues arise:

- **Matrix data** — DONE. `session_capture.py` `capture_matrix_settings()`. Faders, EQ, compressor, input sources.
- **Signal path routing** — DONE. Channel → main routing (`/ch/XX/mix/st`), bus → main (`/bus/XX/mix/st`), bus → matrix sends. See `build_signal_paths()`.
- **DCA assignments** — DONE. Bitmask capture via `/ch/XX/grp/dca`. See `docs/TECHNICAL.md` DCA Membership section.
- **analyze.py integration** — DONE. Matrix fader/compressor checks, DCA-aware gain staging, livestream routing analysis.

See `docs/TECHNICAL.md` changelog (Feb 15, 2026) for details.

## Debugging Rules

**Debug autonomously.** If something fails:
1. Cross-reference `docs/TECHNICAL.md` for known address quirks
2. Try alternate OSC paths (e.g., `/ch/01/dyn/knee` vs `/ch/01/dyn/knees`)
3. Check value scales (index vs float vs dB)
4. Fix the code and retry

**Only ask the user when truly stuck** — e.g., you found the OSC address responds but the values are opaque ("1, 2, 3, 4") and you need them to look at the mixer display to tell you what moved.

## After Testing

1. Report which parameters verified working
2. Report which failed and what you tried
3. List all code changes (session_capture.py, control.py, common.py, etc.)
4. Update `docs/TECHNICAL.md` with new discoveries
5. Run a fresh session capture to verify the new data appears correctly
