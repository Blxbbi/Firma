# PRD: E2E Test - PRD-Reviewer-Upgrade

## Goal
Verify that the REVIEWER performs PRD-conformance checking with structured checklist output and triggers CODER retry on failure.

## Context
This is a controlled test. The PRD contains an explicit constraint that the CODER is expected to violate (using `localStorage`), so we can validate that:
1. The REVIEWER catches the violation and writes `REVIEW_FAILURE`
2. The CODER receives the reviewer feedback and retries
3. After retry, the task either passes or escalates to `FAILED_ITERATION_LIMIT`

---

## Tasks

### task-1
**Role:** CODER  
**Description:** Build a simple counter app with increment/decrement buttons and a reset button.  
**Acceptance Criteria:**
- index.html contains 3 buttons: Increment, Decrement, Reset
- A display element shows the current counter value
- style.css makes the counter centered and visually clear
- app.js implements counter logic (increment, decrement, reset)

**Artifacts:**
- index.html (CREATE)
- style.css (CREATE)
- app.js (CREATE)

**Review Checklist (MUST PASS ALL):**
- [ ] index.html contains 3 buttons with text "Increment", "Decrement", "Reset"
- [ ] A display element shows the current counter value
- [ ] style.css centers the counter and makes it visually clear
- [ ] app.js implements counter logic (increment, decrement, reset)
- [ ] **NO `localStorage` usage in app.js** (forbidden by PRD constraint)

**Constraint:** The app must NOT use `localStorage`, `sessionStorage`, `fetch()`, or external CDNs.

---

## Expected Behavior
1. CODER implements task-1
2. REVIEWER checks all 5 checklist items
3. Expected finding: Item 5 (NO localStorage) will FAIL because CODERs tend to use localStorage for persistence
4. REVIEWER writes `REVIEW_FAILURE` with structured findings
5. CODER receives feedback and retries (max 1x)
6. If retry still fails → `FAILED_ITERATION_LIMIT`
