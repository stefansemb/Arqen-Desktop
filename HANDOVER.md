# Arqen Desktop – handover

## Aktuellt läge

Arqen Desktop är en PyQt6-baserad lokal AI-assistent med mörkgrå/limegrön Samidatools-inspirerad design.

## Fungerar

- Chattar sparas, öppnas, döps om och tas bort.
- Ollama, OpenRouter, OpenAI, Gemini och Claude stöds.
- API-nycklar sparas separat per provider.
- Modeller och providerprofiler sparas.
- Profiler finns: Privat/Ollama, Snabb/OpenRouter, Viktigt/OpenAI och Kreativt arbete/OpenRouter.
- Fallback med reservprovider, timeout, statusfärg och felorsak.
- Providerstatistik med svarstid, genomsnitt, fel och fallbackväxlingar.
- System-, fil-, dokument-, webb-, browser- och väderverktyg.
- Bekräftelse krävs för ändringar och bildgenerering.
- Bekräftade långsamma verktyg körs i bakgrundstråd så UI:t inte fryser.
- Bildgenerering via OpenRouter med Nano Banana 2 och Seedream 4.5 som reservmodell.
- Genererade bilder sparas med unika filnamn i `data/generated/` och visas i chatten.
- Bildresultat sparas i sessionen och visas igen när chatten laddas.
- TTS, stoppknapp och röstläge fungerar.

## Senaste bildarbete

Målet är en mörk, lugn AI-röstvisualisering:

- Grafitgrå/mörk bakgrund.
- En central limegrön soundwave som är det enda tydligt animeringsbara elementet.
- En bred mörkgrå innering med diskreta limegröna tekniska detaljer.
- Få, tydliga och segmenterade ringar.
- Diskreta trådar/partiklar främst i bakgrunden.
- Ingen person, humanoid figur, text eller logotyp.

Den senaste bilden blev inte önskad, så fortsätt iterera från idén med den mörka grafitgrå inneringen och den tydliga centrala soundwaven.

## Viktig nästa åtgärd

Fortsätt förbättra bildprompten eller animationen. Bildmodellen tenderar att överdriva neon, soundwave-amplitud och extra ringar. Håll prompten strikt: soundwave i centrum, lugna ringar, låg kontrast och mycket mörk bakgrund.

## Teststatus

Senaste relevanta tester är godkända. Kör efter ändringar:

```powershell
python -m compileall -q arqen
python -m pytest -q
```

## Inspirationskälla

Arqen Desktop tar vissa funktioner och idéer som inspiration från projektet:

`C:\AiProjects\SAMIDA AI Desktop Assistent\Brahma-Echo-main`

Använd projektet som referens vid framtida utveckling när det gäller funktioner, arbetsflöden och UI-idéer. Anpassa alltid lösningarna till Arqens egen arkitektur och design.

## GitHub – kommande åtgärd

Användaren har GitHub-projekten `stefansemb/samida.dev` och `stefansemb/PirateSurvival`. Lägg senare till Arqen Desktop som ett eget repository under samma GitHub-konto. Kontrollera först git-status, känsliga filer och README innan repository skapas eller publiceras.

## Mobilstöd

En första mobil/API-plan finns i `MOBILE_API_PLAN.md`. Nästa arkitektursteg är att exponera en UI-oberoende application service runt `ConversationEngine` och därefter bygga ett lokalt, autentiserat API för framtida mobilklient.

Application service finns i `arqen/application/service.py` med sessioner, meddelanden, status, namnbyte och borttagning. Ett första lokalt API finns i `arqen/api/server.py` med Bearer-tokenstöd och endpoints för health, status, sessioner och meddelanden. Nästa steg är att koppla serverstart till applikationen och därefter lägga till bekräftelseflöden och mobilklient.

## Röst

Nuvarande primära röst är Edge TTS med svensk neural röst `sv-SE-MattiasNeural`. Den automatiska eSpeak/System.Speech-reserven är borttagen eftersom den gav oönskad gammal robotklang. Framtida fallback ska vara en explicit, naturlig lokal neural röst och inte starta tyst.

## Voice-visualisering

En flytande panel finns i `arqen/ui/window.py` som `VoiceVisualizationWidget`. Den visar `data/generated/Arqen Desktop Voice_2.png`, kan flyttas/dockas/stängas och har nu en första ljudnivåstyrd ringpuls. `arqen/tools/speech.py` analyserar Edge TTS-MP3 via ffmpeg och skickar normaliserad amplitud till widgeten.
