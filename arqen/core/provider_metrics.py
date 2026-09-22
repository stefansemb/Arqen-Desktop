import json
from pathlib import Path
from arqen.config.paths import data_dir


class ProviderMetrics:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_dir() / "provider_metrics.json"

    def record(self, provider: str, model: str, elapsed_ms: float, success: bool, fallback: bool) -> None:
        data = self._load()
        key = f"{provider}/{model}".strip("/")
        item = data.setdefault(key, {"requests": 0, "successes": 0, "errors": 0, "fallbacks": 0, "total_ms": 0.0})
        item["requests"] += 1
        item["total_ms"] += elapsed_ms
        if success:
            item["successes"] += 1
        else:
            item["errors"] += 1
        if fallback:
            item["fallbacks"] += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def reset(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
