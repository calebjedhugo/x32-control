# X32 Session Capture

Run a comprehensive capture of the X-32 mixer state, then analyze it.

## Instructions

**IMPORTANT:** Run each command as a separate Bash call — never chain with `&&` or put multiple commands in one call. Working directory persists between calls.

1. Set working directory:
```bash
cd "/Users/calebhugo/Development/personal dev work.nosync/x32-control"
```

2. Run the session capture script:
```bash
venv/bin/python scripts/session_capture.py --duration 5
```

3. Read the output JSON file that was created (path shown in script output)

4. Run the analysis engine on the capture (outputs JSON):
```bash
venv/bin/python scripts/analyze.py
```

5. Parse the analysis JSON. Summarize for the user:
   - How many channels are active
   - Any **critical** or **warning** findings (group by type: EQ issues, HPF issues, masking conflicts, gain staging)
   - For findings with a `fix` field, tell the user what the fix would do in plain English
   - If there are fixes available, ask: "Want me to apply any of these fixes?"

6. Store the capture path so you can reference it when the user asks about specific channels

## Presenting Findings

Translate findings into sound engineer language. Don't show raw JSON or command syntax.

**Good**: "Jen's flute (ch21) has a +4.5dB boost at 3.3kHz which exceeds the +4dB limit. I can pull that down to +4dB."

**Bad**: "Finding: Band 3: +4.5dB at 3.3kHz exceeds +4.0dB limit for vocal. Fix: python scripts/control.py --channel 21 --eq-band 3 --gain 0.633"

## Applying Fixes

When the user approves a fix:
1. Run the `fix` command from the finding (it's a ready-to-run control.py invocation)
2. Confirm what changed
3. Remind them to listen and verify - "Does that sound right to you?"

For findings WITHOUT a `fix` field (HPF changes, compressor ratio, gain staging):
- These require manual mixer adjustment
- Tell the user what to change and where on the board

## After Capture

**Use the session capture for all questions.** Don't re-query the mixer unless you need real-time data.

## RTA (On-Demand)

When user asks about frequencies, run RTA with **`--update-session`** (working directory already set from step 1):
```bash
venv/bin/python scripts/rta_listen.py --channel 26 --update-session
```

## Data Freshness

- Session capture >24 hours old? Suggest running `/x32-capture` again
- RTA listen warns automatically about old captures
