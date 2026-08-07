# muendlich — Requirements Document

**Working title:** muendlich (Thought Collector)
**Author:** Philip Schaffner
**Date:** 2026-07-01
**Status:** Draft v3 — architecture decisions locked; open questions resolved

> **v3 changelog:** Stage 1 anonymization is now **deterministic — roster/alias matching (fuzzy + phonetic) plus German spaCy NER**. The locally-run LLM option for anonymization is **dropped**. (v2: mobile fixed to PWA; AI fixed to hybrid two-stage; seven open questions resolved.)

---

## 1. Purpose & Problem Statement

As a teacher, you need to assign oral/participation marks across a whole semester, but you rarely have time between lessons to write down observations. This app lets you **capture spoken observations immediately after a lesson**, one class at a time, and have them automatically **structured into per-student notes** and stored. Over the semester these notes — plus sentiment and an optional score — give you an evidence base for a fair oral mark.

The core interaction: after a lesson you open the phone, pick the class, and dictate freely (e.g. *"Anna was great today, helped Beatrice. Colin got on my nerves. Darian spaced out, Felicia didn't have her homework"*). The system splits this into separate observations, attaches each to the right student, and saves it.

---

## 2. Goals & Non-Goals

### Goals
- Capture observations in **seconds**, hands-busy, right after a lesson.
- Reliable **speech → text → per-student structured notes**.
- A **web interface** to review classes, students, and all observations, and to export them.
- **Multi-user**: each teacher sees only their own classes and observations.
- Support the **oral-marking workflow**: sentiment trend + optional manual score per note.
- Self-hosted on your own server.

### Non-Goals (for now)
- Not a full gradebook / report-card system.
- Not a student- or parent-facing app.
- No real-time collaboration between teachers on the same class.
- No integration with school administration systems (SAL, LehrerOffice, etc.) in v1.

---

## 3. Users & Roles

| Role | Capabilities |
|------|--------------|
| **Admin** | Creates and manages teacher accounts; no access to other teachers' observation content. |
| **Teacher (user)** | Manages own classes & students; dictates and reviews observations; exports own data. |

Accounts are **created by the admin** (your decision). Self-registration is out of scope for v1 but the data model should not preclude it later. **Scale target: ~10 users** — small enough that simple admin tooling (a basic user-management page) suffices; no need for self-service onboarding.

---

## 4. High-Level Architecture

```
┌─────────────────────┐        HTTPS/REST        ┌──────────────────────────────┐
│   Phone frontend    │  ───────────────────────▶│         Backend server        │
│  (dictate + select) │        (text only)        │  (Docker)                    │
│  On-device STT      │◀───────────────────────  │                              │
└─────────────────────┘                           │  ┌────────────┐  ┌─────────┐ │
                                                   │  │ Web frontend│  │  API    │ │
┌─────────────────────┐                           │  └────────────┘  └────┬────┘ │
│   Web frontend      │  ◀──────────────────────▶ │                       │      │
│  (review/export)    │                           │  ┌────────────┐   ┌───▼────┐ │
└─────────────────────┘                           │  │  Database   │   │ AI     │ │
                                                   │  │ (Postgres)  │   │ struct.│ │
                                                   │  └────────────┘   └───┬────┘ │
                                                   └───────────────────────┼──────┘
                                                                           │
                                        ┌───────────────────────────┴───────────────────────────┐
                                        │ Stage 1 (local, deterministic): roster/alias match      │
                                        │   (fuzzy + Kölner Phonetik) + German spaCy NER → anon.   │
                                        │ Stage 2 (cloud): Claude/OpenAI API → structure+sentiment │
                                        └─────────────────────────────────────────────────────────┘
```

**Key data-flow decisions (locked):**
- **Frontend is a PWA** (single installable web app for capture *and* review; §7).
- **Speech-to-text runs on the phone** (built-in dictation). The backend only ever receives **text**, never audio — simpler, free, private by default.
- **Backend runs in Docker** on your server.
- **AI runs in hybrid mode:** a **deterministic local pass anonymizes** the dictated text (roster/alias matching with fuzzy + phonetic tolerance, plus German spaCy NER as a backstop for off-roster names), then a **cloud AI structures + sentiment-tags** the anonymized text; names are restored locally afterward (§8, §9). The local pass is **optional in Phase 1** (stubbed pass-through) but the pipeline is built as two stages so it can be switched on without rework. **No locally-run LLM is used.**

---

## 5. Functional Requirements

