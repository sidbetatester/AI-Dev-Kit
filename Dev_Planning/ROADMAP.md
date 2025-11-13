# AI‑Dev‑Kit – Project Tools Runner

Incremental Delivery Plan (v0.1)

Progress
- Completed: P0‑01 Off‑Main‑Thread Execution + Progress + Cancel
  - Implemented background worker, queue-based UI updates, progress bar, and Cancel in `tool_runner_ui.py`.
  - Added logger/progress/cancel plumbing in `file_loader_tool.py` and `project_structure_tool.py`.
  - Added real progress reporting for the structure scan (pre-count + per-entry increments).
- Completed: P0‑02 Atomic Output Writes + Deterministic Ordering
  - Atomic temp-write + `os.replace` in `file_loader_tool.py` for concatenated output and logs.
  - Sorted traversal and deterministic output/log ordering.
- Completed: P0‑03 Encoding Detection & Robust Skips
  - Heuristic binary detection (NUL and control-byte ratio) and skip with log entry.
  - Multi-encoding read strategy (`utf-8`, BOM, UTF-16, `cp1252`, `latin-1`) with final replace fallback.
  - Log includes summary counts (processed/excluded/skipped).
- Completed: P0‑04 Long Paths & Permission Resilience
  - Applied Windows extended-path prefixes for IO calls in both tools.
  - Permission and path-too-long errors are caught and logged without aborting runs.
- Completed: P0‑05 Default Exclude Rules + UI Visibility
  - UI toggle to apply default excludes; label shows active rules.
  - Exclude set threaded into both tools; traversal skips excluded dirs.
  - Deterministic entry ordering in structure tool for stable output.
- Completed: P0‑06 Structured Logging & Copy Logs Action
  - Tool logs now include [LEVEL] prefixes propagated into the UI.
  - Console retains formatted entries and provides a Copy Logs button.

Purpose: Deliver valuable UX, reliability, and customization improvements in safe, reversible steps. Each task below is independently developable and testable in a single session.

Guiding Principles
- Preserve current behavior; new features default off or behind toggles.
- Keep UI responsive (no long operations on main thread).
- Prefer simple, atomic changes; add smoke checks and logs.
- Maintain backward compatibility for outputs; version any schema changes.

Milestones Overview
- Phase 0: Core Stability & Safety
- Phase 1: UX Quick Wins
- Phase 2: Customization & Profiles
- Phase 3: Reliability & Performance
- Phase 4: Light AI Assist (Optional)
- Phase 5: Ask‑the‑Project Q&A (Optional)
- Phase 6: Reports & Integrations

Repo Context (key files)
- tool_runner_ui.py – Tkinter UI and orchestration
- file_loader_tool.py – Concatenation logic and logging
- project_structure_tool.py – Tree/JSON generation and metadata
- Readme.md, requirements.txt, Dev_Planning/

Sequencing
- Recommended order: Phase 0 → 1 → 2 → 3 → 4/5 (optional) → 6
- Within each phase, tasks are independent unless “Depends on” is specified.

—

Phase 0 — Core Stability & Safety

P0‑01: Off‑Main‑Thread Execution + Progress + Cancel — Completed
- Summary: Run scans/concats in worker thread; add progress bar and Cancel.
- Files: tool_runner_ui.py, file_loader_tool.py, project_structure_tool.py
- Acceptance
  - UI remains responsive during long runs.
  - Progress bar updates (at least per directory); Cancel stops work cleanly.
  - No partial/locked outputs after cancel.
- Notes: Use threading + queue; disable controls while running.
- Estimate: M

P0‑02: Atomic Output Writes — Completed
- Summary: Write to temp file then atomic rename; deterministic file ordering.
- Files: file_loader_tool.py
- Acceptance
  - Outputs are produced via temp path then renamed.
  - Consistent ordering (e.g., path‑sorted) across runs.
  - Crash simulations leave no corrupt final files.
- Estimate: S

P0‑03: Encoding Detection & Robust Skips — Completed
- Summary: Add encoding detection with fallback; log unreadable files; continue.
- Files: file_loader_tool.py
- Acceptance
  - Mixed encodings do not break the run.
  - Unreadable files are skipped with Warning entries.
  - Final summary reports counts of processed/skipped.
