# MCP Architecture Review Verification Plan

## Purpose

Validate that the MCP server architecture changes improve reliability, discoverability, output consistency, safety signaling, and agent usability.

This plan is designed to verify both:
- **Current-state gaps** (to confirm known issues are reproducible)
- **Post-refactor behavior** (to confirm fixes are complete and stable)

## Scope

In scope:
- MCP tool definitions and schemas
- Tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`)
- Input validation behavior
- Output shape and schema conformance
- Pagination/filtering guarantees
- Error normalization and actionability
- Basic runtime safety and deterministic behavior

Out of scope:
- GitHub production load/performance benchmarking
- End-to-end third-party editor UX behavior
- Non-MCP CLI ergonomics unrelated to tool contracts

## Preconditions

1. Local checkout is clean.
2. Dependencies are installed:
   ```bash
   uv sync --dev
   ```
3. A valid `GITHUB_TOKEN` is set:
   ```bash
   export GITHUB_TOKEN=...
   ```
4. Optional GHES testing values are available if enterprise scenarios are validated:
   - `GH_HOST`
   - `GITHUB_API_URL`
   - `GITHUB_GRAPHQL_URL`

## Verification Environments

- **Primary**: `stdio` transport via MCP Inspector
- **Secondary**: HTTP transport smoke test (if enabled)

## Success Criteria (Gate)

All of the following must pass:

1. Tool catalog is discoverable and internally consistent.
2. Every tool has strict input schema and explicit safety annotations.
3. List-like tool responses are bounded and paginated (no unbounded defaults).
4. Structured output exists and matches declared output schema.
5. Error responses are normalized, actionable, and do not leak secrets.
6. Validation failures are deterministic and field-specific.
7. Existing tests pass and new contract tests are added for changed behavior.

## Phase 1: Tool Surface Verification

### 1.1 Inspect Tool Metadata

Use MCP Inspector to run `tools/list` and validate:

- Names follow `service_action_resource` (or compatibility alias is clearly marked deprecated).
- Descriptions are one sentence in form: `Does X and returns Y`.
- `inputSchema` exists and includes constraints (`type`, `enum`, `minimum`, `maximum`, defaults where expected).
- `outputSchema` exists for tools returning structured output.
- `annotations` exist and are correct.

Expected result:
- Read-only tools are marked `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`.

### 1.2 Schema Strictness Checks

For each tool schema, confirm:

- Unknown properties are rejected (`additionalProperties: false` or equivalent strict model behavior).
- Free-form strings are avoided when explicit fields are expected.
- Optional fields are explicit and correctly typed.

## Phase 2: Functional Verification in MCP Inspector

Run the following high-value calls in order. Capture request/response JSON for each.

### 2.1 Core Resolution Tool

1. `resolve_open_pr_url` (or renamed equivalent) with default args.
2. Same call with explicit `owner`, `repo`, `branch`.
3. Same call with `select_strategy=latest`.

Expected:
- Returns a single valid PR URL.
- Failure paths provide normalized, actionable errors.

### 2.2 Comment Listing / Fetch Tool (Primary)

4. Basic call with only `pr_url`.
5. Paginated call with explicit `limit` (or equivalent bounded field).
6. Follow-up call using returned `cursor` / `nextPageToken`.
7. Filtered call (e.g., `is_resolved`, `author`, `path_prefix`) if implemented.

Expected:
- Response includes consistent envelope:
  - `items`
  - `nextCursor`/`nextPageToken`
  - `total` (when available)
- No unbounded response by default.
- Cursor advances deterministically.

### 2.3 Validation and Error Behavior

8. Invalid enum value (e.g., bad `output` or `select_strategy`).
9. Out-of-range numeric value (`limit=0`, oversized page size).
10. Unknown parameter injection (`{"unexpectedField":"x"}`).
11. Missing auth token scenario (unset `GITHUB_TOKEN` and retry one read-only call).
12. Rate-limit simulation path (via test harness/mocks if live triggering is impractical).

Expected:
- Errors are normalized with:
  - what failed
  - likely why
  - exact next steps
- No token leakage in any error body/log output returned to client.

## Phase 3: Output Contract Verification

### 3.1 Content + Structured Content

Verify each tool response includes:

- A brief human-readable text in `content`
- Structured data in `structuredContent` when supported/declared

Expected:
- No schema drift between documented and actual structured payload keys.
- If `outputSchema` is declared, returned payload validates.

### 3.2 Determinism Checks

Repeat the same request 2-3 times (stable PR, no new comments) and confirm:

- Field names and top-level shape remain identical
- Ordering is stable or ordering guarantees are documented

## Phase 4: Safety and Architecture Conformance

### 4.1 Safety Hint Audit

Confirm all tools have explicit annotation values and that they match real behavior.

### 4.2 Module Boundary Audit

Confirm implementation structure aligns with the current flat package layout in
`src/mcp_github_pr_review/`:

- `server.py` for MCP tool registration and orchestration
- `models.py` for validated input/output schemas
- `errors.py` for normalized tool error envelopes
- `pagination.py` for cursor encode/decode helpers
- `git_pr_resolver.py` for repository/PR detection and URL resolution

If the codebase is later refactored into `client/`, `tools/`, `schemas/`,
`errors/`, `pagination/`, and `types/`, use this verification plan to enforce
behavioral parity with the current modules.

Expected:
- Runtime config validation happens once at startup/bootstrap in
  `server.py` before tool execution paths fan out.
- HTTP request/retry behavior is centralized (for example via
  `_retry_http_request` + `RateLimitHandler`) with no duplicated ad-hoc
  request wrappers in multiple modules.

## Phase 5: Automated Test Verification

Run:

```bash
uv run ruff format .
uv run ruff check --fix .
uv run mypy .
make compile-check
uv run pytest
```

Required test coverage additions (or equivalent):

- Tool annotation presence and correctness
- `tools/list` schema strictness checks
- Output schema validation tests
- Cursor pagination continuation tests
- Normalized error payload tests (auth, validation, rate-limit)
- Unknown argument rejection tests

## Evidence Collection

Store artifacts in `.context/mcp-arch-review/`:

- `tools-list.json`
- `call-01-...json` through `call-12-...json`
- `pytest.log`
- `mypy.log`
- `ruff.log`
- `summary.md`

## Report Template

Use this summary template at completion:

```md
## MCP Architecture Review Verification Summary

### Status
- Result: PASS | FAIL | PARTIAL
- Date:
- Commit:

### Tooling
- [ ] Tool names and descriptions conform
- [ ] Annotations complete and accurate

### Schemas
- [ ] Strict validation enforced
- [ ] Output schemas present where required

### Outputs
- [ ] content + structuredContent consistency
- [ ] Standardized list envelope (`items`, `nextCursor`, `total`)

### Errors
- [ ] Normalized and actionable
- [ ] No secret leakage

### Pagination
- [ ] Bounded defaults
- [ ] Cursor continuation works

### Tests
- [ ] Ruff, mypy, compile-check, pytest all pass

### Notes / Follow-ups
- ...
```

## Fail Conditions

Any of the following is an automatic failure:

- Tool returns unbounded list without explicit pagination limits.
- Declared schema does not match runtime payload.
- Missing/incorrect safety hints.
- Errors are non-actionable or leak sensitive values.
- Tool behavior contradicts documentation in a way that affects agent control flow.

## Recommended Execution Order

1. `tools/list` metadata and schema audit
2. Positive-path functional calls
3. Negative-path validation/error calls
4. Determinism and pagination checks
5. Lint/type/test gates
6. Final summary artifact generation
