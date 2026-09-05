import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path


# ============================================================
# OPTIONAL SERVER VOICE PACKAGES
# ============================================================

def ensure_voice_package():
    try:
        import edge_tts  # noqa: F401
        return
    except ImportError:
        print("Installing server voice engine (edge-tts) once...")
        subprocess.check_call([
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "edge-tts"
        ])


def ensure_gtts_package():
    try:
        import gtts  # noqa: F401
        return
    except ImportError:
        print("Installing secondary server voice engine (gTTS) once...")
        subprocess.check_call([
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "gTTS"
        ])


ensure_voice_package()
ensure_gtts_package()

import edge_tts
from gtts import gTTS
from gtts.lang import tts_langs


# ============================================================
# APPLICATION PATHS
# ============================================================

ROOT = Path(__file__).resolve().parent

# IMPORTANT:
# Keep the user's existing folder structure:
#
# Language-Translator/
# ├── server.py
# └── static/
#     ├── index.html
#     ├── app.js
#     ├── style.css
#     └── manual.txt
#
STATIC = ROOT / "static"

MANUAL_FILE = STATIC / "manual.txt"


# ============================================================
# SERVER SETTINGS
# ============================================================

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))


# ============================================================
# CACHES
# ============================================================

LANGUAGE_CACHE = {
    "items": None,
    "expires": 0.0
}

VOICE_CACHE = {
    "items": None,
    "expires": 0.0
}

CACHE_LOCK = threading.Lock()


# ============================================================
# LIVE LANGUAGE CATALOG PROVIDERS
# ============================================================

GOOGLE_LANGUAGE_URLS = [
    "https://translate.googleapis.com/translate_a/l?client=webapp&format=html",
    "https://translate.google.com/translate_a/l?client=webapp&format=html",
]


# ============================================================
# GENERAL HTTP JSON HELPER
# ============================================================

def fetch_json(url, timeout=20):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout
    ) as response:
        return json.loads(
            response.read().decode("utf-8")
        )


# ============================================================
# GOOGLE LANGUAGE PARSER
# ============================================================

def parse_google_languages(data):
    candidates = []

    if isinstance(data, dict):
        for key in (
            "languages",
            "sl",
            "tl",
            "data"
        ):
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

                if (
                    isinstance(code, str)
                    and isinstance(name, str)
                    and code.strip()
                ):
                    found[code.strip()] = (
                        name.strip() or code.strip()
                    )

        elif isinstance(candidate, list):

            for item in candidate:

                if isinstance(item, dict):

                    code = (
                        item.get("code")
                        or item.get("languageCode")
                        or item.get("language")
                    )

                    name = (
                        item.get("name")
                        or item.get("displayName")
                        or code
                    )

                    if (
                        isinstance(code, str)
                        and isinstance(name, str)
                    ):
                        found[code.strip()] = (
                            name.strip() or code.strip()
                        )

                elif (
                    isinstance(item, (list, tuple))
                    and len(item) >= 2
                ):

                    code, name = item[0], item[1]

                    if (
                        isinstance(code, str)
                        and isinstance(name, str)
                    ):
                        found[code.strip()] = (
                            name.strip() or code.strip()
                        )

    return [
        {
            "id": code,
            "name": name,
            "translation_code": code
        }
        for code, name in sorted(
            found.items(),
            key=lambda x: x[1].casefold()
        )
        if re.fullmatch(
            r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]+)?",
            code
        )
    ]


# ============================================================
# LIVE LANGUAGE LOADING
# ============================================================

def load_languages(force=False):

    now = time.time()

    with CACHE_LOCK:

        if (
            not force
            and LANGUAGE_CACHE["items"]
            and LANGUAGE_CACHE["expires"] > now
        ):
            return LANGUAGE_CACHE["items"]

    last_error = None

    for url in GOOGLE_LANGUAGE_URLS:

        try:
            items = parse_google_languages(
                fetch_json(url)
            )

            if items:

                with CACHE_LOCK:
                    LANGUAGE_CACHE["items"] = items
                    LANGUAGE_CACHE["expires"] = (
                        time.time() + 3600
                    )

                return items

        except Exception as exc:
            last_error = exc

    with CACHE_LOCK:

        if LANGUAGE_CACHE["items"]:
            return LANGUAGE_CACHE["items"]

    raise RuntimeError(
        "Unable to fetch the live translation language "
        f"catalog: {last_error}"
    )


