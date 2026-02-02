You are working in a Python repo. Goal: increase unit test coverage to >= 98% and keep all tests passing.

Rules:
- ONLY add or modify tests unless a very small, safe code change is required for testability.
- Do not change production logic unless absolutely necessary, and explain why.
- Add meaningful tests (edge cases, error paths, branches), not superficial coverage.
- Use pytest and standard mocking tools.

Verification step (MANDATORY):
- Run: make coverage
- If it fails, inspect missing lines and branches, add tests, and re-run.

Definition of done:
- make coverage exits successfully (coverage >= 98%)
- All tests pass
- No skipped verification steps
- Brief summary of what was tested and why

When finished, print exactly:
COMPLETE
