# Arqen Desktop

Arqen Desktop är en lokal PyQt6-baserad AI-assistent med mörkt gränssnitt,
limegröna accenter och en operativ Mission Control-vy för tasks, workflows,
schedules, agents och aktivitet.

Arqen är byggt för att vara lokalt, kontrollerbart och utbyggbart. Molnmodeller
är valfria; lokal körning via Ollama eller LM Studio fungerar som grund.

## Funktioner

- Chattar, sessionshantering och utbytbara AI-providers.
- Ollama/LM Studio, OpenRouter, OpenAI, Gemini, Claude och Arqen Remote.
- Streaming, avbrytning, native tool calls och fallback-provider.
- Verktyg för system, filer, dokument, webben, browser, väder och tal.
- Bekräftelser för skrivande, radering, flytt, undo och bildgenerering.
- Mission Control med task-kö, workflows, schedules, agents och activity.
- Task-timeout, recovery, approvals och resultatlagring.
- Memory 2.0 med retain, recall, reflect, proveniens, status och confidence.
- Tool Gateway med agentpolicies, risknivåer, katalog och lokal auditlogg.
- Lokal API v1 för sessioner, meddelanden, status, Mission Control och tools.
- Svensk Edge TTS, röstläge, stoppknapp och ljudnivåstyrd visualisering.

## Starta

```powershell
python -m pip install -r requirements.txt
python -m arqen.ui
```

Kärnan utan UI startas med `python -m arqen`. Kontrollera lokal provider med
`python -m arqen.doctor`.

Kopiera `config/arqen.example.json` till `config/arqen.json` och välj provider,
modell och API-inställningar. API-nycklar sparas separat i secrets-konfiguration.

## API och Mission Control

Mission Control kör scheduler och task-worker i desktop-processen. Det lokala
API:t använder Bearer-token när token är konfigurerad. Viktiga endpoints under
`/api/v1` är `/sessions`, `/status`, `/health`, `/mission/tasks`,
`/mission/workflows`, `/mission/schedules`, `/mission/agents`, `/mission/activity`,
`/mission/approvals`, `/tools`, `/tools/policies` och `/tools/audit`.

Se [MOBILE_API_PLAN.md](MOBILE_API_PLAN.md) för API-planen.

## Utveckling

```powershell
python -m compileall -q arqen
python -m pytest -q
```

Aktuell överlämning finns i [HANDOVER.md](HANDOVER.md). Design- och
funktionsbeslut finns i [DESIGN.md](DESIGN.md) och [FEATURE_INVENTORY.md](FEATURE_INVENTORY.md).

## Status

Kärna, Mission Control, Memory 2.0 och den första Tool Gateway-versionen
fungerar lokalt. Nästa större steg är djupare policyhantering, UI för
gateway-administration och mobilklientens bekräftelseflöden.