# ============================================================
# GOOGLE TRANSLATION
# ============================================================

def translate_google(text, source, target):

    if source == target:
        return text

    params = urllib.parse.urlencode({
        "client": "gtx",
        "sl": source,
        "tl": target,
        "dt": "t",
        "ie": "UTF-8",
        "oe": "UTF-8",
        "q": text,
    })

    url = (
        "https://translate.googleapis.com/"
        "translate_a/single?"
        + params
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:

        data = json.loads(
            response.read().decode("utf-8")
        )

    if (
        not isinstance(data, list)
        or not data
        or not isinstance(data[0], list)
    ):
        raise RuntimeError(
            "Translation provider returned an invalid response."
        )

    result = "".join(
        row[0]
        for row in data[0]
        if (
            isinstance(row, list)
            and row
            and isinstance(row[0], str)
        )
    ).strip()

    if not result:
        raise RuntimeError(
            "Translation provider returned an empty result."
        )

    return result


# ============================================================
# TEXT CHUNKING
# ============================================================

def split_text(text, limit=1200):

    text = (
        text
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .strip()
    )

    if not text:
        return []

    if len(text) <= limit:
        return [text]

    chunks = []

    for paragraph in re.split(
        r"\n\s*\n",
        text
    ):

        paragraph = paragraph.strip()

        if not paragraph:
            continue

        sentences = re.split(
            r"(?<=[.!?。！？])\s+",
            paragraph
        )

        current = ""

        for sentence in sentences:

            sentence = sentence.strip()

            if not sentence:
                continue

            candidate = (
                f"{current} {sentence}"
            ).strip()

            if len(candidate) <= limit:

                current = candidate

            else:

                if current:
                    chunks.append(current)

                current = sentence

        if current:
            chunks.append(current)

    return chunks


# ============================================================
# LANGUAGE NORMALIZATION
# ============================================================

def normalize_locale(code):
    return (
        (code or "")
        .strip()
        .replace("_", "-")
        .lower()
    )


# ============================================================
# EDGE TTS VOICE SELECTION
# ============================================================

def choose_voice(voices, language_code):

    wanted = normalize_locale(
        language_code
    )

    if not wanted:
        return None

    exact = [
        v
        for v in voices
        if normalize_locale(
            v.get("Locale")
        ) == wanted
    ]

    if exact:
        return exact[0]

    base = wanted.split(
        "-",
        1
    )[0]

    matches = [
        v
        for v in voices
        if normalize_locale(
            v.get("Locale")
        ).split("-", 1)[0] == base
    ]

    if matches:
        return matches[0]

    return None


# ============================================================
# PROXY SUPPORT
# ============================================================

def proxy_url():

    return (
        os.getenv("HTTPS_PROXY")
        or os.getenv("https_proxy")
        or os.getenv("HTTP_PROXY")
        or os.getenv("http_proxy")
        or None
    )


# ============================================================
# EDGE TTS VOICE CATALOG
# ============================================================

def load_voices(force=False):

    now = time.time()

    with CACHE_LOCK:

        if (
            not force
            and VOICE_CACHE["items"] is not None
            and VOICE_CACHE["expires"] > now
        ):
            return VOICE_CACHE["items"]

    last_error = None

    try:

        voices = asyncio.run(
            edge_tts.list_voices(
                proxy=proxy_url()
            )
        )

        items = [
            {
                "name": v.get("ShortName"),
                "locale": v.get("Locale"),
                "language": v.get("LocaleName"),
                "gender": v.get("Gender"),
                "engine": "edge-tts",
            }
            for v in voices
            if (
                v.get("ShortName")
                and v.get("Locale")
            )
        ]

        items.sort(
            key=lambda x: (
                x["locale"],
                x["name"]
            )
        )

    except Exception as exc:

        last_error = exc
        items = []

    with CACHE_LOCK:

        VOICE_CACHE["items"] = items
        VOICE_CACHE["expires"] = (
            time.time() + 3600
        )

    if not items and last_error:

        print(
            "[VOICE] Edge voice catalog unavailable:",
            last_error
        )

    return items


# ============================================================
# gTTS LANGUAGE LOOKUP
# ============================================================

def gtts_language_for(code):

    wanted = normalize_locale(code)

    supported = tts_langs()

    if wanted in supported:
        return wanted

    base = wanted.split(
        "-",
        1
    )[0]

    if base in supported:
        return base

    for candidate in supported:

        if (
            normalize_locale(candidate)
            .split("-", 1)[0]
            == base
        ):
            return candidate

    return None


# ============================================================
# EDGE TTS SYNTHESIS
# ============================================================

def synthesize_edge(text, voice_name):

    fd, path = tempfile.mkstemp(
        suffix=".mp3"
    )

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
                connect_timeout=20,
                receive_timeout=90,
            )

            await communicator.save(path)

        asyncio.run(make_audio())

        audio = Path(path).read_bytes()

        if not audio:
            raise RuntimeError(
                "Edge TTS returned an empty audio file."
            )

        return audio

    finally:

        try:
            os.remove(path)
        except OSError:
            pass


