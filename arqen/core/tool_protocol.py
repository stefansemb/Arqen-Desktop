import json
import re
from typing import Any

from arqen.core.contracts import ToolRequest


def parse_tool_request(content: str) -> ToolRequest | None:
    """Parse only the explicit Arqen tool-call envelope.

    Expected format: {"tool_call": {"name": "...", "arguments": {...}}}
    Ordinary assistant text, malformed JSON and unknown shapes are ignored.
    """
    normalized = content.strip()
    tagged = re.search(r"<tool_call>\s*(.*?)\s*</tool_call>", normalized, re.IGNORECASE | re.DOTALL)
    if tagged:
        normalized = tagged.group(1).strip()
    else:
        normalized = re.sub(r"<think>.*?</think>", "", normalized, flags=re.IGNORECASE | re.DOTALL).strip()
        direct_to = re.search(r"(?:^|\n)\s*to\s*=\s*([A-Za-z0-9_.+-]+)", normalized, re.IGNORECASE)
        if direct_to:
            return ToolRequest(name=direct_to.group(1), arguments={})
        # Some OpenRouter models emit a bare function-shaped object, for
        # example {"system_status": {}}. Accept it before looking at later
        # duplicate formats the model may append.
        bare_tool = re.search(r'\{\s*"([A-Za-z0-9_.+-]+)"\s*:\s*(\{.*?\}|\[.*?\]|null)\s*\}', normalized, re.DOTALL)
        if bare_tool:
            try:
                bare_args = json.loads(bare_tool.group(2))
            except json.JSONDecodeError:
                bare_args = None
            if bare_tool.group(1) != "tool_call" and isinstance(bare_args, dict):
                return ToolRequest(name=bare_tool.group(1), arguments=bare_args)
        direct_tool = re.search(
            r'\{\s*"tool"\s*:\s*"([A-Za-z0-9_.+-]+)"\s*,\s*"arguments"\s*:\s*(\{.*?\})\s*\}',
            normalized,
            re.DOTALL,
        )
        if direct_tool:
            try:
                direct_args = json.loads(direct_tool.group(2))
            except json.JSONDecodeError:
                direct_args = None
            if isinstance(direct_args, dict):
                return ToolRequest(name=direct_tool.group(1), arguments=direct_args)
        direct_name = re.search(
            r'\{\s*"name"\s*:\s*"([A-Za-z0-9_.+-]+)"\s*,\s*"arguments"\s*:\s*(\{.*?\})\s*\}',
            normalized,
            re.DOTALL,
        )
        if direct_name:
            try:
                name_args = json.loads(direct_name.group(2))
            except json.JSONDecodeError:
                name_args = None
            if isinstance(name_args, dict):
                return ToolRequest(name=direct_name.group(1), arguments=name_args)
        if not normalized.startswith("{"):
            candidates = re.findall(r"\{.*\}", normalized, flags=re.DOTALL)
            if candidates:
                normalized = candidates[-1]
    function_tag = re.match(r"<function\s*=\s*([A-Za-z0-9_.+\-]+)\s*>(.*?)</function>", normalized, re.IGNORECASE | re.DOTALL)
    if function_tag:
        raw_arguments = function_tag.group(2).strip()
        if not raw_arguments:
            arguments = {}
        else:
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                arguments = None
        if isinstance(arguments, dict):
            normalized = json.dumps({"tool_call": {"name": function_tag.group(1), "arguments": arguments}})
    if normalized.startswith("```") and normalized.endswith("```"):
        lines = normalized.splitlines()
        normalized = "\n".join(lines[1:-1]).strip()
        if normalized.lower().startswith("json\n"):
            normalized = normalized[5:].lstrip()
    try:
        payload: Any = json.loads(normalized)
    except json.JSONDecodeError:
        candidates = re.findall(r"\{.*?\}", content, flags=re.DOTALL)
        marker = content.rfind('{"tool_call"')
        if marker >= 0:
            candidates.append(content[marker:])
        payload = None
        for candidate in reversed(candidates):
            try:
                payload, _ = json.JSONDecoder().raw_decode(candidate.strip())
                break
            except (json.JSONDecodeError, ValueError):
                continue
        if payload is None:
            return None
    if isinstance(payload, dict) and isinstance(payload.get("tool_calls"), list):
        calls = payload["tool_calls"]
        if calls and isinstance(calls[0], dict):
            first = calls[0]
            function = first.get("function", first)
            if isinstance(function, dict):
                name = function.get("name")
                arguments = function.get("arguments", function.get("args", {}))
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = None
                if isinstance(name, str) and name.strip() and isinstance(arguments, dict):
                    return ToolRequest(name=name.strip(), arguments=arguments)
    if isinstance(payload, dict) and isinstance(payload.get("tool_call"), str):
        try:
            inner = json.loads(payload["tool_call"])
        except json.JSONDecodeError:
            return None
        payload = {"tool_call": inner}
    if isinstance(payload, dict) and isinstance(payload.get("tool_call"), dict):
        call = payload["tool_call"]
        if "args" in call and "arguments" not in call:
            call["arguments"] = call.pop("args")
        if "tool" in call and "name" not in call:
            payload = {"tool_call": {"name": call["tool"], "arguments": call.get("arguments", {})}}
    if isinstance(payload, dict) and "tool_call" not in payload:
        if "name" in payload and "arguments" in payload:
            payload = {"tool_call": payload}
        elif "name" in payload and "args" in payload:
            payload = {"tool_call": {"name": payload["name"], "arguments": payload["args"]}}
        elif "tool" in payload and "arguments" in payload:
            payload = {"tool_call": {"name": payload["tool"], "arguments": payload["arguments"]}}
        elif "tool" in payload and "args" in payload:
            payload = {"tool_call": {"name": payload["tool"], "arguments": payload["args"]}}
    if tagged and isinstance(payload, dict) and "name" in payload and "arguments" in payload:
        payload = {"tool_call": payload}
    if not isinstance(payload, dict) or set(payload) != {"tool_call"}:
        return None
    call = payload.get("tool_call")
    if not isinstance(call, dict) or set(call) - {"name", "arguments"}:
        return None
    name = call.get("name")
    arguments = call.get("arguments", {})
    if not isinstance(name, str) or not name.strip() or not isinstance(arguments, dict):
        return None
    return ToolRequest(name=name.strip(), arguments=arguments)
