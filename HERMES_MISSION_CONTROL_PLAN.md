# Hermes Mission Control för Arqen

## Mål

Bygga ett säkert operatörslager ovanpå Arqen och senare Hermes. Systemet ska
göra agenternas uppgifter, status, loggar, godkännanden och resultat synliga
från ett ställe utan att ge ett webbgränssnitt direkt shell-access.

## Principer

- Arqens befintliga desktop-assistent förblir fungerande och fristående.
- Agentkörning sker bakom en bridge/service, inte direkt från UI:t.
- Alla uppgifter och resultat har ett strukturerat format och en tydlig status.
- Riskfyllda åtgärder kräver explicit användargodkännande.
- Varje viktig händelse loggas och ska kunna felsökas i efterhand.
- Mission Control byggs först generellt; content-pipeline blir en senare modul.

## Föreslagen arkitektur

```text
Mission Control UI / Arqen UI
              |
              v
       Task & Event API
              |
              v
      Local Mission Bridge
        |             |
        v             v
   Arqen engine     Hermes CLI
        |             |
        +-------> Event store
                       |
                       v
             tasks, agents, logs,
             approvals, schedules,
             outputs and memory
```

Den första versionen kan använda lokal SQLite och filbaserade outputs. En
extern message bus eller Postgres blir aktuell först när flera maskiner,
fjärråtkomst eller högre samtidighet verkligen behövs.

## Första byggfasen: Arqen-native MVP

1. Definiera kontrakt för `Task`, `Agent`, `Event`, `Approval` och `Artifact`.
2. Skapa ett lokalt event/task-store med SQLite.
3. Lägg till en bridge som kan ta emot ett task och köra Arqens befintliga
   `ConversationEngine`.
4. Exponera read-only status och activity feed via det befintliga API-lagret.
5. Lägg till dispatch av en uppgift från UI/API.
6. Lägg till approval-state utan automatisk extern publicering.
7. Verifiera med tester för återstart, fel, dubbla tasks och avbrutna körningar.

## Därefter: Hermes-adapter

Hermes ska kopplas in bakom ett adaptergränssnitt, exempelvis
`AgentRuntime`, så Arqen inte blir hårt beroende av Hermes CLI eller en
specifik version. Adaptern ska kunna:

- starta eller skicka en strukturerad uppgift till Hermes
- läsa tillbaka resultat och exit-status
- rapportera löpande events
- signalera behov av användargodkännande
- avbryta eller återuppta en körning

## Dashboard-moduler

- Overview: aktiva körningar, blockerare och nästa beslut
- Tasks: todo, running, blocked, waiting approval och done
- Agents: roller, health, senaste aktivitet och tillåtna verktyg
- Activity: kronologisk logg med correlation/task-id
- Approvals: risk, payload, beslut och verkställningsresultat
- Schedule: återkommande jobb och senaste körning
- Artifacts: dokument, manus, rapporter och andra outputs
- Memory: korttidsminne, projektwiki och beslut

## Säkerhetsgränser

- Inga API-nycklar i Git.
- Ingen publik port direkt till den lokala agentmiljön.
- Allowlist för verktyg per agent.
- Approval krävs för externa meddelanden, publicering, filradering och andra
  irreversibla eller kostnadskrävande operationer.
- Alla task- och approval-händelser ska vara idempotenta och spårbara.

## Definition of done för första milstolpen

En användare kan skapa en task, se den i statuslistan, låta en lokal agent
köra den, följa activity events, fånga ett fel och återuppta eller avsluta
tasken utan att behöva läsa terminalens rålogg. Alla befintliga tester ska
fortsätta passera.

## Status 2026-09-25

Första milstolpen är nådd. Mission Control heter **Kontrollrum** i gränssnittet.

- Kontrakt, SQLite-lager, bridge, activity, dispatch och approvals finns i
  `arqen/mission/`; alla 141 tester passerar.
- Varje task körs i en egen `ConversationEngine`, så agentens verktygsregler
  aldrig påverkar chatten, och task-samtal sparas separat
  (`data/mission-sessions`).
- Approvals syns i en godkännanderad i alla vyer; ett avslag avbryter tasken.
- Scheduler och task-worker körs i desktop-appen; timeout, recovery, retry och
  borttagning finns.
- Hermes-adaptern finns som `HermesRuntime` i `arqen/mission/runtime.py`. Den är
  opt-in och kopplas in via `mission`-avsnittet i `config/arqen.json`, men bara
  av den lokala API-servern. Desktop-appen kör än så länge bara Arqen-runtime.
