"""One bounded async Responses request per claimed analysis attempt."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

import openai
from pydantic import ValidationError

from app.ai.context import PreparedContext
from app.ai.errors import AnalysisExecutionFailure
from app.ai.output import RunnerOutput
from app.ai.prompt import MAX_OUTPUT_TOKENS, PROMPT_VERSION, SYSTEM_PROMPT, request_input
from app.ai.wire import WireOutput, convert_wire
from app.core.config import Settings

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")
_SAFE_RESPONSE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class ResponsesClient(Protocol):
    async def parse(self, **kwargs: Any) -> Any: ...


class OpenAIClient(Protocol):
    responses: ResponsesClient


def _has_refusal(response: Any) -> bool:
    for output in getattr(response, "output", None) or []:
        if getattr(output, "type", None) == "refusal":
            return True
        for content in getattr(output, "content", None) or []:
            if getattr(content, "type", None) == "refusal":
                return True
    return False


class OpenAIAnalysisAdapter:
    def __init__(self, settings: Settings, client: OpenAIClient) -> None:
        self._model = settings.openai_model
        self._timeout = settings.openai_timeout_seconds
        self._client = client

    async def __call__(self, context: PreparedContext) -> RunnerOutput:
        try:
            bounded_input, digest = request_input(context)
        except ValueError as error:
            raise AnalysisExecutionFailure("provider_unavailable", retryable=False) from error
        try:
            response = await self._client.responses.parse(
                model=self._model,
                instructions=SYSTEM_PROMPT,
                input=bounded_input,
                text_format=WireOutput,
                max_output_tokens=MAX_OUTPUT_TOKENS,
                timeout=self._timeout,
                store=False,
                background=False,
            )
        except (openai.APITimeoutError, TimeoutError) as error:
            raise AnalysisExecutionFailure("provider_timeout", retryable=True) from error
        except (
            openai.APIConnectionError,
            openai.RateLimitError,
            openai.InternalServerError,
        ) as error:
            raise AnalysisExecutionFailure("provider_unavailable", retryable=True) from error
        except openai.APIStatusError as error:
            raise AnalysisExecutionFailure(
                "provider_unavailable", retryable=error.status_code >= 500
            ) from error
        except (ValidationError, json.JSONDecodeError, openai.APIResponseValidationError) as error:
            raise AnalysisExecutionFailure("invalid_structured_output", retryable=False) from error
        except Exception as error:
            raise AnalysisExecutionFailure("provider_unavailable", retryable=True) from error
        if _has_refusal(response):
            raise AnalysisExecutionFailure("provider_refusal", retryable=False)
        parsed = getattr(response, "output_parsed", None)
        if getattr(response, "status", None) != "completed":
            if parsed is None:
                raise AnalysisExecutionFailure("incomplete_response", retryable=True)
            raise AnalysisExecutionFailure("invalid_structured_output", retryable=False)
        if parsed is None:
            raise AnalysisExecutionFailure("invalid_structured_output", retryable=False)
        model_id = getattr(response, "model", None)
        response_id = getattr(response, "id", None)
        if (
            not isinstance(model_id, str)
            or not _SAFE_IDENTIFIER.fullmatch(model_id)
            or not isinstance(response_id, str)
            or not _SAFE_RESPONSE_ID.fullmatch(response_id)
        ):
            raise AnalysisExecutionFailure("invalid_structured_output", retryable=False)
        try:
            wire = WireOutput.model_validate(
                parsed.model_dump() if isinstance(parsed, WireOutput) else parsed
            )
            structured = convert_wire(wire)
            return RunnerOutput(
                model_identifier=model_id,
                prompt_version=PROMPT_VERSION,
                request_provenance=(
                    f"response={response_id};prompt={PROMPT_VERSION};"
                    f"context={context.version};digest=sha256:{digest}"
                ),
                response=structured,
            )
        except (ValidationError, ValueError, TypeError) as error:
            raise AnalysisExecutionFailure("invalid_structured_output", retryable=False) from error
