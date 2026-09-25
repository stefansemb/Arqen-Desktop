"""Reflect: turn recent work into suggested memories the user can approve.

One model call reads recent tasks, the user's recent chat messages and what is
already remembered, and names a few lasting lessons.  Each becomes a
*proposed* memory, so a reflection never writes to memory on its own: the
user approves or rejects every lesson under Minne, like any other suggestion.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from arqen.core.contracts import Message
from arqen.core.memory_store import MemoryStore, looks_secret

MAX_LESSONS = 5
_TASK_LIMIT = 30
_CHAT_LIMIT = 10
_MESSAGES_PER_CHAT = 8
_CLIP = 200


@dataclass(frozen=True)
class ReflectionSources:
    memories: list[str]
    tasks: list[str]
    chats: list[str]

    @property
    def empty(self) -> bool:
        return not self.tasks and not self.chats


def _clip(text: str, limit: int = _CLIP) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def gather_sources(memory_store: MemoryStore, mission_store=None, session_store=None) -> ReflectionSources:
    """Collect what a reflection reads: short lines, newest first."""
    memories = [record.content for record in memory_store.records() if record.status in {"approved", "proposed"}]

    tasks: list[str] = []
    if mission_store is not None:
        agents = {agent.id: agent.name for agent in mission_store.list_agents()}
        rejected = {approval.task_id: approval.action for approval in mission_store.list_approvals("rejected")}
        for task in mission_store.list_tasks()[:_TASK_LIMIT]:
            line = f"{task.title} — {task.status}"
            if task.agent_id:
                line += f" — agent {agents.get(task.agent_id, task.agent_id)}"
            if task.error:
                line += f" — error: {_clip(task.error, 120)}"
            if task.id in rejected:
                line += f" — user rejected {rejected[task.id]}"
            tasks.append(_clip(line, 260))

    chats: list[str] = []
    if session_store is not None:
        for session in session_store.list_sessions()[:_CHAT_LIMIT]:
            # Only what the user wrote: their own words say what they want,
            # and the replies would mostly repeat tool output.
            said = [_clip(m.content) for m in session.messages if m.role == "user" and m.content.strip()]
            if said:
                chats.append(f"{_clip(session.title, 60)}: " + " | ".join(said[-_MESSAGES_PER_CHAT:]))
    return ReflectionSources(memories, tasks, chats)


def build_messages(sources: ReflectionSources) -> list[Message]:
    def section(title: str, lines: list[str]) -> str:
        return f"{title}:\n" + ("\n".join(f"- {line}" for line in lines) if lines else "- (none)")

    system = (
        "You review how a user works with their assistant Arqen and name lasting lessons worth remembering: "
        "preferences, recurring patterns, risks that keep coming back, and decisions. "
        f"Return at most {MAX_LESSONS} lessons as a JSON array of strings and nothing else, e.g. "
        '["Användaren vill ha svar på svenska."]. '
        "Each lesson is one short sentence in Swedish that stays true beyond a single conversation. "
        "Skip one-off requests, anything already in memory, and never include passwords, keys or other secrets. "
        "If nothing lasting stands out, return []."
    )
    user = "\n\n".join((
        section("Already in memory", sources.memories),
        section("Recent tasks (newest first)", sources.tasks),
        section("Recent chats, the user's own messages", sources.chats),
    ))
    return [Message(role="system", content=system), Message(role="user", content=user)]


def parse_lessons(text: str) -> list[str]:
    """The lessons in a model reply, tolerating prose or code fences around the JSON."""
    match = re.search(r"\[.*\]", text or "", re.DOTALL)
    if not match:
        return []
    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    lessons: list[str] = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict):
            item = item.get("lesson") or item.get("text") or ""
        if not isinstance(item, str):
            continue
        lesson = " ".join(item.split())
        if 0 < len(lesson) <= 300 and not looks_secret(lesson) and lesson.casefold() not in {x.casefold() for x in lessons}:
            lessons.append(lesson)
    return lessons[:MAX_LESSONS]


@dataclass(frozen=True)
class ReflectionResult:
    added: list[str]
    skipped: int
    had_sources: bool


def reflect(provider, memory_store: MemoryStore, mission_store=None, session_store=None) -> ReflectionResult:
    """Run one reflection and store its new lessons as proposed memories."""
    sources = gather_sources(memory_store, mission_store, session_store)
    if sources.empty:
        return ReflectionResult([], 0, False)
    reply = provider.respond(build_messages(sources))
    lessons = parse_lessons(getattr(reply, "content", "") or "")
    known = {record.content.casefold() for record in memory_store.records()}
    stamp = datetime.now(timezone.utc).date().isoformat()
    added: list[str] = []
    for lesson in lessons:
        if lesson.casefold() in known:
            continue
        memory_store.retain(lesson, source="reflect", provenance=f"reflect:{stamp}", status="proposed", confidence=0.5)
        known.add(lesson.casefold())
        added.append(lesson)
    return ReflectionResult(added, len(lessons) - len(added), True)
