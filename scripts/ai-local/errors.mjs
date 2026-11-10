export class WorkflowError extends Error {
  constructor(code, message, options = {}) {
    super(message, options);
    this.name = this.constructor.name;
    this.code = code;
    this.exitCode = options.exitCode ?? 1;
    this.details = options.details;
  }
}

export class UsageError extends WorkflowError {
  constructor(message, details) {
    super("invalid_arguments", message, { exitCode: 2, details });
  }
}

export class ConfigurationError extends WorkflowError {
  constructor(message, details) {
    super("invalid_configuration", message, { exitCode: 3, details });
  }
}

export class ProcessError extends WorkflowError {
  constructor(message, details) {
    super("process_error", message, { exitCode: 4, details });
  }
}

export class PreflightError extends WorkflowError {
  constructor(code, message, details) {
    super(code, message, { exitCode: 5, details });
  }
}

export class LockError extends WorkflowError {
  constructor(code, message, details) {
    super(code, message, { exitCode: 6, details });
  }
}

export class GitHubError extends WorkflowError {
  constructor(code, message, details) {
    super(code, message, { exitCode: 7, details });
  }
}

export class TraceabilityError extends WorkflowError {
  constructor(code, message, details) {
    super(code, message, { exitCode: 8, details });
  }
}

export class CodexError extends WorkflowError {
  constructor(code, message, details) {
    super(code, message, { exitCode: 9, details });
  }
}

export class OpenSpecValidationError extends WorkflowError {
  constructor(code, message, details) {
    super(code, message, { exitCode: 10, details });
  }
}

export class IdentityConflictError extends WorkflowError {
  constructor(field, expected, actual) {
    super("identity_conflict", `Identity conflict for ${field}.`, {
      exitCode: 11,
      details: { field, expected, actual },
    });
  }
}

export class VerificationError extends WorkflowError {
  constructor(code, message, details) {
    super(code, message, { exitCode: 12, details });
  }
}
