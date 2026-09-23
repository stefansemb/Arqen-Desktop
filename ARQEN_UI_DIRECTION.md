# Arqen UI-riktning

## Mål

Arqen ska kännas som ett lugnt, premium operatörsgränssnitt för agenter och
workflows. Dashboarden ska visa systemets läge utan att chatten tar över.

## Layout

```text
┌──────────────┬──────────────────────────────┬─────────────────┐
│ Navigation   │ Aktiv vy                     │ Agent-chat      │
│              │ Dashboard / Tasks / Agents   │ drawer, vid     │
│              │                              │ behov           │
└──────────────┴──────────────────────────────┴─────────────────┘
```

Huvudmeny:

- Dashboard
- Tasks
- Workflows
- Agents
- Activity
- Memory
- Content
- Settings

## Visuellt språk

- mörk grafit/svart grund
- kort med subtil border och mjuka hörn
- limegrönt endast för status, fokus, aktiva val och primära actions
- röd/gul endast för fel och väntande beslut
- ingen stor dekorativ bakgrund bakom chatten
- låg visuell brusnivå och konsekvent spacing

## Chat

Chatten ska öppnas som en separat högerpanel när användaren väljer Arqen eller
en specialistagent. Den ska inte ligga permanent över dashboardens huvudyta.

## Implementationsordning

1. Ta bort chat-bakgrunden.
2. Skapa navigationsskal och vyväxling.
3. Flytta Mission Control-panelerna till separata vyer.
4. Lägg till agent-chat som drawer.
5. Lägg Settings i navigationen.
6. Förfina spacing, typography och statusfärger.