- Estimate: S

P0‑04: Long Paths & Permission Resilience (Windows‑friendly) — Completed
- Summary: Handle long/odd paths and permission errors gracefully.
- Files: file_loader_tool.py, project_structure_tool.py
- Acceptance
  - Permission errors are logged, not fatal.
  - Long paths do not crash scanning; skipped when necessary.
- Estimate: S

P0‑05: Default Exclude Rules + UI Visibility — Completed
- Summary: Apply sensible default excludes (.git, venv, node_modules, .idea); show active rules in UI.
- Files: tool_runner_ui.py, file_loader_tool.py, project_structure_tool.py
- Acceptance
  - Defaults applied on fresh run; can be toggled off.
  - UI section displays active excludes.
- Estimate: S

P0‑06: Structured Logging & Copy Logs Action — Completed
- Summary: Log levels (Info/Warning/Error) and Copy‑to‑Clipboard from UI.
- Files: tool_runner_ui.py, file_loader_tool.py
- Acceptance
  - Console shows level tags.
  - One‑click copy of session logs works.
- Estimate: S

—

Phase 1 — UX Quick Wins

P1‑01: Persist Settings
- Summary: Save last project/output dirs, selected tools, column visibility, window size.
- Files: tool_runner_ui.py (add config load/save JSON)
- Acceptance
  - Relaunch restores last settings by default.
  - “Reset to defaults” button clears saved config.
- Estimate: S

P1‑02: Tree Context Menu (Open/Reveal/Copy Path)
- Summary: Right‑click on node: open file, open folder, copy path.
- Files: tool_runner_ui.py
- Acceptance
  - Context menu appears for file/folder nodes.
  - Actions succeed on Windows and macOS/Linux where applicable.
- Estimate: S

P1‑03: Keyboard Shortcuts
- Summary: Run (Ctrl/Cmd+R), Expand/Collapse (Ctrl/Cmd+E), Focus Search (Ctrl/Cmd+F).
- Files: tool_runner_ui.py
- Acceptance
  - Shortcuts trigger expected actions and reflect state.
- Estimate: S

P1‑04: Export Tree → Markdown/CSV
- Summary: Keep ASCII export; add Markdown (indented list) and CSV (path,size,dates).
- Files: tool_runner_ui.py, project_structure_tool.py
- Acceptance
  - User can choose export format; files land in output dir.
- Estimate: S

P1‑05: Search Highlight & Sticky Filters
- Summary: Highlight matches in tree; keep filters when refreshing tree.
- Files: tool_runner_ui.py
- Acceptance
  - Visible highlight for matches; filters persist through reruns.
- Estimate: M

P1‑06: Drag‑and‑Drop Project Root
- Summary: Drop a folder onto window to set root.
- Files: tool_runner_ui.py
- Acceptance
  - DnD sets project root and refreshes UI safely.
- Estimate: S

—

Phase 2 — Customization & Profiles

P2‑01: Saved Profiles
- Summary: Save/load multiple include/exclude sets and output naming presets.
- Files: tool_runner_ui.py
- Acceptance
  - Create, select, rename, delete profiles.
- Estimate: M

P2‑02: Include/Exclude via Glob/Regex + Import .gitignore
- Summary: Advanced patterns with optional import from .gitignore.
- Files: tool_runner_ui.py, file_loader_tool.py, project_structure_tool.py
- Acceptance
  - Glob and regex modes; test simple and complex patterns.
  - Optional “Import from .gitignore” applies rules non‑destructively.
- Estimate: M

P2‑03: Output Schema Versioning + Optional CSV Index
- Summary: Add schemaVersion to JSON; optional CSV index of all files.
- Files: project_structure_tool.py
- Acceptance
  - JSON includes schemaVersion; existing consumers unaffected.
  - CSV index opt‑in works for large trees.
- Estimate: S

P2‑04: Snapshot Labels & Quick Diff
- Summary: Name snapshots; compare two snapshots (counts/size deltas) in a small report.
- Files: tool_runner_ui.py
- Acceptance
  - Label snapshots; select two and see delta summary.
- Estimate: M

—

Phase 3 — Reliability & Performance

