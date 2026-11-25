## Local AI workflow

Use the repository-local runner to select a configured GitHub Project Todo issue and create an OpenSpec proposal that stops for review. Numbered and URL-targeted planning confirm In Progress before proposal generation; cancellation and declined reuse leave status unchanged. Retry a failed numbered proposal with the issue's canonical `--issue` URL. Apply deliberately with `$openspec-apply-change <change-id>`, then use `--sync-task` only after implementation and verification. See `docs/ai-local-workflow.md` for exact commands and fail-closed synchronization rules.
