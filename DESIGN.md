# Arqen Desktop – initial designriktning

## Första visuella temat

Arqens första gränssnitt ska använda samidatools-inspirerad färgsättning:
limegrönt som accent mot nästan svart och mörkgrå paneler.

- nästan svart bakgrund
- mörkgrå paneler och tunna grå borders
- limegröna status- och interaktionselement
- varmvit huvudtext och dämpad grå sekundärtext
- tydlig terminal/HUD-känsla
- funktionell läsbarhet före dekoration

Färgväxling och alternativa teman är framtida funktioner. Färger ska därför
samlas centralt när UI:t byggs, så att temastöd kan läggas till utan att hela
gränssnittet behöver skrivas om.

## Providerstrategi

- Ollama är standard för lokalitet, integritet och arbete utan molnberoende.
- OpenRouter med GPT-5.6 Luna är ett snabbt alternativ när den lokala modellen inte räcker eller kvoten tillåter det.
- OpenAI, Claude och Gemini används som separata alternativ för viktigare eller mer krävande uppgifter.
