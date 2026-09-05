const $ = (id) => document.getElementById(id);

const state = {
  languages: [],
  source: "",
  target: "",
  listening: false,
  recognition: null,
  speaking: false,
  voicesReady: false,
  serverVoices: [],
  audio: null
};

function showError(message) {
  const box = $("error");
  box.textContent = message || "";
  box.classList.toggle("hidden", !message);
}

function setEngine(online, text) {
  const el = $("engine");
  el.className = "engine " + (online ? "online" : "offline");
  el.innerHTML = `<span></span><b>${text}</b>`;
}

function populateSelect(select, query, selected) {
  const q = query.trim().toLocaleLowerCase();

  const list = q
    ? state.languages.filter(
        (x) =>
          x.name.toLocaleLowerCase().includes(q) ||
          x.translation_code.toLocaleLowerCase().includes(q)
      )
    : state.languages;

  select.innerHTML = "";

  const first = document.createElement("option");
  first.value = "";
  first.textContent = list.length
    ? "Select language"
    : "No languages found";

  select.appendChild(first);

  const fragment = document.createDocumentFragment();

  for (const lang of list) {
    const option = document.createElement("option");
    option.value = lang.translation_code;
    option.textContent = lang.name;
    fragment.appendChild(option);
  }

  select.appendChild(fragment);

  if (list.some((x) => x.translation_code === selected)) {
    select.value = selected;
  }
}

function updateLanguageUI() {
  populateSelect(
    $("sourceSelect"),
    $("sourceSearch").value,
    state.source
  );

  populateSelect(
    $("targetSelect"),
    $("targetSearch").value,
    state.target
  );

  const source = state.languages.find(
    (x) => x.translation_code === state.source
  );

  const target = state.languages.find(
    (x) => x.translation_code === state.target
  );

  $("sourceName").textContent =
    source?.name || "Select language";

  $("targetName").textContent =
    target?.name || "Select language";

  $("sourceInfo").textContent = source
    ? `Translation code: ${source.translation_code}`
    : "—";

  $("targetInfo").textContent = target
    ? `Translation code: ${target.translation_code}`
    : "—";

  const ready = Boolean(
    state.source &&
    state.target &&
    state.languages.length
  );

  $("translateBtn").disabled = !ready;

  $("readyText").textContent = ready
    ? "Ready to translate"
    : "Select languages to continue";
}

async function loadLanguages(force = false) {
  showError("");

  $("catalogStatus").textContent = "Loading";
  $("catalogTitle").textContent = "Loading languages…";

  setEngine(false, "CONNECTING");

  try {
    const endpoint = force
      ? "/api/refresh-languages"
      : "/api/languages";

    const response = await fetch(endpoint, {
      cache: "no-store"
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.error ||
        "Unable to load the live language catalog."
      );
    }

    state.languages = Array.isArray(data.languages)
      ? data.languages
      : [];

    if (!state.languages.length) {
      throw new Error(
        "The translation service returned no languages."
      );
    }

    $("catalogCount").textContent =
      `${data.count.toLocaleString()}+`;

    $("translatableCount").textContent =
      data.count.toLocaleString();

    $("catalogStatus").textContent = "Live";

    $("catalogTitle").textContent =
      `${data.count.toLocaleString()} languages detected automatically`;

    setEngine(true, "ENGINE ONLINE");

    /*
      The application does not maintain a hardcoded language list.
      Defaults are selected only from the live catalog.
    */
    const codes = new Set(
      state.languages.map(
        (x) => x.translation_code
      )
    );

    if (!codes.has(state.source)) {
      state.source =
        state.languages[0].translation_code;
    }

    if (
      !codes.has(state.target) ||
      state.target === state.source
    ) {
      state.target =
        state.languages.find(
          (x) =>
            x.translation_code !== state.source
        )?.translation_code || "";
    }

    updateLanguageUI();

  } catch (err) {
    $("catalogStatus").textContent = "Offline";

    $("catalogTitle").textContent =
      "Live catalog unavailable";

    setEngine(false, "ENGINE OFFLINE");

    $("translateBtn").disabled = true;

    showError(
      err.message ||
      "Unable to connect to the translation service."
    );
  }
}

