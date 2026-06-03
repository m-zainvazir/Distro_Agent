# Plan: beauty.distroagent.ai Landing Page

## Context
This is the wedge product — the free hook that converts D2C beauty brand founders
into paying DFY clients. A founder lands here, pastes their Shopify URL, and within
60 seconds sees a beautiful visual report of their top 5 matched boutiques.

First impression = everything. This page must feel like it was designed FOR beauty
brand founders — not a generic SaaS tool. Clean, editorial, luxurious but minimal.

This frontend calls the existing backend:
- `POST /api/v1/discovery/start` — starts the pipeline
- `GET /api/v1/discovery/{task_id}/status` — polls for progress
- `GET /api/v1/discovery/{task_id}/report` — fetches results

---

## Design System

### Color Palette
--color-bg:           #FAFAF8   /* warm off-white, never pure white /
--color-surface:      #FFFFFF   / cards and inputs /
--color-sage:         #7C9A82   / primary accent — sage green /
--color-sage-light:   #E8F0E9   / sage tints for backgrounds /
--color-sage-dark:    #4A6B50   / sage for hover states /
--color-rose:         #C4897A   / dusty rose — secondary accent /
--color-rose-light:   #F5EAE7   / rose tints /
--color-text-primary: #1A1A1A   / headings /
--color-text-secondary: #6B6B6B / subtext /
--color-border:       #E8E4DF   / input borders, card borders /
--color-blur-overlay: rgba(250,250,248,0.85) / blur effect on teaser */

### Typography
Font stack:

Headings: 'Playfair Display' (Google Fonts) — editorial, beauty-brand feel
Body/UI:  'Inter' (Google Fonts) — clean, readable

Scale:

Hero heading:    56px / font-weight 400 (elegant, not heavy)
Section heading: 32px / font-weight 400
Card heading:    18px / font-weight 500
Body:            16px / font-weight 400
Label/caption:   13px / font-weight 500 / letter-spacing 0.08em / uppercase


### Spacing & Shape
Border radius:

Inputs + buttons: 4px  (clean, not bubbly)
Cards:            12px
Pill badges:      999px

Max content width: 720px (centered — keeps it focused, editorial)
Section vertical padding: 80px top/bottom

---

## Step 0 — Project Setup

```bash
# From distroagent/ root:
cd frontend
npx create-next-app@latest . --typescript --tailwind --app --src-dir --no-git
```

### Files to create

| File | Purpose |
|---|---|
| `src/app/layout.tsx` | Root layout — Google Fonts, metadata, global styles |
| `src/app/page.tsx` | Main page — composes all sections |
| `src/app/globals.css` | CSS variables, base resets |
| `src/components/HeroSection.tsx` | Headline + URL input + submit button |
| `src/components/LocationInput.tsx` | Optional city/state input |
| `src/components/LoadingState.tsx` | Animated progress messages |
| `src/components/ResultsSection.tsx` | Top 5 store cards + CTA |
| `src/components/StoreCard.tsx` | Individual store result card |
| `src/components/TeaserBlur.tsx` | Blurred rows 6–50 teaser |
| `src/components/CTABanner.tsx` | "Pitch all 50 stores" Calendly CTA |
| `src/lib/api.ts` | API client — start, poll, fetch results |
| `src/lib/types.ts` | TypeScript types matching backend Pydantic models |
| `src/hooks/useDiscovery.ts` | Custom hook managing full discovery flow state |
| `tailwind.config.ts` | Extended with custom colors and fonts |
| `.env.local` | `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_CALENDLY_URL` |

---

## Step 1 — Tailwind Config + CSS Variables

**File:** `tailwind.config.ts`

Extend the default theme with the design system colors and fonts:

