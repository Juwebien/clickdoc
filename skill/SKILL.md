---
name: clickdoc-author
description: |
  Use when editing pages served by a clickdoc instance, or when an AI
  agent is asked to read and address annotations from the local
  /api/feed of a running clickdoc server. Enforces canonical anchor
  naming, dual-persona "how to modify" cross-links, the lifecycle
  (open → triaged → refined → reviewed → final), and the safety rules
  for what content stays out of public clickdoc framework forks.
version: 1.0.0
metadata:
  audience: [claude-code, codex, hermes, cursor, other-ai-agents]
  related_skills: []
  framework_repo: https://github.com/Juwebien/clickdoc
---

# clickdoc-author — author docs that humans annotate and agents act on

`clickdoc` is a click-to-comment live documentation server. Any HTML
element marked `data-anchor="..."` is annotatable in place. Annotations
sit in a local SQLite file and surface to AI agents via `/api/feed` and
`/api/changes`. This skill formalises HOW to write pages, address
annotations, and keep the system honest.

The same skill applies whether you are running against the bundled
sample pages or against your own overlay folder.

## When to invoke

Trigger this skill the moment any of these is true:

1. You are about to create or edit a `.html` file under the project's
   clickdoc pages directory.
2. You have just read the annotation feed
   (`curl -sS http://127.0.0.1:8088/api/feed`) and an item has
   `type=precision` or `type=spec` — both demand a doc edit.
3. The user mentions "the doc", "clickdoc", "annotation", asks you to
   "respond to the feed", or to add a `data-anchor`.

Do not invoke for unrelated edits in adjacent code repos. clickdoc-author
is doc-only.

## Read the feed first, always

Before editing anything, read open remarks. The feed is plain text,
one block per annotation:

```bash
curl -sS http://127.0.0.1:8088/api/feed
```

Machine-readable filter:

```bash
curl -sS 'http://127.0.0.1:8088/api/annotations?status=open' | jq
```

Recent activity (timeline):

```bash
curl -sS 'http://127.0.0.1:8088/api/changes?since=24h' | jq
```

Open the changes view in a browser (`/pages/changes.html` if your
overlay carries it) to scan colour-coded events: hot &lt;1h, warm &lt;6h,
day &lt;24h, week &lt;7d, old beyond.

## Annotation lifecycle — never skip a stage

Every annotation travels these five ordered stages. The button the
author clicked (`comment` / `spec` / `precision`) is NOT the signal —
every comment is a candidate spec until proven otherwise.

```
open → triaged → refined → reviewed → final
```

| Stage | Meaning | Trigger to advance |
|---|---|---|
| `open` | user just commented | identify spec(s) it maps to |
| `triaged` | spec(s) identified; new spec drafts started | run code/text refinement |
| `refined` | refinement notes merged into the spec | run external review |
| `reviewed` | review notes saved; blocking concerns addressed | spec is sprint-ready |
| `final` | comment fully resolved; spec ready or action complete | terminal |

PATCH pattern:

```bash
curl -sS -X PATCH http://127.0.0.1:8088/api/annotations/<id> \
  -H 'Content-Type: application/json' \
  -d '{
    "lifecycle": "triaged",
    "lifecycle_by": "<agent-or-human-name>",
    "lifecycle_note": "spec foo/spec.md drafted"
  }'
```

Setting `lifecycle: "final"` automatically sets `status: "addressed"`.

## Anchor naming conventions

1. **Mean the meaning, not the position.** `data-anchor="iam-fallback"`
   beats `data-anchor="step-3"`.
2. **Kebab-case, lowercase, ASCII.** No accents, no spaces.
3. **Prefix by section concept**, not by section number.
4. **Stable across renames** — anchors are URLs.
5. **Unique within the page.**

## The dual-persona rule

Every artefact mentioned in the doc (a config file, an env var, a
schema field, a button) should answer the question **"how do I modify
it?"** for two personas:

| Persona | Tools they use | Example |
|---|---|---|
| **user** | the running app's UI / their own CLI | "set my preferred theme" |
| **operator** | code, config files, deploy infra | "bump the default theme platform-wide" |

