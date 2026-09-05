import asyncio
import json
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

import edge_tts
from gtts import gTTS
from gtts.lang import tts_langs

BASE = Path(__file__).resolve().parents[1]
PUBLIC = BASE / "public"

app = FastAPI(title="Language Translator", docs_url=None, redoc_url=None)

LANGUAGE_CACHE = {"items": None, "expires": 0.0}
VOICE_CACHE = {"items": None, "expires": 0.0}
CACHE_LOCK = Lock()

GOOGLE_LANGUAGE_URLS = [
    "https://translate.googleapis.com/translate_a/l?client=webapp&format=html",
    "https://translate.google.com/translate_a/l?client=webapp&format=html",
]


def proxy_url():
    return (os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or
            os.getenv("HTTP_PROXY") or os.getenv("http_proxy") or None)


def fetch_json(url, timeout=20):
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_google_languages(data):
    candidates = []
    if isinstance(data, dict):
        for key in ("languages", "sl", "tl", "data"):
            value = data.get(key)
            if isinstance(value, (dict, list)):
                candidates.append(value)
        if not candidates:
            candidates.append(data)
    elif isinstance(data, list):
        candidates.append(data)

    found = {}
    for candidate in candidates:
        if isinstance(candidate, dict):
            for code, name in candidate.items():
                if isinstance(code, str) and isinstance(name, str) and code.strip():
                    found[code.strip()] = name.strip() or code.strip()
        elif isinstance(candidate, list):
            for item in candidate:
                if isinstance(item, dict):
                    code = item.get("code") or item.get("languageCode") or item.get("language")
                    name = item.get("name") or item.get("displayName") or code
                    if isinstance(code, str) and isinstance(name, str):
                        found[code.strip()] = name.strip() or code.strip()
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    code, name = item[0], item[1]
                    if isinstance(code, str) and isinstance(name, str):
                        found[code.strip()] = name.strip() or code.strip()

    return [
        {"id": code, "name": name, "translation_code": code}
        for code, name in sorted(found.items(), key=lambda x: x[1].casefold())
        if re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]+)?", code)
    ]


def load_languages(force=False):
    now = time.time()
    with CACHE_LOCK:
        if not force and LANGUAGE_CACHE["items"] and LANGUAGE_CACHE["expires"] > now:
            return LANGUAGE_CACHE["items"]

    last_error = None
    for url in GOOGLE_LANGUAGE_URLS:
        try:
            items = parse_google_languages(fetch_json(url))
            if items:
                with CACHE_LOCK:
                    LANGUAGE_CACHE["items"] = items
                    LANGUAGE_CACHE["expires"] = time.time() + 3600
                return items
        except Exception as exc:
            last_error = exc

    with CACHE_LOCK:
        if LANGUAGE_CACHE["items"]:
            return LANGUAGE_CACHE["items"]
    raise RuntimeError(f"Unable to fetch the live translation language catalog: {last_error}")


def translate_google(text, source, target):
    if source == target:
        return text
    params = urllib.parse.urlencode({
        "client": "gtx", "sl": source, "tl": target, "dt": "t",
        "ie": "UTF-8", "oe": "UTF-8", "q": text,
    })
    url = "https://translate.googleapis.com/translate_a/single?" + params
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, list) or not data or not isinstance(data[0], list):
        raise RuntimeError("Translation provider returned an invalid response.")
    result = "".join(
        row[0] for row in data[0]
        if isinstance(row, list) and row and isinstance(row[0], str)
    ).strip()
    if not result:
        raise RuntimeError("Translation provider returned an empty result.")
    return result


def split_text(text, limit=1200):
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        sentences = re.split(r"(?<=[.!?。！？])\s+", paragraph)
        current = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            candidate = (current + " " + sentence).strip()
            if len(candidate) <= limit:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = sentence
        if current:
            chunks.append(current)
    return chunks


def normalize_locale(code):
    return (code or "").strip().replace("_", "-").lower()


def choose_voice(voices, language_code):
    wanted = normalize_locale(language_code)
    if not wanted:
        return None
    exact = [v for v in voices if normalize_locale(v.get("Locale")) == wanted]
    if exact:
        return exact[0]
    base = wanted.split("-", 1)[0]
    matches = [v for v in voices if normalize_locale(v.get("Locale")).split("-", 1)[0] == base]
    return matches[0] if matches else None


def load_voices(force=False):
    now = time.time()
    with CACHE_LOCK:
        if not force and VOICE_CACHE["items"] and VOICE_CACHE["expires"] > now:
            return VOICE_CACHE["items"]

    voices = asyncio.run(edge_tts.list_voices(proxy=proxy_url()))
    items = [
        {
            "name": v.get("ShortName"),
            "locale": v.get("Locale"),
            "language": v.get("LocaleName"),
            "gender": v.get("Gender"),
            "engine": "edge-tts",
        }
        for v in voices
        if v.get("ShortName") and v.get("Locale")
    ]
    items.sort(key=lambda x: (x["locale"], x["name"]))
    with CACHE_LOCK:
        VOICE_CACHE["items"] = items
        VOICE_CACHE["expires"] = time.time() + 3600
    return items


