# MiroFish Codebase Conventions

Observed patterns from reading the actual source files. Last updated: 2026-05-09.

---

## 1. Naming Conventions

### Python (backend)

| Construct | Convention | Example |
|-----------|-----------|---------|
| Modules / files | `snake_case` | `llm_client.py`, `zep_paging.py` |
| Classes | `PascalCase` | `LLMClient`, `SimulationRunner`, `RetryableAPIClient` |
| Methods & functions | `snake_case` | `chat_json()`, `fetch_all_nodes()`, `get_run_state()` |
| Private helpers | leading underscore | `_fetch_page_with_retry()`, `_read_action_log()` |
| Module-level constants | `UPPER_SNAKE_CASE` | `_DEFAULT_PAGE_SIZE`, `_MAX_NODES`, `IS_WINDOWS` |
| Dataclass fields | `snake_case` | `round_num`, `agent_name`, `runner_status` |
| Logger names | dotted hierarchy `mirofish.<module>` | `mirofish.retry`, `mirofish.zep_paging`, `mirofish.simulation_runner` |

### JavaScript / Vue (frontend)

| Construct | Convention | Example |
|-----------|-----------|---------|
| Files | `camelCase.js` or `PascalCase.vue` | `pendingUpload.js`, `App.vue`, `MainView.vue` |
| Exported functions | `camelCase` | `setPendingUpload()`, `getPendingUpload()`, `clearPendingUpload()` |
| Reactive state variable | `state` (module-local) | `const state = reactive({...})` |
| API service instance | `service` (axios instance, default export) | `export default service` |

---

## 2. Async / Await Usage

### Backend — sync-first with async decorator available

The backend is a Flask application (synchronous). LLM calls and file I/O are **synchronous**. The OpenAI SDK is called via `client.chat.completions.create()` — a blocking call.

`retry.py` provides **two decorator variants**:
- `retry_with_backoff` — wraps synchronous functions with `time.sleep`.
- `retry_with_backoff_async` — wraps `async` functions with `asyncio.sleep`.

The async variant imports `asyncio` lazily inside the decorator factory (not at module top-level), so the sync-only Flask app does not pay the cost. No async routes were observed in the services read here.

`zep_paging.py` is fully synchronous (`time.sleep` for retry delays), matching the sync Flask context.

`simulation_runner.py` uses `threading.Thread` (not `asyncio`) for background monitoring. The subprocess lifecycle (start, poll, terminate) is entirely synchronous. No `asyncio` is used in this file.

### Frontend — async/await with Axios

All API calls use `async/await` over Axios promises:
```js
// api/index.js
export const requestWithRetry = async (requestFn, maxRetries = 3, delay = 1000) => {
  for (let i = 0; i < maxRetries; i++) {
    try {
      return await requestFn()
    } catch (error) {
      if (i === maxRetries - 1) throw error
      await new Promise(resolve => setTimeout(resolve, delay * Math.pow(2, i)))
    }
  }
}
```
Exponential backoff uses `delay * Math.pow(2, i)`, matching the backend pattern structurally.

---

## 3. Error Handling Patterns

### Backend

**General pattern:** catch broadly at boundaries, re-raise or convert to domain errors.

```python
# llm_client.py — converts JSONDecodeError to ValueError with context
try:
    return json.loads(cleaned_response)
except json.JSONDecodeError:
    raise ValueError(f"LLM returned invalid JSON: {cleaned_response}")
```

```python
# file_parser.py — silent fallback chain for encoding detection
try:
    return data.decode('utf-8')
except UnicodeDecodeError:
    pass
# then tries charset_normalizer, chardet, then utf-8 with errors='replace'
```

```python
# simulation_runner.py — catch-all in background threads, log and update state
except Exception as e:
    logger.error(f"Monitoring thread failed: {simulation_id}, error={str(e)}")
    state.runner_status = RunnerStatus.FAILED
    state.error = str(e)
    cls._save_run_state(state)
```

**zep_paging.py** is the most selective: it catches only `(ConnectionError, TimeoutError, OSError, InternalServerError)` and deliberately lets other exceptions propagate uncaught, which is the correct pattern for distinguishing transient vs. logic errors. All other modules use broad `except Exception`.

**Retry behavior:**
- Backend decorators (`retry.py`): configurable `exceptions` tuple, default `(Exception,)` — retries everything unless restricted.
- `RetryableAPIClient.call_batch_with_retry` catches all exceptions at the per-item level and appends to a `failures` list, with a `continue_on_failure` flag.

### Frontend

Errors surface through the Axios response interceptor:
```js
if (!res.success && res.success !== undefined) {
  return Promise.reject(new Error(res.error || res.message || 'Error'))
}
```
All network errors are logged to `console.error` and re-rejected. Error handling beyond that is left to individual call sites in the components; no global error-boundary component was seen in `App.vue`.

---

## 4. LLM Call Structure