Single-persona explanations are *incomplete*. If a section only tells
the operator path, add a one-line user-side note (even if it is "users
cannot edit this directly").

Cross-link to a canonical `operations.html` (or equivalent) page that
collects the operator instructions:

```html
<p data-anchor="theme-config">
  Theme is set in <code>config/theme.yaml</code>.
  <a class="op-link" href="/pages/operations.html#theme-config">→ how to modify</a>
</p>
```

The `op-link` class renders as a chevron+underline. The target must be
an anchor that already exists in `operations.html`; if you reference a
missing anchor, add the section to `operations.html` in the same edit.
**No dangling links.**

## Page structure

Every page in a clickdoc overlay follows the same skeleton:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#0b0c10">
  <title>Project · Page name</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="layout">
  <nav class="toc" id="toc">
    <div class="group">Pages</div>
    <a href="/pages/index.html">Index</a>
    <a href="/pages/changes.html">Changes</a>
    <!-- … one per page … -->
  </nav>
  <main>
    <div class="menu-toggle"><button>☰</button></div>
    <header class="page">
      <div class="eyebrow">Project · Section</div>
      <h1 data-anchor="title">…</h1>
      <div class="sub" data-anchor="subtitle">…</div>
    </header>
    <section id="topic-a" data-anchor="topic-a">
      <h2><span class="num">1</span>Topic A</h2>
      <!-- … -->
    </section>
  </main>
</div>
<script src="/static/nav.js"></script>
<script src="/static/annotate.js"></script>
</body>
</html>
```

## CSS components shipped by the framework

Use the shipped classes; do not invent new ones in a per-page `<style>`.
If a genuinely new component is needed, propose it as a PR against the
clickdoc framework repo (https://github.com/Juwebien/clickdoc) and add
it to `static/style.css`.

- `.card` · `.callout[.warn|.red]` · `.kv` (with `.k`/`.v`)
- `.fs-tree` · `.flow` (with `.step`/`.num`/`.text`)
- `.metric-grid`/`.metric` · `.tag[.green|.amber|.violet|.red]`
- `.op-link` (canonical pointer) · `.persona-tabs` · `.persona-block`
- `.parent-graph` · `.artefact`
- `.annot-spinner` · `.annot-badge`

## Workflow when addressing an annotation

```
1. fetch the feed     curl -sS http://127.0.0.1:8088/api/annotations
2. pick the item that fits this turn's scope
3. open the page + anchor in your head
4. apply the dual-persona rule for the section being touched
5. add cross-link if you mention an artefact for the first time
6. systemd auto-reloads on save when clickdoc.path is enabled
7. advance the lifecycle — never just set status=addressed
8. commit & push the page change in your project repo
   (do NOT commit project-specific content to the public clickdoc framework)
```

## What never goes into clickdoc pages

* Tokens, keys, signing material, passwords — also off-limits in the
  annotation comment field.
* User PII the project didn't explicitly invite into the doc.
* Speculative future API surfaces — describe what exists.
* Internal Slack threads, Linear comments verbatim — distil first.

## What never goes into the public clickdoc framework

* Tenant identifiers, cluster names, customer slugs.
* Project-specific page content — keep that in your own overlay.
* Anything that ties the framework to a single deployment.

## Health probes

```bash
systemctl --user status clickdoc.service       # is the service alive?
systemctl --user status clickdoc.path          # is the watcher alive?
curl -sS http://127.0.0.1:8088/api/health      # is the API responding?
journalctl --user -u clickdoc.service -n 50    # recent server logs
sqlite3 ~/.local/share/clickdoc/annotations.db \
  'SELECT id,status,lifecycle,type,page FROM annotations ORDER BY id DESC LIMIT 20'
```

## Source of truth

- Framework: <https://github.com/Juwebien/clickdoc>
- API reference: `pages/api.html` (served by the running instance)
- Authoring guide: `pages/authoring.html`
- Live changes feed: `/api/changes`
