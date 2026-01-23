---
name: design-doc
description: Create a detailed design document in a repo's design/ folder using its template and conventions. Use when the user asks for a design doc, design document, or "$design-doc" that should be numbered (NNN-...), formatted like design/000-design-template.md and design/000-design-example.md, and focused on architecture, workflows, APIs, dependencies, and tests (not implementation).
---

# Design Doc

## Goal

Turn a user prompt into a **highly detailed design document** saved under `design/NNN-kebab-title.md`, following the
repo’s template and conventions. This skill is design-only (no implementation) and does not perform external research.

## Minimal workflow (step-by-step)

Throughout the workflow, do not browse the web. Use only local repo files and user-provided resources.

1. **Scan context quickly**
   - Read `design/000-design-template.md` and `design/000-design-example.md`.
   - Skim other `design/*.md` files to match section order, tone, and depth.
   - Read only the repo files required to understand the feature area.

2. **Ask follow-ups only if blocking**
   - Ask **at most 1-2** questions.
   - Prefer multiple-choice or short answers.
   - If not blocked, make a reasonable assumption and proceed.

3. **Determine the filename (NNN-kebab-title.md)**
   - Use the repo’s `NNN-kebab-title.md` pattern (three-digit, zero-padded).
   - Find the highest existing number in `design/` and increment by 1.
   - Convert the feature title to lowercase kebab-case.
   - If the repo treats `000-*` files as templates/examples, do not count them as the latest feature.

4. **Create the design doc using the template below (super detailed)**
   - Follow the section order exactly.
   - Fill each section with concrete, specific detail.
   - Use Mermaid diagrams for call graphs, sequences, and dependencies.
   - Keep content implementation-agnostic; describe design, APIs, and tests.

5. **Quality bar**
   - Section order matches the template.
   - Mermaid diagrams are valid and referenced.
   - File paths and APIs match repo conventions.
   - Testing plan mirrors module structure and includes integration coverage.
   - All template placeholder text is removed.

## Design doc template (follow exactly)

Use the repo’s template if it differs; otherwise follow this skeleton exactly.

````markdown
# Design Document: <Feature/Module Name>

## Overview

### High-Level Description

### Goals

### Non-Goals

## Workflows

### Workflow 1: <Name>

#### Description

#### Usage Example

```python
```

### Call Graph

```mermaid
```

#### Sequence Diagram

```mermaid
```

#### Key Components

### Workflow 2: <Name>

## Dependencies

```mermaid
```

## Detailed Design

### Module Structure

```text
```

### API Design

#### `path/to/module.py`

```python
```

## Testing Strategy

## Implementation

### Implementation Order

### Tasks

## Open Questions

## Future Enhancements

## Libraries

### New Libraries

### Existing Libraries

## Alternative Approaches

### Approach 1: <Name>

```text

## Section guidance (be super detailed)
```
````

Good:

- **Overview**: Clear problem statement, why it matters, and how this design solves it. Goals are testable.
- **Workflows**: Each workflow includes Description, Usage Example, Call Graph, Key Components, plus a Sequence Diagram
  when multi-component.
- **Dependencies**: Mermaid graph clearly labels new vs existing modules.
- **Detailed Design**: File tree + API stubs with numbered steps describing logic.
- **Testing Strategy**: Unit tests by module, integration tests per workflow, explicit edge cases.
- **Implementation**: Leaf nodes first; tasks list shows dependency ordering.
- **Open Questions**: Include only if there are unknowns; keep to 1-3 items.

Avoid:

- Vague goals or missing non-goals.
- Skipping Mermaid diagrams.
- Omitting integration tests.
- Embedding production code (keep design-level detail).

## Output rules

- Do not perform external research; rely only on user input and local repo files.
- Write the design document to `design/NNN-kebab-title.md`.
- Do not implement production code; keep content design-focused.
- Use Mermaid diagrams for call graphs, sequence flows, and dependencies.
- Use the repo’s terminology and naming conventions.
- Do not preface the design doc with meta commentary; output the doc content directly.

## Trigger examples

- “Help me come up with a $design-doc for implementing…”
- “Create a design document following design/000-design-template.md…”
- “Write a design doc for a new module with workflows, dependencies, and tests…”

## Non-trigger example

- “Implement the feature now” (this skill only creates design docs)