```typescript
const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#FAFAF8',
        surface: '#FFFFFF',
        sage: {
          DEFAULT: '#7C9A82',
          light: '#E8F0E9',
          dark: '#4A6B50',
        },
        rose: {
          DEFAULT: '#C4897A',
          light: '#F5EAE7',
        },
        border: '#E8E4DF',
        'text-primary': '#1A1A1A',
        'text-secondary': '#6B6B6B',
      },
      fontFamily: {
        display: ['Playfair Display', 'Georgia', 'serif'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      maxWidth: {
        content: '720px',
      },
    },
  },
}
```

**File:** `src/app/globals.css`

```css
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;500&family=Inter:wght@400;500;600&display=swap');
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  background-color: #FAFAF8;
  color: #1A1A1A;
  -webkit-font-smoothing: antialiased;
}

/* Smooth scroll */
html { scroll-behavior: smooth; }

/* Focus ring — sage colored, not default blue */
*:focus-visible {
  outline: 2px solid #7C9A82;
  outline-offset: 2px;
}
```

---

## Step 2 — TypeScript Types

**File:** `src/lib/types.ts`

```typescript
export type DiscoveryStatus = 'idle' | 'loading' | 'complete' | 'error'

export interface StartDiscoveryRequest {
  brand_url: string
  location: string          // "Brooklyn, NY" — empty string if not provided
  vertical_tag: string      // hardcoded "aesthetic_beauty" for this frontend
}

export interface StartDiscoveryResponse {
  task_id: string
  status: 'processing'
}

export interface StatusResponse {
  status: 'processing' | 'complete' | 'error'
  progress: number          // 0–100
  current_step: string      // e.g. "Finding matched boutiques..."
}

export interface ScoredStore {
  name: string
  city: string
  state: string
  final_score: number       // 0.0–10.0
  outreach_priority: 'HIGH' | 'MEDIUM' | 'LOW'
  why_matched: string       // 1–2 sentence AI explanation
  match_summary: string
  storefront_image_urls: string[]
}

export interface ReportResponse {
  stores: ScoredStore[]       // all scored stores, sorted by score desc
  brand_name: string
  total_stores_found: number  // e.g. 47
  vision_ran_on: number
}
```

---

## Step 3 — API Client

**File:** `src/lib/api.ts`

```typescript
const BASE = process.env.NEXT_PUBLIC_API_URL

export async function startDiscovery(req: StartDiscoveryRequest): 
  Promise<StartDiscoveryResponse>

export async function pollStatus(taskId: string): 
  Promise<StatusResponse>

export async function fetchReport(taskId: string): 
  Promise<ReportResponse>
```

Rules:
- All functions throw a typed `ApiError` with `message` and `status_code` on non-2xx
- `pollStatus` is called every 2 seconds by the custom hook (not a stream)
- Set `Content-Type: application/json` on all POST requests
- Include `credentials: 'include'` for future auth compatibility

---

## Step 4 — Discovery Hook

**File:** `src/hooks/useDiscovery.ts`

This hook owns ALL state for the discovery flow. Components only read from it.

```typescript
interface UseDiscoveryReturn {
  status: DiscoveryStatus
  progress: number              // 0–100
  currentStep: string           // human-readable progress message
  report: ReportResponse | null
  error: string | null
  startDiscovery: (brandUrl: string, location: string) => Promise<void>
  reset: () => void
}
```

Internal flow:
1. `startDiscovery()` called → set `status = 'loading'`, call `api.startDiscovery()`
2. Store `task_id` in ref
3. Begin polling `api.pollStatus(task_id)` every 2 seconds with `setInterval`
4. On each poll: update `progress` and `currentStep` from response
5. When `status === 'complete'` → call `api.fetchReport()`, set `report`, set `status = 'complete'`
6. When `status === 'error'` → set `error` message, stop polling
7. `reset()` → clears all state back to idle
8. Cleanup: `clearInterval` on unmount

Progress step messages (use these exact strings — they were written for beauty founders):
```typescript
const PROGRESS_MESSAGES: Record<number, string> = {
  0:  'Reading your brand story...',
  15: 'Analyzing your aesthetic and color palette...',
  30: 'Scanning 200+ boutiques in your area...',
  50: 'Matching your vibe to physical storefronts...',
  70: 'Scoring brand-to-shelf fit for top matches...',
  85: 'Generating your personalized match report...',
  95: 'Almost ready...',
}
```

