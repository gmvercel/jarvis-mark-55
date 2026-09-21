# Deploy del backend Cloud

Il backend e pronto per Vercel. Le funzioni sono:

- `GET /api/health`: stato del servizio e configurazione variabili.
- `POST /api/v1/command`: comando autenticato inviato a Gemini.

## Variabili obbligatorie su Vercel

- `GEMINI_API_KEY`: chiave generata in Google AI Studio.
- `JARVIS_CLOUD_TOKEN`: token casuale generato localmente.
- `CORS_ORIGIN`: `*` per il primo test oppure l'origine esatta del dashboard.

Variabili opzionali:

- `GEMINI_MODEL`: predefinito `gemini-2.5-flash`.
- `JARVIS_SYSTEM_PROMPT`: istruzioni personalizzate per Jarvis Cloud.

## Verifica dopo il deploy

Apri:

```text
https://TUO-PROGETTO.vercel.app/api/health
```

Il risultato atteso contiene:

```json
{"ok":true,"service":"jarvis-cloud","gemini_configured":true,"auth_configured":true}
```

Nel dashboard mobile usa:

```text
Endpoint: https://TUO-PROGETTO.vercel.app/api/v1/command
API token: il valore di JARVIS_CLOUD_TOKEN
```

Le chiavi non devono essere inserite nei file del repository. Il backend Cloud e stateless e non controlla ancora il computer locale.
