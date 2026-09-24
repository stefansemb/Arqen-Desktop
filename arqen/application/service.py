from dataclasses import dataclass
from typing import Callable

from arqen.core.engine import ConversationEngine
from arqen.core.session_store import ChatSession, SessionStore


@dataclass(frozen=True)
class MessageResult:
    session_id: str
    user_message: str
    assistant_message: str
    speakable: bool
    status: str = "ready"


@dataclass(frozen=True)
class SessionSummary:
    session_id: str
    title: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ArqenStatus:
    provider: str
    model: str
    voice_enabled: bool
    session_id: str
    status: str = "ready"


class ArqenApplication:
    """Application boundary shared by desktop, API and future mobile clients."""

    def __init__(
        self,
        engine_factory: Callable[[], ConversationEngine],
        session_store: SessionStore | None = None,
    ) -> None:
        self.session_store = session_store or SessionStore()
        self._engine_factory = engine_factory
        self._engines: dict[str, ConversationEngine] = {}

    def create_session(self, title: str = "Ny chatt") -> SessionSummary:
        session = self.session_store.create(title)
        self.session_store.save(session)
        self._engines[session.session_id] = self._new_engine(session)
        return self._summary(session)

    def list_sessions(self) -> list[SessionSummary]:
        return [self._summary(session) for session in self.session_store.list_sessions()]

    def get_session(self, session_id: str) -> ChatSession:
        return self.session_store.load(session_id)

    def rename_session(self, session_id: str, title: str) -> SessionSummary:
        cleaned_title = title.strip()
        if not cleaned_title:
            raise ValueError("Titeln får inte vara tom")
        session = self.session_store.load(session_id)
        session.title = cleaned_title
        self.session_store.save(session)
        return self._summary(session)

    def delete_session(self, session_id: str) -> None:
        self.session_store.delete(session_id)
        self._engines.pop(session_id, None)

    def send_message(self, session_id: str, content: str) -> MessageResult:
        prompt = content.strip()
        if not prompt:
            raise ValueError("Meddelandet får inte vara tomt")
        engine = self._engine_for(session_id)
        response = engine.respond(prompt)
        return MessageResult(
            session_id=session_id,
            user_message=prompt,
            assistant_message=response,
            speakable=engine.last_response_speakable,
        )

    def status(self, session_id: str | None = None) -> ArqenStatus:
        engine = self._engine_for(session_id) if session_id else self._default_engine()
        provider = getattr(engine.provider, "provider_name", "unknown")
        model = getattr(engine.provider, "model", "")
        return ArqenStatus(
            provider=provider,
            model=model,
            voice_enabled=engine.voice_enabled,
            session_id=engine.session.session_id,
        )

    def tool_catalog(self) -> list[dict]:
        return self._default_engine().gateway.catalog()

    def tool_audit(self, limit: int = 100) -> list[dict]:
        return self._default_engine().gateway.audit_entries(limit)

    def tool_policies(self) -> list[dict]:
        return self._default_engine().gateway.policy_view()

    def _default_engine(self) -> ConversationEngine:
        if self._engines:
            return next(iter(self._engines.values()))
        session = self.session_store.create()
        self._engines[session.session_id] = self._new_engine(session)
        return self._engines[session.session_id]

    def _engine_for(self, session_id: str) -> ConversationEngine:
        if session_id not in self._engines:
            session = self.session_store.load(session_id)
            self._engines[session_id] = self._new_engine(session)
        return self._engines[session_id]

    def _new_engine(self, session: ChatSession) -> ConversationEngine:
        engine = self._engine_factory()
        engine.session_store = self.session_store
        engine.session = session
        engine.messages = list(session.messages)
        return engine

    @staticmethod
    def _summary(session: ChatSession) -> SessionSummary:
        return SessionSummary(
            session_id=session.session_id,
            title=session.title,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )
