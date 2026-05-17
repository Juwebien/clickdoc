# clickdoc — Authoring & Lifecycle Spec

## Goal

Define the canonical authoring workflow for clickdoc pages and the
annotation lifecycle that turns a one-line user comment into a
sprint-ready spec without losing context.

## Background

Documentation rots. Users write comments in Slack, Notion, GitHub
issues — none of these read the doc back. clickdoc colocates the
comment with the line of doc that triggered it, and exposes the queue
to any agent on the same machine. The authoring contract makes the
result trustworthy.

## Requirements

1. **Every annotatable element carries `data-anchor="<kebab-id>"`**.
   The id is concept-shaped (`iam-fallback`), not position-shaped
   (`step-3`), so it survives section renumbering.

2. **Every artefact mentioned in a page is dual-persona**. The doc
   answers the question "how do I modify it?" for both the user-of-the
   -system and the operator-of-the-system. If only one side is
   documented, add a one-line note acknowledging the other.

3. **The `op-link` cross-link points to an existing anchor in
   `operations.html`**. No dangling links — adding a cross-link without
   the target is a doc bug.

4. **The lifecycle ladder is the only path to "addressed"**:
   `open → triaged → refined → reviewed → final`. PATCH the annotation
   at each stage with `lifecycle`, `lifecycle_by`, and a short
   `lifecycle_note`. Setting `lifecycle: "final"` auto-sets
   `status: "addressed"`; never the reverse.

5. **The lifecycle_log is append-only**. Each transition writes a row
   like `<ISO> | <stage> | by=<actor> | note=<text>`. The server
   exposes `/api/changes` so any agent can timeline-scroll the
   project's recent activity.

## Non-Goals

- Diffing previous annotation versions (use git for the page itself).
- Replying to comments as a conversation thread (use `response` field
  once at lifecycle=final).
- Cross-project annotation aggregation (clickdoc is per-project).

## Success Criteria

- A new contributor can read `pages/authoring.html` and produce a
  conforming page in ≤ 10 minutes.
- An AI agent reading `/api/feed` can advance an annotation to `final`
  without human help when the change is mechanical.
- `grep -r 'data-anchor=' pages/` returns only kebab-case ids.
- No annotation reaches `addressed` without a `lifecycle=final` row.

## Related Specs

- `clickdoc-mobile-ui` — how the surface adapts to phone use
- (sister project specs that consume clickdoc as their doc backbone)
