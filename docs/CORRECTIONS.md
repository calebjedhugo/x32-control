# Session Corrections Log

## 2026-02-25
- First auto-awesome session. 21 changes applied in pass 1, board powered off before pass 2.
- No engineer corrections to evaluate (board lost all changes on power-off).
- Routing issues found: FX1 on ch09+bus05/06 (should be ch31), FX8 not inserted (should be bus05/06), ch31 insert off. Engineer acknowledged, chose to proceed.
- Stream guard fix: changed yt-dlp format from `bestaudio` to `bestaudio/best` — livestream HLS has no audio-only formats.
- Stream guard still has pipeline stability issues — pipeline dies after running for a while, needs further debugging.
- Note: X32 software running on another machine causes OSC packet drops during captures.
