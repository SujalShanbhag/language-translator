<<<<<<< HEAD
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
=======
# Language Translator — Vercel Ready

This version is prepared for Vercel as one project. The frontend and Python API use same-origin relative paths, so there is no hardcoded deployment domain, public URL, or production port.

## Vercel deployment

1. Upload this project to GitHub.
2. Import the repository into Vercel.
3. Keep the project root at the folder containing `api/`, `public/`, `requirements.txt`, and `vercel.json`.
4. No environment variables are required by this project.
5. Deploy.

Vercel detects `api/index.py` as the Python serverless function and serves the frontend from `public/`.

## Local development

Install dependencies:

```bash
pip install -r requirements.txt
```

For a Vercel-like local environment, install the Vercel CLI and run:

```bash
vercel dev
```

The application itself never hardcodes the Vercel domain or production port. Browser API requests are relative, such as `/api/languages` and `/api/translate`.

## Important production behavior

Vercel functions can be cold-started after periods of inactivity. This project keeps no required session state and rebuilds its in-memory language/voice caches automatically, so inactivity does not require a manual server restart.

Translation and server speech still depend on the availability of their external online providers. No application can guarantee an external provider will never rate-limit, reject, or temporarily fail. When that happens, the application reports the failure rather than displaying an unverified translation or using an unrelated voice.

The server voice uses dynamically retrieved Edge TTS voices, with gTTS as a secondary language-validated transport. A suitable voice is selected from the requested target language; the project does not contain a hardcoded voice-language table.
>>>>>>> f8f386ef310a2b6588aef351e48ddb76816949c2
