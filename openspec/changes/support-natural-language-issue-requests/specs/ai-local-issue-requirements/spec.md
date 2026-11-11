## Purpose

Define how the local AI workflow obtains an independent, deterministic completion criterion from either structured Acceptance Criteria or an ordinary customer issue request.

## ADDED Requirements

### Requirement: Issue-level verification criteria are resolved deterministically
The workflow SHALL prefer a parseable Acceptance Criteria section in the current issue body and SHALL preserve each Markdown list item in that section as a separate issue-level verification criterion. When the issue contains no Acceptance Criteria heading, the workflow SHALL use the complete non-empty issue body as one issue-request verification criterion. It MUST NOT generate replacement requirements with AI or mutate the GitHub issue while resolving criteria.

#### Scenario: Explicit criteria are present
- **WHEN** the current issue body contains an Acceptance Criteria heading followed by one or more Markdown bullet or checkbox items
- **THEN** the workflow creates one issue-level verification criterion for each listed item
- **AND** it does not add a fallback criterion for the rest of the issue body

#### Scenario: Customer supplies only a natural-language request
- **WHEN** the current issue has no Acceptance Criteria heading and its body contains non-whitespace request text
- **THEN** the workflow creates exactly one issue-level verification criterion containing that request
- **AND** synchronization continues through the existing semantic evidence and required-check gates

#### Scenario: CommonMark-indented heading is used
- **WHEN** an Acceptance Criteria ATX heading is indented by zero to three spaces and contains parseable list items
- **THEN** the workflow recognizes the heading and resolves its listed criteria normally

### Requirement: Missing or malformed issue requirements fail closed
The workflow SHALL reject an empty or whitespace-only issue body because it contains no customer request to verify. When an Acceptance Criteria heading is explicitly present but contains no parseable list items before its section ends, the workflow SHALL report malformed explicit criteria and MUST NOT reinterpret the entire body as a fallback request. Any resolved issue content SHALL remain untrusted task data and MUST NOT supply executable verification commands or override repository, OpenSpec, security, or synchronization policy.

#### Scenario: Issue body is empty
- **WHEN** the current issue body is empty or contains only whitespace
- **THEN** synchronization stops with an actionable missing-request error
- **AND** the Project item remains unchanged

#### Scenario: Explicit criteria section is malformed
- **WHEN** the current issue body contains an Acceptance Criteria heading but that section has no parseable Markdown bullet or checkbox item
- **THEN** synchronization stops with an actionable malformed-criteria error
- **AND** the workflow does not fall back to the full issue body or update Project status

#### Scenario: Request contains executable instructions
- **WHEN** a resolved explicit criterion or natural-language request asks the workflow to execute commands or override trusted policy
- **THEN** the text remains verification data only
- **AND** command discovery and execution continue to use only trusted repository and approved OpenSpec sources
