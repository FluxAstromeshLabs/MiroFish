"""
Thin HTTP client for MiroFish backend APIs.
Handles base URL, polling for async tasks, retries, and consistent JSON parsing.
"""

import os
import time
import logging
import requests

logger = logging.getLogger("mirofish.client")

DEFAULT_BASE_URL = "http://localhost:5001/api"
DEFAULT_POLL_INTERVAL = 5  # seconds
DEFAULT_POLL_TIMEOUT = 600  # 10 minutes
DEFAULT_REQUEST_TIMEOUT = 300  # 5 minutes for long requests like interview/all


class MirofishAPIError(Exception):
    """Raised when the backend returns a non-success response."""

    def __init__(self, message: str, status_code: int = None, response_data: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data or {}


class MirofishClient:
    """HTTP client for MiroFish backend endpoints."""

    def __init__(self, base_url: str = None):
        self.base_url = (base_url or os.environ.get("MIROFISH_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.session = requests.Session()

    # ── helpers ──────────────────────────────────────────────

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _check(self, resp: requests.Response) -> dict:
        """Parse JSON and raise on failure."""
        try:
            data = resp.json()
        except ValueError:
            raise MirofishAPIError(
                f"Non-JSON response ({resp.status_code}): {resp.text[:200]}",
                status_code=resp.status_code,
            )
        if resp.status_code >= 400 or not data.get("success", False):
            raise MirofishAPIError(
                data.get("error", f"HTTP {resp.status_code}"),
                status_code=resp.status_code,
                response_data=data,
            )
        return data

    def _get(self, path: str, **kwargs) -> dict:
        resp = self.session.get(self._url(path), timeout=DEFAULT_REQUEST_TIMEOUT, **kwargs)
        return self._check(resp)

    def _post_json(self, path: str, payload: dict = None, **kwargs) -> dict:
        resp = self.session.post(self._url(path), json=payload or {}, timeout=DEFAULT_REQUEST_TIMEOUT, **kwargs)
        return self._check(resp)

    def _post_multipart(self, path: str, data: dict = None, files: list = None, **kwargs) -> dict:
        resp = self.session.post(self._url(path), data=data or {}, files=files or [], timeout=DEFAULT_REQUEST_TIMEOUT, **kwargs)
        return self._check(resp)

    # ── polling ─────────────────────────────────────────────

    def poll_task(
        self,
        task_id: str,
        interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_POLL_TIMEOUT,
        label: str = "task",
    ) -> dict:
        """Poll GET /graph/task/<task_id> until completed or failed."""
        deadline = time.time() + timeout
        last_progress = -1
        while time.time() < deadline:
            result = self._get(f"graph/task/{task_id}")
            task = result.get("data", {})
            status = task.get("status", "")
            progress = task.get("progress", 0)

            if progress != last_progress:
                logger.info(f"[{label}] status={status} progress={progress}%")
                last_progress = progress

            if status == "completed":
                return task
            if status == "failed":
                raise MirofishAPIError(
                    f"{label} failed: {task.get('error', 'unknown')}",
                    response_data=task,
                )
            time.sleep(interval)

        raise MirofishAPIError(f"{label} timed out after {timeout}s")

    def poll_prepare_status(
        self,
        simulation_id: str = None,
        task_id: str = None,
        interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_POLL_TIMEOUT,
    ) -> dict:
        """Poll POST /simulation/prepare/status until ready or failed."""
        deadline = time.time() + timeout
        last_progress = -1
        while time.time() < deadline:
            payload = {}
            if task_id:
                payload["task_id"] = task_id
            if simulation_id:
                payload["simulation_id"] = simulation_id

            result = self._post_json("simulation/prepare/status", payload)
            data = result.get("data", {})
            status = data.get("status", "")
            progress = data.get("progress", 0)

            if progress != last_progress:
                logger.info(f"[prepare] status={status} progress={progress}%")
                last_progress = progress

            if status in ("ready", "completed"):
                return data
            if status == "failed":
                raise MirofishAPIError(
                    f"Prepare failed: {data.get('error', 'unknown')}",
                    response_data=data,
                )
            time.sleep(interval)

        raise MirofishAPIError(f"Prepare timed out after {timeout}s")

    def poll_run_status(
        self,
        simulation_id: str,
        interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_POLL_TIMEOUT,
    ) -> dict:
        """Poll GET /simulation/<id>/run-status until completed or env is in wait mode."""
        deadline = time.time() + timeout
        last_round = -1
        while time.time() < deadline:
            result = self._get(f"simulation/{simulation_id}/run-status")
            data = result.get("data", {})
            status = data.get("runner_status", "")
            current_round = data.get("current_round", 0)

            if current_round != last_round:
                total = data.get("total_rounds", "?")
                logger.info(f"[run] status={status} round={current_round}/{total}")
                last_round = current_round

            if status in ("completed", "waiting_for_command"):
                return data
            if status in ("failed", "error"):
                raise MirofishAPIError(
                    f"Simulation run failed: {data.get('error', status)}",
                    response_data=data,
                )
            time.sleep(interval)

        raise MirofishAPIError(f"Run status poll timed out after {timeout}s")

    def poll_env_alive(
        self,
        simulation_id: str,
        interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_POLL_TIMEOUT,
    ) -> dict:
        """Poll POST /simulation/env-status until env_alive is True."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            result = self._post_json("simulation/env-status", {"simulation_id": simulation_id})
            data = result.get("data", {})
            if data.get("env_alive"):
                logger.info(f"[env] alive — twitter={data.get('twitter_available')}, reddit={data.get('reddit_available')}")
                return data
            time.sleep(interval)

        raise MirofishAPIError(f"Env not alive after {timeout}s")

    # ── graph endpoints ─────────────────────────────────────

    def generate_ontology(
        self,
        file_paths: list[str],
        simulation_requirement: str,
        project_name: str = "Research Run",
        additional_context: str = "",
    ) -> dict:
        """POST /graph/ontology/generate (multipart)."""
        files = []
        for path in file_paths:
            fname = os.path.basename(path)
            files.append(("files", (fname, open(path, "rb"))))

        form_data = {
            "simulation_requirement": simulation_requirement,
            "project_name": project_name,
        }
        if additional_context:
            form_data["additional_context"] = additional_context

        try:
            result = self._post_multipart("graph/ontology/generate", data=form_data, files=files)
            return result.get("data", {})
        finally:
            for _, (_, fobj) in files:
                fobj.close()

    def build_graph(self, project_id: str, **kwargs) -> dict:
        """POST /graph/build. Returns task_id."""
        payload = {"project_id": project_id, **kwargs}
        result = self._post_json("graph/build", payload)
        return result.get("data", {})

    def get_task(self, task_id: str) -> dict:
        """GET /graph/task/<task_id>."""
        result = self._get(f"graph/task/{task_id}")
        return result.get("data", {})

    # ── simulation endpoints ────────────────────────────────

    def get_entities(self, graph_id: str) -> dict:
        """GET /simulation/entities/<graph_id>."""
        result = self._get(f"simulation/entities/{graph_id}")
        return result.get("data", {})

    def create_simulation(self, project_id: str, graph_id: str = None, **kwargs) -> dict:
        """POST /simulation/create."""
        payload = {"project_id": project_id}
        if graph_id:
            payload["graph_id"] = graph_id
        payload.update(kwargs)
        result = self._post_json("simulation/create", payload)
        return result.get("data", {})

    def prepare_simulation(self, simulation_id: str, **kwargs) -> dict:
        """POST /simulation/prepare. Returns task_id for async polling."""
        payload = {"simulation_id": simulation_id, **kwargs}
        result = self._post_json("simulation/prepare", payload)
        return result.get("data", {})

    def start_simulation(self, simulation_id: str, **kwargs) -> dict:
        """POST /simulation/start."""
        payload = {"simulation_id": simulation_id, **kwargs}
        result = self._post_json("simulation/start", payload)
        return result.get("data", {})

    def get_run_status(self, simulation_id: str) -> dict:
        """GET /simulation/<id>/run-status."""
        result = self._get(f"simulation/{simulation_id}/run-status")
        return result.get("data", {})

    def get_env_status(self, simulation_id: str) -> dict:
        """POST /simulation/env-status."""
        result = self._post_json("simulation/env-status", {"simulation_id": simulation_id})
        return result.get("data", {})

    def interview_all(self, simulation_id: str, prompt: str, platform: str = None, timeout: int = 180) -> dict:
        """POST /simulation/interview/all."""
        payload = {"simulation_id": simulation_id, "prompt": prompt, "timeout": timeout}
        if platform:
            payload["platform"] = platform
        result = self._post_json("simulation/interview/all", payload)
        return result.get("data", {})

    def close_env(self, simulation_id: str, timeout: int = 30) -> dict:
        """POST /simulation/close-env."""
        result = self._post_json("simulation/close-env", {"simulation_id": simulation_id, "timeout": timeout})
        return result.get("data", {})

    def get_simulation(self, simulation_id: str) -> dict:
        """GET /simulation/<simulation_id>."""
        result = self._get(f"simulation/{simulation_id}")
        return result.get("data", {})
