# KnowTwin — User Guide

> For HR managers and team leads running knowledge transfer processes.

---

## Quick start — your first offboarding in 10 minutes

You just opened KnowTwin for the first time. Here's exactly what to do, step by step.

### 1. Enter your API key
The first screen asks for an API key. Your IT administrator gives you this. Paste it and click **Save**. You won't see this screen again.

### 2. You're on the Processes page
This is your home. It shows all active offboarding processes. Right now it's empty (or has a demo process).

### 3. Create your first process
Click **New Process** at the top. Fill in:
- **Employee name**: the person who is leaving (e.g., "Maria Lopez")
- **Role**: their job title (e.g., "Account Manager")
- **Department**: their team (e.g., "Sales")
- **Exit date**: their last day — pick from the calendar
- **Priority**: Routine / Urgent / Emergency

Click **Create process**. You're taken to the process detail page.

### 4. What you see now
A page with:
- A **progress bar** at the top (0% — you just started)
- A **stage indicator**: Getting started → Collecting documents → Analyzing documents → Knowledge transfer → Handoff ready
- **Next steps** cards telling you exactly what to do next
- **Metrics**: Documents (0), Knowledge items (0), Sessions (0), Completeness (0%)

### 5. Follow the next steps
The cards on the process page tell you what to do. Click each one:

**"Upload source documents"** → takes you to Setup → Documents. Drag files here (contracts, org charts, wikis). For each file, pick how much you trust it (contract = high, email = low).

**"Process documents"** → click this button in Setup → Documents. The AI reads everything and extracts knowledge. Wait 1-3 minutes. When done, you'll see how many findings it extracted.

**"Schedule knowledge transfer"** → takes you to Interviews. The system suggests topics based on what's MISSING from the documents. Click a topic → start a session → the employee answers questions.

**"Review contradictions"** → takes you to Decisions. If the documents say one thing and the employee says another, you decide which is correct.

### 6. Check progress
Go back to **Processes** (first item in the sidebar). Your process card now shows:
- A **traffic light**: 🟢 green (>80% complete, no contradictions) / 🟡 yellow (in progress) / 🔴 red (behind schedule or many contradictions)
- Days until the employee leaves
- What to do next

### 7. Ask the Knowledge Assistant
Click **Knowledge Assistant** in the sidebar. Select the employee from the dropdown. Ask anything:
- "Who manages the Banco Norte account?"
- "What happens when the ETL pipeline fails?"
- "What informal agreements exist with CloudBase?"

You get a natural language answer with citations. If something is disputed, it shows both versions.

### 8. You're done when
- Completeness is above 80%
- All contradictions are resolved (0 pending)
- The replacement team can get useful answers from the Knowledge Assistant

---

## What is KnowTwin?

KnowTwin captures undocumented knowledge from employees who are leaving your organization. It combines document analysis, AI-guided interviews, and a knowledge assistant to ensure critical expertise isn't lost.

**The problem:** When an experienced employee leaves, they take years of undocumented knowledge — informal agreements, workarounds, client relationships, decision context — that no wiki captures.

**The solution:** KnowTwin extracts this knowledge through structured interviews, cross-references it against existing documentation, detects contradictions, and makes it queryable by the replacement team.

---

## Getting started

### First time setup

1. Open the KnowTwin desktop app
2. Enter your API key (provided by your administrator)
3. You'll land on the **Processes** page — your command center

### Your API key

Your administrator generates API keys. Each key has a role:
- **Admin/Curator**: full access — create processes, upload documents, review findings, configure agents
- **Employee**: limited — participate in interviews, see own contributions
- **Consumer**: read-only — query the knowledge assistant, view the knowledge graph

---

## How to run an offboarding process

### Step 1: Create a new process

**Where:** Processes → **New Process** button

Fill in the employee's details:
| Field | What to enter | Example |
|-------|--------------|---------|
| Employee name | Full name of the departing employee | Juan Garcia |
| Role | Their job title | Senior Developer |
| Department | Their team or department | Engineering |
| Exit date | Their last working day | 2026-07-20 |
| Key accounts | Clients or projects they manage (comma-separated) | Banco Norte, RetailCo, CloudBase |

Click **Create**. The system creates the process and shows you the process detail page with a progress bar.

### Step 2: Upload source documents

**Where:** Setup → **Documents** tab

Upload any documents related to the employee's work:
- **Contracts and SLAs** (reliability: High) — formal agreements with clients
- **Org charts** (reliability: Low) — often outdated
- **Technical wikis** (reliability: Medium) — internal documentation
- **Runbooks and procedures** (reliability: Medium) — operational guides
- **Project plans** (reliability: High) — strategic documents
- **Emails or memos** (reliability: Low) — informal communications

