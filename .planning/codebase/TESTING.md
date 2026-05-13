# MiroFish Test Coverage

Honest assessment of current test state. Last updated: 2026-05-09.

---

## Summary

**Test coverage is essentially zero.** There is one script in `backend/scripts/` that resembles a test, but it is not wired into any test runner and uses `print` instead of assertions. The frontend has no test infrastructure at all.

---

## Backend

### Test files found

| File | Type | Framework | Notes |
|------|------|-----------|-------|
| `backend/scripts/test_profile_format.py` | Manual smoke script | None — plain Python | Not a pytest test; uses `print()` and manual inspection instead of `assert`. Must be run directly with `python scripts/test_profile_format.py`. |

No files matching `test_*.py`, `*_test.py`, or anything under a `tests/` directory were found anywhere else in the backend.

### Test configuration

`backend/pyproject.toml` declares pytest as a dev dependency:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pipreqs>=0.5.0",
]

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
]
```

pytest-asyncio is listed, suggesting async tests were anticipated. However there is no `pytest.ini`, no `[tool.pytest.ini_options]` section in `pyproject.toml`, and no `conftest.py`. The test runner has been configured as a dependency but never actually set up.

### How to run the existing script

```bash
cd backend
python scripts/test_profile_format.py
```

This prints to stdout. It will succeed if `OasisProfileGenerator._save_twitter_csv` and `_save_reddit_json` produce files with the expected fields. It does not fail the process on missing fields — it only prints `[Error]` or `[Pass]` strings.

### How to run pytest (once tests exist)

```bash
cd backend
# With uv (the lockfile suggests uv is in use):
uv run pytest

# Or directly:
pytest
```

There are no tests to discover yet, so this will return "no tests ran."

---

## Frontend

### Test files found

None. A search across the entire `frontend/` tree found zero `.test.js`, `.spec.js`, `.test.ts`, or `.spec.ts` files.

### Test configuration

`package.json` has no `test` script:

```json
"scripts": {
    "dev": "vite --host",
    "build": "vite build",
    "preview": "vite preview"
}
```

No Vitest, Jest, or any other test framework is listed in `dependencies` or `devDependencies`. Running `npm test` would fail with "missing script: test."

---

## Coverage Gaps by Area

### High-value, untested areas

| Area | File(s) | Why it matters |
|------|---------|----------------|
| LLM JSON parsing & `<think>` stripping | `utils/llm_client.py` | Regex-based stripping and JSON fence removal can break with edge-case model output; no tests validate the regex. |
| Retry backoff logic | `utils/retry.py` | The decorator has jitter, exponential delay, and `on_retry` callbacks — none verified. Async variant imports `asyncio` lazily; never exercised. |
| Text chunking | `utils/file_parser.py` | `split_text_into_chunks` has complex boundary-detection logic (Chinese sentence terminators, overlap arithmetic); a wrong `start` offset could silently drop text. |
| Zep pagination cursor logic | `utils/zep_paging.py` | UUID cursor handling (`uuid_` vs `uuid` attribute fallback) and the 2000-node cap are untested. |
| Simulation state persistence round-trip | `services/simulation_runner.py` | `_save_run_state` / `_load_run_state` serialize and deserialize complex nested state; a field name change would silently set defaults with no alert. |
| Profile format output | `scripts/test_profile_format.py` | Partially covered by the smoke script, but only for two hand-crafted profiles, with no assertions on field values, only field presence. |
| API response envelope | Any Flask route | No integration tests verify that routes return `{"success": true/false, ...}` in a consistent shape. |
| Frontend store state management | `store/pendingUpload.js` (and others) | The reactive singleton pattern is not tested; `clearPendingUpload` not verified to actually reset all fields. |
| Frontend API retry | `api/index.js` | `requestWithRetry` exponential backoff is untested; the `maxRetries` boundary (throwing on the last attempt) is unverified. |

---

## Recommendations

### Immediate wins (low effort, high value)

1. **Convert `test_profile_format.py` to a real pytest test.** Replace `print("[Pass]")` with `assert` statements. Add a `tests/` directory and a `conftest.py`.

2. **Add pytest config to `pyproject.toml`:**
   ```toml
   [tool.pytest.ini_options]
   testpaths = ["tests"]
   asyncio_mode = "auto"
   ```

3. **Unit-test `LLMClient.chat_json`** with a mock OpenAI client. Cover: valid JSON, JSON wrapped in Markdown fences, `<think>` block stripping, invalid JSON (should raise `ValueError`).

4. **Unit-test `split_text_into_chunks`** with deterministic inputs. Verify no characters are lost when `overlap > 0`.

5. **Unit-test `retry_with_backoff`** using `unittest.mock.patch('time.sleep')` to avoid real delays and assert retry counts.

### Medium effort

6. **Add Vitest to the frontend.** It integrates directly with Vite and requires minimal config:
   ```bash
   npm install -D vitest @vue/test-utils
   ```
   Then add `"test": "vitest"` to `package.json` scripts.

7. **Test the store modules** (`pendingUpload.js`, `graph.js`, etc.) — these are pure functions over `reactive` state and are straightforward to unit-test without mounting components.

8. **Integration test the Flask API** with `pytest` + Flask's built-in `app.test_client()`. Start with the simulation status and action-retrieval routes.

### Longer term

9. **Contract tests for LLM JSON schema.** The `chat_json` caller chain assumes specific keys in the returned dict. Snapshot tests or schema validation (using `pydantic` models, which are already a declared dependency) would catch prompt-drift regressions.

10. **End-to-end smoke test for simulation lifecycle.** Start → poll status → stop, using a mocked subprocess. This would catch the many `os.path.exists` / file-read paths in `simulation_runner.py`.
