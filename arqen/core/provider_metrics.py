import json
from pathlib import Path
from arqen.config import paths
from arqen.core.contracts import Usage


class ProviderMetrics:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or paths.data_dir() / "provider_metrics.json"

    def record(
        self,
        provider: str,
        model: str,
        elapsed_ms: float,
        success: bool,
        fallback: bool,
        usage: Usage | None = None,
    ) -> None:
        data = self._load()
        key = f"{provider}/{model}".strip("/")
        item = data.setdefault(key, {})
        # Files written before tokens were tracked simply lack the keys.
        for name, start in (("requests", 0), ("successes", 0), ("errors", 0), ("fallbacks", 0),
                            ("total_ms", 0.0), ("prompt_tokens", 0), ("completion_tokens", 0), ("cost", 0.0)):
            item.setdefault(name, start)
        item["requests"] += 1
        item["total_ms"] += elapsed_ms
        if success:
            item["successes"] += 1
        else:
            item["errors"] += 1
        if fallback:
            item["fallbacks"] += 1
        if usage is not None:
            item["prompt_tokens"] += usage.prompt_tokens
            item["completion_tokens"] += usage.completion_tokens
            item["cost"] += usage.cost
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def totals(self) -> Usage:
        """Tokens and cost across every provider and model ever recorded."""
        total = Usage()
        for item in self._load().values():
            if not isinstance(item, dict):
                continue
            total.prompt_tokens += int(item.get("prompt_tokens") or 0)
            total.completion_tokens += int(item.get("completion_tokens") or 0)
            try:
                total.cost += float(item.get("cost") or 0.0)
            except (TypeError, ValueError):
                pass
        return total

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
