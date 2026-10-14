# Valley Medical AI Platform: Proof of Concept

Working POC of the two feasibility core proofs:

1. **Meditab IMS integration** (AI-02, AI-03): find a patient, see their full record with a source on every item, generate a cited pre-visit summary, and view chronic-pain trends.
2. **Controlled billing agent** (parts of AI-16, AI-17, AI-18): the 8-step denial and follow-up workflow, with human review of every classification, human approval of every draft, and no ability to send anything externally.

> **Synthetic data only.** Meditab and the billing system are simulated behind adapter interfaces, because their real interfaces are not yet known. Do not load real patient data into this POC.

## Quick start

### Docker

```bash
cp .env.example .env          # optional: add GEMINI_API_KEY (free key) or ANTHROPIC_API_KEY
docker compose up --build
```

Open http://localhost:8080. The API is at http://localhost:8000/docs.

### Local development

Needs Python 3.11+ and Node 20+.

```bash
cp .env.example backend/.env
make install
make api      # terminal 1: FastAPI on :8000
make ui       # terminal 2: React on :5173 (proxies /api to :8000)
make test     # backend tests
```

Without a key for the chosen provider (default `gemini`), the backend uses a deterministic **offline mock model**, so the demo works with no network. The mock shows the workflow; it says nothing about real model accuracy.

## Demo script (about 10 minutes)

Use the **Signed in as** menu (bottom left) to switch roles. In this POC that menu stands in for real sign-in.

**Proof 1: Meditab records** (sign in as *Dr. Test, provider*)

1. **Patients.** Note that two patients share the same name and date of birth. This is why matching uses identifiers, never names.
2. **Testpatient, Avery → Pre-visit summary → Write pre-visit summary.** Each statement has a citation chip; click one to see the exact Meditab record, encounter, date and page. Medications and allergies are also listed straight from structured data.
3. **Chronic pain tab.** Shows pain, function, sleep and mood trends, plus pain before and after each procedure. No AI is used on this tab.
4. **Democase, Riley.** Labs show as *unavailable* (a simulated Meditab outage), not as empty. An outside MRI whose printed MRN belongs to someone else is **withheld** and sent to the exception queue.

**Proof 2: Billing agent**

5. Sign in as *Biller Test*. Open **Billing work → Read work queue**. The agent opens cases and proposes categories. Every case stops at **Needs classification review**.
6. **CLM-9001** (medical necessity). Confirm the classification. The agent retrieves only the records this category needs, finds no gaps, and drafts an appeal citing them.
7. Sign in as *Approver Test*. Approve the draft, optionally editing it first. The case is routed to the Appeals specialist. **Nothing is sent.** Staff record their own submission reference in step 8.
8. Look at these other cases:
   - **CLM-9002.** Imaging is missing, so the agent drafts a *provider query* instead of an appeal.
   - **CLM-9003.** Timely filing is a hard stop; the agent will not draft and escalates instead.
   - **CLM-9004.** The payer remark contains "IGNORE PREVIOUS INSTRUCTIONS…". This is flagged and treated as data.
   - **CLM-9005.** The date of birth on the claim doesn't match Meditab. The agent stops before reading any records.
   - **CLM-9008.** The rule result overrides the model's suggestion.
9. The queue holds **31 synthetic claims (27 need work)** across 10 patients. The **status bar** above the queue counts cases in each status (Needs classification review, Needs draft approval, Draft rejected, With owner, Submitted by staff, Escalated, Completed, No action needed); click one to filter. As *Approver Test*, **Load demo workload** moves 15 cases through the real agent into that mix, so the queue looks like work in progress. The cases in this script stay at review so you can still walk through them live. The loader's decisions are excluded from the accuracy and usability figures in Billing insights.
   Use the filter chips (*Needs a person*, *Escalated*, *With owner*, *Done*), search and sorting. Other cases worth opening:
   - **CLM-9009 / CLM-9027** ($2,850 and $1,150): radiofrequency ablation appeals. The agent finds the physical therapy course, the diagnostic blocks and the MRI pages as evidence.
   - **CLM-9010 vs CLM-9012**: two prior-authorization denials. One has an authorization number on file (appeal); one doesn't (provider query).
   - **CLM-9013 / CLM-9030**: codes not in the rule table, so the model decides and the case is flagged *low confidence*.
   - **CLM-9015, 9016, 9017, 9028**: eligibility, duplicate and timely-filing hard stops.
   - **CLM-9025**: a second, subtler injection attempt ("SYSTEM NOTICE TO AI ASSISTANT…"), also flagged.
   - **CLM-9026**: a one-letter typo in the patient's last name. The agent stops before reading any records.
   - **CLM-9019, 9020, 9024**: paid or recently worked, so no action.
10. **Exceptions** shows everything that stopped for a person.
11. Sign in as *Admin Test* and open **Audit log**. Every read, model call and approval is listed, with an intact hash chain.

