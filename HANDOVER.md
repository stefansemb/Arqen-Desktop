# Arqen – handover

## Aktuellt läge

Arqen är en PyQt6-baserad lokal AI-assistent och operatörsgränssnitt för agenter,
med mörkgrå/limegrön design och helt svenskt gränssnitt. Kärnan är stabil:
molnmodeller streamar, anropar verktyg nativt och går att avbryta mitt i.

Repot ligger på `https://github.com/stefansemb/Arqen-Desktop`, gren `main`, och
arbetet sker direkt i `main`. Sedan 2026-09-25 är `main` Mission Control-linjen
(i gränssnittet kallad **Kontrollrum**). Gamla Arqen Desktop är pensionerad och
utvecklas inte vidare; sista versionen finns kvar som taggen
`arqen-desktop-legacy`. Mappen `C:\AiProjects\Arqen Desktop` är en separat,
gammal utcheckning med egen `data/`; en `git pull` där gör den till Kontrollrum.

## Fungerar

- Chattar sparas, öppnas, döps om och tas bort från chattlistan i Chatt-vyn.
- Ollama, OpenRouter, OpenAI, Gemini och Claude stöds.
- API-nycklar sparas separat per provider. Modeller och providerprofiler sparas.
- Profiler: Privat/Ollama, Snabb/OpenRouter (mimo-v2.6-pro), Viktigt/OpenAI
  (gpt-5.6), Kreativt/Gemini (gemini-3.1-flash-lite).
- Streaming, nativa verktygsanrop och avbrytning mot OpenAI-kompatibla moln.
- Verktygsloopen kör upp till 16 steg per tur. Tar budgeten slut ställs en sista
  fråga utan verktyg, så turen alltid slutar i ord och aldrig i rå verktygsutdata.
- Bekräftelse krävs **bara** för verktyg som inte går att ångra: de som skriver
  till disk (`write`, `delete`, `move`, `undo`), `generate_image` (som både
  skriver fil och kostar pengar) och `close_program` (osparat arbete kan gå
  förlorat). `close_program` kontrollerar först att processen finns och är
  entydig, så man tillfrågas aldrig om något som inte körs. Att öppna program,
  filer eller webbsidor sker utan att fråga.
- En godkänd bekräftelse lämnar tillbaka turen till modellen, som ser resultatet
  och avslutar med egna ord.
- Arbetskatalog väljs i inställningarna, fliken Arbetsyta. Tom betyder programmets
  egen mapp. Arqens eget tillstånd följer installationen och påverkas inte.
- Statistikpanel med tokens och kostnad, dockad under röstpanelen. Kostnaden är
  OpenRouters egen siffra ur `usage.cost`, inte en uppskattning.
- Huvudfönstret öppnas där det stängdes, på rätt skärm. Röst- och
  statistikpanelen dockas till höger; lossade öppnas de där de senast flöt.
- System-, fil-, dokument-, webb-, browser- och väderverktyg. Fillistningar visar
  storlek, så "läs den kortaste" inte kräver att varje fil öppnas.
- Bildgenerering via OpenRouter med Nano Banana 2 och Seedream 4.5 som reserv.
  Bilder sparas i `data/generated/`, visas i chatten och följer med sessionen.
- TTS, stoppknapp och röstläge fungerar.

## Viktiga nästa åtgärder

1. Kostnad per anrop och nyckelhantering i Tool Gateway återstår, se status
   under spåret nedan. Memory 2.0 är i stort sett klart.

Reserven (`FallbackProvider`) har `supports_tools`, `respond_stream` och 90 s
timeout. Profilval i Inställningar skrev tidigare in 10 s; nu används
`ProviderConfig().fallback_timeout`, och den sparade konfigurationen är rättad.
Reserven är fortfarande avstängd medan modeller utvärderas.

Verktygsscheman väljs redan per tur (`build_relevant_tool_schemas`, högst 12 plus
de som alltid erbjuds), så alla 36 skickas inte längre varje gång.

## Kontrollrum (Mission Control) – aktuellt läge

I koden heter delen Mission Control; i gränssnittet visas den som Kontrollrum.
Den har separata vyer för Översikt, Uppgifter, Arbetsflöden, Scheman, Agenter och
Aktivitet. Översikt är systemöversikt medan Kontrollrum är den operativa kön.
Tasks, workflows, schedules och agentkort använder en mer kortbaserad och
lättläst layout. Activity visar senaste händelsen per task och
task-resultat kan öppnas i ett större Markdown-renderat resultatfönster.

