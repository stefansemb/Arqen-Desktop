# Arqen Desktop – funktionsinventering

Detta dokument är ett beslutsunderlag för Arqen Desktop. Brahma Echo används som funktionell referens. Kod, branding och licensbundna resurser kopieras inte.

## Beslutsstatus

- `OPEN` – inte bedömd ännu
- `KEEP` – ska byggas i Arqen
- `REVIEW` – kräver teknisk eller produktmässig utvärdering
- `DROP` – ska inte ingå
- `LATER` – värdefull, men inte i första versionen

## Prioriterad inventering

| Område | Funktion | Referens i nuvarande projekt | Prioritet | Status |
|---|---|---|---:|---|
| Kärna | Konversation och sessionshantering | `main.py`, `llm_client.py`, `core/echo.py` | Hög | KEEP |
| AI | Utbytbar modellklient och fallback | `llm_client.py`, `or_client.py` | Hög | KEEP |
| Röst | Taligenkänning, TTS och avbrott | `core/echo.py`, `sound_manager.py` | Hög | OPEN |
| Aktivering | Wake word och global hotkey | `core/hotkey.py`, `core/echo.py` | Hög | OPEN |
| Verktyg | Action-/tool-dispatch | `main.py`, `actions/` | Hög | KEEP |
| Säkerhet | Bekräftelser före riskfyllda åtgärder | `core/confirm.py` | Hög | KEEP |
| Minne | Långtidsminne och användarprofil | `memory/`, `core/identity.py` | Hög | OPEN |
| Desktop | Appar, filer, fönster och systemkontroll | `actions/`, `core/window_context.py` | Hög | OPEN |
| Skärm | Skärmläsning, vision och kontext | `actions/screen_processor.py`, `actions/attention_monitor.py` | Hög | OPEN |
| Webbläsare | Browser automation | `actions/browser_control.py`, `actions/playwright_mcp_client.py` | Medel | OPEN |
| Dokument | Dokument, PDF, presentationer och kalkylblad | `actions/office_*`, `actions/pdf_tools.py`, `actions/docx_tools.py` | Medel | OPEN |
| Produktivitet | Kalender, möten, påminnelser och briefing | `actions/calendar_scheduler.py`, `actions/meeting_assistant.py` | Medel | OPEN |
| Integrationer | Google Workspace | `actions/google_workspace_mcp.py` | Medel | OPEN |
| Kommunikation | Discord och meddelandebryggor | `discord_bot.py`, `actions/send_message.py` | Medel | OPEN |
| Fjärrstyrning | Mobil/fjärranslutning | `brahma_connect/`, `actions/mobile_autopilot.py` | Låg | OPEN |
| Smart hem | Enheter och providers | `smart_home/` | Låg | OPEN |
| Agent | Planering, kö och exekvering | `agent/` | Medel | OPEN |
| Självförbättring | Lärda regler och preferenser | `core/learned_rules.py` | Medel | OPEN |
| Självreparation | Felanalys, patchning och rollback | `actions/auto_heal_engine.py`, `core/boot_sentry.py`, `core/undo.py` | Låg | REVIEW |
| UI | Desktopgränssnitt och status | `ui.py` | Hög | KEEP |
| Proaktivitet | Bakgrundsvakter och notifieringar | `actions/background_monitor.py`, `actions/proactive.py` | Medel | OPEN |
| Pluginer | Utbyggbar pluginarkitektur | `plugin_manager.py`, `plugins/` | Hög | OPEN |
| Visuell persona | Animerad form/bild som reagerar på röst och svar | Framtida UI-/röstvisualisering | Låg | LATER |

## Första beslutspunkter

1. Definiera Arqens kärnloop och modellabstraktion.
2. Definiera säkerhetsmodellen för verktyg och datorstyrning.
3. Definiera minnesmodellen.
4. Bygga ett minimalt fungerande röst-/textflöde.
5. Lägga till funktioner en kategori i taget.

## Fattade designbeslut

- Arqen ska inte vara beroende av OpenRouter eller Gemini.
- Lokal AI-provider är standard; molnproviders blir valfria adapters.
- Första gränssnittet ska vara mörkt cyberpunk med gröna accenter.
- Temaväxling får stöd senare, men färger ska hållas centralt.
- Textflöde och säkra verktyg byggs före röst, vision och avancerad automation.
- En framtida visuell persona kan animeras efter Arqens röstaktivitet och svar; detta byggs inte i nuvarande fas.

## Regel för varje funktion

Varje funktion får ett separat beslut innan implementation:

- Vad löser den för användaren?
- Är den säker och begriplig?
- Kräver den externa konton eller tjänster?
- Ska den finnas i första versionen?
- Hur testas och återställs den?
