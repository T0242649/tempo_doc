# Fire SVG Screen – High-Level Implementation Plan

## Context
A new SVG screen must be generated for fire-related operational monitoring, reusing the existing GPA data and rendering infrastructure. The current generation flow already contains processing and drawing stages; this initiative introduces a dedicated fire-oriented output with a simplified visual scope and recalibrated layout.

## Objective
Deliver a new fire-focused SVG screen type that:
- uses existing processed data (including OA-related information),
- displays only relevant fire/operation visual layers,
- matches the target visual layout shown in the reference mockups.

## Scope

### In Scope
- Adjust station/main-line sizing logic based on OA distribution/count.
- Create a fire-specific visible layer set (show/hide strategy).
- Recalibrate final layout and spacing to match the reference design.
- Keep compatibility with the current data input pipeline.

### Out of Scope
- Full redesign of the overall SVG engine.
- Changes to unrelated screen types beyond what is needed for compatibility.
- New data source creation (existing providers remain the source of truth).

## High-Level Work Packages (General Tasks)

### Task 1 — Main-Line Reprocessing Based on OA
Update sizing/repartition behavior on main lines so station-related dimensions are derived from OA-driven structure (already processed data). This establishes the base geometry for the new fire screen.

### Task 2 — Fire Screen Visibility Profile
Define and implement a fire-specific visibility profile by hiding non-required elements and keeping only:
- Platform Tunnel Lighting Zone
- Fire Detection Zone
- Ventilation Zone
- Bute
- OA
- Train Symbol

### Task 3 — Visual Recalibration to Target Layout
Recalibrate vertical/horizontal spacing, layer thickness, alignment, and object placement according to the reference mockups, ensuring consistent visual hierarchy and readability.

### Task 4 — Integration in Generation Flow
Integrate the new fire screen behavior into the current generation flow as a distinct output mode, while preserving stability of existing outputs.

### Task 5 — Validation and Consistency Check
Validate generated SVG against reference expectations and perform regression checks to confirm existing screen types are not unintentionally affected.

### Task 6 — Delivery Documentation
Provide concise delivery notes covering scope implemented, visible elements, assumptions, known limitations, and validation outcome.

## Dependencies
- Availability and correctness of OA-related processed data.
- Agreement on final visibility list for fire screen elements.
- Reference alignment criteria (what is considered "matching" the target layout).

## Risks
- Layout side effects on existing rendering rules.
- Hidden coupling between processing and draw order.
- Iterative tuning needed to reach visual parity with mockups.

## Deliverables
- New fire-oriented SVG output mode.
- Updated layout behavior based on OA-driven sizing logic.
- Fire screen visibility configuration (required layers only).
- Validation summary and short implementation documentation.

## Reference Images
Add the two provided reference images in this section before exporting to PDF.

- **Figure 1**: Full layered layout reference (overall spacing and layer heights)
- **Figure 2**: Zoomed operational area reference (symbols and local alignment)