---

## Step 5 — Page Layout

**File:** `src/app/layout.tsx`

```typescript
export const metadata: Metadata = {
  title: 'DistroAgent — Find Boutiques That Will Love Your Brand',
  description: 'Drop your Shopify URL. See which boutiques match your aesthetic in 60 seconds.',
  openGraph: {
    title: 'Find Your Perfect Boutique Partners',
    description: 'AI-powered wholesale distribution for D2C beauty brands.',
  },
}
```

Body: `bg-bg font-sans` — that is all. No nav, no footer clutter.

---

## Step 6 — Hero Section

**File:** `src/components/HeroSection.tsx`

### Visual layout (top to bottom):
[top label]
WHOLESALE DISTRIBUTION · POWERED BY AI
[main headline — Playfair Display, 56px]
Drop Your Shopify URL.
See Which Boutiques
Will Love You.
[subheadline — Inter, 18px, text-secondary]
Paste your store link below. In 60 seconds, our AI analyzes your
brand aesthetic and finds the physical boutiques most likely to
carry — and sell — your products.
[URL input field]
[ https://yourbrand.myshopify.com              ] ← big, full-width
[location input — smaller, optional]
[ City, State (optional — e.g. Brooklyn, NY)  ]
[CTA button — full width, sage green]
[ Get My Free Report → ]
[trust line below button — small, centered, text-secondary]
✦ Free · No account needed · Results in ~60 seconds

### URL Input specs:
- Height: 56px
- Font size: 16px
- Border: 1px solid `#E8E4DF`
- Border radius: 4px
- Placeholder: `https://yourbrand.myshopify.com or etsy.com/shop/yourshop`
- On focus: border changes to sage `#7C9A82`, box-shadow: `0 0 0 3px rgba(124,154,130,0.15)`
- Validate on submit: must start with `http` — show inline error if not

### Submit Button specs:
- Height: 52px
- Background: sage `#7C9A82`
- Text: `Get My Free Report →` — Inter 16px font-weight 500, white
- On hover: background `#4A6B50`, transition 150ms
- On loading: disabled + show spinner (replace arrow with spinning circle)
- Disabled state: opacity 0.6, cursor not-allowed

### Top label:
- Text: `WHOLESALE DISTRIBUTION · POWERED BY AI`
- Style: Inter 12px, font-weight 500, letter-spacing 0.1em, uppercase, color sage `#7C9A82`
- Add a subtle horizontal rule on each side (sage colored, 40px wide)

---

## Step 7 — Loading State

**File:** `src/components/LoadingState.tsx`

Replaces the form while processing. Full section, centered.

### Layout:
[animated botanical ring — CSS only, no image]
Analyzing your brand
[progress message — fades between steps]
[progress bar — thin, sage colored]
[████████████░░░░░░░░] 65%
[small text below]
Scanning boutiques in Brooklyn, NY

### Botanical ring animation:
- A circle (120px diameter) made with CSS border
- Sage colored border, 3px thick
- One quarter of the border is rose `#C4897A`
- Rotates infinitely with `animate-spin` (slow — 2s duration)
- Inside the ring: a small leaf emoji 🌿 or the letter D in Playfair Display

### Progress bar specs:
- Container: full width, 4px height, background `#E8F0E9` (sage-light), border-radius 999px
- Fill: sage `#7C9A82`, transitions width smoothly (CSS transition 500ms)
- Updates from `progress` value in the hook (0–100)

### Progress message:
- Fades out old message, fades in new one (CSS opacity transition 300ms)
- Matches `PROGRESS_MESSAGES` from the hook
- Font: Playfair Display, 22px, text-primary, italic

---

## Step 8 — Results Section

**File:** `src/components/ResultsSection.tsx`

Shown when `status === 'complete'`. Receives `report: ReportResponse`.

### Layout (top to bottom):
[results header]
Your Top Boutique Matches
[subtext] We found {report.total_stores_found} boutiques in {location}.
Here are the 5 strongest fits for {report.brand_name}.
[5 store cards — see StoreCard spec below]
[teaser blur section — see TeaserBlur spec]
[CTA banner — see CTABanner spec]

---

## Step 9 — Store Card

**File:** `src/components/StoreCard.tsx`

Props: `store: ScoredStore`, `rank: number`

### Visual layout:
┌─────────────────────────────────────────────────────────┐
│  [rank number]    [store name]           [score badge]  │
│      01           Glow Collective          91% match    │
│                   Brooklyn, NY                          │
│  ─────────────────────────────────────────────────────  │
│  [why this store?]                                      │
│  "Minimalist packaging aligns with their clean beauty   │
│   curation. They carry 4 indie skincare brands in your  │
│   price range."                                         │
│                                          [HIGH badge]   │
└─────────────────────────────────────────────────────────┘

### Rank number:
- Large, Playfair Display, 48px, color `#E8E4DF` (very light — background decoration)
- Positioned top-left, slightly overlapping card edge

### Store name:
- Inter 18px, font-weight 500, text-primary
- City, State below: Inter 13px, text-secondary

### Score badge:
- Pill shape (border-radius 999px)
- Background: sage-light `#E8F0E9`
- Text: `91% match` — sage-dark `#4A6B50`, font-weight 600, 14px
- Score = `Math.round(store.final_score * 10)` as percentage

### "Why this store?" section:
- Label: `WHY THIS STORE?` — 11px, uppercase, letter-spacing 0.08em, text-secondary
- Text: `store.why_matched` — Inter 15px, text-secondary, line-height 1.6
- Subtle left border: 2px solid sage-light `#E8F0E9`
- Left padding: 12px

### Priority badge (bottom right):
- HIGH → background rose-light, text rose `#C4897A`
- MEDIUM → background sage-light, text sage-dark
- LOW → background `#F5F5F5`, text text-secondary
- All: pill shape, 11px uppercase, font-weight 500

### Card container:
- Background: white
- Border: 1px solid `#E8E4DF`
- Border radius: 12px
- Padding: 24px
- Box shadow: `0 1px 3px rgba(0,0,0,0.06)`
- On hover: box shadow `0 4px 16px rgba(0,0,0,0.08)`, border-color sage-light
- Transition: 200ms all

### Entry animation:
- Cards animate in one at a time with a 100ms stagger
- Each card: `opacity 0 → 1`, `translateY 12px → 0`, duration 400ms
- Use CSS classes + `animation-delay` based on rank index

---

## Step 10 — Teaser Blur Section

**File:** `src/components/TeaserBlur.tsx`

Shown below the 5 real cards. Teases that 45 more stores exist.

### Layout:
[3 fake blurred cards stacked with decreasing opacity]
Card outline visible but content is blurred (filter: blur(6px))
Each card slightly smaller/more transparent than the one above
[overlay text centered over the blur]
+{report.total_stores_found - 5} more boutiques in your report
[lock icon — simple SVG]
Unlock your full report to see every match,
complete contact details, and draft outreach emails.

### Implementation:
- Real `StoreCard` components with fake prop data (same shape, different content)
- Wrapper div with `filter: blur(6px)` + `pointer-events: none` + `user-select: none`
- Overlay div positioned absolute, centered — uses a white-to-transparent gradient at top
- The 3 fake cards have decreasing opacity: 0.7, 0.5, 0.3
- Container: `position: relative`, `overflow: hidden`

### Fake card data (use these — they look realistic):
```typescript
const TEASER_STORES = [
  { name: '████████ Studio', city: '██████', score: 88 },
  { name: '████████ & Co.',  city: '██████', score: 84 },
  { name: 'The ████████',   city: '██████', score: 81 },
]
```
Use `████` blocks (U+2588 repeated) instead of blur on text — looks more intentional.

---

## Step 11 — CTA Banner

**File:** `src/components/CTABanner.tsx`

Shown below the teaser section. This is the conversion moment.

### Layout:
┌─────────────────────────────────────────────────────────┐
│                                                         │
│  Want us to pitch all {total} boutiques for you?       │
│                                                         │
│  Our team will send hyper-personalized outreach to      │
│  every matched store — and handle the negotiations.     │
│                                                         │
│  [  Book a Free Strategy Call  →  ]                    │
│                                                         │
│  ✦ Done-for-you · No templates · Real relationships    │
│                                                         │
└─────────────────────────────────────────────────────────┘

### Container:
- Background: sage `#7C9A82` (full width, edge to edge within content column)
- Border radius: 16px
- Padding: 48px
- Text: white throughout

### Headline:
- Playfair Display, 32px, font-weight 400, white
- Dynamic: `Want us to pitch all {report.total_stores_found} boutiques for you?`

### Body text:
- Inter 16px, `rgba(255,255,255,0.85)`, line-height 1.6

### Button:
- Background: white
- Text: sage-dark `#4A6B50`, Inter 16px, font-weight 600
- Height: 52px, border-radius: 4px, padding: 0 32px
- On hover: background `#F5F5F5`
- `href`: `process.env.NEXT_PUBLIC_CALENDLY_URL`
- Opens in new tab: `target="_blank" rel="noopener noreferrer"`

### Trust line below button:
- `✦ Done-for-you · No templates · Real relationships`
- Inter 13px, `rgba(255,255,255,0.7)`, centered

---

## Step 12 — Error States

Handle these gracefully — never show a raw error to the user.

| Error condition | What to show |
|---|---|
| Invalid URL format | Inline below input: "Please enter a full URL starting with https://" |
| URL not a Shopify/Etsy store | "We couldn't recognize this as a Shopify or Etsy store. Try your full store URL." |
| Backend timeout (> 90s) | "This is taking longer than usual. Try again in a moment." + Reset button |
| Generic API error | "Something went wrong on our end. Please try again." + Reset button |
| Zero stores found | "We couldn't find matching boutiques for this location. Try a larger city." |

All errors: rose accent `#C4897A` for the icon/border, never red, never alarming.

---

## Step 13 — Responsive Behaviour

This is a single-column, centered layout — naturally responsive.

| Breakpoint | Changes |
|---|---|
| Mobile (< 640px) | Hero heading: 36px. Cards: padding 16px. CTA banner: padding 28px. |
| Tablet (640–1024px) | Hero heading: 44px. Full design as specified. |
| Desktop (> 1024px) | Max content width: 720px centered. Same as tablet. |

No horizontal scrolling at any size.

---

## Step 14 — Environment Variables

**File:** `.env.local`
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_CALENDLY_URL=https://calendly.com/your-link-here

---

## Step 15 — Deployment Config

**File:** `vercel.json` (in frontend/ root)

```json
{
  "rewrites": [
    {
      "source": "/api/:path*",
      "destination": "http://your-railway-url.railway.app/api/:path*"
    }
  ]
}
```

This proxies API calls through Vercel — avoids CORS issues in production.

---

## Verification

1. `npm run build` — zero TypeScript errors, zero build warnings
2. `npm run dev` — page loads at localhost:3000 with no console errors
3. Visual check — hero section, Playfair Display font loading, sage/rose colors correct
4. Form validation — submitting empty field shows inline error, no API call made
5. Loading state — mock the API to return `progress: 50`, confirm progress bar and message display correctly
6. Results — mock `ReportResponse` with 5 stores, confirm all 5 cards render with correct score percentage
7. Teaser — confirm blur cards appear below, block characters visible, not actual blur
8. CTA — Calendly link opens in new tab
9. Error state — mock API 500, confirm user-friendly message shown, reset button works
10. Mobile — open Chrome DevTools → iPhone 12 Pro, confirm heading wraps correctly, no overflow

---

## Implementation Checklist

### Step 0 — Setup
- [ ] `create-next-app` run with TypeScript + Tailwind + App Router flags
- [ ] `tailwind.config.ts` extended with all custom colors and font families
- [ ] `globals.css` has Google Fonts import, CSS variables, base resets
- [ ] `.env.local` created with both variables
- [ ] `npm run dev` starts without errors

### Step 1 — Types + API Client
- [ ] `src/lib/types.ts` — all 6 interfaces defined with correct field names matching backend
- [ ] `src/lib/api.ts` — all 3 functions implemented with typed errors
- [ ] API base URL reads from `NEXT_PUBLIC_API_URL` env variable

### Step 2 — Discovery Hook
- [ ] `useDiscovery.ts` — all 6 return values implemented
- [ ] Polling starts on `startDiscovery()` call, stops on complete or error
- [ ] `clearInterval` called on component unmount (no memory leaks)
- [ ] All 8 progress messages mapped to correct progress thresholds
- [ ] `reset()` returns all state to initial values

### Step 3 — Hero Section
- [ ] `HeroSection.tsx` renders headline in Playfair Display
- [ ] Top label with sage color and letter-spacing correct
- [ ] URL input — 56px height, sage focus ring, correct placeholder
- [ ] Location input — rendered below URL input, marked optional
- [ ] Submit button — sage background, disabled during loading
- [ ] Inline validation — error shown for non-http URLs without API call
- [ ] Trust line below button present

### Step 4 — Loading State
- [ ] `LoadingState.tsx` replaces form while `status === 'loading'`
- [ ] Rotating ring animation works (CSS only)
- [ ] Progress bar updates width based on `progress` value
- [ ] Progress message fades between steps
- [ ] Location shown in sub-text if provided

### Step 5 — Store Card
- [ ] `StoreCard.tsx` renders rank number in large Playfair Display
- [ ] Score shown as percentage (`Math.round(score * 10)`)
- [ ] `why_matched` text with left sage border
- [ ] Priority badge correct colors for HIGH/MEDIUM/LOW
- [ ] Hover state: elevated shadow, border color change
- [ ] Entry animation with stagger delay

### Step 6 — Results Section
- [ ] `ResultsSection.tsx` renders exactly 5 `StoreCard` components (stores[0..4])
- [ ] Header shows `brand_name` and `total_stores_found`
- [ ] Stores passed in correct order (already sorted by score from backend)

### Step 7 — Teaser Blur
- [ ] `TeaserBlur.tsx` renders 3 fake cards below real results
- [ ] Block character text (████) used instead of CSS blur on text
- [ ] Overlay shows correct count: `total_stores_found - 5`
- [ ] `pointer-events: none` on blur container
- [ ] Decreasing opacity on the 3 teaser cards

### Step 8 — CTA Banner
- [ ] `CTABanner.tsx` — sage background, white text
- [ ] Headline is dynamic with `total_stores_found`
- [ ] Calendly button opens in new tab
- [ ] Trust line below button present
- [ ] `NEXT_PUBLIC_CALENDLY_URL` read from env

### Step 9 — Error States
- [ ] All 5 error conditions handled with user-friendly messages
- [ ] Rose accent color used (not red) for error styling
- [ ] Reset button shown on timeout and generic errors
- [ ] No raw error messages or stack traces ever shown to user

### Step 10 — Responsive
- [ ] Mobile (375px): heading 36px, no horizontal scroll, cards readable
- [ ] Desktop (1280px): content max-width 720px centered
- [ ] No layout breaks between 375px and 1440px

### Final Verification
- [ ] `npm run build` — zero errors
- [ ] All 10 manual checks from Verification section pass
- [ ] Page loads in < 2 seconds on localhost
- [ ] Fonts (Playfair Display + Inter) loading from Google Fonts correctly
- [ ] Colors match design system exactly (no default Tailwind blues anywhere)