Scheduler- och task-worker körs i desktop-appen. Schedules kan vara dagliga,
veckovisa, månatliga eller engångskörningar och visas i mänskligt språk.
One-time-schedules stängs av efter körning. Tasks har timeout/recovery,
resultatlagring och kan tas bort med bekräftelse; running tasks kan tas bort,
men tasks som väntar på approval skyddas.

Varje task körs i en egen `ConversationEngine` (`ArqenWindow._new_task_engine`),
byggd från sparade inställningar. Tidigare lånade tasks chattens engine, vilket
permanent smalnade av chattens verktyg och skrev task-prompter i öppen chatt.
`ArqenRuntime` sparar task-samtal i `data/mission-sessions`, skilt från chattarna.

Godkännanden samlas i en gul rad överst i alla vyer: chattens verktygsfrågor och
agenternas approvals, med GODKÄNN/AVVISA direkt. Ett avslag återupptar tasken så
att den blir avbruten i stället för att vänta för evigt.

Chatt-vyn har en chattlista till vänster (högerklick: Öppna, Byt namn, Ta bort;
F2 och Delete). Verktyg-vyn har flikarna Katalog, Agenter och Logg; svenska namn
och kategorier ligger i `arqen/ui/tool_catalog.py`, och ett test kräver att
varje nytt verktyg får en post där.

Scout är research-agent och har tillgång till `search_web` och
`fetch_webpage`. Reddit kan blockera direkthämtning, så framtida webbresearch
bör ha Reddit JSON/RSS-fallback, retry/backoff, källgränser och tydlig fallback
till GitHub, Hacker News och officiella release notes.

## Nya prioriterade spår

### 1. Arqen Memory 2.0

Utveckla minnet mot ett lokalt, kontrollerbart retain/recall/reflect-system:

- `retain`: fakta, beslut och erfarenheter med källa och proveniens.
- `recall`: relevant minne inför nya tasks.
- `reflect`: sammanfatta lärdomar, återkommande risker och mönster.
- status och confidence, exempelvis föreslaget, godkänt och föråldrat.
- Memory-vy för granskning, redigering och borttagning.

Hindsight och agentmemory är inspirationskällor. Börja lokalt och stegvis utan
att införa en tung extern databas direkt.

**Status 2026-09-25:**

- Klart: `retain` med källa, proveniens, status och confidence
  (`arqen/core/memory_store.py`).
- Klart: `recall` används i varje tur. Upp till 12 godkända minnen skickas alla
  med; fler filtreras mot senaste meddelandet (svenska stoppord bort, böjningar
  matchas via prefix) och modellen får veta att det är ett urval. Minnesdelen
  av systemmeddelandet byts ut per tur, så det förblir ett enda.
- Klart: bara godkända minnen presenteras som "User-approved memory".
- Klart: Arqen föreslår minnen med verktyget `propose_memory`
  (`arqen/tools/memory_tools.py`). Det sparar med status "proposed", avvisar
  sådant som ser ut som lösenord eller nycklar, och erbjuds modellen i varje
  tur (`Tool.always_offered`) eftersom ordmatchningen annars aldrig väljer det.
  "Kom ihåg att …" sparar fortfarande direkt som godkänt.
- Klart: Minne-vyn visar förslag överst med Godkänn/Redigera/Avvisa, godkända
  minnen under, och kan markera föråldrad/återställa. Menyn visar antalet
  förslag ("Minne · 2").
- Klart: reflektion (`arqen/core/reflection.py`). Knappen REFLEKTERA i
  Minne-vyn läser de 30 senaste uppgifterna (status, fel, avvisade
  godkännanden), användarens egna meddelanden i de 10 senaste chattarna och
  befintligt minne, och ber modellen om högst 5 bestående lärdomar. De sparas
  som förslag (källa "reflect") och godkänns som andra förslag; en reflektion
  skriver aldrig in minnen själv. Ett modellanrop per körning, i egen tråd och
  med egen provider. Inget underlag betyder inget anrop.
  `MemoryStore.reflect()` är kvar som statusräkning.
