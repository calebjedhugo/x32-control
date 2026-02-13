# X32 Debug - Hardware Verification & Capture Gaps

Connect to the mixer. Verify Claude can control every parameter type. Fix capture gaps. Debug autonomously.

## Setup

```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control" && source venv/bin/activate
```

Read `docs/TECHNICAL.md` and `scripts/common.py` before starting. You'll need them for OSC addresses and value conversions.

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

### Matrix (test on matrix that feeds livestream)
- [ ] Matrix fader (`/mtx/01/mix/fader` — find the correct matrix first)
- [ ] Matrix EQ band gain
- [ ] Matrix compressor threshold (if available)

### Bus Sends (test on ch01 → bus15)
- [ ] Send level (`/ch/01/mix/15/level`)
- [ ] Send on/off (`/ch/01/mix/15/on`)

## Part 2: Capture Gap Fixes

The session capture (`session_capture.py`) is missing critical data. Extend it to capture:

### Matrix Data (Cam L / Cam R)
The livestream runs through matrices. Capture:
- Matrix faders, EQ, compressor
- Matrix input sources (which buses/main feed the matrix, at what levels)
- Figure out the OSC addresses — likely `/mtx/01/...` pattern

### Complete Signal Path Routing
Currently captured: channel → bus sends. NOT captured:
- **Channel main/subgroup routing** — whether a channel routes to main LR or to a bus pair as a subgroup. This is why the subgroup buses (Vocal, Drums, Acoustic, Electronic) show -inf sends — channels route to them as subgroups, not via sends.
- **Bus → main routing** — whether each bus feeds main LR
- **Bus → matrix routing** — how buses feed the livestream matrices

The subgroup buses (Vocal bus09, Acoustic bus10, Drums bus12, Electronic bus13) route ONLY to the livestream, NOT to mains. This routing must be captured so Claude can trace the full path.

### DCA Assignments
Capture which channels belong to each DCA group. Claude needs this for level math — a DCA trim affects every channel in the group.
- OSC addresses likely at `/dca/1/...` or similar — investigate

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
