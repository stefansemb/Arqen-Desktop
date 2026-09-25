"""How the Tools view presents each tool: category, Swedish name and summary.

The tool's own description is written for the model and stays in English;
this table is only for people reading the catalogue.  A tool that is missing
here still shows up, under "Övrigt" with its model description.
"""

from __future__ import annotations

from dataclasses import dataclass

# Display order of the catalogue sections.
CATEGORIES = (
    "System",
    "Fönster & program",
    "Filer i arbetsytan",
    "Dokument",
    "Webb",
    "Webbläsare",
    "Röst & bild",
    "Minne",
    "Utveckling",
    "Google",
    "Meddelanden",
    "MCP",
    "Övrigt",
)


@dataclass(frozen=True)
class ToolInfo:
    category: str
    title: str
    summary: str


_TOOLS: dict[str, ToolInfo] = {
    "system_status": ToolInfo("System", "Systemstatus", "Operativsystem och Python-miljö."),
    "current_time": ToolInfo("System", "Aktuell tid", "Dagens datum och klockslag."),
    "system_resources": ToolInfo("System", "Resurser", "Processor- och minnesanvändning just nu."),
    "running_processes": ToolInfo("System", "Processer", "De processer som använder mest processor."),
    "active_window": ToolInfo("Fönster & program", "Aktivt fönster", "Titel och process för fönstret i fokus."),
    "open_windows": ToolInfo("Fönster & program", "Öppna fönster", "Listar synliga fönster."),
    "focus_window": ToolInfo("Fönster & program", "Fokusera fönster", "Tar fram ett fönster efter titel."),
    "launch_path": ToolInfo("Fönster & program", "Öppna fil eller mapp", "Öppnar med Windows standardprogram."),
    "launch_program": ToolInfo("Fönster & program", "Starta program", "Startar ett installerat program."),
    "installed_programs": ToolInfo("Fönster & program", "Installerade program", "Listar program från registret."),
    "close_program": ToolInfo("Fönster & program", "Stäng program", "Avslutar en process via PID eller namn."),
    "workspace_files": ToolInfo("Filer i arbetsytan", "Lista filer", "Filer och storlekar i arbetsytans rot."),
    "search_workspace_files": ToolInfo("Filer i arbetsytan", "Sök filnamn", "Söker filnamn i hela arbetsytan."),
    "search_workspace_content": ToolInfo("Filer i arbetsytan", "Sök i innehåll", "Söker text i filerna."),
    "read_workspace_file": ToolInfo("Filer i arbetsytan", "Läs fil", "Läser en textfil."),
    "write_workspace_file": ToolInfo("Filer i arbetsytan", "Skriv fil", "Skapar eller skriver över en textfil."),
    "delete_workspace_file": ToolInfo("Filer i arbetsytan", "Ta bort fil", "Tar bort en fil."),
    "move_workspace_file": ToolInfo("Filer i arbetsytan", "Flytta fil", "Flyttar eller byter namn på en fil."),
    "undo_workspace_file_change": ToolInfo("Filer i arbetsytan", "Ångra filändring", "Återställer den senaste ändringen."),
    "read_pdf": ToolInfo("Dokument", "Läs PDF", "Hämtar texten ur en PDF."),
    "read_docx": ToolInfo("Dokument", "Läs Word", "Hämtar texten ur en DOCX-fil."),
    "read_xlsx": ToolInfo("Dokument", "Läs Excel", "Blad och celler ur en XLSX-fil."),
    "search_web": ToolInfo("Webb", "Sök på webben", "Kort lista med sökträffar."),
    "fetch_webpage": ToolInfo("Webb", "Hämta webbsida", "Titel och läsbar text från en sida."),
    "open_webpage": ToolInfo("Webb", "Öppna i webbläsare", "Öppnar en adress i din webbläsare."),
    "weather_forecast": ToolInfo("Webb", "Väderprognos", "Kvällsprognos för Göteborg."),
    "browser_navigate": ToolInfo("Webbläsare", "Gå till adress", "Arqens webbläsare öppnar en adress."),
    "browser_read_page": ToolInfo("Webbläsare", "Läs sida", "Titel och synlig text på sidan."),
    "browser_list_links": ToolInfo("Webbläsare", "Lista länkar", "Länkarna på sidan."),
    "browser_click_link": ToolInfo("Webbläsare", "Klicka länk", "Klickar på en länk efter text."),
    "browser_back": ToolInfo("Webbläsare", "Bakåt", "Går tillbaka en sida."),
    "browser_forward": ToolInfo("Webbläsare", "Framåt", "Går fram en sida."),
    "speak_text": ToolInfo("Röst & bild", "Läs upp", "Läser upp text med rösten."),
    "stop_speech": ToolInfo("Röst & bild", "Stoppa uppläsning", "Avbryter pågående uppläsning."),
    "generate_image": ToolInfo("Röst & bild", "Skapa bild", "Genererar en bild via OpenRouter. Kostar pengar."),
    "propose_memory": ToolInfo("Minne", "Föreslå minne", "Föreslår något att minnas. Du godkänner det under Minne."),
    "github_list_repos": ToolInfo("Utveckling", "GitHub: lista repon", "Dina repon, senast ändrade först."),
    "github_list_issues": ToolInfo("Utveckling", "GitHub: lista issues", "Öppna issues i ett repo."),
    "github_read_issue": ToolInfo("Utveckling", "GitHub: läs issue", "Titel, status, etiketter och text."),
    "github_list_pull_requests": ToolInfo("Utveckling", "GitHub: lista pull requests", "Öppna pull requests i ett repo."),
    "github_create_issue": ToolInfo("Utveckling", "GitHub: skapa issue", "Skapar en ny issue i ett repo."),
    "gmail_search_messages": ToolInfo("Google", "Gmail: sök mejl", "Söker i din Gmail och listar träffar."),
    "gmail_read_message": ToolInfo("Google", "Gmail: läs mejl", "Avsändare, ämne, text och bilagor."),
    "gmail_create_draft": ToolInfo("Google", "Gmail: skapa utkast", "Sparar ett mejlutkast. Inget skickas."),
    "calendar_list_events": ToolInfo("Google", "Kalender: kommande", "Händelser i din kalender de närmaste dagarna."),
    "calendar_create_event": ToolInfo("Google", "Kalender: skapa händelse", "Lägger in en händelse i din kalender."),
    "drive_search_files": ToolInfo("Google", "Drive: sök filer", "Söker filer på namn och innehåll."),
    "drive_read_file": ToolInfo("Google", "Drive: läs fil", "Texten ur Docs, Kalkylark, Presentationer och textfiler."),
    "discord_send_message": ToolInfo("Meddelanden", "Discord: skicka", "Skickar ett meddelande till din kanal."),
    "telegram_send_message": ToolInfo("Meddelanden", "Telegram: skicka", "Skickar ett meddelande via din bot."),
}


def tool_info(name: str, model_description: str = "") -> ToolInfo:
    """The display info for ``name``, falling back to its model description."""
    if name in _TOOLS:
        return _TOOLS[name]
    if name.startswith("mcp_"):
        # MCP tools come from the user's servers; show the server's own name.
        from arqen.connectors.mcp import display_title

        return ToolInfo("MCP", display_title(name) or name, model_description)
    return ToolInfo("Övrigt", name, model_description)
