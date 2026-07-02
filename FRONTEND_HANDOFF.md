# KnowTwin Frontend Handoff — Phase 2

> For Lienzo. Backend Phase 2 complete (184 tests green). All endpoints live at :8090.

## Stack

React 18 + Vite + Tailwind + shadcn/ui + TypeScript + TanStack Query.
Source: `frontend/src/`. Dev: `npm run dev` → :3001. Build: `npm run build`.

## Existing views (Phase 1)

| Route | View | Role | Files |
|-------|------|------|-------|
| `/setup` | Setup/Curation | curator/admin | `views/SetupCuration/` (7 panels) |
| `/interview` | Interview | employee | `views/InterviewView/` (6 components) |
| `/twin` | Twin Query | consumer | `views/TwinView/` (5 components) |
| Settings drawer | Settings | admin | `components/SettingsDrawer.tsx` (4 sections) |

## Existing shared components

- `SafeText` — XSS-safe text render (ALL claim/evidence output MUST use this)
- `StateBadge` — 6 corroboration states
- `CorroborationBadge` — corroboration level display
- `Loading`, `EmptyState`, `ErrorBoundary`, `ConfirmDialog`

## Existing hooks (TanStack Query)

`useClaims`, `useDocuments`, `useCoverage`, `useSettings`, `useProviders`, `useCellConfigs`, `useInterviews`, `useTwin`, `useExport`

## API client

`lib/api.ts` — `get<T>`, `post<T>`, `put<T>`, `del<T>`. Auth via Bearer token (sessionStorage).
Base URL: `http://localhost:8090`. Error handling: throws on non-200.

## Security rules (NON-NEGOTIABLE)

- `react/no-danger=error` in ESLint — zero `dangerouslySetInnerHTML`
- ALL claim/evidence/transcript text via `SafeText` component
- API key in sessionStorage (never localStorage, never DOM, never logs)
- Frontend is NOT a security boundary — every filter server-enforced
- CSV exports use `_csv_safe` server-side (formula injection protection)

---

## Phase 2 — What needs frontend work

### 1. EXTEND: Setup/Curation view (`views/SetupCuration/`)

#### 1a. CurationInbox — batch operations (P2.9)
New endpoint: `PUT /claims/batch`
```
Body: { ids: UUID[], action: "approve"|"reject"|"set_sensitivity", value?: string }
Response: { succeeded: [{id, new_state}], failed: [{id, error}] }
```
- Add multiselect checkboxes to claim rows
- Batch action bar (approve/reject/set_sensitivity) appears when selection > 0
- Partial failure: show succeeded count + failed items with errors
- Invalidate claims query after batch

#### 1b. CurationInbox — force approve (D-P1.19-1)
Existing endpoint: `PUT /claims/{id}/promote`
```
Body: { new_level: "validated", force: true }
```
- "Approve" button for curator/admin sends `force: true`
- Respects CAP (interview claims max = corroborated_by_employee) — show error if CAP blocks

#### 1c. Audit trail drawer (P2.9)
New endpoint: `GET /claims/{id}/audit`
```
Response: [{ id, user_id, action, details: {}, created_at }]
```
- Clickable icon on each claim row → opens drawer/modal with timeline
- Ordered ASC (oldest first)

#### 1d. DisputeQueue — resolution workflow (P2.6)
New endpoints:
```
GET  /claims/disputes?project_id=N         → { disputes: [{claim, counterpart}], total }
PUT  /claims/{id}/resolve                  → { resolution: "in_favor"|"against", resolution_note: string }
PUT  /claims/{id}/assign-resolver          → { resolver_user_id: int }
GET  /claims/{id}/dispute-detail           → { claim, counterpart, why_resolved }
```
- Resolve action: ConfirmDialog → note input → PUT resolve
- Resolver assignment: dropdown of project members
- Both sides update on resolve (counterpart gets inverse state)
- `why_resolved` is deterministic text — display as-is via SafeText

### 2. EXTEND: Interview view (`views/InterviewView/`)

#### 2a. Score chip (P2.1)
New endpoint: `GET /projects/{pid}/employees/{eid}/score`
```
Response: { employee_id, score: float, components: { coverage_contrib, contradiction_yield, quality, gaming_penalty }, claim_count }
```
- Small chip/badge showing score (0-100) in the interview header
- Employee sees own score only
- Tooltip with component breakdown

