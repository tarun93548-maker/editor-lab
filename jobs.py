import json
import threading
from pathlib import Path
from typing import Any, Dict, Optional


class JobStore:
    def __init__(self, storage_dir: str = "temp/jobs"):
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, job_id: str) -> Path:
        return self._dir / f"{job_id}.json"

    def create(self, job_id: str):
        data = {
            "job_id": job_id,
            "status": "queued",
            "message": "Queued",
            "progress": 0,
            "transcript": None,
            "variations": None,
            "rendered_files": None,
        }
        with self._lock:
            self._path(job_id).write_text(json.dumps(data), encoding="utf-8")

    def get(self, job_id: str) -> Optional[Dict]:
        with self._lock:
            p = self._path(job_id)
            if not p.exists():
                return {}
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}

    def update(self, job_id: str, **kwargs):
        with self._lock:
            p = self._path(job_id)
            if not p.exists():
                return
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return
            data.update(kwargs)
            p.write_text(json.dumps(data), encoding="utf-8")


job_store = JobStore()