def gtts_language_for(code):
    wanted = normalize_locale(code)
    supported = tts_langs()
    if wanted in supported:
        return wanted
    base = wanted.split("-", 1)[0]
    if base in supported:
        return base
    for candidate in supported:
        if normalize_locale(candidate).split("-", 1)[0] == base:
            return candidate
    return None


def supported_language_name(language):
    try:
        return tts_langs().get(language, language)
    except Exception:
        return language


def synthesize_edge(text, voice_name):
    fd, path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    try:
        async def make_audio():
            communicator = edge_tts.Communicate(
                text=text,
                voice=voice_name,
                rate="+0%",
                volume="+0%",
                pitch="+0Hz",
                proxy=proxy_url(),
                connect_timeout=15,
                receive_timeout=45,
            )
            await communicator.save(path)
        asyncio.run(make_audio())
        audio = Path(path).read_bytes()
        if not audio:
            raise RuntimeError("Edge TTS returned an empty audio file.")
        return audio
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def synthesize_gtts(text, language_code):
    language = gtts_language_for(language_code)
    if not language:
        raise RuntimeError("The selected language has no secondary server voice available.")
    if len(text) > 1800:
        raise RuntimeError("The secondary server voice supports shorter text; use the primary server voice for long text.")
    fd, path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    try:
        gTTS(text=text, lang=language, slow=False).save(path)
        audio = Path(path).read_bytes()
        if not audio:
            raise RuntimeError("Secondary TTS returned an empty audio file.")
        return audio, {
            "name": f"gtts:{language}",
            "locale": language,
            "language": supported_language_name(language),
            "gender": "",
            "engine": "gTTS",
        }
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def synthesize(text, language_code):
    voices = load_voices()
    voice = choose_voice(voices, language_code)
    errors = []

    if voice:
        for attempt in range(2):
            try:
                return synthesize_edge(text, voice["name"]), voice
            except Exception as exc:
                errors.append(f"Primary server voice attempt {attempt + 1}: {exc}")

    try:
        return synthesize_gtts(text, language_code)
    except Exception as exc:
        errors.append(f"Secondary server voice: {exc}")

    if not voice:
        raise RuntimeError("No working server voice was found for the selected language. " + " | ".join(errors))
    raise RuntimeError("Server voice generation failed. " + " | ".join(errors))


class TranslateRequest(BaseModel):
    text: str
    source: str
    target: str


class SpeakRequest(BaseModel):
    text: str
    language: str
    voice: str | None = None


@app.get("/api/health")
def health():
    languages = load_languages()
    return {
        "status": "online",
        "translation_provider": "Google Translate Web",
        "language_count": len(languages),
        "server_voice": "available on demand",
    }


@app.get("/api/languages")
def languages():
    items = load_languages()
    return {"count": len(items), "languages": items}


@app.get("/api/refresh-languages")
def refresh_languages():
    items = load_languages(force=True)
    return {"count": len(items), "languages": items}


@app.get("/api/voices")
def voices():
    items = load_voices()
    return {"count": len(items), "voices": items}


@app.get("/api/refresh-voices")
def refresh_voices():
    items = load_voices(force=True)
    return {"count": len(items), "voices": items}


@app.get("/api/manual")
def manual():
    return FileResponse(PUBLIC / "manual.txt", media_type="text/plain; charset=utf-8")


@app.post("/api/translate")
def translate(payload: TranslateRequest):
    text = payload.text.strip()
    source = payload.source.strip()
    target = payload.target.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Enter text to translate.")
    if not source or not target:
        raise HTTPException(status_code=400, detail="Select source and target languages.")
    codes = {x["translation_code"] for x in load_languages()}
    if source not in codes or target not in codes:
        raise HTTPException(status_code=400, detail="The selected language is not currently available from the live translation catalog.")
    chunks = split_text(text)
    translated = [translate_google(chunk, source, target) for chunk in chunks]
    result = "\n\n".join(x for x in translated if x).strip()
    if not result:
        raise HTTPException(status_code=502, detail="No verified translation was returned.")
    return {"translation": result, "provider": "Google Translate Web", "chunks": len(chunks)}


@app.post("/api/speak")
def speak(payload: SpeakRequest):
    text = payload.text.strip()
    language = payload.language.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Nothing to speak.")
    if not language:
        raise HTTPException(status_code=400, detail="Select a target language before using server voice.")
    if len(text) > 5000:
        raise HTTPException(status_code=400, detail="Text-to-speech is limited to 5,000 characters per request.")
    try:
        audio, voice = synthesize(text, language)
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={"error": "Server voice could not generate audio.", "detail": str(exc)},
        )
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-store",
            "X-Voice-Name": voice["name"],
            "X-Voice-Locale": voice["locale"],
        },
    )


@app.get("/")
def root():
    return FileResponse(PUBLIC / "index.html")


@app.get("/{path:path}")
def static_files(path: str, request: Request):
    # API routes are handled above. This route only serves the existing frontend assets.
    candidate = (PUBLIC / path).resolve()
    if PUBLIC.resolve() not in candidate.parents:
        raise HTTPException(status_code=404, detail="Not found")
    if candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(PUBLIC / "index.html")
