# Arqen Desktop

En fristående desktop-assistent byggd stegvis med egen kärna och egen identitet.

Den första visuella riktningen är ett mörkt cyberpunkgränssnitt med gröna
accenter. Temastöd kan läggas till senare.

## Första milstolpen

Den första versionen fokuserar på en textbaserad kärna:

- konversationsmeddelanden
- utbytbara AI-providers
- verktygsregister
- explicit säkerhetskontroll före verktygskörning
- lokal AI-provider via Ollama/LM Studio-kompatibelt API

Röst, vision, minne och desktop-automation läggs till först när kärnan är stabil.

Externa molnproviders läggs till som valfria adapters senare. Arqen ska inte kräva
OpenRouter eller Gemini för att kunna köras.

## Starta demo

```powershell
python -m arqen
```

När PyQt6 är installerat kan UI:t startas med:

```powershell
python -m arqen.ui
```

Kontrollera lokal provider med:

```powershell
python -m arqen.doctor
```

Kopiera `config/arqen.example.json` till `config/arqen.json` och ändra modell
eller provider vid behov. Om filen saknas används lokal provider som standard.