- Kvar vid behov: schemalagd reflektion, t.ex. veckovis.
- Kvar vid behov: bättre matchning än ord (t.ex. embeddings) om minnet växer
  sig stort.

### 2. Arqen Tool Gateway

Bygg ett lokalt verktygs- och nyckelproxy-lager:

- registry för alla agentverktyg med risknivå och beskrivning.
- policy per agent och verktyg.
- secrets injiceras server-side och exponeras aldrig i prompt eller tool-resultat.
- auditlogg med user, agent, tool, tid, status och kostnad — aldrig hemligheter.
- senare UI för verktygskatalog, policies, approvals och användningshistorik.

Börja som en intern modul/tjänst i Arqen. Det bör prioriteras högt eftersom det
ger säkerhets-, kostnads- och integrationsgrund för framtida agentfunktioner.

**Status 2026-09-25:**

- Klart: register med risknivå, regler per agent (`ToolPolicy`) och auditlogg i
  `data/tool-audit.jsonl` (`arqen/tools/gateway.py`).
- Klart: UI i Verktyg-vyn med katalog, agentregler och logg.
- Kvar: kostnad per anrop i auditloggen.
- Kvar: nyckelhantering via gatewayn. Nycklarna ligger i `arqen-secrets.json`
  och läses direkt av providers; gatewayn injicerar inga hemligheter än.

### 3. Anslutningar (verktygsarsenal) – fas 1, 2 och 3 byggda

**Status fas 3, Google (klar 2026-09-25):**
`arqen/connectors/google.py` och `arqen/tools/google_tools.py`. Användaren
skapar en egen OAuth-klient av typen Desktop app och fyller i klient-ID och
klienthemlighet i anslutningsdialogen. LOGGA IN MED GOOGLE öppnar webbläsaren;
svaret tas emot av en kortlivad lyssnare på `127.0.0.1` (slumpad port) och
växlas in med PKCE (S256) och `state`-kontroll. Bara refresh-token sparas (i
`arqen-secrets.json`, `Connector.issued`); åtkomsttoken hålls i minnet och
förnyas när den har under en minut kvar. Konto och beviljade behörigheter
sparas i `arqen.json` (inte bland hemligheterna, annars skulle gatewayn rensa
användarens mejladress ur mejllistor). Behörigheter: `gmail.readonly`,
`gmail.compose` (det finns ingen behörighet för bara utkast; Arqen har inget
skicka-verktyg), `calendar.events`, `drive.readonly`. Kryssar användaren ur
något hos Google visas vilka som saknas. KOPPLA FRÅN återkallar hos Google
(i bakgrunden) och raderar nycklarna. Byts klient-ID krävs ny inloggning.
Verktyg: `gmail_search_messages`, `gmail_read_message`, `gmail_create_draft`
(godkännande), `calendar_list_events`, `calendar_create_event` (godkännande,
lokal tid, heldag med exklusivt slutdatum), `drive_search_files`,
`drive_read_file` (Docs/Presentationer som text, Kalkylark som CSV, textfiler;
högst 256 kB). Obs: i testläge går Googles refresh-token ut efter 7 dagar.
Då sätts `needs_reconnect` i `arqen.json` (`Connector.needs_reconnect()`):
kortet visar BEHÖVER ÅTERANSLUTAS och knappen ÅTERANSLUT, menyn visar
"Anslutningar · 1", och verktygen ber om ny inloggning. Vid appstart provas
inloggningen en gång i bakgrunden (`_check_sign_ins`), så statusen syns innan
verktygen behövs. En lyckad förnyelse eller ny inloggning tar bort markeringen.
Provad mot riktigt konto 2026-09-25: läsverktygen fungerar.


Beslutad och fas 1–2 samt MCP-delen av fas 3 byggda 2026-09-25.

**Status fas 3, MCP:** egen klient utan beroenden (`arqen/connectors/mcp_client.py`)
för Streamable HTTP (JSON eller SSE, valfri Bearer-token, bara https eller
localhost) och stdio (lokalt program, JSON-rader; brus på stdout hoppas över).
Varje anrop öppnar en egen kort session. Servrar läggs till med
+ MCP-SERVER i Anslutningar och sparas i `arqen.json` under `mcp_servers`
tillsammans med verktygslistan, så appstart aldrig väntar på en server
(`arqen/connectors/mcp.py`). Verktygen blir `mcp_<server>_<verktyg>` (högst 64
tecken), bär serverns JSON-schema och kräver godkännande om servern inte märkt
dem `readOnlyHint`. `sync_mcp_tools` uppdaterar chattens verktyg direkt efter
ändring; uppgifter får dem via sin egen motor. Att ta bort en server rensar dess
verktyg ur agenternas listor.