# ============================================================
# gTTS SYNTHESIS
# ============================================================

def synthesize_gtts(text, language_code):

    language = gtts_language_for(
        language_code
    )

    if not language:
        raise RuntimeError(
            "The selected language has no secondary "
            "server voice available."
        )

    if len(text) > 1800:
        raise RuntimeError(
            "The secondary server voice supports shorter "
            "text; use Edge TTS for long text."
        )

    fd, path = tempfile.mkstemp(
        suffix=".mp3"
    )

    os.close(fd)

    try:

        gTTS(
            text=text,
            lang=language,
            slow=False
        ).save(path)

        audio = Path(path).read_bytes()

        if not audio:
            raise RuntimeError(
                "Google TTS returned an empty audio file."
            )

        return audio, {
            "name": f"gtts:{language}",
            "locale": language,
            "language": supported_language_name(
                language
            ),
            "gender": "",
            "engine": "gTTS",
        }

    finally:

        try:
            os.remove(path)
        except OSError:
            pass


# ============================================================
# gTTS LANGUAGE NAME
# ============================================================

def supported_language_name(language):

    try:
        return tts_langs().get(
            language,
            language
        )
    except Exception:
        return language


# ============================================================
# SPEECH SYNTHESIS
# ============================================================

def synthesize(
    text,
    language_code,
    requested_voice=None
):

    voices = load_voices()

    voice = None

    if requested_voice:

        voice = next(
            (
                v
                for v in voices
                if v["name"] == requested_voice
            ),
            None
        )

    else:

        voice = choose_voice(
            voices,
            language_code
        )

    errors = []

    if voice:

        for attempt in range(2):

            try:

                return (
                    synthesize_edge(
                        text,
                        voice["name"]
                    ),
                    voice
                )

            except Exception as exc:

                errors.append(
                    f"Edge TTS attempt "
                    f"{attempt + 1}: {exc}"
                )

                time.sleep(0.5)

    try:

        return synthesize_gtts(
            text,
            language_code
        )

    except Exception as exc:

        errors.append(
            f"gTTS: {exc}"
        )

    if voice is None:

        raise RuntimeError(
            "No working server voice was found for "
            "the selected language. "
            + " | ".join(errors)
        )

    raise RuntimeError(
        "Server voice generation failed. "
        + " | ".join(errors)
    )


# ============================================================
# JSON RESPONSE
# ============================================================

def json_response(
    handler,
    status,
    payload
):

    raw = json.dumps(
        payload,
        ensure_ascii=False
    ).encode("utf-8")

    handler.send_response(status)

    handler.send_header(
        "Content-Type",
        "application/json; charset=utf-8"
    )

    handler.send_header(
        "Cache-Control",
        "no-store"
    )

    handler.send_header(
        "Content-Length",
        str(len(raw))
    )

    handler.end_headers()

    handler.wfile.write(raw)


# ============================================================
# HTTP HANDLER
# ============================================================

