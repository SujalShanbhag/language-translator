# Language Translator — Permanent Server Voice

## Start

```bash
python server.py
```

The application uses only HTML, CSS, JavaScript and Python. The existing dashboard UI is preserved.

## Server voice

Server speech is selected dynamically from the current Edge TTS voice catalog. If Edge TTS is temporarily unavailable, the server checks the current gTTS language catalog and can generate speech only for the requested language. It never selects an unrelated language as a fallback.

## Deployment

Install dependencies with `pip install -r requirements.txt` and start with `python server.py`. The server listens on `0.0.0.0` and uses the platform `PORT` environment variable when supplied.

## Important

Server speech requires the deployed server to have outbound HTTPS access to its speech provider. A hosting platform that blocks outbound WebSocket/HTTPS traffic cannot generate cloud TTS audio regardless of the frontend code.
