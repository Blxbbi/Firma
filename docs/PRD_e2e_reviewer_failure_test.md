# PRD: E2E Test — Guaranteed REVIEW_FAILURE

## Goal
Verify that the REVIEWER detects a guaranteed constraint violation, writes `REVIEW_FAILURE`, and the CODER retries with structured feedback.

## Context
This test uses an **intentionally unnatural constraint** that LLM CODERs almost always violate: **"KEINE `const`/`let` — NUR `var` verwenden"**. Modern JS defaults to `const`/`let`, so this should trigger a deterministic REVIEW_FAILURE.

---

## Tasks

### task-1
**Role:** CODER  
**Description:** Build a simple counter app with increment/decrement buttons and a reset button.  
**Acceptance Criteria:**
- `index.html` enthält 3 Buttons: Increment, Decrement, Reset
- Ein Display-Element zeigt den aktuellen Zählerstand
- `style.css` zentriert den Counter und macht ihn visuell klar
- `app.js` implementiert Counter-Logik (increment, decrement, reset)

**Artifacts:**
- `index.html` (CREATE)
- `style.css` (CREATE)
- `app.js` (CREATE)

**Review Checklist (MUST PASS ALL):**
- [ ] `index.html` enthält 3 Buttons mit Text "Increment", "Decrement", "Reset"
- [ ] Ein Display-Element zeigt den aktuellen Zählerstand
- [ ] `style.css` zentriert den Counter und macht ihn visuell klar
- [ ] `app.js` implementiert Counter-Logic (increment, decrement, reset)
- [ ] **`app.js` verwendet KEINE `const`- oder `let`-Deklarationen — NUR `var`**

**Hard Constraint:**
```
VERBOTEN: const, let
ERLAUBT: var
```

---

## Expected Behavior
1. CODER implementiert task-1
2. REVIEWER prüft alle 5 Checklist-Items
3. **Item 5 FAIL** weil CODER natürlicherweise `const`/`let` verwendet
4. REVIEWER schreibt `REVIEW_FAILURE` mit strukturierten Findings
5. CODER erhält `previous_feedback` und retried (max 1x)
6. Nach Retry: entweder Fix → `REVIEW_APPROVED` oder persistenter Verstoß → `FAILED_ITERATION_LIMIT`
