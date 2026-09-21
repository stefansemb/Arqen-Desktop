from arqen.core.tool_protocol import parse_tool_request


def test_valid_tool_call_is_parsed() -> None:
    request = parse_tool_request(
        '{"tool_call":{"name":"system_status","arguments":{}}}'
    )
    assert request is not None
    assert request.name == "system_status"


def test_fenced_json_tool_call_is_parsed() -> None:
    request = parse_tool_request(
        '```json\n{"tool_call":{"name":"system_status","arguments":{}}}\n```'
    )
    assert request is not None
    assert request.name == "system_status"


def test_ollama_tagged_tool_call_is_parsed() -> None:
    request = parse_tool_request(
        '<tool_call>{"name":"write_workspace_file","arguments":{"path":"test.txt","content":"Hej"}}</tool_call>'
    )
    assert request is not None
    assert request.name == "write_workspace_file"
    assert request.arguments["path"] == "test.txt"


def test_stringified_tool_call_is_parsed() -> None:
    request = parse_tool_request(
        '{"tool_call":"{\\"name\\": \\"system_status\\", \\"arguments\\": {}}"}'
    )
    assert request is not None
    assert request.name == "system_status"


def test_tool_alias_is_parsed() -> None:
    request = parse_tool_request(
        '{"tool_call":{"tool":"system_status","arguments":{}}}'
    )
    assert request is not None
    assert request.name == "system_status"


def test_normal_text_is_not_a_tool_call() -> None:
    assert parse_tool_request("Please answer normally.") is None


def test_malformed_tool_call_is_rejected() -> None:
    assert parse_tool_request('{"tool_call":{"name": "system_status"}}') is not None
    assert parse_tool_request('{"tool_call":{"name": 12}}') is None
