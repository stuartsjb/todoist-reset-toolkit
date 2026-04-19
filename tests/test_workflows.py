from __future__ import annotations

import unittest
from unittest.mock import patch

import cleanup_todoist_misc
import delete_todoist_projects
import delete_todoist_tasks
import unarchive_todoist_projects


class TaskWorkflowTests(unittest.TestCase):
    @patch("delete_todoist_tasks.post_json_with_retries")
    def test_restore_completed_task_accepts_ok_status(self, post_json) -> None:
        post_json.return_value = {"sync_status": {"abc": "ok"}}

        delete_todoist_tasks.restore_completed_task("token", "task-id")

        post_json.assert_called_once()
        payload = post_json.call_args.args[2]
        self.assertIn("item_uncomplete", payload["commands"])
        self.assertIn("task-id", payload["commands"])

    @patch("delete_todoist_tasks.post_json_with_retries")
    def test_restore_completed_task_raises_for_item_not_found(self, post_json) -> None:
        post_json.return_value = {
            "sync_status": {
                "abc": {
                    "error_tag": "ITEM_NOT_FOUND",
                    "error": "Item not found",
                }
            }
        }

        with self.assertRaises(delete_todoist_tasks.TodoistItemNotFoundError):
            delete_todoist_tasks.restore_completed_task("token", "task-id")

    @patch("delete_todoist_tasks.post_json_with_retries")
    def test_restore_completed_task_raises_for_unexpected_status(self, post_json) -> None:
        post_json.return_value = {"sync_status": {"abc": "error"}}

        with self.assertRaises(delete_todoist_tasks.TodoistError):
            delete_todoist_tasks.restore_completed_task("token", "task-id")

    @patch("delete_todoist_tasks.delete_with_retries")
    def test_delete_task_uses_task_endpoint(self, delete_with_retries) -> None:
        delete_todoist_tasks.delete_task("token", "task-id")

        delete_with_retries.assert_called_once()
        self.assertEqual(delete_with_retries.call_args.args[0], "token")
        self.assertTrue(delete_with_retries.call_args.args[1].endswith("/tasks/task-id"))


class ProjectWorkflowTests(unittest.TestCase):
    @patch("delete_todoist_projects.fetch_paginated")
    def test_paginate_active_projects_uses_projects_endpoint(self, fetch_paginated) -> None:
        fetch_paginated.return_value = [{"id": "project-id"}]

        projects = delete_todoist_projects.paginate_active_projects("token")

        self.assertEqual(projects, [{"id": "project-id"}])
        self.assertTrue(fetch_paginated.call_args.args[1].endswith("/projects"))

    @patch("delete_todoist_projects.delete_with_retries")
    def test_delete_project_uses_project_endpoint(self, delete_with_retries) -> None:
        delete_todoist_projects.delete_project("token", "project-id")

        delete_with_retries.assert_called_once()
        self.assertTrue(delete_with_retries.call_args.args[1].endswith("/projects/project-id"))

    @patch("unarchive_todoist_projects.sync_request")
    def test_unarchive_project_sends_unarchive_command(self, sync_request) -> None:
        sync_request.return_value = {"sync_status": {"abc": "ok"}}

        unarchive_todoist_projects.unarchive_project("token", "project-id")

        sync_request.assert_called_once()
        payload = sync_request.call_args.args[1]
        self.assertIn("project_unarchive", payload["commands"])
        self.assertIn("project-id", payload["commands"])

    @patch("unarchive_todoist_projects.sync_request")
    def test_unarchive_project_raises_for_failed_sync_status(self, sync_request) -> None:
        sync_request.return_value = {"sync_status": {"abc": "error"}}

        with self.assertRaises(unarchive_todoist_projects.TodoistError):
            unarchive_todoist_projects.unarchive_project("token", "project-id")


class MetadataCleanupTests(unittest.TestCase):
    def test_build_safe_cleanup_commands_includes_supported_metadata(self) -> None:
        state = {
            "labels": [{"id": "label-id", "is_deleted": False}],
            "filters": [{"id": "filter-id", "is_deleted": False}],
            "workspace_filters": [{"id": "workspace-filter-id", "is_deleted": False}],
            "sections": [{"id": "section-id", "is_deleted": False}],
            "reminders": [{"id": "reminder-id", "is_deleted": False}],
            "notes": [{"id": "note-id", "is_deleted": False}],
            "locations": [{"id": "location-id"}],
        }

        commands = cleanup_todoist_misc.build_safe_cleanup_commands(state)
        command_types = [command["type"] for command in commands]

        self.assertIn("label_delete", command_types)
        self.assertIn("filter_delete", command_types)
        self.assertIn("workspace_filter_delete", command_types)
        self.assertIn("section_delete", command_types)
        self.assertIn("reminder_delete", command_types)
        self.assertIn("note_delete", command_types)
        self.assertIn("clear_locations", command_types)

    def test_build_safe_cleanup_commands_skips_deleted_and_frozen_items(self) -> None:
        state = {
            "labels": [{"id": "deleted-label", "is_deleted": True}],
            "filters": [{"id": "frozen-filter", "is_frozen": True}],
            "workspace_filters": [{"id": "frozen-workspace-filter", "is_frozen": True}],
            "sections": [],
            "reminders": [],
            "notes": [],
            "locations": [],
        }

        with patch("builtins.print"):
            commands = cleanup_todoist_misc.build_safe_cleanup_commands(state)

        self.assertEqual(commands, [])

    def test_build_notification_commands_marks_all_read_when_notifications_exist(self) -> None:
        state = {"live_notifications": [{"id": "notification-id", "is_deleted": False}]}

        commands = cleanup_todoist_misc.build_notification_commands(state)

        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0]["type"], "live_notifications_mark_read_all")


if __name__ == "__main__":
    unittest.main()
