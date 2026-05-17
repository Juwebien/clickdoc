# clickdoc — Mobile-First UI Spec

## Goal

Make clickdoc usable from a phone for the two primary tasks: **reading
the doc** and **leaving an annotation**. Desktop is denser; mobile is
the primary read-and-react surface.

## Requirements

1. **Fixed topbar on mobile** (`@media max-width: 900px`) with
   hamburger + current page title. Height 52 px. Stays put as the
   page scrolls.

2. **Sidebar TOC becomes a left-slide drawer** on mobile. Width
   `min(300px, 86vw)`. Translates from `-100%` to `0` over 220 ms.
   Backdrop element behind (`.toc-backdrop`) blocks page interaction
   and dismisses on tap. Esc key dismisses.

3. **Body scroll lock** when drawer is open (`body.drawer-open` →
   `overflow: hidden; touch-action: none`). Prevents background
   scroll-bleed.

4. **Annotation popup = bottom-sheet on mobile** (`max-width 600px`).
   Anchored to `flex-end` of the overlay container; rounded only at
   top; slide-up animation; drag-handle visual at top. Reachable with
   the thumb while the keyboard is open.

5. **`max-height: 85dvh`** uses the dynamic viewport unit so the panel
   shrinks/grows with the visual viewport (Safari URL bar, Android
   keyboard).

6. **Textarea font-size ≥ 16 px** to prevent iOS auto-zoom on focus.

7. **FAB (`+` button) sits in a thumb-safe zone**: `bottom: 82px`
   (above the bottom-sheet anchor, above iOS Safari URL bar after
   collapse) and `safe-area-inset` aware on notched devices.

8. **Tapping a TOC link closes the drawer** before navigating, so the
   user lands on the new page with no leftover UI state.

9. **WCAG AA contrast** for all foreground text against the dark
   background. Verify with the OKLCH palette in `static/style.css`.

## Non-Goals

- Light theme (deferred).
- Drag-to-dismiss on the bottom-sheet (visual handle only for now).
- Multi-page annotation overview overlay (separate spec — would be
  `clickdoc-annotation-navigator`).

## Success Criteria

- Cold-open the doc on a phone, find a target page in ≤ 2 taps.
- Open the annotation panel, type a comment, save — all reachable with
  one hand on a 6.1" phone.
- Lighthouse mobile ≥ 90 on the bundled `pages/index.html`.

## Related Specs

- `clickdoc-author` — authoring contract
- Future: `clickdoc-annotation-navigator` (per-page side panel listing
  every annotation with lifecycle pill + scroll-to-anchor)
- Future: `clickdoc-section-collapse-badges` (collapsible sections
  with annotation count badges)