class Handler(SimpleHTTPRequestHandler):

    def __init__(
        self,
        *args,
        **kwargs
    ):

        super().__init__(
            *args,
            directory=str(STATIC),
            **kwargs
        )

    def log_message(
        self,
        fmt,
        *args
    ):

        print(
            "[HTTP]",
            fmt % args
        )

    # --------------------------------------------------------
    # GET
    # --------------------------------------------------------

    def do_GET(self):

        path = urllib.parse.urlparse(
            self.path
        ).path

        # ----------------------------------------------------
        # HEALTH
        # ----------------------------------------------------

        if path == "/api/health":

            try:

                languages = load_languages()
                voices = load_voices()

                json_response(
                    self,
                    200,
                    {
                        "status": "online",
                        "translation_provider":
                            "Google Translate Web",
                        "language_count":
                            len(languages),
                        "server_voice_count":
                            len(voices),
                        "secondary_voice_language_count":
                            len(tts_langs()),
                    }
                )

            except Exception as exc:

                json_response(
                    self,
                    503,
                    {
                        "status": "offline",
                        "error": str(exc)
                    }
                )

            return

        # ----------------------------------------------------
        # LANGUAGES
        # ----------------------------------------------------

        if path in (
            "/api/languages",
            "/api/refresh-languages"
        ):

            try:

                languages = load_languages(
                    force=path.endswith(
                        "refresh-languages"
                    )
                )

                json_response(
                    self,
                    200,
                    {
                        "count": len(languages),
                        "languages": languages
                    }
                )

            except Exception as exc:

                json_response(
                    self,
                    503,
                    {
                        "error": str(exc)
                    }
                )

            return

        # ----------------------------------------------------
        # VOICES
        # ----------------------------------------------------

        if path in (
            "/api/voices",
            "/api/refresh-voices"
        ):

            try:

                voices = load_voices(
                    force=path.endswith(
                        "refresh-voices"
                    )
                )

                json_response(
                    self,
                    200,
                    {
                        "count": len(voices),
                        "voices": voices
                    }
                )

            except Exception as exc:

                json_response(
                    self,
                    503,
                    {
                        "error": str(exc)
                    }
                )

            return

        # ----------------------------------------------------
        # USER MANUAL
        # ----------------------------------------------------

        if path == "/api/manual":

            try:

                # Resolve the exact expected file.
                manual_file = (
                    STATIC / "manual.txt"
                )

                if not manual_file.exists():
                    json_response(
                        self,
                        404,
                        {
                            "error":
                                "User manual file not found: "
                                "static/manual.txt"
                        }
                    )
                    return

                if not manual_file.is_file():
                    json_response(
                        self,
                        500,
                        {
                            "error":
                                "User manual path is not a file."
                        }
                    )
                    return

                raw = manual_file.read_bytes()

                if not raw:
                    json_response(
                        self,
                        500,
                        {
                            "error":
                                "The user manual file is empty."
                        }
                    )
                    return

                self.send_response(200)

                self.send_header(
                    "Content-Type",
                    "text/plain; charset=utf-8"
                )

                self.send_header(
                    "Cache-Control",
                    "no-store"
                )

                self.send_header(
                    "Content-Length",
                    str(len(raw))
                )

                self.end_headers()

                self.wfile.write(raw)

            except Exception as exc:

                json_response(
                    self,
                    500,
                    {
                        "error":
                            "Unable to read the user manual.",
                        "detail": str(exc)
                    }
                )

            return

        # ----------------------------------------------------
        # NORMAL STATIC FILES
        # ----------------------------------------------------

        return super().do_GET()

    # --------------------------------------------------------
    # POST
    # --------------------------------------------------------

    def do_POST(self):

        path = urllib.parse.urlparse(
            self.path
        ).path

        try:

            length = int(
                self.headers.get(
                    "Content-Length",
                    "0"
                )
            )

            if (
                length <= 0
                or length > 2_000_000
            ):
                raise ValueError(
                    "Invalid request size."
                )

            payload = json.loads(
                self.rfile.read(length)
                .decode("utf-8")
            )

            # ------------------------------------------------
            # TRANSLATION
            # ------------------------------------------------

            if path == "/api/translate":

                text = str(
                    payload.get(
                        "text",
                        ""
                    )
                ).strip()

                source = str(
                    payload.get(
                        "source",
                        ""
                    )
                ).strip()

                target = str(
                    payload.get(
                        "target",
                        ""
                    )
                ).strip()

                if not text:
                    raise ValueError(
                        "Enter text to translate."
                    )

                if not source or not target:
                    raise ValueError(
                        "Select source and target languages."
                    )

                codes = {
                    x["translation_code"]
                    for x in load_languages()
                }

                if (
                    source not in codes
                    or target not in codes
                ):
                    raise ValueError(
                        "The selected language is not "
                        "currently available from the "
                        "live translation catalog."
                    )

                chunks = split_text(text)

                translated = [
                    translate_google(
                        chunk,
                        source,
                        target
                    )
                    for chunk in chunks
                ]

                result = "\n\n".join(
                    x
                    for x in translated
                    if x
                ).strip()

                if not result:
                    raise RuntimeError(
                        "No verified translation was returned."
                    )

                json_response(
                    self,
                    200,
                    {
                        "translation": result,
                        "provider":
                            "Google Translate Web",
                        "chunks":
                            len(chunks)
                    }
                )

                return

            # ------------------------------------------------
            # SERVER SPEECH
            # ------------------------------------------------

            if path == "/api/speak":

                text = str(
                    payload.get(
                        "text",
                        ""
                    )
                ).strip()

                language = str(
                    payload.get(
                        "language",
                        ""
                    )
                ).strip()

                requested_voice = (
                    str(
                        payload.get(
                            "voice",
                            ""
                        )
                    ).strip()
                    or None
                )

                if not text:
                    raise ValueError(
                        "Nothing to speak."
                    )

                if len(text) > 5000:
                    raise ValueError(
                        "Text-to-speech is limited to "
                        "5,000 characters per request."
                    )

                audio, voice = synthesize(
                    text,
                    language,
                    requested_voice
                )

                self.send_response(200)

                self.send_header(
                    "Content-Type",
                    "audio/mpeg"
                )

                self.send_header(
                    "Cache-Control",
                    "no-store"
                )

                self.send_header(
                    "X-Voice-Name",
                    voice["name"]
                )

                self.send_header(
                    "X-Voice-Locale",
                    voice["locale"]
                )

                self.send_header(
                    "Content-Length",
                    str(len(audio))
                )

                self.end_headers()

                self.wfile.write(audio)

                return

            # ------------------------------------------------
            # UNKNOWN POST
            # ------------------------------------------------

            json_response(
                self,
                404,
                {
                    "error": "Not found"
                }
            )

        except ValueError as exc:

            json_response(
                self,
                400,
                {
                    "error": str(exc)
                }
            )

        except Exception as exc:

            if path == "/api/speak":

                json_response(
                    self,
                    502,
                    {
                        "error":
                            "Server voice could not "
                            "generate audio.",
                        "detail": str(exc)
                    }
                )

            else:

                json_response(
                    self,
                    502,
                    {
                        "error":
                            "Translation was not shown "
                            "because the translation provider "
                            "did not return a verified result.",
                        "detail": str(exc)
                    }
                )


# ============================================================
# APPLICATION START
# ============================================================

if __name__ == "__main__":

    print("=" * 62)
    print(
        " LANGUAGE TRANSLATOR — "
        "HTML / CSS / JS / PYTHON"
    )
    print("=" * 62)

    print(
        f"Open: http://127.0.0.1:{PORT}"
    )

    print(
        f"Server bind: {HOST}:{PORT}"
    )

    print(
        "Static directory:",
        STATIC
    )

    print(
        "Manual file:",
        MANUAL_FILE
    )

    print(
        "Server voice: "
        "Microsoft Edge neural voices "
        "(loaded dynamically)"
    )

    server = ThreadingHTTPServer(
        (HOST, PORT),
        Handler
    )

    threading.Thread(
        target=server.serve_forever,
        daemon=True
    ).start()

    try:

        import webbrowser

        webbrowser.open(
            f"http://127.0.0.1:{PORT}"
        )

    except Exception:
        pass

    try:

        while True:
            time.sleep(3600)

    except KeyboardInterrupt:

        print("\nStopping...")

        server.shutdown()