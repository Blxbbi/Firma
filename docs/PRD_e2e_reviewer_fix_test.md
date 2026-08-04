# PRD: E2E Test - Reviewer Role-Prompt Fix

## Goal
Verify the reviewer role-prompt fix works correctly in a complete end-to-end run.

## Tasks

### task-1
**Role:** CODER  
**Description:** Foundation: Create base HTML structure, CSS styling system, and JavaScript state management for 4-step onboarding wizard.  
**Acceptance Criteria:**
- index.html contains navigation, 4 step containers (Step-1 through Step-4), and footer
- style.css defines CSS variables for colors and spacing, includes reset, grid layout, and navigation styles
- app.js implements state management (currentStep, userData), router functions, event system, and utility functions
**Artifacts:**
- index.html (CREATE)
- style.css (CREATE)
- app.js (CREATE)

### task-2
**Role:** CODER  
**Description:** Step 1+2 Implementation: Add welcome screen to Step-1 and feature selection list to Step-2.  
**Acceptance Criteria:**
- Step-1 container displays welcome screen with logo, headline, description, and next button
- Step-2 container displays a feature list with 5 checkboxes
- app.js handles toggle events, welcome animation, feature selection, validation, and state updates
**Artifacts:**
- index.html (UPDATE)
- style.css (UPDATE)
- app.js (UPDATE)

### task-3
**Role:** CODER  
**Description:** Step 3 Implementation: Add pricing overview to Step-3.  
**Acceptance Criteria:**
- Step-3 container displays pricing overview with 3 plans (Basic/Pro/Enterprise)
- Pricing cards have hover effects and selection buttons
- app.js handles plan selection and price calculation
**Artifacts:**
- index.html (UPDATE)
- style.css (UPDATE)
- app.js (UPDATE)

### task-4
**Role:** CODER  
**Description:** Finalization: Add summary and completion to Step-4.  
**Acceptance Criteria:**
- Step-4 container displays summary of all user inputs
- Success message and restart button are present
- app.js generates summary, handles form submit, and restart functionality
**Artifacts:**
- index.html (UPDATE)
- style.css (UPDATE)
- app.js (UPDATE)
