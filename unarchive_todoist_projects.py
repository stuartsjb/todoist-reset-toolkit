#!/usr/bin/env python3
"""List or unarchive archived Todoist projects using official Todoist APIs."""

from __future__ import annotations

import argparse
import json

from todoist_api import (
    API_V1_BASE,
    TodoistError,
    command,
    fetch_paginated,
    load_token,
    sync_request,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List or unarchive archived Todoist projects using the official API."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Unarchive the projects instead of only listing them.",
    )
    return parser.parse_args()


def paginate_archived_projects(token: str) -> list[dict]:
    return fetch_paginated(
        token,
        f"{API_V1_BASE}/projects/archived",
        "listing archived projects",
    )


def unarchive_project(token: str, project_id: str) -> None:
    commands = [command("project_unarchive", {"id": project_id})]
    payload = sync_request(
        token,
        {"commands": json.dumps(commands)},
        "unarchiving a project",
    )
    sync_status = payload.get("sync_status", {})
    status = next(iter(sync_status.values()), None)
    if status != "ok":
        raise TodoistError(f"Failed to unarchive project {project_id}: {status!r}")


def main() -> int:
    args = parse_args()
    token = load_token()

    projects = paginate_archived_projects(token)
    print(f"Found {len(projects)} archived project(s).")

    for project in projects:
        print(f"- {project['name']} ({project['id']})")

    if not args.apply:
        print()
        print("List only. No changes were made.")
        return 0

    for index, project in enumerate(projects, start=1):
        print(f"[{index}/{len(projects)}] Unarchiving project {project['name']} ({project['id']})...")
        unarchive_project(token, str(project["id"]))

    print()
    print("Finished unarchiving archived projects.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