**Status fas 2:** GitHub (`arqen/connectors/github.py`, verktyg i
`arqen/tools/github_tools.py`: lista repon, lista/läs issues, lista pull
requests, skapa issue med godkännande) och Discord (webhook) + Telegram (bot)
(`arqen/connectors/messaging.py`, `arqen/tools/messaging_tools.py`; skicka
kräver godkännande). Nycklar sparas i `arqen-secrets.json` under `connectors`
via `arqen/connectors/store.py`; paus/avisering i `arqen.json` under
`connectors`. Verktyg med `connector_id` erbjuds modellen bara när anslutningen
är aktiv (`Tool.available()`), läser sin nyckel först när de körs
(`Tool.credentials()`), och gatewayn rensar sparade nycklar ur all
verktygsutdata. Anslutningsdialogen har TESTA ANSLUTNING (utan bieffekter),
SPARA, KOPPLA FRÅN och paus. Discord/Telegram kan avisera när en uppgift blir
klar eller misslyckas (av som standard; `_notify_task_changes` i fönstret,
aldrig för uppgifter som var klara innan appen startade). `tests/conftest.py`
pekar även om `paths.config_dir`, så tester aldrig rör riktiga nycklar.
`save_provider_config` bevarar nu övriga nycklar i båda konfigurationsfilerna
(skrev tidigare om dem från grunden). Inspirerad av en "Tool armory": ett rutnät
med integrationer som ansluts och delas ut till agenter.

**Status fas 1:** `arqen/connectors/` (Connector, tilldelningslogik och
registret) och vyn *Anslutningar* under System. De inbyggda verktygsgrupperna
byggs ur kategorierna i `tool_catalog.py`; agentväljaren ger GE TILLGÅNG / GE
ALLA / TA BORT per kort och sparar i agentens `allowed_tools` (godkänneregler
för borttagna verktyg rensas). Chatten har fortfarande alla verktyg; att välja
"Arqen (chatten)" i väljaren återstår. En agents tomma verktygslista betyder nu
*inga* verktyg (tidigare *alla*), och AKTIVERA/INAKTIVERA behåller agentens
verktyg (tömde dem tidigare).

Plan för helheten:

- **Anslutning = paket:** en fil per integration i `arqen/connectors/` med namn,
  kategori, beskrivning, inloggningssätt (ingen, token/API-nyckel, OAuth,
  MCP-adress) och de verktyg den ger. Skriv-/publiceringsverktyg kräver
  godkännande som standard.
- **Nycklar via Tool Gateway:** token sparas i `arqen-secrets.json` och fylls i
  av gatewayn först när verktyget körs; aldrig i prompt, verktygsresultat eller
  logg. Detta är samtidigt Tool Gatewayens kvarvarande nyckelhantering.
- **Vy:** egen menypost *Anslutningar* under System. Kort med sökning och status
  (Ansluten, Pausad, Behöver återanslutas, + Anslut); anslut-dialog med
  TESTA ANSLUTNING. Neutrala bokstavsikoner, inga varumärkeslogotyper.
- **Agentval överst:** varje kort får "Ge <agent> tillgång". Ersätter på sikt
  kommafältet i Redigera agent. De inbyggda verktygsgrupperna visas som kort.

Faser:

1. Ramverk, vy och agentval med de inbyggda verktygsgrupperna. **Klar.**
2. Första integrationer: **GitHub** (personlig token) och **Discord/Telegram**
   (webhook/bot för aviseringar, t.ex. när en uppgift är klar). **Klar.**
3. Google via OAuth (Gmail, Kalender, Drive) och en MCP-klient som öppnar
   många verktyg via en anslutning.

## Medvetna val

- **Fallback är avstängt** i `config/arqen.json` medan modeller utvärderas, så
  mätningar gäller en modell i taget. Det är ett val, inte en glömd inställning.
