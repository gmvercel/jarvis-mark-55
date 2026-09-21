# Google integration setup

The `google_workspace` plugin uses Google's official APIs and OAuth. The first Google command opens a browser consent page; the token is stored locally in `config/google_token.json`.

## One-time setup

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create or select a project.
3. Enable these APIs: Gmail, Google Calendar, Google Drive, Google Docs, Google Sheets, Google Slides, and YouTube Data API v3.
4. Configure the OAuth consent screen. For a personal account, choose External and add your Google account as a test user if the app is still in testing.
5. Create OAuth credentials with application type **Desktop app**.
6. Download the JSON file and save it as `config/google_client_secret.json`.
7. Install dependencies with the same Python interpreter used to start JARVIS:

```powershell
python -m pip install -r requirements.txt
```

8. Start JARVIS and say `collega il mio account Google` or use the `authenticate` Google action.

## Examples

- `Apri l'ultima mail che mi è arrivata da GitHub`
- `Riassumi le ultime email del dottore`
- `Trova l'email che parla dei farmaci`
- `Scrivi una mail a mario@example.com allegando C:\\Users\\Renat\\Desktop\\preventivo.pdf`
- `Crea un evento domani alle 10:00 chiamato Riunione`
- `Trova su Drive il preventivo 2026`
- `Leggi il foglio con id ... nell'intervallo Sheet1!A1:D20`
- `Cerca su YouTube video di ...`

The plugin exposes the complete action surface through `plugins/google_workspace.py`. Google APIs may require re-authorization when scopes are expanded; remove `config/google_token.json` and authenticate again if Google reports an invalid grant or missing permission.
