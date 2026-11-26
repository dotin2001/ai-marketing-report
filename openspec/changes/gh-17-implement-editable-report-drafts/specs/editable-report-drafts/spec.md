## Purpose

Enable report owners to save and reopen editable report content and chart declarations while preserving trusted metrics, provenance, and concurrent editing safety.

## ADDED Requirements

### Requirement: The active draft exposes editable content and chart configuration
The owner-authorized report detail and draft-save response SHALL expose the active draft revision, ordered objectives, narrative items grouped by supported sections, limitations, labeled claims, and ordered chart declarations with their referenced metric identities and safe presentation fields. A draft with no items in a collection SHALL expose an empty collection. Reads MUST NOT expose source content, internal object keys, credentials, or foreign resource metadata.

#### Scenario: Reopen a saved draft
- **WHEN** the owner retrieves a report after saving narrative, limitations, claims, and charts
- **THEN** the active draft contains those saved values in their declared order with the current revision and safe references

#### Scenario: Foreign or absent report is read
- **WHEN** a principal requests another owner's report or an unknown report
- **THEN** both return the same `404 resource_not_found` shape without disclosing draft content or revision

### Requirement: The owner can save permitted draft sections atomically
`PATCH /api/v1/reports/{report_id}/draft` SHALL accept `expected_revision >= 1` and at least one of `objectives`, `narrative`, `limitations`, `claims`, or `charts`. Each supplied collection SHALL replace that collection as a whole in the submitted order; omitted collections SHALL retain their saved values, and an empty supplied collection SHALL clear that collection except that objectives MUST remain nonempty. A successful effective save SHALL atomically advance the active draft revision once and return `200` with the complete `DraftDetail`; it SHALL NOT create a version, PDF, source, metric, or analysis result. Objectives SHALL retain their existing bounds and normalization. Narrative SHALL use only `summary`, `findings`, `anomalies`, `recommendations`, or `data_gaps` sections and supported observation, hypothesis, or user-claim labels. Claims SHALL remain explicitly labeled `user_claim`; nonblank text and deterministic ordering SHALL be required for each saved item. The request MUST reject undeclared or protected fields, including owner, lifecycle state, original source values, computed metric values, AI provenance, version identity, and job state.

#### Scenario: Save several sections together
- **WHEN** an owner submits a current revision with narrative, limitations, claims, and charts
- **THEN** all supplied collections are saved together, the revision advances exactly once, omitted objectives are preserved, and no immutable version or export is created

#### Scenario: Clear one section
- **WHEN** an owner submits an empty limitations collection and omits narrative and claims
- **THEN** limitations are cleared while narrative and claims retain their previous contents

#### Scenario: Invalid field or content
- **WHEN** a request contains an unknown field, a metric value override, a blank item, an unsupported section or classification, or an empty objectives list
- **THEN** it returns `422 validation_failed` with safe field details and leaves every collection and the draft revision unchanged

### Requirement: Draft saves detect conflicting revisions
Every draft mutation, including objective and chart edits, SHALL compare the submitted expected revision with the current active draft revision inside one transaction. A stale revision SHALL return `409 revision_conflict`, leave the stored draft unchanged, and SHALL NOT partially apply any collection or overwrite a newer edit. The response MUST permit the client to retain its unsaved submitted content for recovery. Authorization SHALL run before revealing revision or reference information.

#### Scenario: Two edits race
- **WHEN** two valid saves use the same current expected revision
- **THEN** at most one succeeds, the other receives `409 revision_conflict`, and the successful content is unchanged by the rejected save

#### Scenario: Foreign owner submits a stale revision
- **WHEN** a principal patches another owner's report with any expected revision
- **THEN** the response is the same safe `404 resource_not_found` as an unknown report, with no revision metadata

### Requirement: Charts and provenance references remain trustworthy
Each chart SHALL declare one of `bar`, `line`, or `table`, a nonblank title and scope, optional display labels, and one to eight unique metric-result IDs from the report's current compatible metric result set. The draft SHALL accept at most 16 charts. It MUST reject foreign, historical, stale, or missing metric references and any embedded numeric override. A claim source reference, when supplied, MUST belong to the same owner and report. Editing report presentation content MUST NOT alter immutable sources, calculated metrics, AI provenance, or prior versions. A changed draft revision SHALL prevent an in-flight analysis captured at an older relevant revision from overwriting the saved content.

#### Scenario: Valid chart is saved
- **WHEN** an owner saves an ordered chart using current computed metric IDs and supported presentation fields
- **THEN** the draft returns that chart and its metric identities without copying or altering metric values

#### Scenario: Unsupported chart reference is rejected
- **WHEN** a chart cites a metric from another owner, report, or noncurrent result set, repeats a metric ID, or includes a numeric override
- **THEN** the save is rejected atomically with a safe validation error and no draft revision change

#### Scenario: Draft changes during analysis
- **WHEN** a pending analysis finishes after the owner saves a newer draft revision
- **THEN** its stale result cannot overwrite the saved narrative, limitations, claims, or charts
