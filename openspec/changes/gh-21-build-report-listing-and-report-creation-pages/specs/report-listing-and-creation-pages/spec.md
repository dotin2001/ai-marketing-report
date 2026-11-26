## Purpose

Let an authenticated report owner find existing reports and create a new report with clear validation and request feedback as the first step of the marketing reporting workflow.

## ADDED Requirements

### Requirement: Show an owner-scoped report listing
The report listing SHALL render the summaries returned by the authenticated `GET /api/v1/reports` contract, including each report's name, inclusive start and end dates, and server-derived stage. It SHALL offer a route to the creation form. It MUST NOT infer a report stage from missing fields, display another owner's data, or treat unauthenticated access as an empty collection.

#### Scenario: Reports are available
- **WHEN** an authenticated listing request returns one or more report summaries
- **THEN** the page displays each returned name, inclusive period, and stage with a clear creation action

#### Scenario: No reports are available
- **WHEN** an authenticated listing request succeeds with an empty `data` array
- **THEN** the page displays an empty state explaining that no reports exist and offers creation

### Requirement: Present explicit listing request and pagination states
The listing SHALL distinguish loading, success, empty, recoverable request failure, and unauthenticated states. It SHALL use the API's opaque `page.next_cursor` only when `page.has_more` is true, append subsequent pages in server order without duplicate report IDs, and offer recovery from an invalid cursor by restarting at the first page. A failed subsequent page SHALL preserve already displayed reports.

#### Scenario: Initial request is pending or fails
- **WHEN** the first listing request is pending or fails
- **THEN** the page presents an accessible loading state or a safe error with a retry action, respectively

#### Scenario: Owner is unauthenticated
- **WHEN** the API responds `401 unauthenticated`
- **THEN** the page presents an authentication-required state and does not display an empty-list message

#### Scenario: Owner loads another page
- **WHEN** the response has `has_more: true` and a `next_cursor`, and the owner requests more
- **THEN** the next request uses that cursor without parsing it and appends distinct summaries in response order

#### Scenario: Later page fails
- **WHEN** loading a subsequent page fails or returns `400 invalid_cursor`
- **THEN** existing summaries remain visible and the page offers retry or a first-page restart for an invalid cursor

### Requirement: Validate report creation fields
The creation form SHALL collect a name, inclusive start and end calendar dates, and 1–20 objectives. Before submission it SHALL trim and require a 1–200 character name, require dates in `YYYY-MM-DD` form with end on or after start, and trim and require each objective to contain 1–2,000 characters. It SHALL identify invalid fields, support adding and removing objectives within those limits, and use the server's `422 validation_failed` detail paths to display additional safe field errors. Validation errors SHALL preserve all entered values.

#### Scenario: Valid creation fields
- **WHEN** a user enters a non-blank bounded name, valid inclusive period, and at least one bounded non-blank objective
- **THEN** the form permits submission of the normalized values to `POST /api/v1/reports`

#### Scenario: Invalid creation fields
- **WHEN** a name or objective is blank or too long, the objective count is outside 1–20, a date is malformed, or the end precedes the start
- **THEN** the form blocks submission, identifies the affected fields, and retains the entered values

#### Scenario: Server rejects a field
- **WHEN** creation returns `422 validation_failed` with field paths
- **THEN** the form shows the corresponding safe field feedback and retains the entered values for correction

### Requirement: Submit creation safely and show outcome
The creation form SHALL send an `Idempotency-Key` with a valid request, prevent concurrent repeated submissions, and reuse that key when retrying the same semantic command after an uncertain or retryable outcome. Editing the command SHALL use a fresh key. A successful creation or replay SHALL return the user to the listing with the created report visible. Creation failure SHALL distinguish authentication, validation, idempotency conflict, and recoverable service failure using safe API messages; it SHALL preserve form data and provide a suitable retry or correction action. It SHALL NOT imply that creating a report also attaches a source, starts analysis, creates a version, or exports a PDF.

#### Scenario: Repeated click or uncertain retry
- **WHEN** a user submits the same valid command repeatedly or retries after an uncertain outcome
- **THEN** at most one in-flight request is started at a time and the same command is retried with the same idempotency key

#### Scenario: Creation succeeds or is replayed
- **WHEN** creation returns a report detail successfully
- **THEN** the user returns to the listing and can see the new report in its server-derived `created` stage

#### Scenario: Creation fails without success
- **WHEN** the API responds with an authentication, validation, idempotency, or recoverable request error
- **THEN** the form retains entered data and presents safe, actionable feedback without claiming a report was created

### Requirement: Keep the pages accessible across viewport and motion settings
The listing and creation pages SHALL provide visible labels, keyboard-operable controls, meaningful focus after navigation or validation failure, announced loading and error status, usable small-screen layouts, sufficient contrast, and reduced-motion behavior.

#### Scenario: Keyboard user encounters validation error
- **WHEN** a keyboard user submits an invalid form
- **THEN** focus moves to the error summary or first invalid field, and field errors remain associated with their controls

#### Scenario: Narrow viewport or reduced motion
- **WHEN** the pages are used on a narrow viewport or with reduced motion enabled
- **THEN** all report data, form controls, and actions remain operable without motion-dependent feedback
