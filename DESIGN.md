# Arqen – designriktning

## Visuellt tema

Arqens gränssnitt använder samidatools-inspirerad färgsättning: limegrönt som
accent mot nästan svart och mörkgrå paneler.

- nästan svart bakgrund
- mörkgrå paneler och tunna grå borders
- limegröna status- och interaktionselement
- varmvit huvudtext och dämpad grå sekundärtext
- gult för det som väntar på användaren, rött för fel
- tydlig terminal/HUD-känsla, till exempel röstpanelens ring
- funktionell läsbarhet före dekoration

Färgerna samlas centralt: grundtemat i `CyberpunkGreenTheme` och röstpanelens
färger i `VoicePalette` (`arqen/ui/theme.py`). Röstpanelens färger kan skrivas
över i `config/arqen.json` under `"theme": {"voice": {...}}`. Fler teman och
temaväxling är framtida funktioner.

## Språk

Gränssnitt, röst och chatt är på svenska. Texterna samlas i
`arqen/ui/strings.py` (`tr()`), så språket kan bytas på ett ställe. Kod,
loggar och tester är på engelska.

## Providerstrategi

- Lokal provider (Ollama eller LM Studio) är grunden för lokalitet, integritet
  och arbete utan molnberoende; Arqen ska aldrig vara beroende av en enskild
  molnleverantör.
- Färdiga profiler väljer provider och modell:
  - **Privat** – Ollama lokalt, utan reserv i molnet.
  - **Snabb** – OpenRouter med `xiaomi/mimo-v2.6-pro` för vardagen.
  - **Viktigt** – OpenAI `gpt-5.6` för viktigare uppgifter.
  - **Kreativt** – Gemini `gemini-3.1-flash-lite` för idéer och skrivande.
- Claude och Arqen Remote finns som separata alternativ.
- En reservprovider kan slås på, men är avstängd medan modeller utvärderas så
  att mätningar gäller en modell i taget.
