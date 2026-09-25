# Arqen – funktionsinventering

Detta dokument är ett beslutsunderlag för Arqen. Brahma Echo används som
funktionell referens; kod, branding och licensbundna resurser kopieras inte.
Kolumnen *Var* pekar på Arqens egen kod där funktionen finns, annars på
referensen i Brahma Echo.

Status uppdaterad 2026-09-25.

## Beslutsstatus

- `OPEN` – inte bedömd ännu
- `KEEP` – ska byggas i Arqen
- `DONE` – byggd i Arqen och i bruk
- `REVIEW` – kräver teknisk eller produktmässig utvärdering
- `DROP` – ska inte ingå
- `LATER` – värdefull, men inte i första versionen

## Prioriterad inventering

| Område | Funktion | Var | Prioritet | Status |
|---|---|---|---:|---|
| Kärna | Konversation och sessionshantering | `arqen/core/engine.py`, `arqen/core/session_store.py` | Hög | DONE |
| AI | Utbytbar modellklient och reserv | `arqen/providers/` | Hög | DONE |
| Röst | Taligenkänning, TTS och avbrott | `arqen/tools/speech.py`, `arqen/tools/microphone.py` | Hög | DONE |
| Aktivering | Wake word och global hotkey | Brahma Echo: `core/hotkey.py`, `core/echo.py` | Hög | OPEN |
| Verktyg | Verktygsregister och körning | `arqen/tools/registry.py`, `arqen/tools/executor.py` | Hög | DONE |
| Säkerhet | Bekräftelser före åtgärder som inte går att ångra | `arqen/tools/executor.py`, godkännanderaden i `arqen/ui/window.py` | Hög | DONE |
| Säkerhet | Tool Gateway: risknivåer, regler per agent, logg | `arqen/tools/gateway.py` | Hög | KEEP (kostnad och nyckelhantering återstår) |
| Minne | Långtidsminne med förslag, recall och reflektion | `arqen/core/memory_store.py`, `arqen/core/reflection.py` | Hög | DONE |
| Desktop | Appar, filer, fönster och systemkontroll | `arqen/tools/` | Hög | DONE |
| Skärm | Skärmläsning, vision och kontext | Brahma Echo: `actions/screen_processor.py`, `actions/attention_monitor.py` | Hög | OPEN |
| Webbläsare | Webbläsarstyrning | `arqen/tools/browser_tools.py` (Playwright) | Medel | DONE |
| Dokument | PDF, Word och Excel | `arqen/tools/*_documents.py` | Medel | DONE |
| Produktivitet | Kalender, möten, påminnelser och briefing | Brahma Echo: `actions/calendar_scheduler.py`, `actions/meeting_assistant.py` | Medel | OPEN |
| Integrationer | Google Workspace | Brahma Echo: `actions/google_workspace_mcp.py` | Medel | OPEN |
| Kommunikation | Discord och meddelandebryggor | Brahma Echo: `discord_bot.py`, `actions/send_message.py` | Medel | OPEN |
| Fjärrstyrning | Mobil/fjärranslutning | `arqen/api/` (lokalt API finns, mobilklient saknas) | Låg | KEEP |
| Smart hem | Enheter och providers | Brahma Echo: `smart_home/` | Låg | OPEN |
| Agent | Uppgifter, kö, arbetsflöden och scheman | `arqen/mission/` | Medel | DONE |
| Självförbättring | Lärda regler och preferenser | `propose_memory` och reflektion i minnet | Medel | DONE |
| Självreparation | Felanalys, patchning och rollback | Brahma Echo: `actions/auto_heal_engine.py`, `core/boot_sentry.py`, `core/undo.py` | Låg | REVIEW |
| UI | Gränssnitt, Kontrollrum och status | `arqen/ui/window.py` | Hög | DONE |
| Proaktivitet | Bakgrundsvakter och notifieringar | Brahma Echo: `actions/background_monitor.py`, `actions/proactive.py` | Medel | OPEN |
| Pluginer | Utbyggbar pluginarkitektur | Brahma Echo: `plugin_manager.py`, `plugins/` | Hög | OPEN |
| Visuell persona | Animerad form som reagerar på röst och svar | Röstpanelens ring i `arqen/ui/window.py` | Låg | DONE |

## Fattade designbeslut

- Arqen ska inte vara beroende av OpenRouter, Gemini eller någon annan enskild
  molnleverantör.
- Lokal AI-provider är grunden; molnproviders är valfria adapters.
- Gränssnittet är mörkt med limegröna accenter och helt på svenska.
- Temaväxling får stöd senare, men färger hålls centralt.
- Textflöde och säkra verktyg byggs före vision och avancerad automation.
- Allt som inte går att ångra kräver användarens godkännande, och minnen blir
  aldrig betrodda utan att användaren godkänt dem.

## Regel för varje funktion

Varje funktion får ett separat beslut innan implementation:

- Vad löser den för användaren?
- Är den säker och begriplig?
- Kräver den externa konton eller tjänster?
- Ska den finnas i första versionen?
- Hur testas och återställs den?