For each document, select the **trust level**:
- **High** (contract, signed plan, ADR) — the system trusts these strongly
- **Medium** (wiki, presentation) — trusted but may be outdated
- **Low** (org chart, email, other) — treated as potentially stale

> **Tip:** You don't need to have every document before starting. Upload what you have, run the analysis, and add more later.

### Step 3: Run AI analysis

**Where:** Setup → Documents → **Process documents** button

Click to start. The AI reads every uploaded document and extracts structured knowledge:
- Who manages what
- Which systems depend on each other
- Client relationships and contacts
- Technical decisions and their rationale
- Risks and informal agreements

This takes 1-3 minutes depending on document volume. When done, you'll see:
- **Knowledge items extracted**: how many facts the AI found
- **Contradictions detected**: conflicts between documents (e.g., org chart says Maria manages ETL, but the wiki says Andres does)
- **Knowledge gaps**: areas where documentation is thin

### Step 4: Interview the employee

**Where:** Interviews → **New Session**

The system suggests interview topics based on knowledge gaps — areas where documentation is thin or contradictions exist. You can:
- Accept the suggested topics
- Add your own topics
- Set the session's communication style (technical vs conversational)

**During the interview:**
- The AI asks questions and the employee responds (text or voice)
- The AI extracts knowledge from each response in real-time
- A coverage bar shows how much knowledge has been captured
- Contradictions between the employee's answers and documentation are flagged

**After each session:**
- The AI compares new information against documents
- Weak contradictions are auto-resolved (employee overrides outdated docs)
- Strong contradictions are flagged for your review
- The next session's questions are updated based on what was learned

> **Tip:** 2-4 sessions of 30-45 minutes typically capture 70-90% of critical knowledge. The system tells you when coverage is sufficient.

### Step 5: Review findings

**Where:** Setup → **Curation Inbox**

Review the knowledge items extracted by the AI:
- **Approve** — confirm the finding is accurate
- **Reject** — dismiss incorrect findings
- **Change visibility** — mark sensitive items as restricted

**Where:** Decisions → **Contradictions**

Review contradictions between documents and interview answers:
- See both versions side by side
- See the source reliability score
- **Resolve** — decide which version is correct, with a note explaining why

### Step 6: Query the Knowledge Assistant

**Where:** Knowledge Assistant

Ask questions about the employee's knowledge in natural language:

> "Who manages the Banco Norte account?"
> "What happens if the ETL pipeline fails at night?"
> "What informal agreements exist with CloudBase?"

The assistant answers with:
- A natural language response
- Citations to specific sources (document or interview session)
- Flags for any disputed information

### Step 7: Monitor progress

**Where:** Processes → click on the process

The process detail page shows:
- **Progress bar** — overall knowledge completeness percentage
- **Stage** — where you are (Getting started → Collecting documents → Analyzing documents → Knowledge transfer → Handoff ready)
- **Next steps** — what to do next, with action buttons
- **Open contradictions** — disputes still needing resolution
- **Days until exit** — time remaining

> **Goal:** Reach 80%+ knowledge completeness with 0 open contradictions before the employee's last day.

---

## Understanding the dashboard

### Knowledge completeness (%)

This measures how much of the employee's expected knowledge areas have been captured. It's based on:
- How many knowledge areas have at least one finding
- The criticality of each area (client accounts weigh more than internal tools)
- Whether findings have been verified or are still unconfirmed

### Contradictions

When the AI finds two conflicting pieces of information (e.g., a document says the SLA is 4 hours, but the employee says it's 2 hours verbally), it flags a contradiction. You decide which is correct.

- **Auto-resolved**: weak source (like an org chart) overridden by interview — the system handles this
- **Pending review**: strong source (like a contract) conflicts with interview — you need to decide

### Knowledge items status

| Status | Meaning |
|--------|---------|
| Unverified | Extracted but not yet reviewed |
| Verified | Confirmed by a second source or approved by curator |
| Disputed | Contradicts another finding — needs resolution |
| Restricted | Contains sensitive information — limited visibility |

---

## Tips for a successful offboarding

1. **Start early** — begin the process at least 2 weeks before the exit date
2. **Upload documents first** — the AI needs something to compare against
3. **Don't skip the interviews** — documents miss informal knowledge, relationships, and workarounds
4. **Review contradictions promptly** — they affect the quality of the knowledge assistant
5. **Let the replacement try the assistant** — if they can get useful answers, the process worked
6. **Export a report** — Settings → Export for a permanent knowledge transfer record

---

## Need help?

- **Swagger API docs**: http://localhost:8090/docs
- **Contact**: Eco Consulting — support@ecoconsulting.es