## Feature pack: Phase 1 WBS items added to the POC

| Feature | WBS item | Where to see it |
| --- | --- | --- |
| **Documentation audit (AI-23)**: seven rules, deterministic first; AI checks must quote the note verbatim or become a finding; clinicians confirm or dismiss each finding | #10 | Patient → *Documentation audit* tab |
| **Billing insights (AI-18)**: classification accuracy vs reviewers, supporting-record completeness, draft usability ratings, active handling time vs a time-study baseline, money at stake, CSV export | #14, N6 | *Billing insights* |
| **Acceptance scorecard**: runs the real pipelines in an isolated sandbox against a labelled test set, injects failures, and scores all 15 acceptance criteria from the feasibility document, with hard gates and sample sizes | #18 | *Acceptance scorecard* (admin runs it) |
| **AI gateway**: every model call metered (tokens, latency, model, prompt version), monthly token budget, admin kill switch, summary reuse when the chart hasn't changed | N3, N9, N10 | *AI usage* |

Also included: handling time is measured on every human decision (the timer runs only while the case is on screen and in focus), and approvers rate each edited draft as minor or major to measure "usable with minor or no revision".

### Feature pack demo (about 8 minutes)

1. As *Dr. Test*: open **Samplecase, Jordan (SYN100002) → Documentation audit → Run documentation audit**. Five findings, each linked to its Meditab record. Confirm one; dismiss one with a reason.
2. Same patient, **Pre-visit summary**: write it twice. The second time it is reused ("nothing in the chart has changed"), with no AI call.
3. As *Biller Test*, then *Approver Test*: work CLM-9001 through to approval (rate the draft if you edit it). As *Approver Test*, open **Billing insights → Load synthetic demo baseline**. Accuracy, usability, handling time and money now populate. The synthetic baseline is labelled as such.
4. As *Admin Test*: **Acceptance scorecard → Run acceptance tests**. Open any criterion to see its evidence. With a live model, the accuracy figures are real measurements.
5. As *Admin Test*: **AI usage → Pause all AI**. Read the work queue or write a summary: work falls back to the exception queue safely. Resume.

## How this maps to the feasibility requirements

| Client requirement (feasibility document) | Where it is implemented |
| --- | --- |
| Retrieve structured data, notes, PDFs; link every item to patient, encounter, date, source | `services/clinical_record.py` (`RecordItem.source`), document pages cited individually |
| Zero wrong-patient disclosure | `services/patient_matching.py` (deterministic, fail-closed), document quarantine, cross-patient guard |
| Citations for material clinical statements; no fabrication | `services/summary.py`, `services/grounding.py` (unsupported statements removed and shown) |
| Chronic pain: pain, function, sleep, mood, meds, procedures, imaging, treatment response | `services/chronic_pain.py` |
| Safe handling of failed or incomplete retrievals | Sections marked `unavailable`; summary lists data gaps |
| Read-only; write-back not performed | Adapters expose read methods only |
| Billing steps 1–8 with controls | `agents/billing_agent.py` (state machine) |
| Hard rules override the model; stop and escalate conditions | `services/billing_rules.py` (`CARC_RULES`, `HARD_STOPS`) |
| Human review of classification; no submission without approval | Human gates in the state machine; approve permission limited to `billing_approver`; no send capability exists |
| Exception queue; retries capped; no duplicate actions | `services/exceptions.py`, LLM retry cap, `ActionRecord` idempotency ledger, optimistic locking |
| Version control for prompts and models | `llm/prompts.py` versions, logged with every model call |
| Complete audit trail; end-to-end case replay | `audit.py` (hash-chained), per-case event log |
| Role-based access, minimum necessary | `security.py` permissions; billing agent reads records scoped per requirement |

## Project layout

```
backend/
  app/
    adapters/meditab/   base.py (interface)  mock.py (synthetic Meditab)
    adapters/billing/   base.py (interface)  mock.py (synthetic billing queue)
    agents/billing_agent.py   8-step state machine
    services/           patient matching, record assembly, summary, chronic pain,
                        grounding checks, billing rules, exception queue
    llm/                Gemini and Claude clients (forced tool use), offline mock, versioned prompts
    api/                FastAPI routes
    audit.py            hash-chained audit log
    security.py         roles and permissions
  fixtures/             synthetic Meditab patients and billing claims
  tests/
frontend/               React + TypeScript (Vite)
```

## Choosing the AI model

Set `VM_LLM_PROVIDER` to `gemini` (default), `anthropic` or `mock`.

