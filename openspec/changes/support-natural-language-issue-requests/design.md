## Context

See `proposal.md` for motivation and `specs/ai-local-issue-requirements/spec.md` for normative behavior. Synchronization builds its semantic verification manifest in `scripts/ai-local/verification.mjs`. The current parser recognizes only an unindented Acceptance Criteria heading with bullet items and throws `acceptance_criteria_missing` for every other body, including a meaningful plain-language request and a heading indented within CommonMark's allowance.

Issue text is untrusted. It may define what outcome must be verified, but it cannot become a source of executable commands, repository policy, or GitHub mutations. The existing workflow already fingerprints the live issue and verifies every manifest entry before the narrow Todo-to-Done mutation; this change must preserve those gates.

## Goals / Non-Goals

**Goals:**

- Resolve issue-level criteria deterministically without requiring customers to know a Markdown template.
- Preserve explicit Acceptance Criteria as the higher-fidelity contract when authors provide them.
- Distinguish an absent heading from a deliberately present but malformed criteria section.
- Keep issue content untrusted and preserve all current verification and synchronization gates.

**Non-Goals:**

- Generate, rewrite, summarize, or persist acceptance criteria with AI.
- Mutate issue bodies, comments, checkboxes, or issue state.
- Allow issue text to declare verification commands or override trusted instructions.
- Make title-only or empty-body issues eligible for synchronization.

## Decisions

### 1. Resolve explicit criteria first, then use one deterministic fallback criterion

The parser will scan the current issue body for an Acceptance Criteria heading. If it finds a valid section, it will return the existing one-entry-per-list-item representation. If it finds no such heading, it will trim the body and return the complete remaining text as one `issue_criterion` with a stable fallback identifier and source reference.

Using the complete body avoids an AI-authored interpretation and preserves the customer's own request as the independent completion contract. Splitting prose into sentences was rejected because punctuation, abbreviations, and Markdown make sentence boundaries ambiguous and could change the meaning. Using the issue title as a fallback was rejected because titles are commonly too short to verify safely.

### 2. Treat an explicitly malformed section differently from an absent section

The parser will track whether it encountered an Acceptance Criteria heading separately from whether it collected list items. A present heading with zero parseable items will produce `acceptance_criteria_malformed`; an empty or whitespace-only body with no heading will produce `issue_request_missing`. Neither case may fall back or reach verification.

This prevents a malformed explicit contract from being silently broadened to the whole body. Treating both cases as a natural-language fallback was rejected because an author who intentionally created a criteria section reasonably expects that section to be authoritative.

### 3. Recognize CommonMark-compatible ATX heading indentation

Heading recognition will allow zero to three leading spaces before one to six `#` characters while retaining the current case-insensitive Acceptance Criteria name and section-level termination rules. Four or more leading spaces remain non-heading content because CommonMark treats them as an indented code block.

Accepting arbitrary leading whitespace was rejected because code blocks containing example headings must not become live criteria sections.

### 4. Preserve manifest, fingerprint, and command trust boundaries

The fallback entry will use the same `issue_criterion` kind consumed by semantic verification, so no downstream verifier bypass is introduced. The existing raw-issue fingerprint continues to invalidate evidence whenever the customer edits the request. Verification-command discovery remains limited to trusted repository instructions, approved OpenSpec artifacts, and declared scripts; neither explicit nor fallback issue criteria are scanned as command sources.

Creating a new manifest kind was rejected because the semantic meaning is unchanged: both forms are issue-level completion criteria. Automatically editing GitHub to add generated criteria was rejected because it would mutate customer-authored content and let AI redefine the source contract.

## Risks / Trade-offs

- **[Risk] A long or broad issue body becomes one demanding semantic criterion** → Preserve it verbatim so verification must evidence the full customer request; explicit bullet criteria remain recommended for complex work.
- **[Risk] A typo that resembles an Acceptance Criteria heading but has no list items blocks synchronization** → Return a distinct actionable malformed-section error rather than silently weakening the contract.
- **[Risk] Multiline fallback text increases verification prompt size** → Use only the existing bounded issue body already loaded by the workflow and avoid duplicating it into generated criteria.
- **[Trade-off] Natural-language fallback is less granular than explicit bullets** → Keep all OpenSpec requirements, scenarios, tasks, and repository checks as additional mandatory manifest entries.

## Migration Plan

1. Update the parser and error outcomes without changing manifest or evidence schema versions.
2. Add focused parser/manifest tests for explicit, indented, plain-text, empty, and malformed bodies plus a synchronization regression that cannot mutate Done when fallback verification fails.
3. Update workflow documentation to mark explicit criteria as recommended rather than mandatory.
4. Run the focused Node tests, the complete `npm test` suite, and strict OpenSpec validation.

No data migration or GitHub update is required. Rolling back the parser and documentation restores the previous strict-heading behavior; existing evidence for explicitly structured issues remains compatible.
