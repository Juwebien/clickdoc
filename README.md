# clickdoc

### Your doc just became a conversation.

**Tap any sentence. Type what bothers you. An AI agent picks it up
seconds later — and either fixes the doc, opens a spec, or writes the
code that resolves the question.**

That is the entire product. One Python file, one SQLite file, one
folder of HTML. No SaaS, no login, no telemetry, no `npm install`.
The annotation queue lives on your disk and surfaces to any tool that
reads `/api/feed` — your team, your CI, or the AI assistant already
running in your terminal.

```
You write a doc.
A reader taps the line that's wrong.
Their comment sits next to that line in SQLite.
Your AI agent reads the queue, fixes the line, marks it final.
Loop closes. Doc stays alive.
```

It is the missing layer between "writing docs" and "shipping code" —
the place where the gap between *what's documented* and *what's true*
gets named, tracked, and closed.

[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![python: 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)
![dependencies: none](https://img.shields.io/badge/deps-stdlib--only-green.svg)
![status: 0.2.0](https://img.shields.io/badge/version-0.2.0-blueviolet.svg)

---

## Why

You write docs. People read them on their phone. They want to leave a
remark without opening Slack, Notion, or a GitHub issue. clickdoc lets
them tap the sentence that bothers them and type their thought right
there. The comment is stored on disk and surfaced to any tool that
wants to act on it — a human triager, a CI bot, or an AI agent running
on the same machine.

It is intentionally small:

- one Python file (`server.py`, ~750 lines, stdlib only)
- one SQLite file (WAL mode)
- two JS files + one CSS file (`static/`)
- no build step, no `npm install`, no Docker required
- single command to install as a systemd user service

---

## Quickstart — try it in 60 seconds

```bash
git clone https://github.com/Juwebien/clickdoc ~/clickdoc
cd ~/clickdoc
python3 server.py
```

Open <http://localhost:8088>. Click the title. Type a comment. Watch it
appear at <http://localhost:8088/api/feed> as plain text.

## Install as a service (one command)

```bash
git clone https://github.com/Juwebien/clickdoc ~/clickdoc
cd ~/clickdoc
./install.sh
```

That's it. The installer:

- checks Python ≥ 3.11
- copies systemd user units to `~/.config/systemd/user/`
- substitutes the working directory to your actual clone path
- enables the auto-reload watcher
- enables the service and starts it
- smoke-tests `/api/health`

To customise:

```bash
./install.sh --pages   ~/my-project/docs/pages   # overlay your own pages
./install.sh --port    9000                      # bind a different port
./install.sh --host    127.0.0.1                 # local-only access
./install.sh --author  my-handle                 # tag annotations
./install.sh --no-watcher                        # skip clickdoc.path
./install.sh --uninstall                         # tear it down
```

The installer is idempotent and pure user-mode — no `sudo` needed.

---

## Overlay your own content

The bundled `pages/` folder is a welcome / demo. Point an env var at
your own folder and your pages take precedence:

```bash
CLICKDOC_PAGES_DIR=$HOME/my-docs/pages python3 server.py
```

The overlay is checked **first** for every path under `/pages/`. If
your overlay has `index.html`, it replaces the welcome. If it doesn't
have `api.html`, the bundled one wins. Same logic for static assets
via `CLICKDOC_STATIC_DIR`.

You don't need to copy files. clickdoc reads them where they live, so
you can keep doc-as-code in your project repo and serve it from there.

---

## API

| Method | Path                                | Notes                                              |
|--------|-------------------------------------|----------------------------------------------------|
| GET    | `/api/health`                        | `{"status":"ok"}`                                  |
| GET    | `/api/annotations[?status=&lifecycle=&page=&type=]` | list with filters             |
| POST   | `/api/annotations`                   | create — body `{page, anchor?, line_excerpt?, type, comment}` |
| PATCH  | `/api/annotations/<id>`              | update `{status?, response?, author?, lifecycle?, lifecycle_by?, lifecycle_note?}` |
| DELETE | `/api/annotations/<id>`              | remove                                             |
| GET    | `/api/feed[?status=open]`            | plain-text feed for AI agents                      |
| GET    | `/api/changes[?since=24h&kind=&limit=]` | unified timeline (annotations + edits + lifecycle) |

### Annotation lifecycle

Every annotation travels these five ordered stages:

```
open → triaged → refined → reviewed → final
```

Setting `lifecycle: "final"` automatically sets `status: "addressed"`.
The full audit trail lives in the `lifecycle_log` column and surfaces
through `/api/changes`. See `skill/SKILL.md` for the workflow.

---

## AI-agent workflow

Local agents (Claude Code, Codex, Cursor, etc.) can read the open queue
at session start:

```bash
curl -sS http://localhost:8088/api/feed
```

…and advance a comment through the lifecycle:

```bash
curl -sS -X PATCH http://localhost:8088/api/annotations/12 \
  -H 'Content-Type: application/json' \
  -d '{
        "lifecycle": "final",
        "lifecycle_by": "claude-code",
        "lifecycle_note": "spec foo/spec.md drafted + merged",
        "response": "Done in commit abc1234."
      }'
```

Use the `type` field to route by intent. A `spec` annotation can become
a tracked issue. A `precision` annotation tells you to edit the doc. A
`comment` is free-form thought. **All three** are candidate work items
— the lifecycle ladder is the contract, not the button label.

The bundled skill (`skill/SKILL.md`) is the canonical reference. Drop
it into your agent's skill directory (`~/.claude/skills/`,
`~/.codex/skills/`, `~/.hermes/shared-skills/`, …) and every session
inherits the authoring + annotation discipline.

---

## How a page becomes annotatable

Add `data-anchor="some-id"` to any HTML element. That element becomes
clickable, opens the annotation modal with the line as excerpt, and
stores the annotation against that anchor.

```html
<p data-anchor="theme-config">
  Theme is set in <code>config/theme.yaml</code>.
</p>
```

Tap the paragraph → modal opens → save → annotation stored. The
sidebar TOC shows an open-count badge next to the page link.

See `pages/authoring.html` for a full guide.

---

## Mobile (since 0.2.0)

- Fixed topbar with current page title (auto-derived from `<h1>`)
- Left-slide drawer for navigation (`☰` button)
- Annotation popup = bottom-sheet (slide-up, keyboard-friendly)
- FAB `+` in thumb-zone with safe-area awareness
- Body scroll-locked while the drawer is open
- Esc / tap-backdrop closes

The mobile spec lives at `docs/specs/clickdoc-mobile-ui/spec.md`.

---

## Deploy

This repo ships several deploy recipes in `ops/`:

- `ops/clickdoc.service` — systemd user unit (installed by `install.sh`)
- `ops/clickdoc.path` — companion auto-reload watcher
- `ops/Caddyfile.example` — TLS reverse proxy
- `ops/k8s/httproute.yaml` — Kubernetes Gateway API exposure
- `ops/docker-compose.yml` — container deploy with a named volume

---

## Environment

| Variable                 | Default                                        | Effect                                  |
|--------------------------|------------------------------------------------|-----------------------------------------|
| `CLICKDOC_LISTEN_HOST`   | `0.0.0.0`                                      | bind address                            |
| `CLICKDOC_LISTEN_PORT`   | `8088`                                         | bind port                               |
| `CLICKDOC_DB_PATH`       | `$XDG_DATA_HOME/clickdoc/annotations.db`       | SQLite file                             |
| `CLICKDOC_PAGES_DIR`     | _(unset)_                                      | overlay pages dir (checked first)       |
| `CLICKDOC_STATIC_DIR`    | _(unset)_                                      | overlay static dir (checked first)      |
| `CLICKDOC_AUTHOR`        | `anon`                                         | default author tag for new annotations  |

---

## Security model

clickdoc has **no built-in authentication**. Treat the API as
trusted-LAN-only. Put a reverse proxy with auth in front when exposing
beyond your machine. The default systemd unit binds `0.0.0.0:8088` —
pass `--host 127.0.0.1` to `install.sh` for local-only.

Annotations are stored as plain text. **Don't paste secrets into the
comment field.** The page content is served as-is; if an overlay folder
contains sensitive content, gate the server behind your usual auth.

The SQLite file lives at `~/.local/share/clickdoc/annotations.db` by
default. `--uninstall` removes the systemd units but **keeps the DB**;
delete it manually if you want a clean slate.

---

## Spec kit

This repo follows a small spec-kit convention under `docs/specs/`:

- `docs/specs/clickdoc-author/spec.md` — authoring & lifecycle
- `docs/specs/clickdoc-mobile-ui/spec.md` — mobile UI contract

Each spec is a single markdown file with Goal · Requirements ·
Non-Goals · Success Criteria · Related Specs. Contributions are
welcome — open a PR with a new spec dir if you want to formalise a
contract.

---

## License

MIT — see [LICENSE](LICENSE).
