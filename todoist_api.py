"""Shared Todoist API helpers used by the reset toolkit scripts."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

try:
    import requests
    from dotenv import load_dotenv
except ModuleNotFoundError as exc:
    missing = exc.name or "a required package"
    print(f"Missing dependency: {missing}")
    print()
    print("Set up the virtual environment and install dependencies first:")
    print("  python3 -m venv .venv")
    print("  source .venv/bin/activate")
    print("  pip install -r requirements.txt")
    print()
    print("Then rerun your command.")
    raise SystemExit(1) from exc


API_V1_BASE = "https://api.todoist.com/api/v1"
SYNC_BASE = f"{API_V1_BASE}/sync"
PAGE_LIMIT = 200
NETWORK_RETRY_SECONDS = 60
SERVER_RETRY_SECONDS = 300


class TodoistError(RuntimeError):
    """Raised when Todoist API operations fail."""


class TodoistRateLimitError(TodoistError):
    """Raised when Todoist asks the client to retry later."""

    def __init__(self, retry_after: float, message: str) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TodoistRetryableHttpError(TodoistError):
    """Raised when Todoist returns a temporary server-side error."""

    def __init__(self, retry_after: float, message: str) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def load_token() -> str:
    load_dotenv(dotenv_path=Path(".env"))
    token = os.getenv("TODOIST_TOKEN", "").strip()
    if not token or token == "your_todoist_api_token_here":
        raise TodoistError(
            "TODOIST_TOKEN is missing. Put your real token in .env before running."
        )
    return token


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def format_utc_timestamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S UTC")


def wait_for_retry(action: str, wait_seconds: float) -> None:
    retry_at = utc_now() + timedelta(seconds=wait_seconds)
    print(
        f"{action} Retrying at {format_utc_timestamp(retry_at)} "
        f"(in {wait_seconds:.0f}s)..."
    )
    time.sleep(wait_seconds)
    print(f"{action} Retrying now at {format_utc_timestamp(utc_now())}...")


def raise_for_status(response: requests.Response) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        body = response.text.strip()
        if response.status_code == 429:
            retry_after = 60.0
            try:
                payload = response.json()
                retry_after = float(
                    payload.get("error_extra", {}).get("retry_after", retry_after)
                )
            except ValueError:
                pass
            raise TodoistRateLimitError(retry_after, "Todoist API rate limit reached.") from exc
        if response.status_code in {500, 502, 503, 504}:
            retry_after = SERVER_RETRY_SECONDS
            retry_after_header = response.headers.get("Retry-After")
            if retry_after_header:
                try:
                    retry_after = max(float(retry_after_header), 1.0)
                except ValueError:
                    pass
            message = f"Todoist temporary server error {response.status_code}"
            if body:
                message = f"{message}: {body}"
            raise TodoistRetryableHttpError(retry_after, message) from exc

        message = f"Todoist API error {response.status_code}"
        if body:
            message = f"{message}: {body}"
        raise TodoistError(message) from exc


def get_json_with_retries(
    token: str,
    url: str,
    params: dict[str, str | int] | None = None,
    action: str = "inspecting Todoist",
) -> dict:
    while True:
        try:
            response = requests.get(
                url,
                headers=auth_headers(token),
                params=params,
                timeout=30,
            )
            raise_for_status(response)
            return response.json()
        except TodoistRateLimitError as exc:
            wait_for_retry(f"Rate limited while {action}.", max(exc.retry_after, 1.0))
        except TodoistRetryableHttpError as exc:
            print(exc)
            wait_for_retry(
                f"Temporary Todoist server error while {action}.",
                max(exc.retry_after, 1.0),
            )
        except requests.RequestException as exc:
            print(f"Transient network error while {action}: {exc}")
            wait_for_retry(f"Network error while {action}.", NETWORK_RETRY_SECONDS)


def delete_with_retries(token: str, url: str, action: str) -> None:
    while True:
        try:
            response = requests.delete(
                url,
                headers=auth_headers(token),
                timeout=30,
            )
            raise_for_status(response)
            return
        except TodoistRateLimitError as exc:
            wait_for_retry(f"Rate limited while {action}.", max(exc.retry_after, 1.0))
        except TodoistRetryableHttpError as exc:
            print(exc)
            wait_for_retry(
                f"Temporary Todoist server error while {action}.",
                max(exc.retry_after, 1.0),
            )
        except requests.RequestException as exc:
            print(f"Transient network error while {action}: {exc}")
            wait_for_retry(f"Network error while {action}.", NETWORK_RETRY_SECONDS)


def post_json_with_retries(
    token: str,
    url: str,
    data: dict[str, str],
    action: str = "posting to Todoist",
) -> dict:
    while True:
        try:
            response = requests.post(
                url,
                headers=auth_headers(token),
                data=data,
                timeout=30,
            )
            raise_for_status(response)
            return response.json()
        except TodoistRateLimitError as exc:
            wait_for_retry(f"Rate limited while {action}.", max(exc.retry_after, 1.0))
        except TodoistRetryableHttpError as exc:
            print(exc)
            wait_for_retry(
                f"Temporary Todoist server error while {action}.",
                max(exc.retry_after, 1.0),
            )
        except requests.RequestException as exc:
            print(f"Transient network error while {action}: {exc}")
            wait_for_retry(f"Network error while {action}.", NETWORK_RETRY_SECONDS)


def sync_request(token: str, data: dict[str, str], action: str = "using sync API") -> dict:
    while True:
        try:
            response = requests.post(
                SYNC_BASE,
                headers=auth_headers(token),
                data=data,
                timeout=30,
            )
            raise_for_status(response)
            return response.json()
        except TodoistRateLimitError as exc:
            wait_for_retry(f"Rate limited while {action}.", max(exc.retry_after, 1.0))
        except TodoistRetryableHttpError as exc:
            print(exc)
            wait_for_retry(
                f"Temporary Todoist server error while {action}.",
                max(exc.retry_after, 1.0),
            )
        except requests.RequestException as exc:
            print(f"Transient network error while {action}: {exc}")
            wait_for_retry(f"Network error while {action}.", NETWORK_RETRY_SECONDS)


def fetch_paginated(token: str, url: str, action: str) -> list[dict]:
    cursor: str | None = None
    results: list[dict] = []

    while True:
        params: dict[str, str | int] = {"limit": PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        payload = get_json_with_retries(token, url, params, action)
        results.extend(payload.get("results", []))
        cursor = payload.get("next_cursor")
        if not cursor:
            return results


def fetch_sync_state(token: str) -> dict:
    return sync_request(
        token,
        {
            "sync_token": "*",
            "resource_types": json.dumps(["all"]),
        },
    )


def active(items: Iterable[dict]) -> list[dict]:
    return [item for item in items if not item.get("is_deleted", False)]


def chunks(items: list[dict], size: int) -> Iterable[list[dict]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def command(command_type: str, args: dict | None = None) -> dict:
    payload = {
        "type": command_type,
        "uuid": str(uuid.uuid4()),
    }
    if args is not None:
        payload["args"] = args
    return payload
