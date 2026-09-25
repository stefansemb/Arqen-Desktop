# Arqen – mobil/API-plan

## Mål

Göra Arqens kärna åtkomlig för en framtida mobilapp eller mobil webbläsare utan att ersätta den fungerande PyQt6-klienten.

## Föreslagen struktur

```text
Desktop UI / Mobil UI
          |
      API v1
          |
  Arqen application service
          |
ConversationEngine
          |
Providers, sessions, memory och verktyg
```

`ConversationEngine` ska fortsätta vara den gemensamma kärnan. API-lagret ska inte känna till PyQt6 och desktop-UI:t ska inte behöva användas för att skicka ett meddelande.

## Första API-kontraktet

Bas: `/api/v1`

| Metod | Endpoint | Syfte |
|---|---|---|
| GET | `/health` | Kontrollera att Arqen körs |
| GET | `/sessions` | Lista sparade chattar |
| POST | `/sessions` | Skapa en ny chatt |
| GET | `/sessions/{session_id}` | Hämta en chatt med meddelanden |
| POST | `/sessions/{session_id}/messages` | Skicka ett meddelande och få Arqens svar |
| PATCH | `/sessions/{session_id}` | Byta namn på en chatt |
| DELETE | `/sessions/{session_id}` | Ta bort en chatt |
| GET | `/status` | Provider-, röst- och arbetsstatus |
| POST | `/voice/stop` | Stoppa pågående uppläsning |
| GET | `/mission/tasks` | Lista Mission Control-tasks |
| GET | `/mission/activity` | Lista task-aktivitet |
| GET | `/mission/agents` | Lista agents och runtime-status |
| GET | `/mission/approvals` | Lista approvals |
| GET | `/mission/schedules` | Lista schedules |
| GET | `/mission/workflows` | Lista workflows |
| GET | `/tools` | Verktygskatalog och risknivåer |
| GET | `/tools/policies` | Aktiva agentpolicies |
| GET | `/tools/audit` | Senaste auditposter |

## Implementerat läge (2026-09-25)

Alla endpoints i tabellen ovan finns i `arqen/api/server.py`, plus:

| Metod | Endpoint | Syfte |
|---|---|---|
| GET | `/control/status` | Server- och systemstatus för kontrollsidan (disk, minne) |
| GET | `/mission/tasks/{id}` | En task med dess händelser |
| GET | `/mission/workflows/{id}/runs` | Körningar av ett arbetsflöde |
| POST | `/mission/tasks` | Skapa en task |
| POST | `/mission/tasks/{id}/run` | Köra en task |
| POST | `/mission/tasks/{id}/resume` | Återuppta en task efter approval |
| POST | `/mission/agents` | Skapa eller uppdatera en agent |
| POST | `/mission/approvals` | Begära en approval |
| POST | `/mission/approvals/{id}/decision` | Godkänna eller avslå |
| POST | `/mission/schedules` | Skapa ett schema |
| POST | `/mission/workflows` | Skapa ett arbetsflöde |
| POST | `/mission/workflows/{id}/run` | Köra ett arbetsflöde |
| POST | `/mission/runs/{id}/resume` | Återuppta en körning som väntat på approval |

Servern visar också två enkla sidor: `/` (mobil) och `/control`.

Rättat 2026-09-25:

- `POST /voice/stop` stoppar nu uppläsningen; tidigare svarade den utan att
  göra något.
- `POST /mission/approvals/{id}/decision` återupptar tasken efter beslutet, som
  desktop-appen: ett avslag avbryter den, ett godkännande kör klart den. Svaret
  innehåller `task_status` och `result`.
- Att återuppta en körning kräver `POST /mission/runs/{id}/resume`; en GET ger
  405, så en länk eller förhämtning inte kan starta arbete.
- Arbetsflödesrutterna (lista, skapa, köra, återuppta) gav alltid 500 eftersom
  de läste attribut som bara finns på servern. De fungerar nu.

Kvar att göra:

- API:t kräver bara token om en är satt (`--token` eller `ARQEN_API_TOKEN`);
  standard är ingen token.
- Bekräftelseflödet för verktyg via klienten och själva mobilklienten återstår.
- API-servern kör en egen scheduler och task-worker mot samma databas som
  desktop-appen; tasks claimas så att samma task inte körs två gånger.

## Exempel: skicka meddelande

`POST /api/v1/sessions/{session_id}/messages`

```json
{
  "content": "Vad är klockan?"
}
```

Svar vid lyckad behandling:

```json
{
  "data": {
    "session_id": "...",
    "user_message": "Vad är klockan?",
    "assistant_message": "...",
    "speakable": false,
    "status": "ready"
  }
}
```

Bekräftelsekrävande verktyg ska inte köras direkt via mobilklienten. API:t ska returnera ett tydligt väntande tillstånd med verktygsnamn och argument så att klienten kan visa en bekräftelse.

## Säkerhet från början

- API:t ska som standard endast lyssna lokalt (`127.0.0.1`).
- Fjärråtkomst ska kräva en explicit aktiverad funktion.
- Mobilanslutning ska använda en token i `Authorization: Bearer ...`.
- API-nycklar till AI-providers ska aldrig returneras till klienten.
- Felmeddelanden till klienten ska inte innehålla stack traces eller hemligheter.

## Befintlig kod som kan återanvändas

- `arqen/core/engine.py` – konversations- och verktygsflöde.
- `arqen/core/session_store.py` – sessioner och meddelanden.
- `arqen/config/settings.py` – providerkonfiguration.
- `arqen/providers/` – providerabstraktioner.
- `arqen/tools/` – verktygsregister och executor.

## Första implementationen

1. Skapa en UI-oberoende application service runt `ConversationEngine`.
2. Lägg till ett lokalt API med `/health`, `/status` och meddelande-endpointen.
3. Testa API:t utan mobilapp.
4. Lägg därefter till sessioner, bekräftelser och röstkontroller.

Mobilappen/webbklienten kommer senare att vara en klient till detta API, inte en separat kopia av Arqens logik.
