import re

from arqen.core.contracts import Message, ToolRequest
from arqen.core.tool_protocol import parse_tool_request
from arqen.providers.base import AIProvider
from arqen.tools.executor import ToolExecutor
from arqen.tools.registry import ToolRegistry
from arqen.tools.schema import build_tool_schemas
from arqen.core.session_store import ChatSession, SessionStore
from arqen.core.memory_store import MemoryStore
from collections.abc import Callable


_PATH_WITH_EXTENSION = re.compile(r"^(.*?\.[A-Za-z0-9]{1,8})(?:\s|$)")


def _leading_path(rest: str) -> str:
    """Take just the file path out of ``läs <path> och gör något med den``.

    Everything after the first token that carries a file extension belongs to
    the instruction, not to the path.  Paths themselves may contain spaces, so
    the extension is what marks the end rather than the first space.
    """
    match = _PATH_WITH_EXTENSION.match(rest.strip())
    return match.group(1) if match else rest.strip()


class ConversationEngine:
    def __init__(
        self,
        provider: AIProvider,
        tools: ToolRegistry | None = None,
        on_tool_request: Callable[[str], None] | None = None,
        on_confirmation_required: Callable[..., None] | None = None,
        on_partial_response: Callable[[str], None] | None = None,
        session_store: SessionStore | None = None,
        memory_store: MemoryStore | None = None,
        should_cancel: Callable[[], bool] | None = None,
        max_tool_steps: int = 8,
    ) -> None:
        self.provider = provider
        self.tools = tools or ToolRegistry()
        self.executor = ToolExecutor(self.tools)
        self.on_tool_request = on_tool_request
        self.on_confirmation_required = on_confirmation_required
        self.on_partial_response = on_partial_response
        self.should_cancel = should_cancel
        self.max_tool_steps = max_tool_steps
        self.session_store = session_store or SessionStore()
        self.memory_store = memory_store or MemoryStore()
        self.session = self.session_store.create()
        self.messages: list[Message] = []
        self.voice_enabled = False
        self.last_response_speakable = False

    def _ensure_system_context(self) -> None:
        if self.messages:
            return
        tool_description = self.tools.prompt_description()
        memories = self.memory_store.list()
        memory_context = "\n".join(f"- {item}" for item in memories) or "none"
        self.messages.append(
            Message(
                role="system",
                content=(
                    "You are Arqen Desktop. Use normal text for conversation. "
                    "Answer in Swedish by default unless the user asks for another language. "
                    "Request a tool only with the exact JSON tool_call envelope. "
                    "Never claim a tool ran unless a tool result is provided. "
                    "Never claim to remember a person, fact, or note unless it appears in User-approved memory. "
                    "Do not invent memory entries or say that notes were saved without an explicit memory command.\n\n"
                    f"Available tools:\n{tool_description or 'none'}"
                    f"\n\nUser-approved memory:\n{memory_context}"
                ),
            )
        )

    def respond(self, prompt: str) -> str:
        self.last_response_speakable = False
        voice_command = prompt.strip().casefold()
        if voice_command in {"röstläge på", "rostläge på", "voice mode on"}:
            self.voice_enabled = True
            return "Röstläge aktiverat."
        if voice_command in {"röstläge av", "rostläge av", "voice mode off"}:
            self.voice_enabled = False
            return "Röstläge avstängt."
        if (voice_command.startswith("säg ") or voice_command.startswith("sag ")) and not self.voice_enabled:
            return "Röstläge är avstängt. Slå på 🔊 för att använda uppläsning."
        self._ensure_system_context()
        memory_response = self._handle_memory_command(prompt)
        if memory_response is not None:
            self.messages.append(Message(role="user", content=prompt))
            self.messages.append(Message(role="assistant", content=memory_response))
            self._save_session()
            return memory_response
        export_response = self._handle_export_command(prompt)
        if export_response is not None:
            self.messages.append(Message(role="user", content=prompt))
            self.messages.append(Message(role="assistant", content=export_response))
            self._save_session()
            return export_response
        document_response = self._handle_document_command(prompt)
        if document_response is not None:
            self.messages.append(Message(role="user", content=prompt))
            self.messages.append(Message(role="assistant", content=document_response))
            self._save_session()
            return document_response
        self._add_desktop_context()
        self.messages.append(Message(role="user", content=prompt))
        return self._run_tool_loop(prompt)

    def _cancelled(self) -> bool:
        return bool(self.should_cancel and self.should_cancel())

    def _run_tool_loop(self, prompt: str) -> str:
        """Call the provider, run any tool it asks for, then let it continue.

        Providers with native tool calling drive the loop themselves.  For the
        others the keyword heuristics in ``_direct_safe_command`` stand in, and
        a single tool result still ends the turn because the model has no way
        to act on it.
        """
        native = getattr(self.provider, "supports_tools", False)
        tools = build_tool_schemas(self.tools) if native else None
        direct_request = None if native else self._direct_safe_command(prompt)
        last_content = ""

        for _ in range(self.max_tool_steps):
            if self._cancelled():
                break
            if direct_request is not None:
                request, response = direct_request, None
                direct_request = None
            else:
                response = self._call_provider(tools)
                if self._cancelled():
                    break
                request = response.tool_request or parse_tool_request(response.content)
                last_content = response.content

            if request is None:
                self.messages.append(Message(role="assistant", content=response.content))
                self.last_response_speakable = self.voice_enabled
                self._save_session()
                return response.content

            self.last_response_speakable = False
            if self.on_tool_request:
                self.on_tool_request(request.name)
            if response is not None and response.tool_calls:
                self.messages.append(Message(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                ))
            result = self.executor.execute(request.name, request.arguments)
            if result.confirmation_required:
                if self.on_confirmation_required:
                    self.on_confirmation_required(request.name, request.arguments)
                content = f"Jag behöver din bekräftelse innan jag kör verktyget '{request.name}'."
                self.messages.append(Message(role="tool", content=content, tool_call_id=request.call_id))
                self._save_session()
                return content
            self.messages.append(Message(role="tool", content=result.output, tool_call_id=request.call_id))
            last_content = result.output
            if not native:
                # Without native tool calling the model cannot read the result,
                # so the tool output is the answer.
                self._save_session()
                return result.output

        self._save_session()
        if self._cancelled():
            return last_content or "Avbrutet."
        return last_content or "Jag kom inte vidare."

    def _call_provider(self, tools: list[dict] | None):
        if hasattr(self.provider, "respond_stream"):
            return self.provider.respond_stream(
                self.messages, self.on_partial_response, self._cancelled, tools
            )
        if tools:
            return self.provider.respond(self.messages, tools)
        return self.provider.respond(self.messages)

    def _save_session(self) -> None:
        self.session.messages = list(self.messages)
        if self.session.title == "Ny chatt":
            first_user = next((m.content for m in self.messages if m.role == "user"), "")
            if first_user:
                self.session.title = first_user.strip()[:40]
        self.session_store.save(self.session)

    def new_session(self, title: str = "Ny chatt") -> ChatSession:
        self.session = self.session_store.create(title)
        self.messages = []
        return self.session

    def load_session(self, session_id: str) -> ChatSession:
        self.session = self.session_store.load(session_id)
        self.messages = list(self.session.messages)
        return self.session

    def _add_desktop_context(self) -> None:
        active_window = self.tools.get("active_window")
        if active_window is None:
            return

    def _handle_memory_command(self, prompt: str) -> str | None:
        text = prompt.strip()
        lower = text.lower()
        if lower.startswith("kom ihåg att "):
            fact = text[len("kom ihåg att "):].strip()
            self.memory_store.remember(fact)
            return f"Jag har sparat i minnet: {fact}"
        if lower in {"visa mitt minne", "visa minnet", "vad minns du"}:
            memories = self.memory_store.list()
            return "Mitt minne är tomt." if not memories else "Jag minns:\n- " + "\n- ".join(memories)
        if lower.startswith("glöm att "):
            fact = text[len("glöm att "):].strip()
            return (
                f"Jag har glömt: {fact}"
                if self.memory_store.forget(fact)
                else f"Jag hade inte sparat: {fact}"
            )
        return None

    def _handle_export_command(self, prompt: str) -> str | None:
        lower = prompt.strip().lower()
        prefixes = ("exportera chatten som ", "spara chatten som ")
        prefix = next((item for item in prefixes if lower.startswith(item)), None)
        if prefix is None:
            return None
        path = prompt.strip()[len(prefix):].strip()
        if not path.lower().endswith((".txt", ".md")):
            path += ".md"
        lines = [f"# {self.session.title}", ""]
        for message in self.messages:
            if message.role == "system":
                continue
            label = {"user": "DU", "assistant": "ARQEN", "tool": "VERKTYG"}.get(message.role, message.role.upper())
            lines.extend([f"## {label}", message.content, ""])
        result = self.executor.execute(
            "write_workspace_file",
            {"path": path, "content": "\n".join(lines)},
        )
        if result.confirmation_required:
            return f"Jag behöver din bekräftelse innan jag exporterar chatten till '{path}'."
        return result.output

    def _handle_document_command(self, prompt: str) -> str | None:
        lower = prompt.strip().lower()
        if lower.startswith("sammanfatta vad du nyss") or lower.startswith("sammanfatta det du nyss"):
            last_tool = next((message for message in reversed(self.messages) if message.role == "tool"), None)
            if last_tool is None:
                return "Det finns inget tidigare verktygssvar att sammanfatta."
            messages = [
                Message(role="system", content="Sammanfatta verktygssvaret på svenska i exakt två korta meningar."),
                Message(role="user", content=last_tool.content[:30_000]),
            ]
            return self.provider.respond(messages).content
        if lower.startswith("sammanfatta resultat ") or lower.startswith("sammanfatta resultat "):
            number = prompt.strip().split()[-1]
            if not number.isdigit():
                return "Ange ett resultatnummer, exempelvis: sammanfatta resultat 3"
            search_tool = self.tools.get("search_web")
            index = int(number) - 1
            results = getattr(search_tool, "last_results", []) if search_tool else []
            if not 0 <= index < len(results):
                return "Det resultatnumret finns inte i den senaste sökningen."
            fetched = self.executor.execute("fetch_webpage", {"url": results[index][1]})
            if not fetched.ok:
                return fetched.output
            messages = [
                Message(role="system", content="Sammanfatta webbsidan kort på svenska. Ta med syfte, huvudpunkter och viktiga slutsatser."),
                Message(role="user", content=fetched.output[:30_000]),
            ]
            return self.provider.respond(messages).content
        if lower.startswith("jämför ") or lower.startswith("jamfor "):
            return self._compare_documents(prompt.strip()[7:].strip())
        prefixes = ("sammanfatta ", "sammanfatta dokument ")
        prefix = next((item for item in prefixes if lower.startswith(item)), None)
        if prefix is None:
            return None
        path = prompt.strip()[len(prefix):].strip()
        suffix = path.lower().rsplit(".", 1)[-1] if "." in path else ""
        tool_name = {
            "txt": "read_workspace_file",
            "md": "read_workspace_file",
            "pdf": "read_pdf",
            "docx": "read_docx",
            "xlsx": "read_xlsx",
        }.get(suffix)
        if tool_name is None:
            return f"Jag kan ännu inte sammanfatta filtypen: {suffix or 'okänd'}."
        result = self.executor.execute(tool_name, {"path": path})
        if not result.ok:
            return result.output
        document = result.output[:30_000]
        messages = [
            Message(role="system", content="Sammanfatta dokumentet kort på svenska. Ta med syfte, huvudpunkter och viktiga slutsatser."),
            Message(role="user", content=f"Dokument: {path}\n\n{document}"),
        ]
        return self.provider.respond(messages).content

    def _compare_documents(self, specification: str) -> str:
        parts = specification.split(" med ", 1)
        if len(parts) != 2:
            return "Ange två filer, exempelvis: jämför ett.pdf med två.pdf"
        paths = [part.strip() for part in parts]
        contents = []
        for path in paths:
            suffix = path.lower().rsplit(".", 1)[-1] if "." in path else ""
            tool_name = {
                "txt": "read_workspace_file",
                "md": "read_workspace_file",
                "pdf": "read_pdf",
                "docx": "read_docx",
                "xlsx": "read_xlsx",
            }.get(suffix)
            if tool_name is None:
                return f"Jag kan inte jämföra filtypen: {path}"
            result = self.executor.execute(tool_name, {"path": path})
            if not result.ok:
                return result.output
            contents.append(result.output[:20_000])
        messages = [
            Message(role="system", content="Jämför två dokument på svenska. Lista likheter, skillnader och saknade delar tydligt."),
            Message(role="user", content=f"Dokument 1: {paths[0]}\n{contents[0]}\n\nDokument 2: {paths[1]}\n{contents[1]}"),
        ]
        return self.provider.respond(messages).content
        try:
            context = active_window.run({})
            system_message = self.messages[0]
            self.messages[0] = Message(
                role="system",
                content=(
                    system_message.content
                    + f"\n\nCurrent desktop context: {context}"
                ),
            )
        except Exception:
            # Context is helpful, but must never prevent normal conversation.
            return

    def _direct_safe_command(self, prompt: str) -> ToolRequest | None:
        """Handle explicit, read-only diagnostics without model formatting risk."""
        lower_prompt = prompt.strip().lower()
        image_starts = ("generera bild ", "generera en bild ", "skapa bild ", "skapa en bild ")
        if lower_prompt.startswith(image_starts):
            image_prompt = prompt.split(" ", 2)[-1].strip()
            return ToolRequest(name="generate_image", arguments={"prompt": image_prompt})
        if lower_prompt.startswith(("skapa en ", "generera en ")) and any(word in lower_prompt for word in ("ai", "assistent", "holograf", "cyberpunk", "bild")):
            return ToolRequest(name="generate_image", arguments={"prompt": prompt.strip()})
        image_terms = ("soundwave", "ljudvåg", "ljudvag", "bild", "ringar", "neon", "holograf", "cyberpunk")
        image_leads = ("behåll", "behall", "ändra", "andra", "gör", "gor", "skapa", "generera", "designa", "förfina", "forfina", "förbättra", "forbattra", "justera", "utgå", "utga")
        if lower_prompt.startswith(image_leads) and any(term in lower_prompt for term in image_terms):
            return ToolRequest(name="generate_image", arguments={"prompt": prompt.strip()})
        if prompt.strip().lower() in {"systemstatus", "system status"}:
            return ToolRequest(name="system_status", arguments={})
        if prompt.strip().lower() in {"tid", "time", "klockan"}:
            return ToolRequest(name="current_time", arguments={})
        if prompt.strip().lower() in {"resurser", "systemresurser", "system resources"}:
            return ToolRequest(name="system_resources", arguments={})
        lower_prompt = prompt.strip().casefold()
        if "väder" in lower_prompt and "göteborg" in lower_prompt:
            return ToolRequest(name="weather_forecast", arguments={})
        if prompt.strip().lower() in {
            "processer",
            "pågående processer",
            "korande processer",
            "running processes",
            "vilka program körs just nu?",
            "vilka program körs just nu",
        }:
            return ToolRequest(name="running_processes", arguments={})
        if prompt.strip().lower() in {"fönster", "fonster", "öppna fönster", "öppna fonster", "open windows"}:
            return ToolRequest(name="open_windows", arguments={})
        if prompt.strip().lower() in {"installerade program", "installerade appar", "installed programs"}:
            return ToolRequest(name="installed_programs", arguments={})
        if prompt.strip().lower().startswith("sök installerade program efter ") or prompt.strip().lower().startswith("sok installerade program efter "):
            query = prompt.split(" efter ", 1)[1].strip()
            return ToolRequest(name="installed_programs", arguments={"query": query})
        if prompt.strip().lower().startswith("stäng program ") or prompt.strip().lower().startswith("stang program "):
            target = prompt.split(" ", 2)[2].strip()
            return ToolRequest(name="close_program", arguments={"target": target})
        if prompt.strip().lower().startswith("stäng ") or prompt.strip().lower().startswith("stang "):
            target = prompt.split(" ", 1)[1].strip()
            return ToolRequest(name="close_program", arguments={"target": target})
        if prompt.strip().lower().startswith("fokusera på ") or prompt.strip().lower().startswith("fokusera pa "):
            title = prompt.split(" ", 2)[2].strip()
            return ToolRequest(name="focus_window", arguments={"title": title})
        if prompt.strip().lower().startswith("säg ") or prompt.strip().lower().startswith("sag "):
            text = prompt.split(" ", 1)[1].strip()
            return ToolRequest(name="speak_text", arguments={"text": text})
        if prompt.strip().lower() in {"stoppa uppläsning", "stoppa rösten", "tysta arqen", "stop speech"}:
            return ToolRequest(name="stop_speech", arguments={})
        if prompt.strip().lower().startswith("öppna fil ") or prompt.strip().lower().startswith("oppna fil "):
            path = prompt.split(" ", 2)[2].strip()
            return ToolRequest(name="launch_path", arguments={"path": path})
        if prompt.strip().lower().startswith("öppna program ") or prompt.strip().lower().startswith("oppna program "):
            program = prompt.split(" ", 2)[2].strip()
            return ToolRequest(name="launch_program", arguments={"program": program})
        if prompt.strip().lower().startswith("starta ") or prompt.strip().lower().startswith("start "):
            program = prompt.split(" ", 1)[1].strip()
            return ToolRequest(name="launch_program", arguments={"program": program})
        if prompt.strip().lower().startswith("öppna mapp ") or prompt.strip().lower().startswith("oppna mapp "):
            path = prompt.split(" ", 2)[2].strip()
            return ToolRequest(name="launch_path", arguments={"path": path})
        if prompt.strip().lower() in {"aktivt fönster", "aktivt fonster", "active window"}:
            return ToolRequest(name="active_window", arguments={})
        if prompt.strip().lower() in {"lista filer", "visa filer", "workspace filer"}:
            return ToolRequest(name="workspace_files", arguments={})
        if prompt.strip().lower().startswith("sök efter ") or prompt.strip().lower().startswith("sok efter "):
            query = prompt.split(" ", 2)[-1].strip()
            return ToolRequest(name="search_workspace_files", arguments={"query": query})
        if prompt.strip().lower().startswith("sök innehåll efter ") or prompt.strip().lower().startswith("sok innehall efter "):
            query = prompt.split(" ", 3)[-1].strip()
            return ToolRequest(name="search_workspace_content", arguments={"query": query})
        if (
            prompt.strip().lower().startswith("läs url ")
            or prompt.strip().lower().startswith("las url ")
        ):
            url = prompt.split(" ", 2)[-1].strip()
            return ToolRequest(name="fetch_webpage", arguments={"url": url})
        if prompt.strip().lower().startswith("navigera till "):
            url = prompt.split(" ", 2)[-1].strip()
            return ToolRequest(name="browser_navigate", arguments={"url": url})
        if prompt.strip().lower() in {"läs webbläsarsidan", "läs webblasarsidan", "läs aktuell webbsida"}:
            return ToolRequest(name="browser_read_page", arguments={})
        if "under about" in prompt.strip().lower() or "om about" in prompt.strip().lower():
            return ToolRequest(name="browser_read_page", arguments={"section": "ABOUT"})
        if prompt.strip().lower() in {"visa länkar", "visa länkar på sidan", "visa lankar"}:
            return ToolRequest(name="browser_list_links", arguments={})
        if prompt.strip().lower() in {"gå tillbaka", "gå bakåt", "backa i webbläsaren"}:
            return ToolRequest(name="browser_back", arguments={})
        if prompt.strip().lower() in {"gå framåt", "framåt i webbläsaren"}:
            return ToolRequest(name="browser_forward", arguments={})
        if prompt.strip().lower().startswith("klicka på ") or prompt.strip().lower().startswith("klicka pa "):
            text = prompt.split(" ", 2)[-1].strip()
            return ToolRequest(name="browser_click_link", arguments={"text": text})
        if (
            prompt.strip().lower().startswith("öppna url ")
            or prompt.strip().lower().startswith("oppna url ")
            or prompt.strip().lower().startswith("öppna webbsida ")
            or prompt.strip().lower().startswith("oppna webbsida ")
        ):
            url = prompt.split(" ", 2)[-1].strip()
            return ToolRequest(name="open_webpage", arguments={"url": url})
        if prompt.strip().lower().startswith("öppna ") or prompt.strip().lower().startswith("oppna "):
            target = prompt.split(" ", 1)[-1].strip()
            if target.lower().startswith("resultat ") and target.split()[-1].isdigit():
                search_tool = self.tools.get("search_web")
                index = int(target.split()[-1]) - 1
                if search_tool is not None and 0 <= index < len(getattr(search_tool, "last_results", [])):
                    return ToolRequest(name="open_webpage", arguments={"url": search_tool.last_results[index][1]})
                return None
            if target.lower().startswith("länk ") or target.lower().startswith("lank "):
                from arqen.tools.browser_tools import STATE
                index = int(target.split()[-1]) - 1 if target.split()[-1].isdigit() else -1
                if 0 <= index < len(STATE.last_links):
                    return ToolRequest(name="open_webpage", arguments={"url": STATE.last_links[index][1]})
                return None
            if "." in target and " " not in target and not target.startswith((".", "\\")):
                url = target if target.startswith(("http://", "https://")) else f"https://{target}"
                return ToolRequest(name="open_webpage", arguments={"url": url})
        if prompt.strip().lower().startswith("sök webben efter ") or prompt.strip().lower().startswith("sok webben efter "):
            query = prompt.split(" ", 3)[-1].strip()
            return ToolRequest(name="search_web", arguments={"query": query})
        if prompt.strip().lower().startswith("läs pdf ") or prompt.strip().lower().startswith("las pdf "):
            path = prompt.split(" ", 2)[-1].strip()
            return ToolRequest(name="read_pdf", arguments={"path": path})
        if prompt.strip().lower().startswith("läs docx ") or prompt.strip().lower().startswith("las docx "):
            path = prompt.split(" ", 2)[-1].strip()
            return ToolRequest(name="read_docx", arguments={"path": path})
        if prompt.strip().lower().startswith("läs xlsx ") or prompt.strip().lower().startswith("las xlsx "):
            path = prompt.split(" ", 2)[-1].strip()
            return ToolRequest(name="read_xlsx", arguments={"path": path})
        if prompt.strip().lower().startswith("läs ") or prompt.strip().lower().startswith("las "):
            path = _leading_path(prompt.split(" ", 1)[-1].strip())
            if path.lower().endswith(".pdf"):
                return ToolRequest(name="read_pdf", arguments={"path": path})
            if path.lower().endswith(".docx"):
                return ToolRequest(name="read_docx", arguments={"path": path})
            if path.lower().endswith(".xlsx"):
                return ToolRequest(name="read_xlsx", arguments={"path": path})
            return ToolRequest(name="read_workspace_file", arguments={"path": path})
        if prompt.strip().lower() in {"ångra", "ångra senaste filändring", "undo"}:
            return ToolRequest(name="undo_workspace_file_change", arguments={})
        return None

    def confirm_pending_tool(self, accepted: bool) -> str:
        result = self.executor.confirm_pending(accepted)
        self.messages.append(Message(role="tool", content=result.output))
        self._save_session()
        return result.output
