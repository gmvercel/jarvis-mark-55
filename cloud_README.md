# JARVIS Cloud on Vercel

This is the first cloud backend for the remote dashboard. It is stateless: commands are sent to Gemini and no conversation or API key is stored by the function.

## Deploy

1. Create a Vercel project pointing at this repository.
2. Set these Environment Variables in Vercel:

   - `GEMINI_API_KEY`: a Gemini API key for the cloud project.
   - `JARVIS_CLOUD_TOKEN`: a long random token used by the dashboard client.
   - `CORS_ORIGIN`: the dashboard origin, or `*` while testing.
   - `GEMINI_MODEL`: optional, defaults to `gemini-2.5-flash`.
   - `JARVIS_SYSTEM_PROMPT`: optional cloud-specific assistant instructions.

3. Deploy and verify `https://YOUR-DOMAIN.vercel.app/api/health`.
4. In the dashboard Cloud mode, enter:

   - Endpoint: `https://YOUR-DOMAIN.vercel.app/api/v1/command`
   - API token: the value of `JARVIS_CLOUD_TOKEN`

## API

`POST /api/v1/command`

```json
{"message":"Cosa ho in agenda oggi?","source":"jarvis-remote","mode":"cloud"}
```

Response:

```json
{"ok":true,"reply":"..."}
```

The endpoint requires `Authorization: Bearer <JARVIS_CLOUD_TOKEN>`. The Cloud mode cannot control the local PC yet; that requires a separate outbound agent/relay.