#### 2b. Deletion request (P2.11)
New endpoint: `POST /my-claims/{cid}/request-deletion`
```
Body: { reason?: string }
Response: { id, claim_id, status: "pending" }
```
- ClaimSidebar: "Request deletion" button per claim (employee-own only)
- ConfirmDialog with optional reason

#### 2c. Style indicator (P2.8)
The `/respond` endpoint now returns `style_directive` in the response:
```
{ ..., style_directive: { framing, follow_up_style, length_guidance } }
```
- Optional: show current style mode (technical/relational/adaptive) as a subtle indicator

### 3. EXTEND: Twin view (`views/TwinView/`)

#### 3a. Enhanced disputes (P2.6)
Twin query response now includes dispute groups with:
```
disputes: [{ versions: [{claim_id, evidence_text, doc_strength_breakdown, ...}], why_resolved }]
```
- `DisputePanel.tsx` already exists — extend to show `doc_strength_breakdown` (source_count, freshness, tier)
- Show `why_resolved` text (deterministic, never LLM)
- Both versions always visible for disputed claims

### 4. EXTEND: Settings drawer

#### 4a. Retention policy (P2.11)
Endpoint: `PUT /projects/{pid}/settings`
```
Body: { retention: { retention_days: int|null, auto_expiry: bool } }
```
- `RetentionPolicy.tsx` already exists — wire to real endpoint if not already
- Admin-only toggle + days input

#### 4b. Deletion requests management (P2.11 — curator/admin)
New endpoint: `GET /claims/deletion-requests?project_id=N`
```
Response: [{ id, claim_id, requested_by, reason, status, created_at }]
```
New endpoint: `PUT /claims/deletion-requests/{id}/review`
```
Body: { decision: "approve"|"reject", note?: string }
```
- New section in Settings or separate panel in Setup view
- List pending requests → approve/reject with note

### 5. NEW: Manager view (P2.10 — deferred, only with real client signal)

New route: `/manager`
New endpoints:
```
GET /projects/{pid}/scores               → [{ employee_id, score, components, claim_count }]
GET /projects/{pid}/risks?horizon_days=N  → (future — P2.3 not built yet)
```
- Score overview for all employees (table/chart)
- Process-not-person framing: "Knowledge capture completeness"
- Manager/admin role gate (client-side UX only — server enforces)

---

## New hooks needed

```typescript
// hooks/useDisputes.ts
useDisputes(projectId) → GET /claims/disputes
useMutateResolve(claimId) → PUT /claims/{id}/resolve
useMutateAssignResolver(claimId) → PUT /claims/{id}/assign-resolver

// hooks/useScoring.ts
useScore(projectId, employeeId) → GET /projects/{pid}/employees/{eid}/score
useAllScores(projectId) → GET /projects/{pid}/scores

// hooks/useDeletions.ts
useRequestDeletion(claimId) → POST /my-claims/{cid}/request-deletion
useDeletionRequests(projectId) → GET /claims/deletion-requests
useReviewDeletion(requestId) → PUT /claims/deletion-requests/{id}/review

// hooks/useBatch.ts
useBatchClaims() → PUT /claims/batch

// hooks/useAudit.ts
useClaimAudit(claimId) → GET /claims/{id}/audit
```

## OpenAPI

Full endpoint docs live at `http://localhost:8090/docs` (Swagger UI).

---

## User journeys (per role)

### Curator/Admin journey (Setup view — primary workspace)

