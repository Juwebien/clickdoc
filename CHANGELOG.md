# Changelog

## 0.2.0 — 2026-05-17

### Lifecycle ladder
- Added `lifecycle` + `lifecycle_log` columns to the annotations table
  (open → triaged → refined → reviewed → final).
- PATCH endpoint accepts `lifecycle`, `lifecycle_by`, `lifecycle_note`;
  setting `lifecycle: "final"` auto-sets `status: "addressed"`.
- `/api/annotations?lifecycle=<stage>` filter.
- `/api/changes` emits a new event kind `lifecycle_transition`,
  derived from the per-row append-only log.
- Idempotent migration: existing DBs gain the new columns on first run.

### Mobile-first UI
- Fixed top bar with hamburger + current page title (auto-derived
  from `<h1>`). Replaces the sticky bar with a negative-margin hack.
- Left-slide drawer for navigation, with backdrop + scroll lock +
  Esc-to-close. Tap-link auto-dismisses the drawer.
- Annotation popup becomes a bottom-sheet on `max-width: 600px` —
  slide-up, drag-handle visual, `max-height: 85dvh`.
- FAB (`+`) repositioned for one-handed reach with
  `env(safe-area-inset-*)` awareness; lifted above the bottom-sheet
  anchor on mobile.
- `body.drawer-open` locks page scroll.

### Installer
- New `install.sh`: one-command systemd user service install with
  `--pages`, `--port`, `--host`, `--author`, `--no-watcher`,
  `--uninstall` flags. Pure user-mode (no `sudo`).
- Service + path units use a clone-relative WorkingDirectory; the
  installer substitutes the actual path.

### Authoring skill
- New `skill/SKILL.md` documenting anchor naming, dual-persona
  cross-link rule, lifecycle ladder, and the never-include lists
  (secrets, PII, speculative future surfaces, project-specific content
  in the public framework).
- Drop into `~/.claude/skills/`, `~/.codex/skills/`,
  `~/.hermes/shared-skills/` to share the discipline.

### Spec kit
- `docs/specs/clickdoc-author/spec.md` — authoring & lifecycle.
- `docs/specs/clickdoc-mobile-ui/spec.md` — mobile UI contract.

### Strip
- Removed project-specific references from all bundled files. The repo
  is now fully generic for distribution.

## 0.1.0 — 2026-05-17

### Initial release
- stdlib-only Python HTTP server with SQLite-WAL persistence
- per-element annotation overlay (click any `[data-anchor]`)
- three annotation types: comment, spec, precision
- plain-text feed at `/api/feed` for AI agents to triage
- overlay model: `CLICKDOC_PAGES_DIR` to mount per-project content
- deploy recipes: systemd user service, systemd path watcher,
  Caddyfile, k8s Gateway API HTTPRoute, docker-compose
- CI workflow with smoke test + overlay resolution test
- MIT license
