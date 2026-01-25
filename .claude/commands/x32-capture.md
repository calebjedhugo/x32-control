# X32 Session Capture

Run a comprehensive capture of the X-32 mixer state for this session.

## Instructions

1. Run the session capture script:
```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control" && source venv/bin/activate && python scripts/session_capture.py --duration 5
```

2. Read the output JSON file that was created (path shown in script output)

3. Summarize for the user:
   - How many channels are active
   - Any gain staging issues (channels running too hot or too quiet)
   - Notable signal paths (e.g., "Vocals route through Bus 5 with an Exciter")

4. Store the capture path so you can reference it when the user asks about specific channels

## Example Summary

"Captured 12 active channels. Gain staging looks good except:
- Kick (ch26) is running hot - consider backing off the preamp
- Sara (ch3) is quiet compared to other vocals

Signal routing:
- Vocals (ch1-6) → Bus 5 (Vocal Bus) with Exciter (FX8) → Main
- Drums (ch22-28) → direct to Main
- Keys (ch17-18) → Bus 3 (Keys) → Main"

## After Capture

**Use the session capture for all questions.** You have:
- All channel settings (EQ, dynamics, preamp, routing)
- All bus settings
- All FX slots and routing
- Signal path analysis

**Don't re-query the mixer** unless you need real-time data.

## When User Asks About Frequencies

If user asks "what frequencies is the kick hitting?", run RTA:
```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control" && source venv/bin/activate && python scripts/rta_listen.py --channel 26 --update-session
```

**Always use `--update-session`** to splice RTA results back into the session capture. This way:
- You don't have to re-listen if they ask again
- All data stays in one place
- The script warns if session capture is >24 hours old

## Data Freshness

If user returns another day or asks about stale data:
- Session capture >24 hours old? Suggest running `/x32-capture` again
- RTA listen will warn you automatically about old captures