```
1. CREATE PROCESS
   → ProcessSetupForm: enter employee name, role, tenure, area, accounts, exit date
   → POST /projects (composite) → project + employee user + project_members

2. UPLOAD DOCUMENTS
   → DocumentUpload: drag-drop files with trust_hint selector (contract/wiki/orgchart/email)
   → POST /documents/upload → poll GET /documents until status='indexed'
   → Run Curator: POST /projects/{id}/curator/run → wait for extraction

3. REVIEW CLAIMS (daily workflow — most time spent here)
   → CurationInbox: see all extracted claims, filter by level/entity/dispute
   → Single approve: click claim → PUT /claims/{id}/promote {new_level, force: true}
   → Batch approve: select 10-50 claims → PUT /claims/batch {ids, action: "approve"}
   → Reject: select → PUT /claims/batch {ids, action: "reject"} → ConfirmDialog
   → Change sensitivity: select → PUT /claims/batch {ids, action: "set_sensitivity", value: "public"}
   → View audit: click audit icon → GET /claims/{id}/audit → timeline drawer

4. RESOLVE DISPUTES
   → DisputeQueue: see disputed claims ordered by doc_strength
   → Click dispute → both versions side-by-side + doc_strength breakdown
   → Resolve: PUT /claims/{id}/resolve {resolution: "in_favor"|"against", note}
   → Assign resolver: PUT /claims/{id}/assign-resolver {resolver_user_id}

5. REVIEW DELETION REQUESTS
   → Settings or dedicated panel: GET /claims/deletion-requests?project_id=N
   → Approve: PUT /claims/deletion-requests/{id}/review {decision: "approve"} → GDPR erasure
   → Reject: {decision: "reject", note} → claim unchanged

6. CONFIGURE
   → AgentConfigPanel: swap LLM model/provider per agent (PUT /cells/configs)
   → SettingsDrawer: sanitization defaults, retention policy, STT, export

7. MONITOR
   → CoverageDashboard: entity coverage % with color-coded states
   → Scoring: GET /projects/{pid}/scores → all employees' contribution scores
```

### Employee journey (Interview view)

```
1. START SESSION
   → InterviewPage: see session history + "Start new session" button
   → POST /interviews {project_id, topic, comm_style?} → POST /{session_id}/start
   → Coverage bar shows current % (WebSocket updates live)

2. INTERVIEW (core loop)
   → ChatInterface: type response to interviewer's questions
   → POST /{session_id}/respond {text} → returns claims_this_turn + coverage + style_directive
   → VoiceRecorder: optional voice → POST /{session_id}/voice → same flow
   → ClaimSidebar: see claims extracted this session with badges (new/confirms/contradicts)
   → TopicIndicator: shows current topic + convergence status

3. MANAGE OWN CLAIMS
   → ClaimSidebar: request deletion of own claim → POST /my-claims/{cid}/request-deletion
   → See own score chip: GET /projects/{pid}/employees/{eid}/score → score + breakdown

4. END SESSION
   → POST /{session_id}/close → rollup generated → curator_post fires → dossier regenerated
   → SessionHistory: see completed sessions with summaries
```

### Consumer journey (Twin view)

```
1. ASK THE TWIN
   → TwinChat: type question about the departing employee's knowledge
   → POST /twin/query {question, project_id} → answer + sources + disputes

2. REVIEW SOURCES
   → SourcePanel: click citation [1] → see evidence_text, source type, date, trust tier, confidence
   → Disputed sources show both versions + doc_strength + why_resolved

3. CALIBRATE TRUST
   → CoverageOverview: see which entities have good coverage vs gaps
   → Helps consumer know where to trust the Twin vs where to verify independently

4. EXPORT
   → SettingsDrawer (if admin/curator): export claims as CSV/JSON, download verified base document
```

### Manager journey (future — P2.10, deferred)

```
1. OVERVIEW
   → /manager route: see all employee scores + coverage by account + risk alerts
   → Process framing: "Knowledge capture completeness" (not person evaluation)

2. REDISTRIBUTION (future)
   → Single-point-of-failure detection → suggest knowledge transfer targets
```

---

## Key interaction patterns

| Pattern | Implementation |
|---------|---------------|
| Multiselect + batch | Checkbox per row → floating batch bar → PUT /claims/batch |
| Optimistic update | TanStack Query mutation → optimistic update → rollback on 409/403 |
| Real-time coverage | WebSocket → CoverageBar animation → invalidate coverage query |
| Audit drawer | Click icon → slide-out panel → GET /claims/{id}/audit → timeline ASC |
| ConfirmDialog | Destructive actions (reject, delete, resolve) → ConfirmDialog with note input |
| Role-based visibility | Client-side: hide/show buttons by role. Server: enforces on every request |
| Error handling | 401→login, 403→toast, 409→transition error, 422→field validation |

---

## Priority order (recommended)

1. Batch operations + force approve (Setup view — most used curator flow)
2. Dispute resolution UI (Setup view — both-version + resolve)
3. Deletion workflow (Settings/Setup — GDPR compliance)
4. Audit trail (Setup view — accountability)
5. Score chip (Interview view — employee feedback)
6. Manager view (new route — deferred until client signal)