| Provider | Key | Model setting (default) |
| --- | --- | --- |
| `gemini` | `GEMINI_API_KEY` (free key from Google AI Studio) | `VM_GEMINI_MODEL` (`gemini-3.5-flash-lite`; free-tier models change, so check Google's model list) |
| `anthropic` | `ANTHROPIC_API_KEY` | `VM_ANTHROPIC_MODEL` (`claude-sonnet-5-5`) |
| `mock` | none | offline, deterministic |

If `VM_LLM_PROVIDER` is not set and `GEMINI_API_KEY` is missing, the mock is used and a warning is logged. If you set the provider explicitly, its key is required. `/health` shows which client is active.

All calls use forced tool use / function calling, so output is structured JSON; retries are capped (`VM_LLM_MAX_RETRIES`). Gemini "thinking" tokens count toward its output limit, so it uses `VM_GEMINI_MAX_TOKENS` (default 8192). A blocked or truncated Gemini answer is reported as a model failure, not used.

**Data:** with the POC's synthetic data, no PHI is sent. Free-tier Gemini prompts may be used by Google to improve its products, so never use real patient data. Any real use needs a paid plan or BAA with the model provider and approved retention terms first.

## What is simulated, and assumptions

| Area | POC | Needed for production |
| --- | --- | --- |
| Meditab interface | Mock adapter over JSON | Discovery: API, FHIR, HL7, DB replica or export. Then write one class implementing `MeditabAdapter`. |
| Billing queue | Mock adapter over JSON | Discovery: Meditab billing module, separate PM system, clearinghouse or RCM vendor |
| Sign-in | Demo headers and a role menu | SSO or OIDC with server-side roles |
| Billing rules | Illustrative CARC mappings, required evidence and routing | Rules approved by Valley Medical |
| Database | SQLite | Postgres, encrypted, with backups and retention |
| Grounding checks | Small drug lexicon | Maintained terminology (e.g. RxNorm) and clinician-reviewed evaluation set |

## Next enhancements (suggested order)

1. Real Meditab adapter once discovery confirms the interface. Add incremental sync and a freshness report (acceptance criterion C06).
2. OCR pipeline for scanned PDFs, with page-level citations, and measured OCR quality (WBS #5).
3. Replace the illustrative documentation rules and billing rules with Valley Medical's approved rules.
4. Grow the acceptance test set with Valley Medical's reviewers; run it on every prompt or model change (regression).
5. Real sign-in (OIDC), Postgres, background jobs for model calls, and monitoring.
6. Sensitive-data segmentation for 42 CFR Part 2 and psychotherapy notes (WBS N2).

## Host it free (Render)

The root `Dockerfile` builds one image in which the backend also serves the UI, so the whole POC runs as **one free Render web service** (no credit card). `render.yaml` configures it.

1. Push this repository to GitHub (a **private** repository is fine). Check that `.env` is **not** committed: `git ls-files | grep .env` should list only `.env.example`.
2. In Render: **New → Blueprint**, connect GitHub, and pick the repository.
3. When asked, enter:
   - `VM_DEMO_PASSWORD`: a password you'll share with the client. The browser asks for it; any username works.
   - `GEMINI_API_KEY`: your key, or leave it empty to run on the offline mock model.
4. Wait for the build (about 5 minutes), then open the `…onrender.com` URL.

What to expect on the free tier:
- **It sleeps after 15 minutes without visitors.** The next visit takes about a minute to wake it. Open the URL a few minutes before a demo.
- **Data resets when it restarts or redeploys**, because the free disk is temporary. Each demo starts clean: *Read work queue*, then *Load demo workload*.
- **Small CPU.** Pages are fine; batch AI work is limited by the model's rate limit anyway.
- **Synthetic data only.** Free hosting has no BAA. Never load real patient data here.

To run the same image locally: `docker build -t vm-poc . && docker run -p 8000:8000 -e VM_DEMO_PASSWORD=test vm-poc`, then open http://localhost:8000.

## Rate limits (429 Too Many Requests)

Reading a 27-claim queue makes one model call per claim, and loading the demo workload adds about 12 more. Free and low-tier API keys allow only a few requests per minute, so the app:

- **Throttles** model calls to `VM_LLM_REQUESTS_PER_MINUTE` (default 10). Set it just under your key's limit, which is shown in the provider console. Batch actions take longer but don't fail.
- **Waits as long as the provider asks** when it does return 429 (Gemini's `retryDelay`), up to `VM_LLM_MAX_RETRY_WAIT_SECONDS`.
- **Fails safely** if a call still fails: the case goes to the exception queue, nothing is guessed.
- **Recovers in one click**: *Billing work → Retry N with AI*, or *Retry with AI* on a case. Only model failures can be retried; hard stops and safety escalations still need a person.

A daily quota cannot be throttled around. If it is used up, use a paid key or `VM_LLM_PROVIDER=mock` for the demo.

## Known limitations

- The mock model always produces well-formed output. Test with a real model (Gemini or Claude) before judging quality.
- Model calls run inside the request. Production should move them to a job queue.
- The audit chain uses a single writer. It is fine for the POC but needs serialised writes or a ledger service at scale.
