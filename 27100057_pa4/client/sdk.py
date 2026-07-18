"""Reliable Python client SDK for the deployed Document Analyst (Part 3)."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator

import httpx
from dotenv import load_dotenv


class AnalystClientError(Exception):
    def __init__(self, message: str, status_code=None, request_id=None):
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id


class DocumentAnalystClient:
    def __init__(
        self,
        endpoint_name: str,
        host: str | None = None,
        token: str | None = None,
        timeout: float = 120.0,
        max_retries: int = 3,
    ) -> None:
        load_dotenv()
        self.endpoint_name = endpoint_name
        self.host = (host or os.environ.get("DATABRICKS_HOST", "")).rstrip("/")
        self.token = token or os.environ.get("DATABRICKS_TOKEN", "")
        if not endpoint_name:
            raise ValueError("endpoint_name cannot be empty")
        if not self.host or not self.token:
            raise OSError("DATABRICKS_HOST and DATABRICKS_TOKEN are required")
        if timeout <= 0 or max_retries < 0:
            raise ValueError("timeout must be positive and max_retries cannot be negative")
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            timeout=timeout,
        )

    @property
    def _invocations_url(self) -> str:
        return f"{self.host}/serving-endpoints/{self.endpoint_name}/invocations"

    def _error(self, response: httpx.Response) -> AnalystClientError:
        try:
            body = response.json()
            message = body.get("message") or body.get("error", {}).get("message") or response.text
        except (ValueError, AttributeError):
            message = response.text
        request_id = response.headers.get("x-request-id") or response.headers.get("x-databricks-request-id")
        return AnalystClientError(message, response.status_code, request_id)

    def _post(self, payload: dict) -> httpx.Response:
        started = time.monotonic()
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.post(self._invocations_url, json=payload)
            except httpx.TimeoutException as exc:
                elapsed = time.monotonic() - started
                raise TimeoutError(f"Request timed out after {elapsed:.3f} seconds") from exc
            if response.status_code not in (429, 503):
                if response.is_error:
                    raise self._error(response)
                return response
            if attempt == self.max_retries:
                raise self._error(response)
            time.sleep(min(2**attempt, 8))
        raise RuntimeError("unreachable")

    @staticmethod
    def _answer(data: dict | list) -> str:
        # MLflow's LangGraph flavor can return the single prediction directly
        # as a one-element list instead of wrapping it in ``predictions``.
        if isinstance(data, list):
            if not data:
                raise AnalystClientError("Endpoint response did not contain an answer")
            data = data[0]
        if not isinstance(data, dict):
            raise AnalystClientError("Endpoint returned an unsupported response shape")
        choices = data.get("choices")
        if choices:
            message = choices[0].get("message", {})
            return str(message.get("content", choices[0].get("text", "")))
        predictions = data.get("predictions")
        if predictions:
            item = predictions[0] if isinstance(predictions, list) else predictions
            if isinstance(item, dict):
                messages = item.get("messages", [])
                if messages:
                    last = messages[-1]
                    return str(last.get("content", last) if isinstance(last, dict) else last)
                return str(item.get("final_answer", item))
            return str(item)
        if "final_answer" in data:
            return str(data["final_answer"])
        raise AnalystClientError("Endpoint response did not contain an answer")

    def ask(self, question: str) -> str:
        if not question.strip():
            raise ValueError("question cannot be empty")
        response = self._post({"messages": [{"role": "user", "content": question}]})
        return self._answer(response.json())

    def ask_streaming(self, question: str) -> Iterator[str]:
        if not question.strip():
            raise ValueError("question cannot be empty")
        payload = {"messages": [{"role": "user", "content": question}], "stream": True}
        started = time.monotonic()
        try:
            with self._client.stream("POST", self._invocations_url, json=payload) as response:
                if response.is_error:
                    response.read()
                    error = self._error(response)
                    if (
                        response.status_code in (400, 422)
                        and "does not support streaming" in str(error).lower()
                    ):
                        # Models-from-code endpoints without ``predict_stream``
                        # reject stream=true. A single complete chunk is the
                        # documented fallback for this client API.
                        yield self.ask(question)
                        return
                    raise error
                yielded = False
                buffered = []
                for line in response.iter_lines():
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        buffered.append(line)
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    event = json.loads(raw)
                    choices = event.get("choices", [])
                    chunk = ""
                    if choices:
                        chunk = choices[0].get("delta", {}).get("content", "")
                        chunk = chunk or choices[0].get("message", {}).get("content", "")
                    if chunk:
                        yielded = True
                        yield chunk
                if not yielded and buffered:
                    yield self._answer(json.loads("".join(buffered)))
        except httpx.TimeoutException as exc:
            elapsed = time.monotonic() - started
            raise TimeoutError(f"Streaming request timed out after {elapsed:.3f} seconds") from exc

    def health_check(self) -> bool:
        url = f"{self.host}/api/2.0/serving-endpoints/{self.endpoint_name}"
        try:
            response = self._client.get(url)
            if response.is_error:
                return False
            state = response.json().get("state", {})
            return state.get("ready", "").upper() == "READY"
        except (httpx.HTTPError, ValueError):
            return False

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
