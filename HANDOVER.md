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
- Profiler: Lokal/Ollama, Snabb/OpenRouter, Viktigt/OpenAI, Kreativt/OpenRouter.
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

1. `reflect` i Memory 2.0 och kostnad/nyckelhantering i Tool Gateway återstår,
   se status under respektive spår nedan.

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
- Kvar: `reflect` räknar bara status; den sammanfattar inga lärdomar än.
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

## Medvetna val

- **Fallback är avstängt** i `config/arqen.json` medan modeller utvärderas, så
  mätningar gäller en modell i taget. Det är ett val, inte en glömd inställning.
- `LocalProvider` saknar `supports_tools`. Lokala modeller går via
  nyckelordsheuristiken i `_direct_safe_command` istället.
- Med en nativ provider körs `_direct_safe_command` aldrig, så de svenska
  genvägarna (`läs …`, `ångra`) går genom modellen och dess verktyg.

## Teststatus

131 tester, alla gröna. Kör efter ändringar:

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
