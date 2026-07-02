# KnowTwin — Design System
*Offboarding knowledge-capture UI · Apple Liquid Glass × Teenage Engineering · midnight + ivory, surgical orange, color-coded signal*

Source of truth for the KnowTwin visual language. KnowTwin is a **fork of EcoDB** and inherits its design language **verbatim** — same tokens, same primitives, same motion, same depth model. This doc documents that shared system and adds the **KnowTwin domain layer** (§7): claim states, coverage states, dispute states, and role-based sections that replace EcoDB's memory/entity semantics.

Design authority: **Lienzo** (Design Lead). Parent system: `C:\Users\Admin\Documents\EcoDB\design_system\design.md`. When this doc is silent, the EcoDB `design.md` governs.

**Primary theme is LIGHT** (ivory + bright white frosted glass). Dark (midnight) is fully supported via the theme toggle but is the secondary mode.

---

## 0 · Golden rule

KnowTwin **looks like EcoDB**. Do not invent a second visual language. Every color, radius, shadow, font, and motion curve comes from the shared token set (§2). What changes between the two products is **content and domain semantics** (§7), never the chrome. If a KnowTwin screen and an EcoDB screen sit side by side, they read as the same product family.

---

## 1 · Principles (inherited from EcoDB, verbatim)

1. **Three depth layers, always.** Backdrop (content for glass to refract) → liquid-glass *tray* → floating frosted *cards*. Cards are **raised** (elevation shadow + bright top edge), **never sunken/inset**. The single exception is a dark recessed screen (e.g. a graph/transcript viewport). This depth hierarchy is the core of the look.
2. **Two temperatures — LIGHT is primary.** Light = clean **ivory + bright white frosted glass** (a Braun product in morning light). Dark = **midnight blue-black** with cool slate glass (Mission Control at night) — *not* brown, *not* blue-cold-gray.
3. **Surgical orange (`#F5631E`) for signal; terracotta for action.** Orange marks *only* live/active/critical signal: status dots, the active session, chart "now" markers, the **on** toggle, section accent lights. The **primary button** is a warmer **terracotta** gradient (§3) so CTAs feel grounded, not neon. Never decorative.
   - **WCAG floor (norm):** signal colors `--accent` (#F5631E), `--red` (#DE4630), `--grn`, and any low-lightness section/state hue carry L≈0.19–0.28 and *cannot* reach 4.5:1 on a light surface. A low-L color is only ever **dot / glow / border / background-tint**, never the **fill color of small text (<18px) in light mode**. To convey a claim/coverage/dispute state in text: colored dot + `--ink-1/ink-2` text, not colored text. This norm is load-bearing for KnowTwin because the app is dense with state (§7).
4. **Color-coded signal as identity.** Beyond orange, domain states (claim level, coverage state, dispute state, source kind) carry a quiet, consistent accent (§7). Applied as small touches — a badge dot, a row dot, a drawer kicker — never as fills or panels.
5. **Monochrome data, restrained chrome.** Numbers, scores, and charts are graphite (light) / cool ivory (dark). Instrument feel comes from precision, tabular numerals, and spacing — not color.
6. **Real dashboard primitives only.** Tables, lists, drawers, badges, segmented controls, toggles, indicator dots, coverage meters, chat surfaces, command palette. **No gauges/dials. No skeuomorphic buttons.**
7. **Quiet motion.** Values tick, the coverage bar settles, the active session blinks, drawers slide. Nothing bounces.

---

## 2 · Tokens (shared with EcoDB — ported verbatim to `src/styles/tokens.css`)

CSS custom properties scoped to `[data-theme="light"]` / `[data-theme="dark"]`. Never hardcode — reference the var. The full token file is copied from `EcoDB/dashboard/src/styles/tokens.css`; only the §2.8 signal names are re-pointed to KnowTwin's domain (§7).

### 2.1 Brand / semantic (theme-independent)
```
--accent:   #F5631E   /* primary signal orange */
--accent-2: #FF8A4C   /* lighter orange (hover) */
--grn:      #4E9E6A   /* positive / ok / clear */
--red:      #DE4630   /* alert / negative / unknown */
```

### 2.2 Type
```
--font-mono: 'DM Mono'         → labels, tags, ALL numbers/scores/data (tabular-nums), chrome
--font-body: 'Hanken Grotesk'  → titles, questions, evidence text, body, button labels
```
- `font-variant-numeric: tabular-nums` on every number (scores, counts, doc_strength), always.
- Section titles: 11px / `letter-spacing:.14em` / uppercase / 600 / `--ink-2`.
- Score value 32px mono 500 · badge/meta 9.5–11px mono.

### 2.3 Ink (text on glass) — tuned for contrast (do not regress)
| Token | Light | Dark | Use |
|---|---|---|---|
| `--ink-1` | `#1f1d1a` | `#eef1f7` | primary text / evidence / scores |
| `--ink-2` | `#5e584f` | `#b6bdca` | titles, secondary, small captions |
| `--ink-3` | `#625c52` | `#868e9c` | labels, meta, ticks (min for small grey text) |
| `--ink-4` | `#a9a397` | `#4a505c` | idle / disabled |

> Small grey mono text uses `--ink-2` for captions, never lighter than `--ink-3`. WCAG AA floor already tuned in the EcoDB source — don't regress it.

### 2.4 Backdrop, 2.5 Liquid glass, 2.6 Geometry, 2.7 charts
Identical to EcoDB `design.md` §2.4–2.7. Non-flat refracting backdrop (warm/cool radial blobs + soft-light grain), tray/card glass with cursor-tracked specular, radii (`--r-xl 26 / --r-lg 20 / --r-md 13 / --r-sm 8 / --r-btn 11`), grid gap 16, card padding 16–18, tray padding 22. See `tokens.css`.

### 2.8 Color-coded signal — re-pointed to KnowTwin domain
The EcoDB `--kind-*` / `--type-*` / `--sec-*` vars are **kept as the palette** but re-mapped to KnowTwin meanings in §7. The hues themselves do not change (blue `#6e9ecf`, amber `#c4a86a`, violet, teal, green, red, orange) — only what they *signify*.

---

## 3 · Component kit (port from EcoDB, adapt labels only)

All ship isolated, all states, light+dark. Port from EcoDB's kit; KnowTwin adds no new primitive shapes, only new *badge vocabularies* (§7).

### Primitives (port verbatim)
- **GlassCard** — `variant: default|compact|flush`, `accent?: <hue>`, `state: rest|hover|loading|empty|error`, `head{title, tag|control}`. The container everything sits in. Loading = shimmer skeleton; empty/error = quiet centered message.
- **Dot** — `s: on(orange)|ok(green)|alert(red)|idle` + domain-state variants (§7); `anim: pulse|blink|none`.
- **Chip** — mono micro-label; `tone?: hot`.
- **Button** — `variant: default | primary | tint | danger`, plus `loading|disabled|pressed`. **default** = frosted glass + hairline. **primary** = terracotta gradient (`#D5704A→#C45D38→#B6502F`) + top specular — the CTA (Approve, Resolve, Start session). **tint** = orange-tinted glass. **danger** = muted red tint (Reject, Delete) — *not* a bright fill.
- **Toggle** — `on:boolean`. Orange gradient track ON, neutral recessed well OFF.
- **SegmentedControl** — `options:string[]`, `value`. e.g. claim filter `All / Pending / Draft / Disputed`.
- **ThemeToggle** — recessed flat button, sun (dark) / moon (light).
- **Drawer** — right-side glass panel; `kind` sets a kicker + dot + 7% hue wash. KnowTwin uses it for **audit trail** and **dispute detail**. Closes on ✕ / scrim / Esc.
- **ConfirmDialog** — glass modal for destructive/privileged actions (reject, delete, resolve, force approve). Optional note input.

### Data / surface
- **Badge family** (§7) — the KnowTwin-specific layer: `CorroborationBadge`, `DisputeBadge`, `CoverageStateBadge`, `TrustTierBadge`, `SensitivityBadge`. All = dot + ink label (never colored text fill), mono.
- **ClaimRow** — `subject.predicate` + evidence (via `SafeText`) + badges + row actions (approve, audit icon, select checkbox). The workhorse of the Setup view.
- **CoverageMeter** — entity coverage %, color-coded state (§7), denominator shown. Monochrome bar + state dot.
- **ScoreChip** — 0–100 mono value + label, tooltip breakdown. Graphite, never colored fill.
- **SourceCitation** — Twin source: kind dot + type + date + trust-tier badge + confidence, clickable to evidence.

### Chrome
- **NavRail / TopBar** — glass tray. Per-section color legend (§7.5). Brand mark + wordmark, StatusPill (API health), clock, ThemeToggle.

---

## 4 · Security-visual invariants (NON-NEGOTIABLE — from FRONTEND_HANDOFF)

These are design constraints, not just code rules — they shape the components:
- **Zero `dangerouslySetInnerHTML`.** `react/no-danger=error`.
- **ALL** claim / evidence / transcript / `why_resolved` / resolution-note text renders through the **`SafeText`** component. Every badge and row that shows user/agent content wraps it.
- **API key lives in the Electron main process only** (secure-store, `safeStorage`/DPAPI, encrypted on disk). It is **never** exposed to the renderer, never in the DOM, never logged. The renderer talks to the API only through the `window.knowtwin` IPC bridge (fetch/sse), which attaches the `Bearer` header in main. This replaces the old sessionStorage rule from the Phase-1 handoff — that rule was written for a browser SPA; as an Electron app (like EcoDB) secure-store is strictly stronger. `adv-seg` verifies the port.
- Frontend is **not** a security boundary. Role-based show/hide is UX only; the server enforces. Never imply in the UI that hiding a button = access control.

---

## 5 · Brand mark

KnowTwin is part of Pepe's portfolio / a client (Manu) product — **no "Eco Consulting" text**. Nav shows the shared square-outline mark (three bars, **middle bar signal-orange**, outer two `currentColor`) next to the **KnowTwin** wordmark. Bare, no chip.

---

## 6 · Motion & responsive (inherited)
- Quiet motion only: coverage bar settles, active session dot blinks, drawer slides, values tick. No bounce/elastic. Ease-out curves. `prefers-reduced-motion` stops ambient motion.
- Desktop-first (curator workstation). Responsive grid added at build: ≥1280 multi-panel · 768–1280 two-col · <768 single + drawer→sheet.
- A11y: focus rings, aria on toggle/drawer/dialog/segmented, keyboard nav, `check-contrast` PASS before delivery.

---

## 7 · KnowTwin domain layer (THE difference from EcoDB)

Where EcoDB signals *memory types* and *entity kinds*, KnowTwin signals **claim epistemics**. All of the following render as **dot + `--ink-1/2` label**, mono, per the §1.3 WCAG norm — never as colored text fill or panel.

### 7.1 Corroboration level (claim lifecycle) — `CorroborationBadge`
The trust ladder. Dot color climbs from grey (unshipped) to green (validated):
```
draft                     → --ink-4 grey   (not embedded, not shown to Twin)
single_source             → #6e9ecf blue   (one source, embedded)
corroborated              → #4fa0a0 teal   (multiple documentary sources)
corroborated_by_employee  → #c4a86a amber  (employee confirmed in interview)
validated                 → --grn green    (human-approved, top of ladder)
rejected                  → --red red      (soft-deleted, embedding removed)
```

### 7.2 Coverage state (entity knowledge completeness) — `CoverageStateBadge` / `CoverageMeter`
From Spec §5.2, reconciled onto the shared palette. Six states:
```
unknown    → --red red        (0 confirmed claims — a gap)
partial    → #c98a3c amber     (some coverage, below threshold)
clear      → --grn green       (≥50% criticality-weighted coverage)
disputed   → --accent orange   (has an open dispute — signal color, it demands attention)
validated  → #6e9ecf blue      (has a human-validated claim)
stale      → --ink-3 grey       (evidence past freshness window)
```
`CoverageMeter` = monochrome graphite bar (fill = `--chart-bar`) + state dot + `coverage_pct` (mono) + denominator caption ("X of Y expected areas").

### 7.3 Dispute state — `DisputeBadge`
```
undisputed         → no badge (default, don't add noise)
disputed           → --accent orange dot + "Disputed"     (open, needs a resolver)
resolved_in_favor  → --grn green dot + "Resolved (for)"
resolved_against   → --ink-3 grey dot + "Resolved (against)"
```
Disputed claims in the Twin **always show both versions** (never silently pick). `doc_strength` shown as a mono breakdown: `source_count × freshness × (tier+1)`. `why_resolved` is deterministic text → render as-is via `SafeText`, never framed as LLM output.

### 7.4 Trust tier & sensitivity — `TrustTierBadge`, `SensitivityBadge`
```
trust_tier:  0 inferred → --ink-4 · 1 documentary → #6e9ecf blue · 2 formal/recent → --grn green
sensitivity: public → --grn green · team → #c4a86a amber · restricted → --red red
```
Interview claims default to **restricted** — the badge makes that visible so nothing tacit leaks by omission.

### 7.5 Per-section color (nav legend) — role-based
Reusing EcoDB's `--sec-*` hues, re-pointed to KnowTwin's 7 sections:
```
dashboard  #F5631E orange   (HOME — Command Center, the operative hub, gets the brand hue)
setup      #D98C4A amber    (curation workflow — was orange, moved to amber when Dashboard took brand hue)
interview  #5C8FC9 blue     (employee conversation)
twin       #4E9E6A green    (consumer query — the payoff, "clear" green)
graph      #4FA0A0 teal     (knowledge visualization — force-graph, entity exploration)
ontology   #8E78BC violet   (entity/predicate management — alias, merge, CRUD)
settings   #8A8F9C slate
```
Each nav item + active state carries its hue as LED dot + left bar + icon. The nav reads as a color legend of who-does-what. Manager view (#D98C4A) is DEFERRED — not in nav until client signal.

### 7.6 Role framing (copy-level, from Brief)
- The Manager/scoring surfaces use **process framing**, never person-evaluation: "Knowledge capture completeness", not "employee ranking". The `ScoreChip` tooltip explains its components (coverage_contrib, contradiction_yield, quality, gaming_penalty) as *process signals*.
- Employees see **only their own** claims and score. The UI never exposes another employee's data to an employee, and the design must not imply it could.

---

## 8 · Build notes (Phase 3 engineering — this build)
- **Stack = EcoDB's, full stop (Pepe, 2026-07-02): FULL ELECTRON DESKTOP APP, not a browser SPA.** React 18 + Vite 6 + Tailwind 3.4 + TanStack Query + react-router 6 **+ Electron** (main + preload + secure-store + electron-builder NSIS). Ported from `EcoDB/dashboard`. The frontend stops being a Docker service and becomes a desktop client that talks to the KnowTwin API at `http://localhost:8090`. If any line of this doc implies a browser-only SPA, this line overrides it.
- **Electron scaffold port (from `EcoDB/dashboard`):** `src/main.ts` (BrowserWindow, IPC bridge, CSP, permission-deny, SSRF guard, upload-via-main), `src/preload.ts` (`window.knowtwin` contextBridge — key never crosses), `src/secure-store.ts` (`safeStorage`/DPAPI + electron-store, encrypted key at rest), `src/config-store.ts` (API base URL, default `http://localhost:8090`), `src/lib/api-url.ts` (SSRF resolve), `vite.config.ts` (`vite-plugin-electron/simple`), `electron-builder.yml` + `package.json` build block (NSIS, `productName: KnowTwin`, `appId: com.knowtwin.app`), `tsconfig.electron.json`. Rename every `ecodb:` IPC channel → `knowtwin:` and `window.ecodb` → `window.knowtwin`. `app.setName('knowtwin')` before any electron-store.
- **Data-layer rewire:** the renderer's `lib/api.ts` (currently direct `fetch` + Bearer from sessionStorage) is rewired to call `window.knowtwin.fetch(path, opts)` — the bridge owns auth. `lib/auth.ts` → `hasApiKey/setApiKey/clearApiKey` over the bridge (auth screen on first run to enter the key). **WebSocket (interview real-time, Spec §4.2):** open coordination point with Hilo/adv-seg — either proxy WS through main (key stays in main) or allow the renderer to open `ws://localhost:8090/...?key=` with CSP `connect-src` permitting it. Decide before building the Interview view.
- **Foundation port order:** (1) visual: `tokens.css` (§2.8→§7) · `tailwind.config.ts` (§7.5) · `index.css` glass base · `index.html` fonts + `data-theme="light"` — (2) Electron scaffold (above) + auth screen — (3) data-layer rewire — (4) app shell (NavRail + TopBar) — (5) component kit — (6) view retrofit + Phase 2 features.
- **Fonts:** DM Mono + Hanken Grotesk via `@fontsource/dm-mono` + `@fontsource/hanken-grotesk` (self-hosted, same as EcoDB — the prod CSP has no `font-src`, so fonts must be same-origin files, `assetsInlineLimit: 0`).
- **Retrofit scope (Pepe, carta blanca 2026-07-02):** make KnowTwin's frontend *equivalent* to EcoDB's — full Electron app, full adoption across the existing 4 views, plus the 6 Phase 2 features on the same system.
- Keep the deliberate corrections: **light is primary**, **dark = midnight not brown**, **ink contrast** (§2.3), **terracotta CTA vs signal-orange** (§3), **color-by-meaning via dot+ink, never colored text** (§1.3 / §7).

---

*Built on the EcoDB design system (Lienzo, Design Lead). KnowTwin inherits the visual language; the domain layer §7 is what makes it KnowTwin. Backend Phase 2 complete (Hilo's team). This build = Phase 3 frontend, workflow-frontend v1.*
