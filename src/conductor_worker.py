"""Conductor worker that runs Sentinel-2 preprocessing for all available ZIPs."""

import json
import logging
import math
import os
import socket
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import config
from preprocess_sentinel2 import process_archives

LOGGER = logging.getLogger(__name__)
TASK_TYPE = os.getenv("CONDUCTOR_TASK_TYPE", "preprocess_sentinel2")
WORKER_ID = os.getenv("CONDUCTOR_WORKER_ID", socket.gethostname())
CONDUCTOR_SERVER_URL = os.getenv(
    "CONDUCTOR_SERVER_URL", "http://host.docker.internal:8080/api"
).rstrip("/")
POLL_TIMEOUT = int(os.getenv("CONDUCTOR_POLL_TIMEOUT_SECONDS", "30"))
TASK_INPUT_KEYS = {
    "workspace_dir",
    "input_zip_dir",
    "extract_dir",
    "output_dir",
    "bands",
    "include_20m_bands",
    "bands_20m",
    "target_resolution_m",
    "scale_factor",
    "delete_extracted_bands_after_merge",
}


def _settings_from_input(input_data: dict) -> config.PreprocessingSettings:
    unknown_keys = input_data.keys() - TASK_INPUT_KEYS
    if unknown_keys:
        raise ValueError(
            f"Unknown preprocessing task input(s): {', '.join(sorted(unknown_keys))}"
        )

    defaults = config.DEFAULT_SETTINGS

    def directory(key: str, default):
        value = input_data.get(key)
        if value is None:
            return default
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a non-empty path string")
        return Path(value).expanduser().resolve()

    def bands(key: str, default: tuple[str, ...]) -> tuple[str, ...]:
        value = input_data.get(key)
        if value is None:
            return default
        if not isinstance(value, list) or any(
            not isinstance(band, str) or not band.strip() for band in value
        ):
            raise ValueError(f"{key} must be an array of non-empty strings")
        return tuple(band.strip() for band in value)

    def positive_number(key: str, default: float) -> float:
        value = input_data.get(key)
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} must be a positive number")
        try:
            number = float(value)
        except OverflowError as error:
            raise ValueError(f"{key} must be a positive number") from error
        if not math.isfinite(number) or number <= 0:
            raise ValueError(f"{key} must be a positive number")
        return number

    include_20m_bands = input_data.get("include_20m_bands")
    if include_20m_bands is None:
        include_20m_bands = defaults.include_20m_bands
    elif not isinstance(include_20m_bands, bool):
        raise ValueError("include_20m_bands must be a boolean")

    delete_extracted_bands = input_data.get("delete_extracted_bands_after_merge")
    if delete_extracted_bands is None:
        delete_extracted_bands = defaults.delete_extracted_bands_after_merge
    elif not isinstance(delete_extracted_bands, bool):
        raise ValueError("delete_extracted_bands_after_merge must be a boolean")

    workspace_dir = directory("workspace_dir", defaults.workspace_dir)
    input_zip_dir = directory(
        "input_zip_dir",
        workspace_dir / "eodag" / "downloads",
    )

    return config.PreprocessingSettings(
        workspace_dir=workspace_dir,
        input_zip_dir=input_zip_dir,
        extract_dir=directory("extract_dir", defaults.extract_dir),
        output_dir=directory("output_dir", defaults.output_dir),
        bands=bands("bands", defaults.bands),
        include_20m_bands=include_20m_bands,
        bands_20m=bands("bands_20m", defaults.bands_20m),
        target_resolution_m=positive_number(
            "target_resolution_m",
            defaults.target_resolution_m,
        ),
        scale_factor=positive_number("scale_factor", defaults.scale_factor),
        delete_extracted_bands_after_merge=delete_extracted_bands,
    )


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
        input_data = task.get("inputData", {})
        if input_data is None:
            input_data = {}
        if not isinstance(input_data, dict):
            raise ValueError("Conductor task inputData must be an object")
        settings = _settings_from_input(input_data)
        output_files = process_archives(settings=settings)
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
