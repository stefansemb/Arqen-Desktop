import base64
import json
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

from arqen.config.settings import load_provider_profile
from arqen.tools.base import Tool
from arqen.tools.costs import report_cost
from arqen.config import paths


class GenerateImageTool(Tool):
    name = "generate_image"
    description = "Generates an image from a prompt through OpenRouter and saves it locally."
    requires_confirmation = True
    arguments_schema = {"prompt": str}

    def run(self, arguments: dict) -> str:
        config = load_provider_profile("openrouter")
        api_key = self.provider_key("openrouter")
        if not api_key:
            raise RuntimeError("OpenRouter API-nyckel saknas")
        encoded = None
        last_error = "OpenRouter returnerade ingen bild"
        for model in ("google/gemini-3.1-flash-image", "bytedance-seed/seedream-4.5"):
            try:
                payload = {"model": model, "prompt": arguments["prompt"]}
                request = Request(
                    "https://openrouter.ai/api/v1/images",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                    method="POST",
                )
                with urlopen(request, timeout=config.timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                encoded = data.get("data", [{}])[0].get("b64_json")
                # OpenRouter's own figure for this image; missing means unknown, not free.
                report_cost((data.get("usage") or {}).get("cost"))
                if encoded:
                    break
                last_error = f"{model} returnerade ingen bild"
            except Exception as exc:
                last_error = str(exc)
        if not encoded:
            raise RuntimeError(last_error)
        output = paths.data_dir() / "generated"
        output.mkdir(parents=True, exist_ok=True)
        path = output / f"arqen-image-{uuid.uuid4().hex[:8]}.png"
        path.write_bytes(base64.b64decode(encoded))
        return f"Bild skapad: {path}"
