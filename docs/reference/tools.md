# MCP Tool Reference

## `fetch_pr_review_comments`

- **Description**: Fetch review comments from a GitHub pull request and render them as Markdown or JSON.
- **Parameters**:
  - `pr_url` (string, optional): Full PR URL. When omitted, auto-resolves from git metadata.
  - `output` (enum): `"markdown"` (default), `"json"`, or `"both"`.
  - `per_page` (int): Overrides pagination size. Defaults from `HTTP_PER_PAGE`.
  - `max_pages` (int): Safety cap on pagination loops. Defaults from `PR_FETCH_MAX_PAGES`.
  - `max_comments` (int): Hard limit on total comments collected. Defaults from `PR_FETCH_MAX_COMMENTS`.
  - `max_retries` (int): Overrides HTTP retry budget. Defaults from `HTTP_MAX_RETRIES`.
  - `include_collapsed_details` (bool): Include content from GitHub `<details>` folds. Defaults to `false`, which preserves `<summary>` and inserts `[Folded details omitted]`.

### Response

Returns one or two text blocks depending on the `output` parameter. Markdown responses are formatted with review comment details including resolution status and code context. By default, folded `<details>` content is removed in all output modes.

## `resolve_open_pr_url`

- **Description**: Resolve the open pull request that matches the current repository and branch.
- **Parameters**:
  - `select_strategy` (enum): One of `branch`, `latest`, `first`, `error`.
  - `owner`, `repo`, `branch` (string, optional): Override auto-detected values.

### Response

String containing the PR URL, e.g. `https://github.com/cool-kids-inc/github-pr-review-mcp-server/pull/42`.

## Roadmap

- `list_pr_review_comments`: metadata-first listing without heavy body/diff payloads.
- `fetch_pr_review_comment`: fetch one selected comment by ID.
- `fetch_pr_review_comments_by_id`: bounded targeted batches by selected IDs.
- Recommended workflow: list first, prioritize comments, then fetch only selected IDs.

## Error Codes

| Code | Description | Recommended Action |
| --- | --- | --- |
| `invalid-arguments` | Missing or malformed parameters. | Inspect payload and reissue with valid fields. |
| `not-found` | PR or repository not available. | Confirm URL or repository access. |
| `unauthorized` | Authentication failure. | Update `GITHUB_TOKEN` scopes or validity. |
| `rate-limited` | GitHub API throttling. | Reduce frequency or raise limits with fewer comments per call. |
| `internal-error` | Unhandled exception. | Review server logs, file an issue with stack trace. |