async function translateText() {
  const text = $("inputText").value.trim();

  if (!text) {
    return showError("Enter text to translate.");
  }

  if (!state.source || !state.target) {
    return showError(
      "Select source and target languages."
    );
  }

  showError("");

  $("output").textContent = "Translating…";
  $("output").classList.remove("result");

  $("provider").textContent = "";

  $("translateBtn").disabled = true;

  try {
    const response = await fetch(
      "/api/translate",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          text,
          source: state.source,
          target: state.target
        })
      }
    );

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.detail ||
        data.error ||
        "Translation was not completed."
      );
    }

    if (!data.translation) {
      throw new Error(
        "No verified translation was returned."
      );
    }

    $("output").textContent =
      data.translation;

    $("output").classList.add("result");

    $("provider").textContent =
      `${data.provider} • ${data.chunks} chunk(s)`;

    $("copyBtn").disabled = false;
    $("speakBtn").disabled = false;

  } catch (err) {
    $("output").textContent =
      "Your verified translation will appear here…";

    $("output").classList.remove("result");

    $("copyBtn").disabled = true;
    $("speakBtn").disabled = true;

    showError(
      err.message ||
      "Translation failed."
    );

  } finally {
    $("translateBtn").disabled =
      !(state.source && state.target);
  }
}

async function loadServerVoices() {
  try {
    const response = await fetch(
      "/api/voices",
      {
        cache: "no-store"
      }
    );

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.error ||
        "Unable to load server voices."
      );
    }

    state.serverVoices =
      Array.isArray(data.voices)
        ? data.voices
        : [];

    state.voicesReady =
      state.serverVoices.length > 0;

  } catch (err) {
    state.serverVoices = [];
    state.voicesReady = false;

    console.warn(
      "Server voice catalog unavailable:",
      err
    );
  }
}

function stopSpeaking() {
  if (state.audio) {
    state.audio.pause();
    state.audio.currentTime = 0;

    const oldAudio = state.audio;

    state.audio = null;

    if (oldAudio.src) {
      URL.revokeObjectURL(oldAudio.src);
    }
  }

  state.speaking = false;

  $("speakBtn").textContent = "🔊 Speak";
}

async function speakOutput() {
  const text = $("output").textContent.trim();

  if (
    !text ||
    text.startsWith("Your verified")
  ) {
    return;
  }

  if (!state.target) {
    return showError(
      "Select a target language before using server voice."
    );
  }

  /*
    Microphone listening and server speech should
    not run at the same time.
  */
  stopListening();

  showError("");

  state.speaking = true;

  /*
    There is intentionally no Stop button here.
    The button remains "Speak".
  */
  $("speakBtn").textContent = "🔊 Speak";

  try {
    const response = await fetch(
      "/api/speak",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          text,
          language: state.target
        })
      }
    );

    if (!response.ok) {
      const data =
        await response
          .json()
          .catch(() => ({}));

      throw new Error(
        data.detail
          ? `${data.error || "Server voice could not generate audio."} ${data.detail}`
          : (
              data.error ||
              "Server voice could not generate audio."
            )
      );
    }

    const blob =
      await response.blob();

    if (!blob.size) {
      throw new Error(
        "The server returned empty audio."
      );
    }

    const url =
      URL.createObjectURL(blob);

    const audio =
      new Audio(url);

    state.audio = audio;

    audio.onended = () => {
      URL.revokeObjectURL(url);

      state.audio = null;
      state.speaking = false;

      $("speakBtn").textContent =
        "🔊 Speak";
    };

    audio.onerror = () => {
      URL.revokeObjectURL(url);

      state.audio = null;
      state.speaking = false;

      $("speakBtn").textContent =
        "🔊 Speak";

      showError(
        "Server voice audio could not be played."
      );
    };

    await audio.play();

  } catch (err) {
    stopSpeaking();

    showError(
      err.message ||
      "Server voice failed."
    );
  }
}

function getRecognition() {
  return (
    window.SpeechRecognition ||
    window.webkitSpeechRecognition
  );
}

function startListening() {
  const Recognition =
    getRecognition();

  if (!Recognition) {
    return showError(
      "Microphone speech recognition is not supported here. Use current Chrome or Edge."
    );
  }

  if (!state.source) {
    return showError(
      "Select a source language before using the microphone."
    );
  }

  stopSpeaking();

  showError("");

  const recognition =
    new Recognition();

  recognition.lang =
    state.source;

  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;

  const base =
    $("inputText").value.trim();

  let committed = base;

  recognition.onresult = (event) => {
    let interim = "";

    for (
      let i = event.resultIndex;
      i < event.results.length;
      i++
    ) {
      const text =
        event.results[i][0]
          .transcript
          .trim();

      if (
        event.results[i].isFinal &&
        text
      ) {
        committed =
          `${committed} ${text}`.trim();
      } else {
        interim +=
          text + " ";
      }
    }

    $("inputText").value =
      committed;

    $("counter").textContent =
      `${committed.length.toLocaleString()} characters`;

    $("interim").textContent =
      interim.trim()
        ? `Listening: ${interim.trim()}`
        : "";

    $("interim").classList.toggle(
      "hidden",
      !interim.trim()
    );
  };

  recognition.onerror =
    (event) => {
      if (
        event.error === "not-allowed" ||
        event.error === "service-not-allowed"
      ) {
        showError(
          "Microphone permission was denied. Allow microphone access and try again."
        );
      } else if (
        event.error !== "aborted"
      ) {
        showError(
          `Microphone input failed: ${event.error}`
        );
      }

      stopListening();
    };

  recognition.onend = () => {
    if (state.listening) {
      /*
        Browsers may stop recognition automatically.
        Restart without losing already committed text.
      */
      try {
        recognition.start();
      } catch {
        // Browser is already restarting.
      }
    }
  };

  state.recognition =
    recognition;

  state.listening = true;

  $("micBtn").textContent =
    "■ Stop Listening";

  $("micBtn").classList.add(
    "listening"
  );

  try {
    recognition.start();
  } catch (err) {
    stopListening();

    showError(
      "Unable to start microphone input."
    );
  }
}

