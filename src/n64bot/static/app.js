"use strict";

(function () {
  var ASK_TIMEOUT_MS = 90000;
  var GENERIC_ERROR = "Something went wrong — try again.";

  var $ = function (id) { return document.getElementById(id); };
  var log = $("log");
  var cart = $("cart");
  var swapBtn = $("swap");
  var form = $("form");
  var input = $("question");
  var sendBtn = $("send");
  var picker = $("picker");
  var pickerClose = $("picker-close");
  var search = $("search");
  var gamesList = $("games");
  var pickerMsg = $("picker-msg");

  var game = null;       // {slug, title} | null
  var inFlight = false;  // an /api/ask request is pending
  var generation = 0;    // bumps when the chat is cleared, so stale answers are dropped
  var searchSeq = 0;     // latest game search request id
  var searchTimer = null;
  var picking = false;   // a PUT /api/game is pending

  // ---- HTTP -------------------------------------------------------------

  // Resolves to {ok, status, data}; never rejects (network errors -> status 0).
  function api(method, url, body, timeoutMs) {
    var opts = { method: method, headers: {} };
    if (timeoutMs) {
      var ctl = new AbortController();
      opts.signal = ctl.signal;
      var t = setTimeout(function () { ctl.abort(); }, timeoutMs);
    }
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return fetch(url, opts).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (data) {
        clearTimeout(t);
        return { ok: res.ok, status: res.status, data: data };
      });
    }, function () {
      clearTimeout(t);
      return { ok: false, status: 0, data: null };
    });
  }

  function detailOf(r) {
    var d = r.data && r.data.detail;
    // FastAPI validation errors put a list in `detail`; only show plain strings.
    return typeof d === "string" && d ? d : GENERIC_ERROR;
  }

  // ---- Rendering --------------------------------------------------------

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // Escape first, then only **bold**. Line breaks are kept by `white-space: pre-wrap`.
  function renderMarkdown(text) {
    return escapeHtml(text).replace(/\*\*([^*\n]+?)\*\*/g, "<strong>$1</strong>");
  }

  function scrollToBottom() {
    log.scrollTop = log.scrollHeight;
  }

  function clearEmpty() {
    var e = log.querySelector(".empty");
    if (e) e.remove();
  }

  function addUser(text) {
    clearEmpty();
    var el = document.createElement("div");
    el.className = "u";
    el.textContent = text;
    log.appendChild(el);
    scrollToBottom();
    return el;
  }

  function addBot(text, isError) {
    clearEmpty();
    var el = document.createElement("div");
    el.className = isError ? "b err" : "b";
    el.innerHTML = renderMarkdown(text);
    log.appendChild(el);
    scrollToBottom();
    return el;
  }

  function addTyping() {
    clearEmpty();
    var el = document.createElement("div");
    el.className = "b";
    el.setAttribute("aria-label", "Looking it up");
    el.innerHTML = '<span class="typing" aria-hidden="true"><i></i><i></i><i></i></span>';
    log.appendChild(el);
    scrollToBottom();
    return el;
  }

  function showEmpty() {
    var el = document.createElement("p");
    el.className = "empty";
    el.textContent = game
      ? "Ask anything about " + game.title + "."
      : "Pick a game to start.";
    log.appendChild(el);
  }

  function resetChat(history) {
    generation += 1;
    inFlight = false;
    updateControls();
    log.textContent = "";
    (history || []).forEach(function (h) {
      addUser(h.question);
      addBot(h.answer);
    });
    if (!history || !history.length) showEmpty();
    scrollToBottom();
  }

  function setGame(g) {
    game = g;
    cart.textContent = "▮ " + (g ? g.title : "No cartridge");
    updateControls();
  }

  function updateControls() {
    input.disabled = !game;
    sendBtn.disabled = !game || inFlight || !input.value.trim();
  }

  // ---- Picker -----------------------------------------------------------

  function openPicker() {
    pickerClose.hidden = !game;
    pickerMsg.hidden = true;
    search.value = "";
    picker.hidden = false;
    loadGames("");
    // Avoid popping the keyboard over the list on touch devices.
    if (!window.matchMedia || !window.matchMedia("(pointer: coarse)").matches) {
      search.focus();
    }
  }

  function closePicker() {
    if (!game) return; // can't dismiss without a game
    clearTimeout(searchTimer);
    picker.hidden = true;
    input.focus();
  }

  function setPickerMsg(text) {
    pickerMsg.textContent = text;
    pickerMsg.hidden = !text;
  }

  function loadGames(q) {
    var seq = ++searchSeq;
    api("GET", "/api/games?q=" + encodeURIComponent(q)).then(function (r) {
      if (seq !== searchSeq) return; // a newer search superseded this one
      gamesList.textContent = "";
      if (!r.ok || !Array.isArray(r.data)) {
        setPickerMsg("Couldn't load games — try again.");
        return;
      }
      if (!r.data.length) {
        setPickerMsg(q ? "No games match “" + q + "”." : "No manuals ingested yet.");
        return;
      }
      setPickerMsg("");
      r.data.forEach(function (g) {
        var li = document.createElement("li");
        var b = document.createElement("button");
        b.type = "button";
        b.textContent = g.title;
        if (game && game.slug === g.slug) {
          b.className = "active";
          b.setAttribute("aria-current", "true");
        }
        b.addEventListener("click", function () { pick(g.slug); });
        li.appendChild(b);
        gamesList.appendChild(li);
      });
    });
  }

  function pick(slug) {
    if (picking) return;
    picking = true;
    api("PUT", "/api/game", { slug: slug }).then(function (r) {
      picking = false;
      if (!r.ok || !r.data || !r.data.game) {
        setPickerMsg(detailOf(r));
        return;
      }
      var changed = !game || game.slug !== r.data.game.slug;
      setGame(r.data.game);
      if (changed) resetChat(r.data.history);
      closePicker();
    });
  }

  search.addEventListener("input", function () {
    clearTimeout(searchTimer);
    var q = search.value.trim();
    searchTimer = setTimeout(function () { loadGames(q); }, 200);
  });

  swapBtn.addEventListener("click", openPicker);
  pickerClose.addEventListener("click", closePicker);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !picker.hidden) closePicker();
  });

  // ---- Asking -----------------------------------------------------------

  function send() {
    var question = input.value.trim();
    if (!question || inFlight || !game) return;
    inFlight = true;
    input.value = "";
    autoGrow();
    updateControls();

    var gen = generation;
    addUser(question);
    var typing = addTyping();

    api("POST", "/api/ask", { question: question }, ASK_TIMEOUT_MS).then(function (r) {
      inFlight = false;
      updateControls();
      if (gen !== generation) return; // chat was cleared (game swapped) meanwhile
      typing.remove();
      if (r.ok && r.data && typeof r.data.answer === "string") {
        addBot(r.data.answer);
        return;
      }
      addBot(detailOf(r), true);
      if (!input.value) {
        input.value = question;
        autoGrow();
        updateControls();
      }
      if (r.status === 409) {
        setGame(null);
        openPicker();
      }
    });
  }

  function autoGrow() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    send();
  });

  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      send();
    }
  });

  input.addEventListener("input", function () {
    autoGrow();
    updateControls();
  });

  // ---- Boot -------------------------------------------------------------

  api("GET", "/api/state").then(function (r) {
    if (r.ok && r.data && r.data.game) {
      setGame(r.data.game);
      resetChat(r.data.history);
      return;
    }
    setGame(null);
    resetChat([]);
    if (!r.ok) addBot(detailOf(r), true);
    openPicker();
  });
})();
