"""Shared argument-validation helpers for tool metadata and diagnostics."""


def schema_description(schema: dict[str, type]) -> str:
    return ", ".join(f"{name}: {kind.__name__}" for name, kind in schema.items())

