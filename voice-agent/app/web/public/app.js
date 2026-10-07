/* Hub Concierge client: /api/token -> LiveKit room -> mic on -> agent audio + transcript + data ("hub"). */
(() => {
  "use strict";
  const LK = window.LivekitClient;
  const $ = (id) => document.getElementById(id);
  const state = { room: null, muted: false, live: false, segs: new Map(), tokens: null, cfg: {} };

  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const safeUrl = (u) => (typeof u === "string" && /^https?:\/\//i.test(u) ? u : "#");
  const setStatus = (t) => { $("status").textContent = t; };

  function card(item, fresh) {
    const li = el("li", "card" + (fresh ? " fresh" : ""));
    const a = el("a", null, item.title || "Untitled");
    a.href = safeUrl(item.url); a.target = "_blank"; a.rel = "noopener noreferrer";
    li.append(a);
    if (item.summary) li.append(el("p", null, item.summary));
    if (item.note) li.append(el("p", null, "Note: " + item.note));
    const tags = el("div", "tags");
    if (item.kind) tags.append(el("span", "tag kind", item.kind));
    if (item.topic) tags.append(el("span", "tag", item.topic));
    if (item.status) tags.append(el("span", "tag state", item.status));
    if (item.released_on) tags.append(el("span", "tag", String(item.released_on).slice(0, 7)));
    li.append(tags);
    return li;
  }

  function showResults(r) {
    $("res-title").textContent = r.title || "Results";
    const list = $("results");
    list.replaceChildren(...(r.items || []).map((i) => card(i, true)));
    if (!(r.items || []).length) list.append(el("li", "card", "Nothing matched. Try a broader topic."));
    const b = $("source");
    b.hidden = false;
    b.textContent = r.source === "lakebase" ? "Lakebase hybrid search"
      : r.source === "lakebase-keyword" ? "Lakebase keyword search" : "Bundled catalog (fallback)";
    b.className = "badge" + (r.source === "lakebase" ? "" : " warn");
  }

  function addSaved(item) {
    const list = $("shortlist");
    for (const n of [...list.children]) if (n.dataset.id === item.id) n.remove();
    const c = card(item, true); c.dataset.id = item.id;
    list.prepend(c);
    $("short-sub").textContent = item.persisted ? "Saved to Lakebase." : "Saved for this session (Lakebase not connected).";
  }

  async function loadShortlist() {
    try {
      const r = await (await fetch("api/shortlist", { cache: "no-store" })).json();
      const items = r.items || [];
      $("shortlist").replaceChildren(...items.map((i) => { const c = card(i, false); c.dataset.id = i.id; return c; }));
      $("short-sub").textContent = items.length ? `${items.length} saved` : (r.error || 'Say "save that one" during a call.');
    } catch { /* offline: leave as is */ }
  }

  function renderFoot() {
    const c = state.cfg, parts = [];
    if (c.model) parts.push(`Model: ${c.model} via Unity AI Gateway`);
    parts.push(c.lakebase ? "Data: Lakebase" : "Data: bundled catalog");
    if (state.tokens) parts.push(`Tokens this call: ${state.tokens.input_tokens} in / ${state.tokens.output_tokens} out`);
    if (c.user) parts.push(`Signed in as ${c.user}`);
    $("foot").textContent = parts.join("  ·  ");
  }

  function onData(payload, _p, _k, topic) {
    if (topic !== "hub") return;
    let msg; try { msg = JSON.parse(new TextDecoder().decode(payload)); } catch { return; }
    if (msg.results) showResults(msg.results);
    if (msg.saved) addSaved(msg.saved);
    if (msg.usage) { state.tokens = msg.usage; renderFoot(); }
    if (msg.session) { state.cfg.model = msg.session.model; state.cfg.lakebase = msg.session.source === "lakebase"; renderFoot(); }
  }

  function onTranscript(segments, participant) {
    const isAgent = participant && participant.identity !== state.room.localParticipant.identity;
    for (const s of segments) {
      let li = state.segs.get(s.id);
      if (!li) {
        li = el("li", isAgent ? "agent" : "you");
        li.append(el("span", "who", isAgent ? "Concierge" : "You"), el("span", "text"));
        state.segs.set(s.id, li);
        $("transcript").append(li);
      }
      li.querySelector(".text").textContent = s.text;
    }
    const t = $("transcript"); t.scrollTop = t.scrollHeight;
  }

  async function connect() {
    const btn = $("connect");
    btn.disabled = true; setStatus("Connecting…");
    try {
      const res = await fetch("api/token", { cache: "no-store" });
      const t = await res.json();
      if (!res.ok) throw new Error(t.error || res.statusText);
      const room = new LK.Room({ adaptiveStream: true, dynacast: true });
      state.room = room;
      room.on(LK.RoomEvent.TrackSubscribed, (track) => {
        if (track.kind === "audio") document.body.append(track.attach());
      });
      room.on(LK.RoomEvent.DataReceived, onData);
      room.on(LK.RoomEvent.TranscriptionReceived, onTranscript);
      room.on(LK.RoomEvent.ParticipantConnected, () => setStatus("Concierge joined. Go ahead and ask."));
      room.on(LK.RoomEvent.ActiveSpeakersChanged, (speakers) => {
        const agentTalking = speakers.some((p) => p.identity !== room.localParticipant.identity);
        $("orb").classList.toggle("speaking", agentTalking);
      });
      room.on(LK.RoomEvent.Disconnected, () => endUI());
      await room.connect(t.serverUrl, t.token);
      await room.localParticipant.setMicrophoneEnabled(true);
      state.live = true; state.tokens = null;
      $("orb").classList.add("live");
      $("mute").disabled = false;
      btn.textContent = "End call"; btn.classList.add("end"); btn.disabled = false;
      setStatus(room.remoteParticipants.size ? "Concierge is here." : "Waiting for the concierge to join…");
    } catch (e) {
      setStatus(`Could not connect: ${e.message}`);
      btn.disabled = false;
      if (state.room) state.room.disconnect();
    }
  }

  function endUI() {
    state.live = false;
    $("orb").classList.remove("live", "speaking");
    $("mute").disabled = true; $("mute").textContent = "Mute"; state.muted = false;
    const btn = $("connect"); btn.textContent = "Start call"; btn.classList.remove("end"); btn.disabled = false;
    setStatus("Call ended");
    loadShortlist();
  }

  $("connect").addEventListener("click", () => {
    if (state.live && state.room) state.room.disconnect(); else connect();
  });
  $("mute").addEventListener("click", async () => {
    if (!state.room) return;
    state.muted = !state.muted;
    await state.room.localParticipant.setMicrophoneEnabled(!state.muted);
    $("mute").textContent = state.muted ? "Unmute" : "Mute";
  });
  $("refresh").addEventListener("click", loadShortlist);

  window.HubConcierge = { showResults, addSaved, onTranscript: (segs, who) => {
    state.room = state.room || { localParticipant: { identity: "me" } }; onTranscript(segs, { identity: who });
  } };  // for demos/tests without a live call

  fetch("api/config", { cache: "no-store" }).then((r) => r.json()).then((c) => {
    state.cfg = c; renderFoot();
    if (!c.livekit_configured) { setStatus("LiveKit is not configured on the server."); $("connect").disabled = true; }
  }).catch(() => {});
  loadShortlist();
})();
