# Spec: P1 — Verticalized Subdomain Wedge (Layers 17 / 19)

## Overview
Blueprint Layer 17's "wedge" lowers acquisition friction with niche-specific entry
subdomains (starting with Aesthetic-Beauty). A founder lands on `beauty.distroagent.ai`,
sees beauty-specific copy, pastes their URL, and gets the free "Top boutique matches"
report — with the **hidden `industry` tag injected automatically** (Layer 19), so the
backend Context Router (`app/core/context_router.py`) applies vertical-specific prompt
guidance without the user choosing anything.

The horizontal backend is unchanged: the discovery API already takes `vertical_tag`,
and the Context Router (spec 305-adjacent, commit `a947ec4`) already consumes it.

## Files
| File | Purpose |
|---|---|
| `frontend/src/lib/verticals.ts` | `VERTICALS` (generic dropdown), `WEDGES` (per-vertical niche copy), `resolveWedge(hostname, search)` |
| `frontend/src/components/HeroSection.tsx` (modify) | Optional `wedge` prop → niche eyebrow/headline/subheadline/placeholder, hides the category dropdown, locks the tag |
| `frontend/src/app/page.tsx` (modify) | Resolve the wedge from `window.location` post-mount; pass to HeroSection |

## Behavior
- **`beauty.distroagent.ai`** (or `skincare.`, `cosmetics.`) → `aesthetic_beauty` wedge.
  Also seeded: `wellness.`, `fashion.`/`apparel.`, `home.`/`decor.`, `food.`/`beverage.`.
- **Apex / `www.` / `app.` / `api.` / Vercel previews / `localhost`** → generic dropdown (no wedge).
- **Local testing override:** `?v=beauty` (or any vertical/alias) forces a wedge on any host.
- On a wedge, `onSubmit` sends `wedge.value` as `vertical_tag`; the dropdown is removed.
- Resolution runs in `useEffect` (post-mount) to avoid SSR/client hydration mismatch.

## Adding a vertical
Add one entry to `WEDGES` + a `SUBDOMAIN_TO_VERTICAL` alias. No component changes.
Keep `value` aligned with a backend Context Router vertical for prompt injection.

## Manual / infra step (cannot be done in code)
- Configure a **wildcard domain `*.distroagent.ai`** (or per-vertical subdomains) in
  Vercel pointing at this app, with the matching DNS CNAME. Same app serves every
  subdomain; `resolveWedge` reads the real hostname at runtime.

## Acceptance Criteria
- [x] `resolveWedge` maps known beauty subdomains/aliases → `aesthetic_beauty`, apex/unknown → null
- [x] HeroSection renders niche copy + hides the dropdown when a wedge is active
- [x] Submitting on a wedge injects the wedge's `vertical_tag` (hidden industry tag)
- [x] Generic apex domain keeps the full category dropdown (no behavior change)
- [x] `npm run build` + `tsc --noEmit` pass
- [ ] Wildcard subdomain configured in Vercel (manual deploy step)
