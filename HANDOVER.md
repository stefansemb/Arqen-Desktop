# Arqen Desktop – handover

## Aktuellt läge

Arqen Desktop är en PyQt6-baserad lokal AI-assistent med mörkgrå/limegrön
Samidatools-inspirerad design. Kärnan är stabil: molnmodeller streamar, anropar
verktyg nativt och går att avbryta mitt i.

Repot ligger på `https://github.com/stefansemb/Arqen-Desktop`, gren `main`.

## Fungerar

- Chattar sparas, öppnas, döps om och tas bort.
- Ollama, OpenRouter, OpenAI, Gemini och Claude stöds.
- API-nycklar sparas separat per provider. Modeller och providerprofiler sparas.
- Profiler: Lokal/Ollama, Snabb/OpenRouter, Viktigt/OpenAI, Kreativt/OpenRouter.
- Streaming, nativa verktygsanrop och avbrytning mot OpenAI-kompatibla moln.
- Verktygsloopen kör upp till 16 steg per tur. Tar budgeten slut ställs en sista
  fråga utan verktyg, så turen alltid slutar i ord och aldrig i rå verktygsutdata.
- Bekräftelse krävs **bara** för verktyg som skriver till disk: `write`, `delete`,
  `move`, `undo` samt `generate_image` (som både skriver fil och kostar pengar).
  Att öppna program, filer eller webbsidor sker utan att fråga.
- En godkänd bekräftelse lämnar tillbaka turen till modellen, som ser resultatet
  och avslutar med egna ord.
- Arbetskatalog väljs i inställningarna, fliken Arbetsyta. Tom betyder programmets
  egen mapp. Arqens eget tillstånd följer installationen och påverkas inte.
- Statistikpanel med tokens och kostnad, flytande som röstpanelen. Kostnaden är
  OpenRouters egen siffra ur `usage.cost`, inte en uppskattning.
- Huvudfönster och båda panelerna öppnas där de stängdes, på rätt skärm.
- System-, fil-, dokument-, webb-, browser- och väderverktyg. Fillistningar visar
  storlek, så "läs den kortaste" inte kräver att varje fil öppnas.
- Bildgenerering via OpenRouter med Nano Banana 2 och Seedream 4.5 som reserv.
  Bilder sparas i `data/generated/`, visas i chatten och följer med sessionen.
- TTS, stoppknapp och röstläge fungerar.

## Viktiga nästa åtgärder

1. **`FallbackProvider` saknar `supports_tools` och `respond_stream`**
   (`arqen/providers/factory.py`). Slås fallback på tappas både streaming och
   nativa verktygsanrop tyst, utan att något syns i gränssnittet. Dess
   standardtimeout på 10 s ligger dessutom långt under verkliga turer — en
   uppmätt MiMo-tur tog 58 s. Måste åtgärdas **innan** fallback slås på igen.
2. Verktygsschemana kostar cirka 2 500 tokens per anrop, eftersom alla 35
   skickas varje gång. Vid långa verktygskedjor dominerar det kostnaden.
   Ett urval per tur vore nästa optimering.

## Medvetna val

- **Fallback är avstängt** i `config/arqen.json` medan modeller utvärderas, så
  mätningar gäller en modell i taget. Det är ett val, inte en glömd inställning.
- `LocalProvider` saknar `supports_tools`. Lokala modeller går via
  nyckelordsheuristiken i `_direct_safe_command` istället.
- Med en nativ provider körs `_direct_safe_command` aldrig, så de svenska
  genvägarna (`läs …`, `ångra`) går genom modellen och dess verktyg.

## Teststatus

63 tester, alla gröna. Kör efter ändringar:

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

Flytande panel i `arqen/ui/window.py` som `VoiceVisualizationWidget`. Visar
`data/generated/Arqen Desktop Voice_2.png`, kan flyttas, dockas och stängas, och
har en ljudnivåstyrd ringpuls. `arqen/tools/speech.py` analyserar Edge TTS-MP3
via ffmpeg och skickar normaliserad amplitud till widgeten.

Bildriktningen är mörk och lugn: grafitgrå bakgrund, en central limegrön
soundwave som enda tydligt animerade element, en bred mörkgrå innering med
diskreta limegröna detaljer, få segmenterade ringar, inga personer eller text.
Bildmodellen överdriver gärna neon, amplitud och antal ringar — håll prompten
strikt. Den senaste bilden blev inte som önskat; arbetet är pausat.

## Mobilstöd

Plan i `MOBILE_API_PLAN.md`. Application service finns i
`arqen/application/service.py` med sessioner, meddelanden, status, namnbyte och
borttagning. Ett lokalt API finns i `arqen/api/server.py` med Bearer-token och
endpoints för health, status, sessioner och meddelanden. Nästa steg är att koppla
serverstart till applikationen och därefter lägga till bekräftelseflöden och
mobilklient.

## Inspirationskälla

Arqen Desktop tar funktioner och idéer som inspiration från:

`C:\AiProjects\SAMIDA AI Desktop Assistent\Brahma-Echo-main`

Använd projektet som referens vid framtida utveckling när det gäller funktioner,
arbetsflöden och UI-idéer. Anpassa alltid lösningarna till Arqens egen arkitektur
och design.
