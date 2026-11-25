"""Safe analysis failure codes shared by the adapter and worker."""

SAFE_FAILURES = frozenset(
    {
        "provider_timeout",
        "provider_refusal",
        "provider_unavailable",
        "incomplete_response",
        "invalid_structured_output",
        "stale_result",
    }
)


class AnalysisExecutionFailure(Exception):
    def __init__(self, code: str, retryable: bool = True) -> None:
        if code not in SAFE_FAILURES:
            raise ValueError("unsupported analysis failure")
        self.code = code
        self.retryable = retryable
        super().__init__(code)
