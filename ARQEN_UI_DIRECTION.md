# Arqen UI-riktning

## Mål

Arqen ska kännas som ett lugnt, premium operatörsgränssnitt för agenter och
arbetsflöden. Översikten ska visa systemets läge utan att chatten tar över.

## Layout

```text
┌──────────────┬──────────────────────────────┬─────────────────┐
│ Navigation   │ Godkännanderad (vid behov)   │ Röstpanel       │
│              ├──────────────────────────────┤ (ring, mikrofon,│
│              │ Aktiv vy                     │  röst)          │
│              │ Översikt / Chatt / Uppgifter │─────────────────│
│              │ / Agenter / Minne / ...      │ Statistik       │
└──────────────┴──────────────────────────────┴─────────────────┘
```

Röst- och statistikpanelen är dockade till höger och kan lossas. Godkännanderaden
syns överst i alla vyer bara när något väntar på användaren.

Huvudmeny (i gränssnittet på svenska):

- **Översikt:** Översikt, Chatt, Kontrollrum
- **System:** Agenter, Aktivitet, Minne, Verktyg
- **Drift:** Uppgifter, Arbetsflöden, Scheman, Innehåll
- Inställningar längst ner

## Visuellt språk

- mörk grafit/svart grund
- kort med subtil border och mjuka hörn
- limegrönt endast för status, fokus, aktiva val och primära actions
- röd/gul endast för fel och väntande beslut
- ingen stor dekorativ bakgrund bakom chatten
- låg visuell brusnivå och konsekvent spacing
- svenska i hela gränssnittet

## Chatt

Chatten är en egen vy med en chattlista till vänster (öppna, byt namn, ta bort)
och konversationen till höger. Ursprungsplanen var en utfällbar högerpanel; den
platsen används nu av röst- och statistikpanelen. Agenter kan öppna chatten från
sina kort.

## Implementationsordning (genomförd)

1. Ta bort chat-bakgrunden.
2. Skapa navigationsskal och vyväxling.
3. Flytta Mission Control-panelerna till separata vyer.
4. Lägg till chatt från agentkort.
5. Lägg Inställningar i navigationen.
6. Förfina spacing, typografi och statusfärger.

## Röstpanelen (genomförd 2026-09-25)

Inspirerad av JARVIS-gränssnittet i `jarvis-claude-code`, men anpassad till
Arqen:

- Kompakt ringbaserad panel till höger med `ARQEN` i mitten.
- Den tidigare ljudvågen ligger lindad runt kärnan.
- Lägena vila, lyssnar, tänker och pratar. Vid tänkande snurrar en markerad del
  av ringen; vid tal lyser en grön indikator och en orange talbåge följer rösten.
- Färgerna är konfigurerbara via Arqens tema (`VoicePalette`).
- Mikrofon- och röstknapparna sitter under ringen.
- Statistikpanelen ligger under röstpanelen med samma yta och palett.

Nästa steg för gränssnittet utvärderas mot helheten innan fler visuella element
läggs till eller tas bort.
