#!/usr/bin/env python3
"""Inspect remaining Todoist tasks without modifying the account."""

from __future__ import annotations

import argparse
import csv
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from todoist_api import (
    API_V1_BASE,
    PAGE_LIMIT,
    TodoistError,
    get_json_with_retries,
    load_token,
    utc_now,
)


COMPLETED_WINDOW_DAYS = 89


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect remaining active and completed Todoist tasks."
    )
    parser.add_argument(
        "--completed-since",
        default=None,
        help="Override TODOIST_COMPLETED_SINCE for this inspection.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=5,
        help="Number of sample completed tasks to print for each project.",
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="Optional CSV path to export all remaining completed tasks.",
    )
    return parser.parse_args()


def load_config(completed_since_override: str | None) -> tuple[str, datetime]:
    token = load_token()
    since_raw = (
        completed_since_override
        or os.getenv("TODOIST_COMPLETED_SINCE", "2000-01-01T00:00:00Z")
    ).strip()
    try:
        since = datetime.fromisoformat(since_raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TodoistError(
            "Completed-since must be an ISO-8601 datetime like 2000-01-01T00:00:00Z."
        ) from exc

    return token, since.astimezone(timezone.utc)


def paginate_projects(token: str) -> dict[str, str]:
    cursor: str | None = None
    projects: dict[str, str] = {}

    while True:
        params: dict[str, str | int] = {"limit": PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        payload = get_json_with_retries(
            token,
            f"{API_V1_BASE}/projects",
            params,
            "listing projects",
        )
        for project in payload.get("results", []):
            projects[str(project["id"])] = project.get("name", "<unnamed>")
        cursor = payload.get("next_cursor")
        if not cursor:
            return projects


def paginate_active_tasks(token: str) -> list[dict]:
    cursor: str | None = None
    tasks: list[dict] = []

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
        tasks.extend(payload.get("results", []))
        cursor = payload.get("next_cursor")
        if not cursor:
            return tasks


def completed_windows(since: datetime, until: datetime) -> Iterable[tuple[datetime, datetime]]:
    current = since
    while current < until:
        window_end = min(current + timedelta(days=COMPLETED_WINDOW_DAYS), until)
        yield current, window_end
        current = window_end


def paginate_completed_tasks(token: str, since: datetime) -> list[dict]:
    tasks: list[dict] = []
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
                "listing completed tasks",
            )
            for task in payload.get("items", []):
                task_id = str(task["id"])
                if task_id in seen_ids:
                    continue
                seen_ids.add(task_id)
                tasks.append(task)
            cursor = payload.get("next_cursor")
            if not cursor:
                break

    return tasks


def export_completed_csv(path: Path, completed_tasks: list[dict], project_names: dict[str, str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "id",
                "content",
                "project_id",
                "project_name",
                "section_id",
                "completed_at",
            ],
        )
        writer.writeheader()
        for task in completed_tasks:
            project_id = str(task.get("project_id", ""))
            writer.writerow(
                {
                    "id": task.get("id", ""),
                    "content": task.get("content", ""),
                    "project_id": project_id,
                    "project_name": project_names.get(project_id, "<unknown project>"),
                    "section_id": task.get("section_id", ""),
                    "completed_at": task.get("completed_at", ""),
                }
            )


def main() -> int:
    args = parse_args()
    token, since = load_config(args.completed_since)

    project_names = paginate_projects(token)
    active_tasks = paginate_active_tasks(token)
    completed_tasks = paginate_completed_tasks(token, since)

    print(f"Active projects visible: {len(project_names)}")
    print(f"Active tasks visible:    {len(active_tasks)}")
    print(f"Completed tasks visible: {len(completed_tasks)}")
    print(f"Completed since:         {since.isoformat()}")
    print()

    active_by_project = Counter(str(task.get("project_id", "")) for task in active_tasks)
    if active_by_project:
        print("Active tasks by project")
        for project_id, count in active_by_project.most_common():
            print(f"- {project_names.get(project_id, '<unknown project>')} ({project_id}): {count}")
        print()

    completed_by_project = Counter(str(task.get("project_id", "")) for task in completed_tasks)
    completed_samples: dict[str, list[dict]] = defaultdict(list)
    for task in sorted(completed_tasks, key=lambda item: item.get("completed_at", "")):
        project_id = str(task.get("project_id", ""))
        if len(completed_samples[project_id]) < args.sample_size:
            completed_samples[project_id].append(task)

    print("Completed tasks by project")
    for project_id, count in completed_by_project.most_common():
        project_name = project_names.get(project_id, "<unknown project>")
        print(f"- {project_name} ({project_id}): {count}")
        for task in completed_samples[project_id]:
            print(
                "  "
                f"{task.get('completed_at', '<no date>')} | "
                f"{task.get('id', '<no id>')} | "
                f"{task.get('content', '<no content>')}"
            )
    if not completed_by_project:
        print("- none")

    if args.csv:
        export_completed_csv(Path(args.csv), completed_tasks, project_names)
        print()
        print(f"Exported completed-task details to {args.csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
