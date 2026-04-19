#!/usr/bin/env python3
"""Delete active Todoist projects using official Todoist APIs."""

from __future__ import annotations

import argparse

from todoist_api import API_V1_BASE, delete_with_retries, fetch_paginated, load_token


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete all active Todoist projects using the official API."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List active projects without deleting them.",
    )
    return parser.parse_args()


def paginate_active_projects(token: str) -> list[dict]:
    return fetch_paginated(
        token,
        f"{API_V1_BASE}/projects",
        "listing active projects",
    )


def delete_project(token: str, project_id: str) -> None:
    delete_with_retries(
        token,
        f"{API_V1_BASE}/projects/{project_id}",
        "deleting a project",
    )


def main() -> int:
    args = parse_args()
    token = load_token()

    projects = paginate_active_projects(token)
    print(f"Found {len(projects)} active project(s).")

    for project in projects:
        print(f"- {project['name']} ({project['id']})")

    if args.dry_run:
        print()
        print("Dry run only. No changes were made.")
        return 0

    for index, project in enumerate(projects, start=1):
        print(f"[{index}/{len(projects)}] Deleting project {project['name']} ({project['id']})...")
        delete_project(token, str(project["id"]))

    print()
    print("Finished deleting active projects.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