function stopListening() {
  state.listening = false;

  if (state.recognition) {
    try {
      state.recognition.stop();
    } catch {
      // Recognition may already be stopped.
    }

    state.recognition = null;
  }

  $("micBtn").textContent =
    "🎙 Speak";

  $("micBtn").classList.remove(
    "listening"
  );

  $("interim").classList.add(
    "hidden"
  );

  $("interim").textContent = "";
}

async function openManual() {
  const overlay =
    $("manualOverlay");

  const stateBox =
    $("manualState");

  const manualText =
    $("manualText");

  overlay.classList.remove(
    "hidden"
  );

  stateBox.textContent =
    "Loading manual…";

  stateBox.classList.remove(
    "hidden"
  );

  manualText.classList.add(
    "hidden"
  );

  try {
    /*
      The manual is served by Python.
      This keeps the existing static/manual.txt
      folder structure.
    */
    const response =
      await fetch(
        "/api/manual",
        {
          method: "GET",
          cache: "no-store",
          headers: {
            "Accept": "text/plain"
          }
        }
      );

    if (!response.ok) {
      let message =
        "Unable to load the user manual.";

      try {
        const data =
          await response.json();

        if (data.error) {
          message = data.error;
        }
      } catch {
        // Response was not JSON.
      }

      throw new Error(message);
    }

    const text =
      await response.text();

    if (!text.trim()) {
      throw new Error(
        "The user manual file is empty."
      );
    }

    manualText.textContent =
      text;

    manualText.classList.remove(
      "hidden"
    );

    stateBox.classList.add(
      "hidden"
    );

  } catch (err) {
    stateBox.textContent =
      err.message ||
      "Unable to load the user manual.";
  }
}

$("sourceSelect").addEventListener(
  "change",
  (e) => {
    state.source =
      e.target.value;

    updateLanguageUI();
  }
);

$("targetSelect").addEventListener(
  "change",
  (e) => {
    state.target =
      e.target.value;

    updateLanguageUI();
  }
);

$("sourceSearch").addEventListener(
  "input",
  updateLanguageUI
);

$("targetSearch").addEventListener(
  "input",
  updateLanguageUI
);

$("inputText").addEventListener(
  "input",
  (e) => {
    $("counter").textContent =
      `${e.target.value.length.toLocaleString()} characters`;
  }
);

$("translateBtn").addEventListener(
  "click",
  translateText
);

$("copyBtn").addEventListener(
  "click",
  async () => {
    try {
      await navigator.clipboard.writeText(
        $("output").textContent
      );

      $("copyBtn").textContent =
        "✓ Copied";

      setTimeout(() => {
        $("copyBtn").textContent =
          "▣ Copy";
      }, 1200);

    } catch {
      showError(
        "Unable to copy the translation."
      );
    }
  }
);

$("speakBtn").addEventListener(
  "click",
  speakOutput
);

$("micBtn").addEventListener(
  "click",
  () => {
    state.listening
      ? stopListening()
      : startListening();
  }
);

$("manualBtn").addEventListener(
  "click",
  openManual
);

$("closeManual").addEventListener(
  "click",
  () => {
    $("manualOverlay")
      .classList.add("hidden");
  }
);

$("manualOverlay").addEventListener(
  "click",
  (e) => {
    if (
      e.target ===
      $("manualOverlay")
    ) {
      $("manualOverlay")
        .classList.add("hidden");
    }
  }
);

$("refreshBtn").addEventListener(
  "click",
  () => loadLanguages(true)
);

window.addEventListener(
  "beforeunload",
  () => {
    stopListening();
    stopSpeaking();
  }
);

Promise.all([
  loadLanguages(),
  loadServerVoices()
]);