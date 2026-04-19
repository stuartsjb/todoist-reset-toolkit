# Contributing

Issues and pull requests are welcome.

Please use the public GitHub repository: <https://github.com/stuartsjb/todoist-reset-toolkit>.

This is a destructive Todoist cleanup toolkit, so safety matters more than cleverness.

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Run tests:

```bash
python3 -m unittest discover
```

## Testing Guidelines

Tests should be offline by default.

Do not write tests that require:

- a real Todoist API token
- live Todoist API calls
- a user's actual Todoist account

Use mocks or small fake response objects for API behavior.

Good things to test:

- dry-run behavior
- checkpoint parsing and saving
- rate-limit and retry handling
- sync command generation
- destructive workflow safety prompts
- handling of Todoist edge cases such as `ITEM_NOT_FOUND`

## Safety Guidelines

Do not commit:

- `.env`
- `.venv`
- `.todoist-delete-checkpoint.json`
- `.todoist-reset-state.json`
- exported CSV files
- logs containing task contents or tokens

When changing destructive behavior, make sure the README and interactive prompts remain clear about what will be deleted.

## Style

Keep the project compatible with Python 3.9+.

Prefer standard-library tools unless an extra dependency clearly improves safety or usability.

Keep command-line workflows cross-platform for macOS and Linux.
