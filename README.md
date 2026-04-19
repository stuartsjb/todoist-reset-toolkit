# Todoist Reset Toolkit

Interactive and scriptable helpers for clearing a Todoist account while keeping the account itself.

This project is intended for people who want a best-effort reset of Todoist data without deleting the Todoist account, for example to preserve legacy pricing. It uses Todoist's official APIs where possible.

The public GitHub repository is <https://github.com/stuartsjb/todoist-reset-toolkit>. Issues and pull requests are welcome there.

## Important Warnings

These scripts are destructive. They can delete tasks, completed tasks, projects, labels, filters, sections, reminders, comments, and other metadata.

Run dry-runs first. Do not run destructive options unless you are sure you want to clear the account.

Todoist rate limits some write operations heavily. Large accounts can take hours or days to clear.

Some Todoist data cannot be cleared through the public API. Reporting / Activity Log entries appear to be view-only. Live notifications can be marked read, but historical read notification records may remain.

## Setup

Use a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On macOS, if you see an SSL/OpenSSL warning from urllib3, use a current Python from Python.org, Homebrew, or another modern Python distribution. Older Apple-provided Python builds may be linked against LibreSSL and can be incompatible with current urllib3 releases.

Start the interactive helper:

```bash
python3 todoist_reset.py
```

Alternatively, install the toolkit as an editable local command:

```bash
pip install -e .
todoist-reset
```

The tool will prompt for your Todoist API token if one is not found. You can either save it locally in `.env` or use it for the current session only.

Never commit `.env`. It contains your Todoist API token and is ignored by git.

See `SECURITY.md` before sharing logs, screenshots, exports, or bug reports.

## Todoist API Usage

This toolkit uses Todoist's official API and a personal API token. Todoist's developer documentation says the API can be used for free, with some features depending on the authenticated user's plan.

Todoist also supports OAuth for apps used by other people. This toolkit is currently designed as a local command-line tool where users provide their own personal API token.

If you build a public hosted service or official integration from this code, review Todoist's current developer documentation, OAuth guidance, rate limits, and integration submission process first.

## Recommended Workflow

The interactive menu is the safest way to use the toolkit:

```bash
python3 todoist_reset.py
```

The menu can:

- show the last cached account inspection
- run a fresh read-only inspection
- delete active and completed tasks
- unarchive archived projects
- delete active projects except the built-in Inbox
- clean labels, filters, sections, reminders, comments, and saved locations
- clear view options and mark live notifications read
- export a report of remaining completed tasks

Destructive menu options run a dry-run first and then require typing `APPLY`.

Example menu:

```text
Todoist Reset Toolkit
Token source: saved locally (abcd...wxyz)
Last account inspection: 2026-04-14T17:30:00Z
  Active tasks:        0
  Completed tasks:     0
  Active projects:     1
  Archived projects:   0
  Labels:              0
  Filters:             0

1. Refresh account inspection
2. Delete active and completed tasks
3. Unarchive archived projects
4. Delete active projects except built-in Inbox
5. Clean labels, filters, reminders, sections, comments, and locations
6. Clear UI metadata and mark notifications read
7. Export remaining completed-task report
8. Settings
0. Exit
```

## Manual Scripts

The individual scripts are still available for advanced/manual use.

Inspect remaining tasks:

```bash
python3 inspect_remaining_tasks.py --completed-since 2000-01-01T00:00:00Z
```

Delete active and completed tasks:

```bash
python3 delete_todoist_tasks.py --dry-run --reset-checkpoint
python3 delete_todoist_tasks.py --reset-checkpoint
```

Unarchive archived projects:

```bash
python3 unarchive_todoist_projects.py
python3 unarchive_todoist_projects.py --apply
```

Delete active projects:

```bash
python3 delete_todoist_projects.py --dry-run
python3 delete_todoist_projects.py
```

Clean labels, filters, sections, reminders, comments, and saved locations:

```bash
python3 cleanup_todoist_misc.py
python3 cleanup_todoist_misc.py --apply
```

Optionally clear view options and mark notifications read:

```bash
python3 cleanup_todoist_misc.py --apply --include-view-options --include-notifications
```

## Tests

Run the offline unit tests with:

```bash
python3 -m unittest discover
```

For contribution guidelines, see `CONTRIBUTING.md`.

## Checkpoints And Cached State

Task deletion stores progress in `.todoist-delete-checkpoint.json` so interrupted long runs can resume.

The interactive menu stores the last read-only inspection in `.todoist-reset-state.json` so it can show the last known account state instantly.

Both files are ignored by git.

## Limitations

Completed-task cleanup uses a restore-then-delete workflow because Todoist does not document a public API endpoint for directly deleting completed task history.

The Todoist web frontend may be able to delete some completed tasks directly even when the public API cannot restore them.

The built-in Inbox project should remain.

Reporting / Activity Log entries do not appear to be user-clearable through the official API.

Live notifications can be marked read, but historical read notification records may remain.

## Contributing And Credit

Issues and pull requests are welcome, especially for safer workflows, clearer warnings, better cross-platform support, and compatibility with Todoist API changes.

This project is MIT licensed, so you are free to use it broadly. If you build on it, improve it, or use it in something public or commercial, a contribution back, credit, or a note would be appreciated where practical.

## License

MIT License. See `LICENSE`.
