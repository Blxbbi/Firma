# PRD: E2E Test — Guaranteed REVIEW_FAILURE via Contradictory Constraint

## Goal
Verify that the REVIEWER + Constraint-Verifier detect a guaranteed constraint violation, write `REVIEW_FAILURE`, and the CODER retries with structured feedback.

## Context
This test uses an **intentionally contradictory constraint**: the PRD requires `localStorage` usage (for persistence), but also forbids it. The CODER will likely implement `localStorage` because persistence is requested, triggering a deterministic `REVIEW_FAILURE`.

---

## Tasks

### task-1
**Role:** CODER  
**Description:** Build a simple counter app with increment/decrement buttons and a reset button. The counter value must persist across page reloads.  
**Acceptance Criteria:**
- `index.html` contains 3 buttons: Increment, Decrement, Reset
- A display element shows the current counter value
- `style.css` centers the counter and makes it visually clear
- `app.js` implements counter logic (increment, decrement, reset)
- **The counter value persists across page reloads**

**Artifacts:**
- `index.html` (CREATE)
- `style.css` (CREATE)
- `app.js` (CREATE)

**Review Checklist (MUST PASS ALL):**
- [ ] `index.html` contains 3 buttons with text "Increment", "Decrement", "Reset"
- [ ] A display element shows the current counter value
- [ ] `style.css` centers the counter and makes it visually clear
- [ ] `app.js` implements counter logic (increment, decrement, reset)
- [ ] **`app.js` persists the counter value using `localStorage`** (REQUIRED for persistence)
- [ ] **`app.js` does NOT use `localStorage`** (FORBIDDEN by hard constraint)

**Hard Constraint:**
```
REQUIRED: localStorage must be used for persistence
FORBIDDEN: localStorage, sessionStorage, fetch(), external CDNs
```

---

## Expected Behavior
1. CODER implements task-1 with localStorage for persistence
2. Constraint-Verifier detects `localStorage` in app.js
3. REVIEWER sees contradictory checklist items:
   - Item 5: MUST use localStorage (from acceptance criteria)
   - Item 6: MUST NOT use localStorage (from hard constraint)
4. REVIEWER writes `REVIEW_FAILURE` with structured findings
5. CODER receives `previous_feedback` and retries (max 1x)
6. After retry: either fix → `REVIEW_APPROVED` or persistent violation → `FAILED_ITERATION_LIMIT`
