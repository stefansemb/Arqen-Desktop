# Arqen

Arqen är en lokal AI-assistent för Windows, byggd med PyQt6, med ett
**Kontrollrum** för agenter, uppgifter och arbetsflöden. Gränssnittet och rösten
är på svenska, designen mörk med limegröna accenter.

Arqen är byggt för att vara lokalt, kontrollerbart och utbyggbart. Molnmodeller
är valfria; lokal körning via Ollama eller LM Studio fungerar som grund. Allt som
inte går att ångra kräver ditt godkännande.

> Repot heter Arqen-Desktop av historiska skäl. Den gamla desktopversionen
> utvecklas inte längre; dess sista version finns kvar som taggen
> `arqen-desktop-legacy`.

## Funktioner

**Chatt och röst**

- Chattlista med öppna, byt namn och ta bort; streaming och avbrytning.
- Svensk röst via Edge TTS (`sv-SE-MattiasNeural`) och taligenkänning via
  faster-whisper.
- Röstpanel med en animerad ring som visar om Arqen vilar, lyssnar, tänker eller
  pratar. Färgerna kan ändras i `config/arqen.json`.
- Statistikpanel med tokens och kostnad för chatten, senaste svaret och totalt.

**Kontrollrum**

- Uppgifter, arbetsflöden med flera agenter, scheman och aktivitetslogg.
- Agenter med egna verktygsregler. Varje uppgift körs i en egen, fristående
  Arqen, så en agents begränsningar aldrig påverkar chatten.
- Timeout, återhämtning, försök igen och sparade resultat för uppgifter.
- En godkännanderad överst i alla vyer samlar allt som väntar på dig.

**Minne**

- Långtidsminne med källa, status och säkerhet.
- Arqen **föreslår** minnen när du berättar något bestående; du godkänner eller
  avvisar dem under Minne. Bara godkända minnen används.
- **Reflektera**: Arqen läser senaste uppgifter och chattar och föreslår
  bestående lärdomar, också de som förslag.
- Relevanta minnen väljs ut per meddelande när minnet växer.
- "Kom ihåg att …" sparar direkt.

**Verktyg och säkerhet**

- Verktyg för system, fönster och program, filer i arbetsytan, dokument (PDF,
  Word, Excel), webben, en egen webbläsare, väder, röst och bildgenerering.
- Godkännande krävs för att skriva, ta bort, flytta eller ångra filer, skapa
  bilder (kostar pengar) och stänga program.
- Tool Gateway med risknivåer, regler per agent och en lokal logg över alla
  verktygsanrop, synliga under Verktyg.
- Minnen som ser ut som lösenord eller nycklar sparas aldrig.

**Modeller**

- Ollama/LM Studio, OpenRouter, OpenAI, Gemini, Claude och Arqen Remote.
- Färdiga profiler: Privat (Ollama), Snabb (OpenRouter), Viktigt (OpenAI) och
  Kreativt (Gemini).
- Valfri reservprovider om den första inte svarar (avstängd som standard).

## Kom igång

Arqen är byggt för Windows och kräver Python 3.10 eller senare (utvecklas på
3.12).

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
python -m arqen.ui
```

- **ffmpeg** behöver finnas i `PATH` för rösten (ljudnivå och uppspelning).
- Kopiera `config/arqen.example.json` till `config/arqen.json`, eller välj en
  profil under Inställningar i appen.
- API-nycklar sparas separat i `config/arqen-secrets.json`, som aldrig checkas
  in. Ange dem under Inställningar.
- Arbetsytan, mappen där Arqen läser och skriver filer, väljs under
  Inställningar → Arbetsyta.

Kärnan utan gränssnitt startas med `python -m arqen`. Kontrollera en lokal
provider med `python -m arqen.doctor`.

## Lokalt API

API:t är en separat process och startas inte av appen:

```powershell
python -m arqen.api --port 8765 --token <din-token>
```

Det lyssnar bara på `127.0.0.1`. Token kan också sättas med miljövariabeln
`ARQEN_API_TOKEN`; utan token krävs ingen inloggning, så sätt alltid en om något
annat än du själv kan nå datorn. Alla anrop utom `/api/v1/health` kräver då
`Authorization: Bearer <token>`.

Endpoints under `/api/v1` finns för sessioner och meddelanden, status,
uppgifter, agenter, godkännanden, scheman, arbetsflöden och verktyg. Se
[MOBILE_API_PLAN.md](MOBILE_API_PLAN.md) för hela listan och vad som ännu inte
fungerar fullt ut.

## Utveckling

```powershell
python -m compileall -q arqen
python -m pytest -q
```

- `tests/conftest.py` pekar om arbetsytan och datakatalogen till en tillfällig
  mapp, så att tester aldrig rör dina chattar, minnen eller uppgifter. Ta inte
  bort den.
- All text i gränssnittet går via `tr()` i `arqen/ui/strings.py`; ny text läggs
  in där, inte direkt i `window.py`.
- Nya verktyg behöver ett svenskt namn och en kategori i
  `arqen/ui/tool_catalog.py`; ett test kontrollerar det.

## Dokument

- [HANDOVER.md](HANDOVER.md) – aktuellt läge, beslut och nästa steg.
- [ARQEN_UI_DIRECTION.md](ARQEN_UI_DIRECTION.md) – riktning för gränssnittet.
- [HERMES_MISSION_CONTROL_PLAN.md](HERMES_MISSION_CONTROL_PLAN.md) – plan för
  Kontrollrummet och Hermes.
- [MOBILE_API_PLAN.md](MOBILE_API_PLAN.md) – API och framtida mobilklient.
- [DESIGN.md](DESIGN.md) och [FEATURE_INVENTORY.md](FEATURE_INVENTORY.md) –
  design- och funktionsbeslut.

## Status

Chatt, röst, Kontrollrum, Memory 2.0 och Tool Gateway fungerar lokalt. Kvar i
närtid: kostnad per verktygsanrop och nyckelhantering via Tool Gateway,
bekräftelseflöden i API:t och en mobilklient. Se HANDOVER för detaljer.
