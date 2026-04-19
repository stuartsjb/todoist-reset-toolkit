#!/usr/bin/env python3
"""Interactive Todoist account reset helper."""

from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

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
    print("Then run:")
    print("  python3 todoist_reset.py")
    raise SystemExit(1) from exc


API_V1_BASE = "https://api.todoist.com/api/v1"
SYNC_BASE = f"{API_V1_BASE}/sync"
PAGE_LIMIT = 200
COMPLETED_WINDOW_DAYS = 89
NETWORK_RETRY_SECONDS = 60
SERVER_RETRY_SECONDS = 300
ENV_FILE = Path(".env")
STATE_FILE = Path(".todoist-reset-state.json")


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


@dataclass
class TokenContext:
    token: str
    source: str


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


def mask_token(token: str) -> str:
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"


def read_env_token() -> str | None:
    load_dotenv(dotenv_path=ENV_FILE)
    token = os.getenv("TODOIST_TOKEN", "").strip()
    if token and token != "your_todoist_api_token_here":
        return token
    return None


def write_env_token(token: str) -> None:
    completed_since = "2000-01-01T00:00:00Z"
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("TODOIST_COMPLETED_SINCE="):
                completed_since = line.split("=", 1)[1].strip()
                break

    ENV_FILE.write_text(
        "\n".join(
            [
                f"TODOIST_TOKEN={token}",
                f"TODOIST_COMPLETED_SINCE={completed_since}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def prompt_for_token() -> TokenContext | None:
    while True:
        print()
        print("No Todoist API token found.")
        print("1. Enter token and save locally in .env")
        print("2. Enter token for this session only")
        print("3. Show where to find the token")
        print("0. Exit")
        choice = input("> ").strip()

        if choice == "1":
            token = getpass.getpass("Todoist API token: ").strip()
            if token:
                write_env_token(token)
                print(f"Saved token locally as {mask_token(token)}.")
                return TokenContext(token=token, source="saved locally")
        elif choice == "2":
            token = getpass.getpass("Todoist API token: ").strip()
            if token:
                print(f"Using token for this session as {mask_token(token)}.")
                return TokenContext(token=token, source="session only")
        elif choice == "3":
            print()
            print("In Todoist, open Settings -> Integrations -> Developer -> API token.")
            print("Do not commit your token to git. This tool keeps .env ignored.")
        elif choice == "0":
            return None
        else:
            print("Please choose one of the menu options.")


def get_token_context() -> TokenContext | None:
    token = read_env_token()
    if token:
        return TokenContext(token=token, source="saved locally")

    env_token = os.environ.get("TODOIST_TOKEN", "").strip()
    if env_token:
        return TokenContext(token=env_token, source="process environment")

    return prompt_for_token()


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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
    token: str, url: str, params: dict[str, str | int] | None = None
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
            wait_for_retry("Rate limited while inspecting Todoist.", max(exc.retry_after, 1.0))
        except TodoistRetryableHttpError as exc:
            print(exc)
            wait_for_retry(
                "Temporary Todoist server error while inspecting Todoist.",
                max(exc.retry_after, 1.0),
            )
        except requests.RequestException as exc:
            print(f"Transient network error while inspecting Todoist: {exc}")
            wait_for_retry("Network error while inspecting Todoist.", NETWORK_RETRY_SECONDS)


def post_sync_with_retries(token: str, data: dict[str, str]) -> dict:
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
            wait_for_retry("Rate limited while inspecting Todoist.", max(exc.retry_after, 1.0))
        except TodoistRetryableHttpError as exc:
            print(exc)
            wait_for_retry(
                "Temporary Todoist server error while inspecting Todoist.",
                max(exc.retry_after, 1.0),
            )
        except requests.RequestException as exc:
            print(f"Transient network error while inspecting Todoist: {exc}")
            wait_for_retry("Network error while inspecting Todoist.", NETWORK_RETRY_SECONDS)


def fetch_paginated(token: str, url: str) -> list[dict]:
    cursor: str | None = None
    results: list[dict] = []

    while True:
        params: dict[str, str | int] = {"limit": PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        payload = get_json_with_retries(token, url, params)
        results.extend(payload.get("results", []))
        cursor = payload.get("next_cursor")
        if not cursor:
            return results


def completed_windows(since: datetime, until: datetime) -> list[tuple[datetime, datetime]]:
    windows: list[tuple[datetime, datetime]] = []
    current = since
    while current < until:
        window_end = min(current + timedelta(days=COMPLETED_WINDOW_DAYS), until)
        windows.append((current, window_end))
        current = window_end
    return windows


def count_completed_tasks(token: str, since: datetime) -> int:
    seen_ids: set[str] = set()
    until = utc_now()

    for window_start, window_end in completed_windows(since, until):
        cursor: str | None = None
        while True:
            params: dict[str, str | int] = {
                "since": window_start.isoformat().replace("+00:00", "Z"),
                "until": window_end.isoformat().replace("+00:00", "Z"),
                "limit": PAGE_LIMIT,
            }
            if cursor:
                params["cursor"] = cursor
            payload = get_json_with_retries(
                token,
                f"{API_V1_BASE}/tasks/completed/by_completion_date",
                params,
            )
            for task in payload.get("items", []):
                seen_ids.add(str(task["id"]))
            cursor = payload.get("next_cursor")
            if not cursor:
                break

    return len(seen_ids)


def active_items(items: list[dict]) -> list[dict]:
    return [item for item in items if not item.get("is_deleted", False)]


def inspect_account(token: str) -> dict:
    print("Inspecting account. This is read-only, but completed history scans can take a while.")
    active_tasks = fetch_paginated(token, f"{API_V1_BASE}/tasks")
    active_projects = fetch_paginated(token, f"{API_V1_BASE}/projects")
    archived_projects = fetch_paginated(token, f"{API_V1_BASE}/projects/archived")
    completed_tasks = count_completed_tasks(
        token,
        datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    sync_state = post_sync_with_retries(
        token,
        {
            "sync_token": "*",
            "resource_types": json.dumps(["all"]),
        },
    )

    live_notifications = active_items(sync_state.get("live_notifications", []))
    unread_notifications = [
        item for item in live_notifications if item.get("is_unread", False)
    ]

    state = {
        "checked_at": utc_now().isoformat().replace("+00:00", "Z"),
        "active_tasks": len(active_tasks),
        "completed_tasks": completed_tasks,
        "active_projects": len(active_projects),
        "archived_projects": len(archived_projects),
        "labels": len(active_items(sync_state.get("labels", []))),
        "filters": len(active_items(sync_state.get("filters", []))),
        "workspace_filters": len(active_items(sync_state.get("workspace_filters", []))),
        "sections": len(active_items(sync_state.get("sections", []))),
        "reminders": len(active_items(sync_state.get("reminders", []))),
        "notes": len(active_items(sync_state.get("notes", []))),
        "locations": len(sync_state.get("locations", [])),
        "live_notifications_total": len(live_notifications),
        "live_notifications_unread": len(unread_notifications),
        "view_options": len(active_items(sync_state.get("view_options", []))),
    }
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return state


def load_cached_state() -> dict | None:
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def print_state(state: dict | None) -> None:
    if not state:
        print("Last account inspection: none")
        return

    print(f"Last account inspection: {state.get('checked_at', '<unknown>')}")
    print(f"  Active tasks:        {state.get('active_tasks', '?')}")
    print(f"  Completed tasks:     {state.get('completed_tasks', '?')}")
    print(f"  Active projects:     {state.get('active_projects', '?')}")
    print(f"  Archived projects:   {state.get('archived_projects', '?')}")
    print(f"  Labels:              {state.get('labels', '?')}")
    print(f"  Filters:             {state.get('filters', '?')}")
    print(f"  Workspace filters:   {state.get('workspace_filters', '?')}")
    print(f"  Sections:            {state.get('sections', '?')}")
    print(f"  Reminders:           {state.get('reminders', '?')}")
    print(f"  Comments/notes:      {state.get('notes', '?')}")
    print(f"  Saved locations:     {state.get('locations', '?')}")
    print(
        "  Live notifications:  "
        f"{state.get('live_notifications_total', '?')} total, "
        f"{state.get('live_notifications_unread', '?')} unread"
    )
    print(f"  View options:        {state.get('view_options', '?')}")


def confirm_apply(prompt: str) -> bool:
    print()
    print(prompt)
    typed = input("Type APPLY to continue, or press Enter to cancel: ").strip()
    return typed == "APPLY"


def run_script(args: list[str]) -> None:
    completed = subprocess.run([sys.executable, *args], check=False)
    if completed.returncode != 0:
        print(f"Command exited with status {completed.returncode}.")


def run_apply_workflow(script: str, dry_run_args: list[str], apply_args: list[str], prompt: str) -> None:
    print()
    print("Dry run")
    run_script([script, *dry_run_args])
    if confirm_apply(prompt):
        run_script([script, *apply_args])


def menu(token_context: TokenContext) -> None:
    actions: dict[str, tuple[str, Callable[[], None]]] = {
        "1": ("Refresh account inspection", lambda: print_state(inspect_account(token_context.token))),
        "2": (
            "Delete active and completed tasks",
            lambda: run_apply_workflow(
                "delete_todoist_tasks.py",
                ["--dry-run", "--reset-checkpoint"],
                ["--reset-checkpoint"],
                "This will delete active and completed tasks where Todoist allows it.",
            ),
        ),
        "3": (
            "Unarchive archived projects",
            lambda: run_apply_workflow(
                "unarchive_todoist_projects.py",
                [],
                ["--apply"],
                "This will unarchive all archived projects.",
            ),
        ),
        "4": (
            "Delete active projects except built-in Inbox",
            lambda: run_apply_workflow(
                "delete_todoist_projects.py",
                ["--dry-run"],
                [],
                "This will delete active projects that Todoist allows you to delete.",
            ),
        ),
        "5": (
            "Clean labels, filters, reminders, sections, comments, and locations",
            lambda: run_apply_workflow(
                "cleanup_todoist_misc.py",
                [],
                ["--apply"],
                "This will delete/clear safe non-task metadata.",
            ),
        ),
        "6": (
            "Clear UI metadata and mark notifications read",
            lambda: run_apply_workflow(
                "cleanup_todoist_misc.py",
                [],
                ["--apply", "--include-view-options", "--include-notifications"],
                "This will clear view options and mark notifications read.",
            ),
        ),
        "7": (
            "Export remaining completed-task report",
            lambda: run_script(
                [
                    "inspect_remaining_tasks.py",
                    "--completed-since",
                    "2000-01-01T00:00:00Z",
                    "--csv",
                    "remaining_completed_tasks.csv",
                ]
            ),
        ),
        "8": ("Settings", lambda: settings_menu(token_context)),
    }

    while True:
        print()
        print("Todoist Reset Toolkit")
        print(f"Token source: {token_context.source} ({mask_token(token_context.token)})")
        print_state(load_cached_state())
        print()
        for key, (label, _) in actions.items():
            print(f"{key}. {label}")
        print("0. Exit")
        choice = input("> ").strip()

        if choice == "0":
            return
        action = actions.get(choice)
        if action is None:
            print("Please choose one of the menu options.")
            continue
        action[1]()


def settings_menu(token_context: TokenContext) -> None:
    while True:
        print()
        print("Settings")
        print(f"Current token source: {token_context.source} ({mask_token(token_context.token)})")
        print("1. Replace token and save locally")
        print("2. Replace token for this session only")
        print("3. Clear cached account inspection")
        print("0. Back")
        choice = input("> ").strip()

        if choice == "1":
            token = getpass.getpass("Todoist API token: ").strip()
            if token:
                write_env_token(token)
                token_context.token = token
                token_context.source = "saved locally"
        elif choice == "2":
            token = getpass.getpass("Todoist API token: ").strip()
            if token:
                token_context.token = token
                token_context.source = "session only"
        elif choice == "3":
            if STATE_FILE.exists():
                STATE_FILE.unlink()
            print("Cleared cached account inspection.")
        elif choice == "0":
            return
        else:
            print("Please choose one of the menu options.")


def main() -> int:
    token_context = get_token_context()
    if token_context is None:
        return 0

    if load_cached_state() is None:
        print()
        print("No previous account inspection found.")
        choice = input("Run a read-only inspection now? [Y/n] ").strip().lower()
        if choice in {"", "y", "yes"}:
            print_state(inspect_account(token_context.token))

    menu(token_context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