- `LocalProvider` saknar `supports_tools`. Lokala modeller går via
  nyckelordsheuristiken i `_direct_safe_command` istället.
- Med en nativ provider körs `_direct_safe_command` aldrig, så de svenska
  genvägarna (`läs …`, `ångra`) går genom modellen och dess verktyg.

## Teststatus

191 tester, alla gröna. Kör efter ändringar:

```powershell
python -m compileall -q arqen
python -m pytest -q
```

`tests/conftest.py` riktar om arbetsytan, appens datakatalog och ångra-lagret
till testets egen mapp. Utan den skriver testerna riktiga chattar, minnesposter
och ångra-punkter i datakatalogen hos den som använder Arqen — 80 sådana chattar
hade hunnit samlas innan det upptäcktes. Ta inte bort den.

## Säkerhetskopior

`backups/` är gitignorerad och innehåller `sessions-20260922-174930` (137
sessioner, varav `test2` med 24 riktiga meddelanden) samt `mimo-hud-test/` med
det HUD-material som användes för att testa mimo-v2.6-pro.

## Röst

Primär röst är Edge TTS med svensk neural röst `sv-SE-MattiasNeural`. Den
automatiska eSpeak/System.Speech-reserven är borttagen eftersom den gav oönskad
robotklang. Framtida fallback ska vara en explicit, naturlig lokal neural röst
och inte starta tyst.

## Voice-visualisering

`VoiceVisualizationWidget` i `arqen/ui/window.py` är en kompakt, helt kodmålad
ring-HUD (ingen PNG längre) inspirerad av JARVIS. Den dockas överst i högerkolumnen
med Stats-panelen under; båda kan fortfarande lossas och öppnas då där de senast
flöt. `ARQEN` står i mitten och den gamla ljudvågen är lindad runt kärnan.

- **idle**: dämpade bågar, långsam drift, svag vågandning.
- **lyssnar**: cyan ring som andas; vågen följer mikrofonnivån
  (`MicrophoneRecorder.on_level`).
- **tänker**: ljus båge med svans snurrar runt huvudringen, plus en motroterande
  inre båge. Gäller även medan Whisper transkriberar.
- **pratar**: orange talbåge vars längd följer TTS-nivån, små prickar som löper
  längs den och en pulserande grön indikator i ONLINE-chippet. Härleds från
  ljudnivån i `arqen/tools/speech.py`, inte från fönstret.

Färgerna ligger i `VoicePalette` (`arqen/ui/theme.py`) och kan skrivas över i
`config/arqen.json` under `"theme": {"voice": {"speaking": "#ff9f1c", ...}}`.
Ogiltiga hexfärger ignoreras. Mikrofon- och röstknapparna sitter under ringen.

Stats-panelen ligger under Voice-panelen med samma yta och palett: sessionens
kostnad som huvudsiffra, en in/ut-stapel för tokens, tre rutor för senaste
svaret (tid, tokens, kostnad) och totalen som en rad under.

## Språk

Hela gränssnittet är på svenska, i linje med röst och chatt. Alla texter går via
`tr()` i `arqen/ui/strings.py`: koden behåller engelska källsträngar som nycklar
och tabellen ger den svenska texten. Status för tasks och events sparas på
engelska i databasen och översätts först när de visas (`status_label`), så
lagring, tester och logik är språkneutrala. Kod, loggar och tester är på
engelska. Ny text i UI:t ska läggas in i tabellen i stället för att skrivas
direkt i `window.py`.

## Mobilstöd

Plan i `MOBILE_API_PLAN.md`. Application service finns i
`arqen/application/service.py` med sessioner, meddelanden, status, namnbyte och
borttagning. Ett lokalt API finns i `arqen/api/server.py` med Bearer-token och
endpoints för health, status, sessioner och meddelanden. Nästa steg är att koppla
serverstart till applikationen och därefter lägga till bekräftelseflöden och
mobilklient.

## Inspirationskälla

Arqen tar funktioner och idéer som inspiration från:

`C:\AiProjects\SAMIDA AI Desktop Assistent\Brahma-Echo-main`

Använd projektet som referens vid framtida utveckling när det gäller funktioner,
arbetsflöden och UI-idéer. Anpassa alltid lösningarna till Arqens egen arkitektur
och design.
