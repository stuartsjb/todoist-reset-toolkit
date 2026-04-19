#!/usr/bin/env python3
"""Inspect or clear remaining non-task Todoist data using official Todoist APIs."""

from __future__ import annotations

import argparse
import json

from todoist_api import (
    TodoistError,
    active,
    chunks,
    command,
    fetch_sync_state,
    load_token,
    sync_request,
)


DEFAULT_BATCH_SIZE = 50


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inventory or clear remaining Todoist labels, filters, sections, "
            "reminders, comments, locations, and related metadata."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete/clear safe categories. Default is inventory only.",
    )
    parser.add_argument(
        "--include-view-options",
        action="store_true",
        help="Also delete custom view options. These are UI preferences.",
    )
    parser.add_argument(
        "--include-notifications",
        action="store_true",
        help="Also mark live notifications as read. This does not delete history.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Number of sync commands to send per request.",
    )
    return parser.parse_args()


def print_inventory(state: dict) -> None:
    categories = [
        ("labels", "Personal labels"),
        ("filters", "Personal filters"),
        ("workspace_filters", "Workspace filters"),
        ("sections", "Sections"),
        ("reminders", "Reminders"),
        ("notes", "Comments/notes"),
        ("locations", "Saved reminder locations"),
        ("live_notifications", "Live notifications"),
        ("view_options", "View options"),
    ]

    print("Inventory")
    for key, label in categories:
        value = state.get(key, [])
        if key == "live_notifications" and isinstance(value, list):
            unread = [
                item
                for item in active(value)
                if item.get("is_unread", False)
            ]
            print(f"  {label}: {len(active(value))} total, {len(unread)} unread")
        elif isinstance(value, list):
            items = active(value) if value and isinstance(value[0], dict) else value
            print(f"  {label}: {len(items)}")
        else:
            print(f"  {label}: present")

    print()
    for key in ["labels", "filters", "workspace_filters", "sections", "reminders", "notes"]:
        items = active(state.get(key, []))
        if not items:
            continue
        print(key)
        for item in items[:25]:
            name = item.get("name") or item.get("content") or item.get("query") or "<unnamed>"
            print(f"  - {item.get('id', '<no id>')}: {name}")
        if len(items) > 25:
            print(f"  ... {len(items) - 25} more ...")
        print()


def build_safe_cleanup_commands(state: dict) -> list[dict]:
    commands: list[dict] = []

    for label in active(state.get("labels", [])):
        commands.append(command("label_delete", {"id": str(label["id"]), "cascade": "all"}))

    for filter_item in active(state.get("filters", [])):
        if filter_item.get("is_frozen"):
            print(f"Skipping frozen filter {filter_item.get('name', filter_item.get('id'))}.")
            continue
        commands.append(command("filter_delete", {"id": str(filter_item["id"])}))

    for workspace_filter in active(state.get("workspace_filters", [])):
        if workspace_filter.get("is_frozen"):
            print(
                "Skipping frozen workspace filter "
                f"{workspace_filter.get('name', workspace_filter.get('id'))}."
            )
            continue
        commands.append(
            command("workspace_filter_delete", {"id": str(workspace_filter["id"])})
        )

    for section in active(state.get("sections", [])):
        commands.append(command("section_delete", {"id": str(section["id"])}))

    for reminder in active(state.get("reminders", [])):
        commands.append(command("reminder_delete", {"id": str(reminder["id"])}))

    for note in active(state.get("notes", [])):
        commands.append(command("note_delete", {"id": str(note["id"])}))

    if state.get("locations"):
        commands.append(command("clear_locations", {}))

    return commands


def build_view_option_commands(state: dict) -> list[dict]:
    commands: list[dict] = []
    for view_option in active(state.get("view_options", [])):
        args = {"view_type": view_option["view_type"]}
        if view_option.get("object_id") is not None:
            args["object_id"] = str(view_option["object_id"])
        commands.append(command("view_options_delete", args))
    return commands


def build_notification_commands(state: dict) -> list[dict]:
    if active(state.get("live_notifications", [])):
        return [command("live_notifications_mark_read_all")]
    return []


def apply_commands(token: str, commands: list[dict], batch_size: int) -> None:
    if not commands:
        print("No cleanup commands to apply.")
        return

    for batch_number, batch in enumerate(chunks(commands, batch_size), start=1):
        print(f"Applying batch {batch_number} with {len(batch)} command(s)...")
        payload = sync_request(token, {"commands": json.dumps(batch)})
        sync_status = payload.get("sync_status", {})
        failures = {
            command_uuid: status
            for command_uuid, status in sync_status.items()
            if status != "ok"
        }
        if failures:
            raise TodoistError(f"Cleanup batch had failures: {failures!r}")


def main() -> int:
    args = parse_args()
    if args.batch_size < 1:
        raise TodoistError("--batch-size must be at least 1.")

    token = load_token()
    state = fetch_sync_state(token)
    print_inventory(state)

    commands = build_safe_cleanup_commands(state)
    if args.include_view_options:
        commands.extend(build_view_option_commands(state))
    if args.include_notifications:
        commands.extend(build_notification_commands(state))

    print(f"Prepared {len(commands)} cleanup command(s).")
    if not args.apply:
        print("Dry run only. No changes were made.")
        print("Use --apply to delete/clear the listed safe categories.")
        return 0

    apply_commands(token, commands, args.batch_size)
    print("Finished miscellaneous cleanup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
