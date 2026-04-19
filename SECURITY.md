# Security

This toolkit uses a Todoist API token with access to your Todoist account.

Do not share your token in:

- GitHub issues
- pull requests
- screenshots
- terminal logs
- CSV exports
- pasted error output

The local `.env` file is ignored by git and should stay private.

If you accidentally publish a Todoist API token, revoke/regenerate it immediately in Todoist:

Settings -> Integrations -> Developer -> API token

When reporting bugs, remove or redact:

- `TODOIST_TOKEN`
- task contents if private
- project names if private
- exported CSV rows if private
- local checkpoint/state files

This project is a local command-line toolkit. It does not need your token to be sent anywhere except Todoist's official API.
