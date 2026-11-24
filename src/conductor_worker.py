"""Conductor worker that runs Sentinel-2 preprocessing for all available ZIPs."""

import json
import logging
import os
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from preprocess_sentinel2 import process_archives

LOGGER = logging.getLogger(__name__)
TASK_TYPE = os.getenv("CONDUCTOR_TASK_TYPE", "preprocess_sentinel2")
WORKER_ID = os.getenv("CONDUCTOR_WORKER_ID", socket.gethostname())
CONDUCTOR_SERVER_URL = os.getenv(
    "CONDUCTOR_SERVER_URL", "http://host.docker.internal:8080/api"
).rstrip("/")
POLL_TIMEOUT = int(os.getenv("CONDUCTOR_POLL_TIMEOUT_SECONDS", "30"))


def _request_json(
    url: str,
    method: str = "GET",
    body: dict | None = None,
    timeout: int = 60,
    expect_json: bool = True,
):
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read()
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"{method} {url} returned HTTP {error.code}: {details}"
        ) from error
    except URLError as error:
        raise RuntimeError(f"Could not reach {url}: {error.reason}") from error

    if not data or not expect_json:
        return None
    try:
        return json.loads(data)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{method} {url} returned invalid JSON") from error


def _poll_task() -> dict | None:
    query = urlencode({"workerid": WORKER_ID, "timeout": POLL_TIMEOUT})
    task = _request_json(
        f"{CONDUCTOR_SERVER_URL}/tasks/poll/{TASK_TYPE}?{query}",
        timeout=POLL_TIMEOUT + 15,
    )
    return task if isinstance(task, dict) and task else None


def _update_task(task: dict, status: str, **fields) -> None:
    updated = dict(task)
    updated.update(fields)
    updated["status"] = status
    updated["workerId"] = WORKER_ID
    _request_json(
        f"{CONDUCTOR_SERVER_URL}/tasks",
        method="POST",
        body=updated,
        expect_json=False,
    )


def _handle_task(task: dict) -> None:
    task_id = task.get("taskId", "unknown")
    try:
        output_files = process_archives()
        _update_task(
            task,
            "COMPLETED",
            outputData={
                "output_count": len(output_files),
                "output_files": [str(path) for path in output_files],
            },
        )
        LOGGER.info("Completed Conductor task %s", task_id)
    except Exception as error:
        LOGGER.exception("Conductor task %s failed", task_id)
        try:
            _update_task(
                task,
                "FAILED",
                reasonForIncompletion=str(error),
                outputData={"error": str(error)},
            )
        except Exception:
            LOGGER.exception("Could not report failure of Conductor task %s", task_id)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if POLL_TIMEOUT <= 0:
        raise ValueError("CONDUCTOR_POLL_TIMEOUT_SECONDS must be greater than zero")

    LOGGER.info(
        "Polling Conductor at %s for task type %s",
        CONDUCTOR_SERVER_URL,
        TASK_TYPE,
    )
    while True:
        try:
            task = _poll_task()
            if task:
                _handle_task(task)
        except Exception:
            LOGGER.exception("Conductor polling failed; retrying in 5 seconds")
            time.sleep(5)


if __name__ == "__main__":
    main()