P3‑01: Parallel Scan with Throttled UI Updates
- Summary: Use a bounded ThreadPool for scanning; batch UI updates to <10/sec.
- Files: project_structure_tool.py, file_loader_tool.py, tool_runner_ui.py
- Acceptance
  - Faster on large trees; UI remains smooth.
- Estimate: M

P3‑02: Chunked Writes & Memory Caps
- Summary: Stream concatenation in chunks; cap buffer size.
- Files: file_loader_tool.py
- Acceptance
  - Large files don’t spike memory; output matches previous content.
- Estimate: S

P3‑03: Incremental Refresh (Optional FS Watch)
- Summary: Re‑scan only changed paths; optional real‑time watch.
- Files: project_structure_tool.py, tool_runner_ui.py
- Acceptance
  - Partial refresh updates tree quickly; full refresh still available.
- Estimate: M/L

P3‑04: Error Recovery & Summary of Skips
- Summary: Retry transient I/O; final summary lists skipped paths and reasons.
- Files: file_loader_tool.py
- Acceptance
  - Transient errors retried with backoff; clear final summary.
- Estimate: S

—

Phase 4 — Light AI Assist (Optional)

P4‑01: Project Brief Generation (Toggle)
- Summary: Generate a short summary using concatenated text + structure JSON.
- Files: tool_runner_ui.py (config), new helper (e.g., ai_brief.py)
- Acceptance
  - Works only if API key configured; produces markdown brief to output dir.
  - Clear labeling; can be disabled globally.
- Estimate: M

P4‑02: Suggested Excludes
- Summary: Propose likely excludes (e.g., venv, dist) before run; user approves.
- Files: tool_runner_ui.py
- Acceptance
  - Non‑blocking suggestions; no change without consent.
- Estimate: S

P4‑03: Guardrails & Privacy
- Summary: “AI is optional” messaging; never send file contents unless user opts in.
- Files: tool_runner_ui.py, Readme.md
- Acceptance
  - Clear toggles and disclosures in UI and README.
- Estimate: S

—

Phase 5 — Ask‑the‑Project Q&A (Optional)

P5‑01: In‑Memory Retriever over Concatenated Text
- Summary: Chunk concatenated file and run simple similarity search.
- Files: new retriever module (e.g., qna_retriever.py)
- Acceptance
  - Can fetch top‑k relevant chunks for a query quickly.
- Estimate: M

P5‑02: Q&A UI Panel
- Summary: Add a tab for questions; show sources; copy answer.
- Files: tool_runner_ui.py
- Acceptance
  - Smooth interaction; answers cite chunk positions.
- Estimate: M

P5‑03: Human‑in‑the‑Loop for Actions
- Summary: If answers imply actions, require explicit user approval.
- Files: tool_runner_ui.py
- Acceptance
  - No actions executed without confirmation; clear diff of proposed changes.
- Estimate: S

—

Phase 6 — Reports & Integrations

P6‑01: One‑Click Report (HTML/Markdown)
- Summary: Bundle tree, metrics, brief, and logs into a shareable report.
- Files: tool_runner_ui.py, project_structure_tool.py
- Acceptance
  - Generates a single report artifact; links to outputs.
- Estimate: M

P6‑02: Headless CLI
- Summary: Run scans/concats via CLI using a config/profile.
- Files: new cli.py, requirements.txt (argparse/typer)
- Acceptance
  - CLI replicates UI core functions; outputs identical.
- Estimate: M

P6‑03: Zip Export + Checksum
- Summary: Zip outputs and compute checksum file for traceability.
- Files: tool_runner_ui.py
- Acceptance
  - Zip and checksum produced alongside outputs.
- Estimate: S

P6‑04: Plugin API (Skeleton)
- Summary: Simple interface to register “tools” with name, run(), config schema.
- Files: tool_runner_ui.py (registry), docs snippet in Readme.md
- Acceptance
  - Example plugin runs; appears in UI list with enable/disable.
- Estimate: L

—

Cross‑Cutting QA Checklist (per task)
- Build/run sanity on Windows; basic run on a medium project.
- Verify no regressions in existing outputs and tree rendering.
- Logs contain clear errors/warnings; no unhandled exceptions.

How To Use This Plan
- Pick any task ID (e.g., P0‑02). We’ll implement it in a focused session.
- Each task is self‑contained and guarded by toggles where relevant.
