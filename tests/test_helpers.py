from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import delete_todoist_tasks
import todoist_api


class FakeHttpError(Exception):
    pass


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        body: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = body
        self.headers = headers or {}

    def json(self) -> dict:
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise todoist_api.requests.HTTPError("boom")


class TodoistApiHelperTests(unittest.TestCase):
    def test_command_builds_sync_command(self) -> None:
        command = todoist_api.command("label_delete", {"id": "123"})

        self.assertEqual(command["type"], "label_delete")
        self.assertEqual(command["args"], {"id": "123"})
        self.assertIsInstance(command["uuid"], str)

    def test_active_filters_deleted_items(self) -> None:
        items = [
            {"id": "1", "is_deleted": False},
            {"id": "2", "is_deleted": True},
            {"id": "3"},
        ]

        self.assertEqual(todoist_api.active(items), [items[0], items[2]])

    def test_chunks_splits_list(self) -> None:
        self.assertEqual(
            list(todoist_api.chunks([1, 2, 3, 4, 5], 2)),
            [[1, 2], [3, 4], [5]],
        )

    def test_raise_for_status_parses_rate_limit_retry_after(self) -> None:
        response = FakeResponse(
            429,
            '{"error_extra": {"retry_after": 1280}, "error": "Too many requests"}',
        )

        with self.assertRaises(todoist_api.TodoistRateLimitError) as raised:
            todoist_api.raise_for_status(response)  # type: ignore[arg-type]

        self.assertEqual(raised.exception.retry_after, 1280)

    def test_raise_for_status_uses_retry_after_header_for_503(self) -> None:
        response = FakeResponse(503, headers={"Retry-After": "42"})

        with self.assertRaises(todoist_api.TodoistRetryableHttpError) as raised:
            todoist_api.raise_for_status(response)  # type: ignore[arg-type]

        self.assertEqual(raised.exception.retry_after, 42)


class TaskDeletionHelperTests(unittest.TestCase):
    def test_should_log_progress(self) -> None:
        self.assertTrue(delete_todoist_tasks.should_log_progress(1))
        self.assertTrue(delete_todoist_tasks.should_log_progress(100))
        self.assertTrue(delete_todoist_tasks.should_log_progress(5, total=5))
        self.assertFalse(delete_todoist_tasks.should_log_progress(42))

    def test_completed_windows_splits_date_range(self) -> None:
        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        until = datetime(2024, 7, 1, tzinfo=timezone.utc)

        windows = list(delete_todoist_tasks.completed_windows(since, until))

        self.assertEqual(windows[0][0], since)
        self.assertEqual(windows[-1][1], until)
        self.assertGreater(len(windows), 1)

    def test_checkpoint_round_trip(self) -> None:
        checkpoint = delete_todoist_tasks.Checkpoint(
            resume_since="2024-01-02T03:04:05.000000Z",
            deleted=12,
            skipped_not_found=3,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "checkpoint.json"
            delete_todoist_tasks.save_checkpoint(path, checkpoint)
            loaded = delete_todoist_tasks.load_checkpoint(path)

        self.assertEqual(loaded.resume_since, checkpoint.resume_since)
        self.assertEqual(loaded.deleted, checkpoint.deleted)
        self.assertEqual(loaded.skipped_not_found, checkpoint.skipped_not_found)

    def test_track_completed_task_metadata(self) -> None:
        stats = delete_todoist_tasks.Stats()

        delete_todoist_tasks.track_completed_task_metadata(
            stats,
            {
                "completed_at": "2024-03-01T00:00:00.000000Z",
                "content": "newer",
            },
        )
        delete_todoist_tasks.track_completed_task_metadata(
            stats,
            {
                "completed_at": "2024-02-01T00:00:00.000000Z",
                "content": "older",
            },
        )

        self.assertEqual(stats.oldest_completed_content, "older")
        self.assertEqual(stats.latest_completed_seen_at, "2024-03-01T00:00:00.000000Z")

    def test_parse_api_datetime(self) -> None:
        parsed = delete_todoist_tasks.parse_api_datetime("2024-01-01T12:00:00Z")

        self.assertEqual(parsed.tzinfo, timezone.utc)
        self.assertEqual(parsed.hour, 12)


if __name__ == "__main__":
    unittest.main()