### 5.1 Mobile app (capture)
- **FR-M1** Log in (session persisted so you don't re-auth every lesson).
- **FR-M2** Show a list of the teacher's classes; select one.
- **FR-M3** Large "dictate" button; uses the phone's on-device dictation to produce text.
- **FR-M4** Show the transcribed text; allow a quick manual edit before sending.
- **FR-M5** Send text + class ID to the backend; show the structured result (which names/observations were detected).
- **FR-M6** Let the user confirm, correct a mis-assigned name, or discard before final save.
- **FR-M7** Handle unmatched (off-roster) names gracefully: when a spoken name doesn't match the roster, **prompt to either add it as a new student in this class or map it to an existing student**. (Storing as "unassigned" is a fallback only if the user skips.)
- **FR-M8** Offline resilience: if the network is down, queue the text locally and sync when back online (nice-to-have for v1).

### 5.2 Web frontend (review & export)
- **FR-W1** Log in.
- **FR-W2** CRUD for **classes** (name, subject, semester, school year).
- **FR-W3** CRUD for **students** within a class (name, optional display/short name, optional aliases for name-matching).
- **FR-W4** View all observations for a class, filterable by student, date, sentiment.
- **FR-W5** Per-student view: chronological list of observations with sentiment + score, and a simple **trend summary** for the semester.
- **FR-W6** Edit/delete individual observations; re-assign an observation to a different student.
- **FR-W7** **Export**: per-class or per-student, as CSV and PDF (and optionally a printable summary sheet for marking day).
- **FR-W8** Manual entry of an observation (typed, without the phone), for completeness.

### 5.3 AI structuring pipeline (backend)

The pipeline is **two stages** so the anonymization step can be added/removed independently:

- **FR-A0 (Stage 1 — local deterministic anonymize, Phase 2; stubbed in Phase 1):** replaces person-names in the raw text with stable placeholders (`Student1`, `Student2`, …), keeping the placeholder→name map **only on the server**. Two layers: (a) **roster/alias matching** for the selected class, tolerant of dictation errors via edit-distance + **Kölner Phonetik** (German phonetic keying); (b) **German spaCy NER** (`de_core_news_*`) as a backstop that catches person-names not on the roster. **No LLM is used in this stage.** In Phase 1 this stage is a **pass-through no-op** so the pipeline shape is already correct.
- **FR-A1** Input to Stage 2: the (optionally anonymized) text + the class roster (names/aliases; placeholders in anonymized mode).
- **FR-A2 (Stage 2 — cloud structure + sentiment):** output is a list of `{student, observation_text, sentiment}` objects.
- **FR-A3** **Name matching** against the roster, tolerant of dictation/spelling errors (e.g. "Colin"/"Collin", phonetic near-matches). Return a confidence and flag low-confidence matches for user confirmation. In anonymized mode, matching happens on placeholders and is restored locally.
- **FR-A4** **Sentiment tagging** per observation on a **three-way scale: `positive / neutral / negative`** (decision locked). This feeds the marking view.
- **FR-A5** Deterministic, structured output (JSON schema / function-calling) so parsing never breaks on prose.
- **FR-A6** Never silently drop content: text that can't be attributed to a student triggers the off-roster prompt (FR-M7); if skipped, it is stored as "unassigned" rather than discarded.
- **FR-A7** The two stages sit behind **provider interfaces** (`Anonymizer`, `Structurer`), each with swappable adapters, so Phase 1 (cloud-only) and Phase 2 (local+cloud) differ only by configuration.

### 5.4 Marking support
- **FR-K1** Each observation stores a **sentiment tag** (AI-proposed, user-editable) **and an optional manual score** field (your decision — both).
- **FR-K2** Per-student semester view aggregates: count of positive/neutral/negative notes, average manual score, and a timeline.
- **FR-K3** Export of the aggregate to support entering the final oral mark (the app **informs**, it does not compute the official grade).

---

## 6. Data Model (initial)

```
User(id, email, password_hash, role, created_at)
Class(id, user_id → User, name, subject, semester, school_year, created_at)
Student(id, class_id → Class, full_name, short_name, aliases[], active)
Observation(id, student_id → Student (nullable for "unassigned"),
            class_id → Class,
            raw_source_id → RawCapture,
            text, sentiment, manual_score (nullable),
            created_at, lesson_date)
RawCapture(id, class_id, user_id, raw_text, created_at, processed_at)
```

Notes:
- Every teacher's rows are scoped by `user_id` (directly or via `Class`) — this is the multi-user isolation boundary and must be enforced on **every** query.
- `RawCapture` keeps the original dictation for audit/re-processing and so nothing is lost if the AI mis-splits.
- `aliases[]` on `Student` improves name matching (nicknames, spelling variants).
- **`lesson_date` defaults to "now"** at capture time (decision locked); it remains editable in the web frontend for the occasional back-dated entry.
- **Retention: keep indefinitely.** No automatic deletion; the teacher removes data via **manual export + delete** (decision locked). Export must therefore be complete enough to serve as an archive before deletion.

---

## 7. Technology Decision 1 — Mobile app: **PWA (decided)**

**Decision: the frontend is a PWA.** The comparison below is retained as rationale; the Flutter/React-Native path is kept only as a documented fallback if iOS Safari dictation proves inadequate.

### Option 1 — PWA (installable web app)
A web app served by your backend, "installed" to the home screen. Uses the browser's Web Speech API / on-device dictation.

**Pros**
- **One codebase**, instantly works on Android and iPhone.
- **No app stores, no Apple Developer account** ($99/yr) — big deal for iPhone.
- Trivial to self-host and update (it's just part of your web deployment).
- Same auth/session as the web frontend; less to build.
- Fastest path to a working MVP.

**Cons**
- **Dictation via the browser is less controllable** than native. On Android/Chrome the Web Speech API works well; on **iOS Safari it is more limited/inconsistent** — you'd typically rely on the keyboard's dictation mic rather than a programmatic API, which is slightly clunkier.
- Background/offline capabilities are weaker (though a service worker covers the queue-and-sync case).
- Feels a touch less "app-like"; no push notifications on iOS pre-recent versions.

### Option 2 — Flutter or React Native (cross-platform native)
A compiled app, one codebase, using native speech plugins (`speech_to_text` for Flutter, `react-native-voice` for RN).

**Pros**
- **Best, most consistent dictation control** across Android and iOS via native speech APIs.
- Smoother UX, real offline support, home-screen presence, notifications.
- Still largely one codebase.

**Cons**
- **Build toolchain** (Android Studio / Xcode) and app signing.
- **iPhone install requires an Apple Developer account** and either TestFlight or sideloading — recurring cost and friction for a personal app.
- More moving parts to maintain than a PWA.
- Slower to first working version.

### Rationale for the decision
Given **on-device STT + Docker self-hosting + ~10 users, German-first**, the **PWA** wins: one codebase for Android and iPhone, no app-store/Apple-Developer overhead, and it reuses the web stack directly. If iOS Safari dictation proves too limited in real use, the capture screen can later be re-implemented in Flutter **without touching the backend** — the API is treated as the stable contract precisely so the frontend can swap. **First-language target is German**, so verify the PWA sets the dictation language to `de-DE` (with the language selectable to support future locales).

---

## 8. Technology Decision 2 — AI structuring: **Hybrid (decided)**

**Decision: hybrid mode with a *deterministic* local Stage 1.** A local pass anonymizes the dictation using **roster/alias matching (fuzzy + Kölner Phonetik) plus German spaCy NER** — **not** a locally-run LLM. The **cloud AI structures + sentiment-tags** the anonymized text; names are restored locally. Stage 1 is **omitted in Phase 1** (cloud-only, names sent as-is for personal use) but the two-stage pipeline is built from the start (FR-A0/FR-A7). The comparison below records why a cloud model is still used for Stage 2.

### Why cloud for Stage 2 (structuring + sentiment)
Splitting messy dictation into per-student observations, fuzzy-matching names, and emitting clean structured JSON is exactly where a frontier **cloud** model excels: highest accuracy, very reliable JSON/function-calling output, no hardware needed, and cheap per request (a few hundred short requests/month is cents to low single-digit euros). The cost is that text leaves your server — which is why Stage 1 anonymizes first (§9).

### Why deterministic (not a local LLM) for Stage 1 (anonymization)
A fully self-hosted LLM was considered — for either structuring or anonymization — and **rejected**:
- For **structuring**, a local model on a CPU-only box would be slower and materially less accurate at name-matching and clean JSON than the cloud, defeating the app's core value.
- For **anonymization**, an LLM is overkill: the task is essentially name detection/replacement, which a **deterministic roster+NER pass does faster, cheaper, and more predictably** (no hallucinated substitutions, fully debuggable) — and it fits your GPU-less hardware perfectly.

So the split is: **deterministic local Stage 1** (privacy) + **cloud Stage 2** (accuracy). Because §5.3 defines a **fixed JSON output contract** and both stages sit behind interfaces (FR-A7), the specific cloud vendor and the Stage-1 implementation remain swappable.

### Decision & hardware fit
Implement the two provider interfaces (`Anonymizer` local, `Structurer` cloud). **Phase 1 = cloud-only structuring, anonymizer stubbed as pass-through. Phase 2 = enable the deterministic local anonymizer.**

**Stage 1 = deterministic, no LLM (decided).** Two layers:
- **(a) Roster/alias matching** against the selected class's names, tolerant of dictation errors via edit-distance (e.g. rapidfuzz) + **Kölner Phonetik** (German phonetic keying). This does the bulk of the work because you're only ever dictating about students you've entered.
- **(b) German spaCy NER** (`de_core_news_sm/md/lg`) as a backstop for person-names *not* on the roster.
- Restore real names locally after Stage 2 returns.

**Known limitation to validate:** German spaCy NER is trained on full-name news text and is weak at tagging bare first names, so Layer (b) is only a backstop; Layer (a) carries the load. And name-substitution is pseudonymization only — identifying details inside the note text itself are not removed (§9).

**Hardware fit (your server: Intel Core i7-13700H, 16 GB RAM, Intel Iris Xe — no discrete GPU):** excellent. spaCy German models are tens of MB and run in milliseconds on CPU; roster matching is trivial. No GPU needed, negligible RAM footprint alongside Postgres + backend. The cloud Stage 2 call is unaffected by local hardware — it's an API request.

---

## 9. Anonymization Design (how it *could* work)

Goal: since the **cloud** AI does the structuring (Stage 2), real student names should not be sent to it. The deterministic Stage 1 handles this before any text leaves the server.

### Approach: name substitution ("pseudonymization") round-trip
Because the backend **already knows the class roster**, it can swap names before the cloud call and restore them after:

1. **Before sending:** replace each roster name (and its aliases) found in the dictated text with a stable placeholder — `Student1`, `Student2`, … — keeping a local map `{Student1 → Anna, Student2 → Beatrice}`. Names never seen by the roster that appear in the text are trickier (see limitations).
2. **Send** the placeholder text to the cloud AI, which structures and sentiment-tags it referring only to placeholders.
3. **After receiving:** map placeholders back to real names locally, then save.

**What this protects:** real names of your students don't reach the third party — only the observation *content* keyed to anonymous tokens.

**Limitations to be honest about:**
- Observation **content itself may contain identifying info** ("the boy who broke his arm") — substitution only handles names, not all personal data. True anonymization is hard.
- **Names spoken but not on the roster** can't be matched from the roster (you can't map what you don't know). Mitigation: the **German spaCy NER** layer flags person-names the roster misses and replaces them too — this is exactly why Stage 1 has both a roster layer and an NER layer.
- It's **pseudonymization**, not full anonymization, under GDPR terms — worth noting for compliance, but a strong improvement over sending raw names.

### Phasing for anonymization (aligned to the hybrid decision)
- **Phase 1:** anonymizer **stubbed as pass-through**; cloud path accepts names as-is (personal use, documented). Get the app working end-to-end.
- **Phase 2:** enable the **deterministic anonymizer** as Stage 1 — roster/alias substitution (fuzzy + phonetic) plus German spaCy NER for off-roster person-names — then cloud structuring on placeholders, with names restored locally. This is the target hybrid architecture. (No locally-run LLM.)

Because Stage 1 is a real pipeline step from day one (just a no-op in Phase 1), turning anonymization on is a **configuration + adapter swap**, not a redesign.

---

## 10. Non-Functional Requirements

- **Privacy/security:** per-user data isolation enforced at the query layer; passwords hashed (bcrypt/argon2); HTTPS only; API authenticated (session or JWT). Student data of minors → follow Swiss/EU data-protection good practice: minimize, secure at rest, allow export & deletion.
- **Deployment:** Docker Compose stack (backend, database). No LLM container needed — the Stage 1 anonymizer (spaCy + roster matching) is a library inside the backend. One-command bring-up; simple backups of the database volume.
- **Reliability:** dictation capture must never lose data — raw text persisted before AI processing; failed AI runs are re-tryable.
- **Performance:** structuring round-trip fast enough to confirm within a few seconds after a lesson.
- **Usability:** the phone flow must be doable one-handed in a noisy hallway in under ~15 seconds per class.
- **Localization:** **German first**, but build i18n-ready — UI strings externalized, dictation language configurable (default `de-DE`), and AI prompts parameterized by language — so additional languages can be added without refactoring.
- **Retention:** data kept **indefinitely**; deletion is manual. Provide a complete per-class/per-student **export** (CSV + PDF) that is trustworthy as an archive before the teacher deletes.
- **Backup/export:** full per-user data export (own the data).

---

## 11. Suggested Technology Stack (for discussion)

A pragmatic, self-hostable, Docker-friendly stack:

| Layer | Suggestion | Why |
|-------|-----------|-----|
| Backend/API | **Python + FastAPI** (or Node + NestJS) | Fast to build, great JSON/schema support, easy AI-SDK integration. |
| Database | **PostgreSQL** | Reliable, relational fit for the model, easy Docker volume backups. |
| Web frontend | **React** (or Svelte) served by the backend | Doubles as the PWA. |
| Mobile | **PWA** (same React app, installable) — decided | Per §7. |
| AI — Stage 2 (cloud, structuring + sentiment) | Anthropic Claude / OpenAI via official SDK | Reliable structured/JSON output. |
| AI — Stage 1 (local, anonymize; Phase 2) | **Deterministic**: roster/alias matching (rapidfuzz + Kölner Phonetik) + **German spaCy** (`de_core_news_*`) NER | No LLM; runs in-process on CPU (§8). |
| Auth | Session cookies or JWT; admin-created accounts | Per §3. |
| Deploy | **Docker Compose** + reverse proxy (Caddy/Traefik for HTTPS) | Per your environment. |

All swappable — this is a starting recommendation, not a lock-in.

---

## 12. Roadmap / Phasing

**MVP (Phase 1) — cloud-only, anonymizer stubbed**
- Admin creates users (~10 target); teacher logs in.
- Web: manage classes & students; view/edit observations; CSV export.
- PWA (German UI, `de-DE` dictation): select class, dictate, review structured result, confirm & save; `lesson_date` defaults to now.
- Two-stage pipeline with **Stage 1 as pass-through** and **Stage 2 = cloud** structuring → `{student, text, sentiment(3-way)}` + name matching with confirmation.
- Off-roster prompt: add-as-new-student or map-to-existing (FR-M7).
- Three-way sentiment + optional manual score on each observation.

**Phase 2 — turn on the hybrid + polish**
- Enable **Stage 1 deterministic anonymizer** (roster/alias + fuzzy/phonetic matching + German spaCy NER) → cloud on placeholders → restore names locally.
- Per-student semester trend view + PDF/summary export for marking day.
- Offline queue-and-sync on the PWA.
- Provider/settings toggle for anonymization on/off.

**Phase 3 (optional / later)**
- Additional UI + dictation languages (i18n groundwork already in place).
- iOS: re-implement capture in Flutter only if Safari dictation is insufficient.
- Aliases/nickname management UI for better name matching.

---

## 13. Resolved Decisions (was: Open Questions)

| # | Question | Decision | Impact |
|---|----------|----------|--------|
| 1 | Sentiment scale | **Three-way** (positive / neutral / negative) | FR-A4, marking aggregates |
| 2 | Lesson date | **Default to "now"**, editable in web | Data model, FR-K |
| 3 | Off-roster names | **Prompt: add as new student *or* map to existing** | FR-M7, FR-A6 |
| 4 | Languages | **German first**, i18n-ready for more later | §10 Localization, PWA `de-DE`, AI prompts parameterized |
| 5 | Retention | **Keep indefinitely; manual export + delete** | §10, export must be archive-grade |
| 6 | Number of users | **~10** | §3, simple admin tooling |
| 7 | Local anonymizer hardware | **i7-13700H / 16 GB / Iris Xe (no discrete GPU)** → ample for the deterministic Stage 1 (spaCy + roster matching run on CPU in milliseconds); no local LLM | §8 hardware fit |

### Remaining items to decide before/at build time
- **Cloud AI vendor** for Stage 2 (Claude vs OpenAI) — pick per cost/quality; the adapter makes this swappable.
- **Stage 1 tuning** in Phase 2 — spaCy model size (`sm`/`md`/`lg`) and fuzzy/phonetic thresholds — tune against real dictation samples for the best precision/recall on names.
- **PDF export layout** for marking day (a per-student one-pager?) — refine in Phase 2.

---

*Next step: with scope locked, I can produce the technical design — API endpoints, the Stage-1/Stage-2 JSON contracts, DB migrations, and a Docker Compose skeleton (backend + Postgres; the Stage-1 anonymizer is an in-process library, so no extra service). Say the word.*