All LLM interaction is centralized in `LLMClient` (`backend/app/utils/llm_client.py`).

**Two public methods:**

| Method | Returns | temperature default | Use case |
|--------|---------|---------------------|----------|
| `chat(messages, ...)` | `str` | `0.7` | Free-form text generation |
| `chat_json(messages, ...)` | `dict` | `0.3` | Structured JSON output |

**Call chain for JSON:**
1. `chat_json` calls `chat` with `response_format={"type": "json_object"}`.
2. `chat` strips `<think>...</think>` blocks (to handle MiniMax M2.5 reasoning traces).
3. `chat_json` then strips Markdown code fences (` ```json ... ``` `).
4. Parses with `json.loads`; raises `ValueError` on failure.

**Configuration:** The client reads `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL_NAME` from `Config` but accepts overrides in the constructor. This makes it usable with any OpenAI-compatible provider.

**What is missing:** `LLMClient` has no retry logic of its own. Callers are expected to wrap it with `@retry_with_backoff` from `retry.py`. It is not enforced.

---

## 5. API Response Format

The backend uses a consistent envelope format, evidenced by the frontend interceptor checking `res.success`:

```json
{ "success": true,  "data": { ... } }
{ "success": false, "error": "human-readable message" }
```

The `simulation_runner.py` cleanup method returns the same shape internally:
```python
return {
    "success": len(errors) == 0,
    "cleaned_files": cleaned_files,
    "errors": errors if errors else None
}
```

Interview results follow a slightly different shape (no top-level `data` wrapper):
```python
{
    "success": True,
    "agent_id": agent_id,
    "prompt": prompt,
    "result": response.result,
    "timestamp": response.timestamp
}
```

**Gap:** The envelope is not enforced by a shared helper or base class. Each route/service constructs the response dict by hand, which allows field name drift (`error` vs `message` vs `errors`).

---

## 6. Frontend State Management Patterns

No Vuex or Pinia is used. State is managed through two mechanisms:

### Module-level reactive state (Vue 3 Composition API)
`pendingUpload.js` is representative:
```js
import { reactive } from 'vue'
const state = reactive({ files: [], simulationRequirement: '', isPending: false })

export function setPendingUpload(files, requirement) { ... }
export function getPendingUpload() { ... }
export function clearPendingUpload() { ... }
```
State is a module singleton. Functions are named imperatively (get/set/clear). The raw `state` object is also exported as the default export, allowing direct reactive binding in templates if needed.

Other store files observed: `graph.js`, `report.js`, `simulation.js`, `index.js` — presumed to follow the same `reactive` + named-function pattern.

### Axios service singleton
`api/index.js` creates one Axios instance (`service`) with a base URL from `VITE_API_BASE_URL` (falls back to `http://localhost:5001`). All components are expected to import from this module rather than create their own Axios instances.

### No global state bus or event system
`App.vue` is a thin shell (`<router-view />`), providing no shared state or event bus. Component communication relies on the store modules above or Vue Router navigation.

---

## 7. Logging Conventions (backend)

`logger.py` provides:
- A `setup_logger(name)` that attaches a rotating file handler (10 MB, 5 backups, date-based filename) and a console handler (INFO+).
- A `get_logger(name)` convenience wrapper used by every other module.
- Module-level shortcut functions (`debug`, `info`, `warning`, `error`, `critical`) on the default root logger — but these are only for convenience in scripts, not used by service classes.

Every service/util that needs logging calls `get_logger('mirofish.<module>')` at the top of the file:
```python
logger = get_logger('mirofish.simulation_runner')
```

Log messages include structured context inline in f-strings (e.g., `simulation_id=`, `pid=`, `platform=`). No structured logging library (e.g., `structlog`) is used.

---

## 8. Dataclass / Serialization Pattern

`simulation_runner.py` uses `@dataclass` for domain objects (`AgentAction`, `RoundSummary`, `SimulationRunState`). Each has a `to_dict()` method for JSON serialization. The more complex `SimulationRunState` has both `to_dict()` (summary) and `to_detail_dict()` (includes `recent_actions`).

There is no Pydantic model used for these objects despite `pydantic>=2.0.0` being in `requirements`. Pydantic is declared but its usage was not observed in the read files.

---

## 9. Cross-Cutting Gaps

- **No type annotations on frontend** — JavaScript is untyped; no TypeScript, no JSDoc types.
- **No request validation middleware** — backend services receive raw dicts from JSON; input validation is ad-hoc.
- **Broad `except Exception` in services** — all retry decorators and most service code catches `Exception`, masking unexpected errors in logs rather than surfacing them as crashes.
- **`asyncio` import inside decorator** — `retry_with_backoff_async` imports `asyncio` inside the factory function at each decoration call, not at module level. This works but is an inconsistent style.
- **No shared response builder** — API response envelopes are hand-constructed; field names are inconsistent (`error` vs `message` vs `errors`).
