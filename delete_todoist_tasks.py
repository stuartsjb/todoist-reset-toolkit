#!/usr/bin/env python3
"""Delete all active and completed Todoist tasks using official Todoist APIs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from dotenv import load_dotenv

from todoist_api import (
    API_V1_BASE,
    PAGE_LIMIT,
    SYNC_BASE,
    TodoistError,
    command,
    delete_with_retries,
    get_json_with_retries,
    load_token,
    post_json_with_retries,
    utc_now,
)


COMPLETED_WINDOW_DAYS = 89
PROGRESS_EVERY = 100
DEFAULT_CHECKPOINT_FILE = ".todoist-delete-checkpoint.json"


class TodoistItemNotFoundError(TodoistError):
    """Raised when Todoist history references an item that can no longer be restored."""


@dataclass
class Stats:
    active_found: int = 0
    active_deleted: int = 0
    completed_found: int = 0
    completed_restored: int = 0
    completed_deleted: int = 0
    completed_skipped_not_found: int = 0
    oldest_completed_at: str | None = None
    oldest_completed_content: str | None = None
    latest_completed_seen_at: str | None = None


@dataclass
class Checkpoint:
    resume_since: str | None = None
    deleted: int = 0
    skipped_not_found: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Delete all Todoist tasks, including completed tasks, using official "
            "Todoist APIs."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be deleted without modifying the account.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.1,
        help="Delay between restore and delete operations for completed tasks.",
    )
    parser.add_argument(
        "--checkpoint-file",
        default=DEFAULT_CHECKPOINT_FILE,
        help="Path to the local JSON checkpoint file.",
    )
    parser.add_argument(
        "--reset-checkpoint",
        action="store_true",
        help="Ignore and overwrite any existing checkpoint.",
    )
    return parser.parse_args()


def load_required_env() -> tuple[str, datetime]:
    load_dotenv()

    token = load_token()
    since_raw = os.getenv("TODOIST_COMPLETED_SINCE", "2000-01-01T00:00:00Z").strip()
    try:
        since = datetime.fromisoformat(since_raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TodoistError(
            "TODOIST_COMPLETED_SINCE must be an ISO-8601 datetime like "
            "2000-01-01T00:00:00Z."
        ) from exc

    return token, since.astimezone(timezone.utc)


def load_checkpoint(path: Path) -> Checkpoint:
    if not path.exists():
        return Checkpoint()

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TodoistError(f"Unable to read checkpoint file {path}: {exc}") from exc

    return Checkpoint(
        resume_since=payload.get("resume_since"),
        deleted=int(payload.get("deleted", 0)),
        skipped_not_found=int(payload.get("skipped_not_found", 0)),
    )


def save_checkpoint(path: Path, checkpoint: Checkpoint) -> None:
    payload = {
        "resume_since": checkpoint.resume_since,
        "deleted": checkpoint.deleted,
        "skipped_not_found": checkpoint.skipped_not_found,
        "updated_at": utc_now().isoformat().replace("+00:00", "Z"),
    }
    try:
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise TodoistError(f"Unable to write checkpoint file {path}: {exc}") from exc


def remove_checkpoint(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError as exc:
        raise TodoistError(f"Unable to remove checkpoint file {path}: {exc}") from exc


def paginate_tasks(token: str) -> Iterable[dict]:
    cursor: str | None = None
    while True:
        params: dict[str, str | int] = {"limit": PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor

        payload = get_json_with_retries(
            token,
            f"{API_V1_BASE}/tasks",
            params,
            "listing active tasks",
        )

        for task in payload.get("results", []):
            yield task

        cursor = payload.get("next_cursor")
        if not cursor:
            break


def delete_task(token: str, task_id: str) -> None:
    delete_with_retries(token, f"{API_V1_BASE}/tasks/{task_id}", "deleting a task")


def should_log_progress(
    index: int, total: int | None = None, every: int = PROGRESS_EVERY
) -> bool:
    if index == 1 or index % every == 0:
        return True
    if total is not None and index == total:
        return True
    return False


def completed_windows(since: datetime, until: datetime) -> Iterable[tuple[datetime, datetime]]:
    current = since
    while current < until:
        window_end = min(current + timedelta(days=COMPLETED_WINDOW_DAYS), until)
        yield current, window_end
        current = window_end


def paginate_completed_tasks(
    token: str, since: datetime, until: datetime
) -> Iterable[dict]:
    for window_index, (window_start, window_end) in enumerate(
        completed_windows(since, until),
        start=1,
    ):
        print(
            "Scanning completed tasks window "
            f"{window_index}: {window_start.date()} to {window_end.date()}..."
        )
        cursor: str | None = None
        page = 0
        while True:
            page += 1
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
                "listing completed tasks",
            )
            items = payload.get("items", [])
            print(
                "  Retrieved page "
                f"{page} with {len(items)} completed task(s)."
            )

            items.sort(key=lambda task: task.get("completed_at", ""))

            for task in items:
                yield task

            cursor = payload.get("next_cursor")
            if not cursor:
                break


def restore_completed_task(token: str, task_id: str) -> None:
    commands = [command("item_uncomplete", {"id": task_id})]
    payload = post_json_with_retries(
        token,
        SYNC_BASE,
        {"commands": json.dumps(commands)},
        "restoring a completed task",
    )

    sync_status = payload.get("sync_status", {})
    status = next(iter(sync_status.values()), None)
    if isinstance(status, dict) and status.get("error_tag") == "ITEM_NOT_FOUND":
        raise TodoistItemNotFoundError(
            f"Completed task {task_id} is no longer restorable."
        )
    if status != "ok":
        raise TodoistError(f"Failed to restore completed task {task_id}: {status!r}")


def summarize(stats: Stats) -> None:
    print()
    print("Summary")
    print(f"  Active tasks found:      {stats.active_found}")
    print(f"  Active tasks deleted:    {stats.active_deleted}")
    print(f"  Completed tasks found:   {stats.completed_found}")
    print(f"  Completed tasks restored:{stats.completed_restored}")
    print(f"  Completed tasks deleted: {stats.completed_deleted}")
    print(f"  Completed tasks skipped: {stats.completed_skipped_not_found}")
    if stats.oldest_completed_at:
        print(f"  Oldest completed task:   {stats.oldest_completed_at}")
        if stats.oldest_completed_content:
            print(f"  Oldest task content:     {stats.oldest_completed_content}")
    if stats.latest_completed_seen_at:
        print(f"  Latest completion seen:  {stats.latest_completed_seen_at}")


def track_completed_task_metadata(stats: Stats, task: dict) -> None:
    completed_at = task.get("completed_at")
    if not completed_at:
        return

    if stats.oldest_completed_at is None or completed_at < stats.oldest_completed_at:
        stats.oldest_completed_at = completed_at
        stats.oldest_completed_content = task.get("content")

    if (
        stats.latest_completed_seen_at is None
        or completed_at > stats.latest_completed_seen_at
    ):
        stats.latest_completed_seen_at = completed_at


def parse_api_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def scan_completed_tasks(token: str, since: datetime, stats: Stats) -> list[str]:
    seen_ids: set[str] = set()
    task_ids: list[str] = []
    now = datetime.now(timezone.utc)

    for task in paginate_completed_tasks(token, since, now):
        task_id = str(task["id"])
        if task_id in seen_ids:
            continue

        seen_ids.add(task_id)
        task_ids.append(task_id)
        stats.completed_found += 1
        track_completed_task_metadata(stats, task)

        if stats.completed_found % 500 == 0:
            latest = stats.latest_completed_seen_at or "unknown"
            print(
                "Collected "
                f"{stats.completed_found} unique completed task(s) so far "
                f"(latest completion seen: {latest})..."
            )

    return task_ids


def delete_completed_tasks_streaming(
    token: str,
    since: datetime,
    stats: Stats,
    sleep_seconds: float,
    checkpoint_path: Path,
    checkpoint: Checkpoint,
) -> None:
    seen_ids: set[str] = set()
    now = datetime.now(timezone.utc)

    for task in paginate_completed_tasks(token, since, now):
        task_id = str(task["id"])
        if task_id in seen_ids:
            continue

        seen_ids.add(task_id)
        stats.completed_found += 1
        track_completed_task_metadata(stats, task)

        if stats.completed_found % 500 == 0:
            latest = stats.latest_completed_seen_at or "unknown"
            print(
                "Discovered "
                f"{stats.completed_found} unique completed task(s) so far "
                f"(latest completion seen: {latest})..."
            )

        if should_log_progress(stats.completed_found):
            completed_at = task.get("completed_at", "unknown")
            print(
                f"[{stats.completed_found}] Restoring and deleting completed tasks... "
                f"(up to completion date {completed_at}; deleted={stats.completed_deleted}; "
                f"skipped={stats.completed_skipped_not_found})"
            )

        try:
            restore_completed_task(token, task_id)
            stats.completed_restored += 1
        except TodoistItemNotFoundError:
            stats.completed_skipped_not_found += 1
            checkpoint.resume_since = task.get("completed_at")
            checkpoint.deleted = stats.completed_deleted
            checkpoint.skipped_not_found = stats.completed_skipped_not_found
            save_checkpoint(checkpoint_path, checkpoint)
            print(
                f"[{stats.completed_found}] Skipping non-restorable completed task "
                f"{task_id}."
            )
            continue

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

        delete_task(token, task_id)
        stats.completed_deleted += 1
        checkpoint.resume_since = task.get("completed_at")
        checkpoint.deleted = stats.completed_deleted
        checkpoint.skipped_not_found = stats.completed_skipped_not_found
        save_checkpoint(checkpoint_path, checkpoint)


def main() -> int:
    args = parse_args()

    try:
        token, completed_since = load_required_env()
        checkpoint_path = Path(args.checkpoint_file)
        checkpoint = Checkpoint()
        if args.reset_checkpoint:
            remove_checkpoint(checkpoint_path)
        else:
            checkpoint = load_checkpoint(checkpoint_path)
            if checkpoint.resume_since:
                resumed_since = parse_api_datetime(checkpoint.resume_since)
                if resumed_since > completed_since:
                    completed_since = resumed_since
                    print(
                        "Resuming from checkpoint at "
                        f"{checkpoint.resume_since} "
                        f"(deleted={checkpoint.deleted}, skipped={checkpoint.skipped_not_found})."
                    )

        stats = Stats()

        active_tasks = list(paginate_tasks(token))
        stats.active_found = len(active_tasks)
        print(f"Found {stats.active_found} active task(s).")

        if args.dry_run:
            scan_completed_tasks(token, completed_since, stats)
            print(f"Found {stats.completed_found} completed task(s) since {completed_since.isoformat()}.")
            print()
            print("Dry run only. No changes were made.")
            summarize(stats)
            return 0

        for index, task in enumerate(active_tasks, start=1):
            task_id = str(task["id"])
            if should_log_progress(index, stats.active_found):
                print(f"[{index}/{stats.active_found}] Deleting active tasks...")
            delete_task(token, task_id)
            stats.active_deleted += 1

        print(
            "Starting streaming deletion of completed tasks from "
            f"{completed_since.isoformat()} onward..."
        )
        delete_completed_tasks_streaming(
            token,
            completed_since,
            stats,
            args.sleep_seconds,
            checkpoint_path,
            checkpoint,
        )
        remove_checkpoint(checkpoint_path)

        summarize(stats)
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except TodoistError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"Network error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
