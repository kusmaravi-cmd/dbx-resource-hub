/* DataPulse UI. No build step: plain ES2019, served by the FastAPI app. */
const DP = (() => {
  const S = {
    fw: null, me: '', store: null, list: [], cur: null, view: 'home', dim: 'R1', role: '', onlyOpen: false,
    saving: false, pending: false, timer: null, sevFilter: '', catFilter: { q: '', dim: '', mode: '' }, drawer: null, drawerErrors: [],
  };
  const $ = (id) => document.getElementById(id);
  const esc = (x) => String(x == null ? '' : x).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const f1 = (x) => (x == null ? '–' : Number(x).toFixed(1));
  const DIM = (id) => S.fw.dimensions.find((d) => d.id === id);
  const LEV = (id) => S.fw.levers.find((l) => l.id === id);
  const Q = (id) => S.fw.questions.find((q) => q.id === id);
  const doc = () => S.cur && S.cur.doc;
  const res = () => S.cur && S.cur.results;
  const TIERS = ['T1', 'T2', 'T3'];
  // Hash routing normally; an in-memory router where the page cannot own the URL (the claude.ai edition).
  const MEM = !!window.DP_MEMORY_ROUTER;
  let memHash = '#/home';
  const getHash = () => (MEM ? memHash : location.hash);
  function setHash(h) { if (MEM) { memHash = h; route(); } else location.hash = h; }

  // ------------------------------------------------------------------ api
  async function api(method, url, body) {
    const r = await fetch(url, { method, headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
    let data = null;
    try { data = await r.json(); } catch (e) { data = null; }
    if (!r.ok) { const err = new Error((data && (data.detail || (data.errors || []).join(' '))) || r.statusText); err.status = r.status; err.data = data; throw err; }
    return data;
  }

  function setSave(t, err) { const e = $('saveState'); e.textContent = t; e.className = 'savestate' + (err ? ' err' : ''); }
  function banner(html, ok) { $('banner').innerHTML = html ? `<div class="banner${ok ? ' ok' : ''}">${html}</div>` : ''; }

  // ------------------------------------------------------------------ boot
  async function init() {
    try {
      const [fw, me, health] = await Promise.all([api('GET', '/api/framework'), api('GET', '/api/me'), api('GET', '/api/health')]);
      S.fw = fw; S.me = me.user; S.store = health.store;
    } catch (e) { $('content').innerHTML = `<div class="empty">Could not load DataPulse: ${esc(e.message)}</div>`; return; }
    $('who').textContent = S.me;
    $('sideFoot').innerHTML = `<b>Framework v${esc(S.fw.version)}</b><br>${S.fw.questions.length} questions · ${S.fw.levers.length} levers · ${S.fw.rules.length} enforcement rules<br>Store: ${esc(S.store.kind)} <span class="mono">${esc(S.store.location || '')}</span>`;
    if (!MEM) window.addEventListener('hashchange', route);
    document.addEventListener('mouseover', tipOn); document.addEventListener('mouseout', tipOff); document.addEventListener('mousemove', tipMove);
    window.addEventListener('beforeunload', (e) => { if (S.timer || S.saving) { e.preventDefault(); e.returnValue = ''; } });
    await route();
  }

  async function route() {
    const h = (getHash() || '#/home').slice(2).split('/');
    const view = h[0] || 'home', id = h[1];
    if (S.drawer) closeDrawer();
    if (id && (!S.cur || S.cur.id !== id)) {
      await flush();
      try { const a = await api('GET', `/api/assessments/${id}`); S.cur = { id, version: a.version, doc: a.doc, results: a.results, meta: a.meta }; }
      catch (e) { S.cur = null; banner(`Could not open assessment: ${esc(e.message)}`); setHash('#/home'); return; }
    }
    if (!id && !['home', 'framework', 'catalog'].includes(view)) { setHash('#/home'); return; }
    if (view === 'home') { try { S.list = await api('GET', '/api/assessments'); } catch (e) { banner(esc(e.message)); } }
    S.view = view; render();
  }
  function go(view) { setHash(`#/${view}` + (S.cur && view !== 'home' ? `/${S.cur.id}` : '')); $('sidebar').classList.remove('open'); }

  // ------------------------------------------------------------------ save
  function dirty() { setSave('Unsaved changes…'); clearTimeout(S.timer); S.timer = setTimeout(() => { S.timer = null; save(); }, 700); }
  async function flush() { if (S.timer) { clearTimeout(S.timer); S.timer = null; await save(); } while (S.saving) await new Promise((r) => setTimeout(r, 80)); }
  async function save() {
    if (!S.cur) return;
    if (S.saving) { S.pending = true; return; }
    S.saving = true; setSave('Saving…');
    try {
      const r = await api('PUT', `/api/assessments/${S.cur.id}`, { version: S.cur.version, doc: S.cur.doc });
      S.cur.version = r.version; S.cur.results = r.results;
      // statuses are server-owned: adopt them without touching fields the user may be typing in
      Object.keys(r.doc.levers || {}).forEach((k) => { const l = (S.cur.doc.levers[k] = S.cur.doc.levers[k] || {}); l.status = r.doc.levers[k].status; l.history = r.doc.levers[k].history; });
      setSave('Saved ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
      refreshLive();
    } catch (e) {
      if (e.status === 409) banner(`${esc(e.message)} <button class="btn sm" onclick="location.reload()">Reload</button>`);
      setSave('Save failed', true);
    } finally {
      S.saving = false;
      if (S.pending) { S.pending = false; save(); }
    }
  }

  // ------------------------------------------------------------------ shell
  function nav() {
    const has = !!S.cur, r = res();
    const prog = r ? `${r.progress.attested}/${r.progress.attested_total}` : '';
    const blockers = r ? r.counts.blocker : 0;
    const item = (v, label, cnt, dis) => `<button class="navbtn${S.view === v ? ' active' : ''}" ${dis ? 'disabled' : ''} onclick="DP.go('${v}')"><span>${label}</span>${cnt ? `<span class="cnt">${cnt}</span>` : ''}</button>`;
    $('nav').innerHTML =
      `<div class="navsec">Workspace</div>${item('home', 'Assessments')}` +
      `<div class="navsec">${has ? esc(doc().name || 'Assessment') : 'Assessment'}</div>` +
      item('setup', 'Scope &amp; use cases', has ? String((doc().use_cases || []).length) : '', !has) +
      item('interview', 'Interview', prog, !has) +
      item('results', 'Results &amp; enforcement', blockers ? `${blockers} blockers` : '', !has) +
      item('levers', 'Levers &amp; roadmap', '', !has) +
      item('report', 'Report &amp; audit', '', !has) +
      `<div class="navsec">Reference</div>${item('framework', 'Framework &amp; rules')}${item('catalog', 'Lever catalog', String(S.fw.levers.length))}`;
    const names = { home: 'Assessments', setup: 'Scope & use cases', interview: 'Interview', results: 'Results & enforcement', levers: 'Levers & roadmap', report: 'Report & audit', framework: 'Framework & rules', catalog: 'Lever catalog' };
    $('crumbA').textContent = has && !['home'].includes(S.view) ? (doc().org ? doc().org + ' · ' : '') + (doc().name || '') : 'DataPulse';
    $('crumbB').textContent = names[S.view] || '';
  }
  function render() {
    if (tipEl) tipEl.style.display = 'none';
    nav();
    const v = VIEWS[S.view] || VIEWS.home;
    $('content').innerHTML = v();
    window.scrollTo(0, 0);
  }
  function refreshLive() {
    nav();
    if (S.view === 'interview') { renderDimNav(); document.querySelectorAll('[data-qenf]').forEach((el) => { el.innerHTML = enfNote(el.dataset.qenf); }); }
    else if (S.view === 'setup') { (doc().use_cases || []).forEach((u, i) => { const el = $('ucst' + i); if (el) el.innerHTML = ucStatus(i); }); }
    else if (['results', 'levers'].includes(S.view)) { const y = window.scrollY; $('content').innerHTML = VIEWS[S.view](); window.scrollTo(0, y); }
  }

  // ------------------------------------------------------------------ home
  const VIEWS = {};
  VIEWS.home = () => {
    const rows = S.list.length ? `<div class="alist">${S.list.map((a) => `<div class="item"><div><b>${esc(a.name)}</b> <span class="muted">${esc(a.org)}</span><div class="tiny muted">${esc(a.mode)} · v${a.version} · updated ${esc((a.updated_at || '').slice(0, 16).replace('T', ' '))} by ${esc(a.updated_by)}</div></div><button class="btn sm" onclick="DP.open('${a.id}')">Open</button></div>`).join('')}</div>`
      : `<div class="empty">No assessments yet. Create the first one.</div>`;
    return `<div class="eyebrow">Platform-agnostic data &amp; AI readiness</div>
      <h1 class="title">Assessments</h1>
      <p class="lede">DataPulse measures whether data is ready for AI, whether AI is improving the data, and whether the program is run so gains compound. It does not take answers at face value: claims need evidence, dimensions cannot outrun their dependencies, and a lever counts only once a system enforces it.</p>
      <div class="grid g2" style="align-items:start">
        <div>${rows}</div>
        <div class="card white"><h3>New assessment</h3>
          <div class="grid" style="margin-top:10px">
            <div class="field"><label>Name</label><input type="text" id="nName" placeholder="e.g. Phase 0 discovery, Q4"></div>
            <div class="field"><label>Organisation</label><input type="text" id="nOrg" placeholder="Client or business unit"></div>
            <div class="field"><label>Mode</label><select id="nMode">${Object.entries(S.fw.modes).map(([k, v]) => `<option value="${k}">${k[0].toUpperCase() + k.slice(1)}: ${esc(v)}</option>`).join('')}</select></div>
            <div class="field"><label>Reference platform for lever guidance</label><select id="nPlat">${Object.entries(S.fw.platforms).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('')}</select></div>
            <button class="btn primary" onclick="DP.create()">Create assessment</button>
          </div></div>
      </div>
      <h2 class="sub">How an assessment runs</h2>
      <div class="grid g4">
        ${[['1 · Scope', 'Name 2–3 AI use cases, their job type (Inference, Training, Agent) and the domains they touch. This sets the denominator for every coverage question.'],
           ['2 · Interview', `${S.fw.questions.filter((q) => q.kind === 'attested').length} episodic questions with anchored levels, plus ${S.fw.questions.filter((q) => q.kind === 'metric').length} measured metrics that triangulate the answers. Filter by the role in the room.`],
           ['3 · Enforce', 'Evidence gates, metric triangulation, weakest critical control, dimension precedence and the readiness ceiling turn claimed scores into enforced scores.'],
           ['4 · Lever', 'Levers are prioritised by the binding constraint and blocked use cases, sequenced into funded waves, and tracked Proposed → Committed → Enforced → Verified.']]
          .map((x) => `<div class="card"><h3>${x[0]}</h3><p class="small muted" style="margin-top:4px">${x[1]}</p></div>`).join('')}
      </div>`;
  };
  async function create() {
    const name = $('nName').value.trim();
    if (!name) { $('nName').focus(); return; }
    try {
      const r = await api('POST', '/api/assessments', { name, org: $('nOrg').value.trim(), mode: $('nMode').value, platform: $('nPlat').value });
      setHash(`#/setup/${r.id}`);
    } catch (e) { banner(esc(e.message)); }
  }

  // ------------------------------------------------------------------ setup
  function setField(path, val) {
    const d = doc(); const parts = path.split('.'); let o = d;
    for (let i = 0; i < parts.length - 1; i++) o = o[parts[i]] = o[parts[i]] || {};
    o[parts[parts.length - 1]] = val; dirty();
  }
  function ucStatus(i) {
    const u = (res().use_cases || [])[i];
    if (!u) return '<span class="status none">–</span>';
    const cls = { Go: 'go', Conditional: 'cond', Blocked: 'blocked' }[u.status] || 'none';
    return `<span class="status ${cls}">${esc(u.status)}${u.readiness != null ? ' · ' + f1(u.readiness) : ''}</span><div class="tiny muted" style="margin-top:3px">${esc(u.reason || '')}</div>`;
  }
  VIEWS.setup = () => {
    const d = doc(); const m = d.meta || {};
    const inp = (path, val, ph, type) => `<input type="${type || 'text'}" value="${esc(val)}" placeholder="${esc(ph || '')}" oninput="DP.setField('${path}', this.value)">`;
    const jobs = Object.entries(S.fw.jobs);
    return `<div class="eyebrow">Step 1 · scoping protocol</div><h1 class="title">Scope &amp; use cases</h1>
      <p class="lede">Scope before you score. Name the AI use cases this program must enable. Each job type has a critical path of readiness dimensions (A5), and Agent and Training use cases also need specific levers enforced before they can go live (ENF-08).</p>
      <div class="grid g2" style="align-items:start">
        <div class="card white"><h3>Assessment</h3><div class="grid g2" style="margin-top:10px">
          <div class="field"><label>Name</label>${inp('name', d.name)}</div>
          <div class="field"><label>Organisation</label>${inp('org', d.org)}</div>
          <div class="field"><label>Date</label>${inp('meta.date', m.date, '', 'date')}</div>
          <div class="field"><label>Assessor</label>${inp('meta.assessor', m.assessor)}</div>
          <div class="field" style="grid-column:1/-1"><label>Attendees and roles</label>${inp('meta.attendees', m.attendees, 'names / roles in the room')}</div>
          <div class="field" style="grid-column:1/-1"><label>Scope: domains and critical data elements in scope</label><textarea oninput="DP.setField('meta.scope', this.value)" placeholder="e.g. Customer domain: customer_id, segment, lifetime value; Finance: net revenue, bookings">${esc(m.scope)}</textarea></div>
        </div></div>
        <div class="card white"><h3>Enforcement settings</h3><div class="grid" style="margin-top:10px">
          <div class="field"><label>Mode</label><select onchange="DP.setField('mode', this.value)">${Object.entries(S.fw.modes).map(([k, v]) => `<option value="${k}" ${d.mode === k ? 'selected' : ''}>${k[0].toUpperCase() + k.slice(1)}</option>`).join('')}</select><div class="tiny muted" style="margin-top:3px">${esc(S.fw.modes[d.mode])}</div></div>
          <div class="grid g2">
            <div class="field"><label>Target level</label><select onchange="DP.setField('target_level', parseFloat(this.value))">${[2.5, 3, 3.5, 4, 4.5].map((t) => `<option value="${t}" ${Number(d.target_level) === t ? 'selected' : ''}>${t}${t === 3 ? ' (platform-enabled)' : ''}</option>`).join('')}</select></div>
            <div class="field"><label>Levers per wave</label><input type="number" min="2" max="15" value="${esc(d.wave_capacity)}" oninput="DP.setField('wave_capacity', parseInt(this.value || '6', 10))"></div>
          </div>
          <div class="field"><label>Reference platform for lever guidance</label><select onchange="DP.setField('platform', this.value)">${Object.entries(S.fw.platforms).map(([k, v]) => `<option value="${k}" ${d.platform === k ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select><div class="tiny muted" style="margin-top:3px">Questions and scoring are platform-agnostic. This only highlights reference implementations.</div></div>
        </div></div>
      </div>
      <h2 class="sub">AI use cases</h2>
      <div class="tbl"><table><thead><tr><th style="width:22%">Use case</th><th>Domain</th><th style="width:130px">Job</th><th>Measurable outcome</th><th>Owner</th><th style="width:26%">Readiness</th><th></th></tr></thead><tbody>
        ${(d.use_cases || []).map((u, i) => `<tr>
          <td><input type="text" value="${esc(u.name)}" oninput="DP.ucSet(${i},'name',this.value)" placeholder="e.g. Next-best-offer agent"></td>
          <td><input type="text" value="${esc(u.domain)}" oninput="DP.ucSet(${i},'domain',this.value)"></td>
          <td><select onchange="DP.ucSet(${i},'job',this.value,true)"><option value="">Choose…</option>${jobs.map(([k]) => `<option ${u.job === k ? 'selected' : ''}>${k}</option>`).join('')}</select></td>
          <td><input type="text" value="${esc(u.outcome)}" oninput="DP.ucSet(${i},'outcome',this.value)" placeholder="e.g. +2pt retention"></td>
          <td><input type="text" value="${esc(u.owner)}" oninput="DP.ucSet(${i},'owner',this.value)"></td>
          <td id="ucst${i}">${ucStatus(i)}</td>
          <td><button class="btn sm danger" onclick="DP.ucDel(${i})" aria-label="Remove">✕</button></td></tr>`).join('') || '<tr><td colspan="7" class="muted">No use cases yet.</td></tr>'}
      </tbody></table></div>
      <div class="row" style="margin-top:10px"><button class="btn" onclick="DP.ucAdd()">Add use case</button></div>
      <div class="grid g3" style="margin-top:16px">${jobs.map(([k, j]) => `<div class="card"><h3>${k}</h3><div class="small muted">${esc(j.desc)}</div><div class="small" style="margin-top:6px">Critical path: <b class="mono">${j.path.join(' · ')}</b></div>${(S.fw.job_lever_gates[k] || []).length ? `<div class="small" style="margin-top:4px">Lever gate: <b class="mono">${S.fw.job_lever_gates[k].join(', ')}</b> Enforced</div>` : ''}</div>`).join('')}</div>
      <h2 class="sub">Danger zone</h2><button class="btn danger" id="delBtn" onclick="DP.del()">Delete this assessment</button>`;
  };
  function ucSet(i, k, v, rerender) { doc().use_cases[i][k] = v; dirty(); if (rerender) nav(); }
  function ucAdd() { doc().use_cases = doc().use_cases || []; doc().use_cases.push({ id: 'uc' + Date.now(), name: '', domain: '', job: '', outcome: '', owner: '' }); dirty(); render(); }
  function ucDel(i) { doc().use_cases.splice(i, 1); dirty(); render(); }
  async function del() {
    const b = $('delBtn');
    if (b && !b.dataset.armed) { b.dataset.armed = '1'; b.textContent = 'Click again to delete (kept in the audit log)'; setTimeout(() => { if (b) { delete b.dataset.armed; b.textContent = 'Delete this assessment'; } }, 5000); return; }
    await flush(); await api('DELETE', `/api/assessments/${S.cur.id}`); S.cur = null; setHash('#/home');
  }

  // ------------------------------------------------------------------ interview
  function scoreColor(s) { if (s == null) return 'var(--faint)'; if (s < 2) return 'var(--crit)'; if (s < 3) return 'var(--warn)'; return 'var(--good)'; }
  function renderDimNav() {
    const el = $('dimnav'); if (!el) return;
    const r = res();
    el.innerHTML = `<div class="field" style="padding:6px"><label>Interviewing</label><select onchange="DP.setRole(this.value)"><option value="">All roles, by dimension</option>${S.fw.roles.map((x) => `<option ${S.role === x ? 'selected' : ''}>${esc(x)}</option>`).join('')}</select></div>
      <label class="tiny muted" style="display:flex;gap:6px;align-items:center;padding:0 8px 4px"><input type="checkbox" ${S.onlyOpen ? 'checked' : ''} onchange="DP.setOpen(this.checked)" style="width:auto"> Unanswered only</label>` +
      TIERS.map((t) => `<div class="tierh">${t} · ${esc(S.fw.tiers[t].name)}</div>` + S.fw.dimensions.filter((d) => d.tier === t).map((d) => {
        const x = r.dimensions[d.id];
        return `<button class="dimbtn${!S.role && S.dim === d.id ? ' active' : ''}" onclick="DP.setDim('${d.id}')"><span class="id">${d.id}</span><span class="nm">${esc(d.name)}</span><span class="prog">${x.answered}/${x.applicable}</span><span class="sc" style="color:${scoreColor(x.enforced)}" title="Enforced score">${f1(x.enforced)}</span></button>`;
      }).join('')).join('');
  }
  function evRows(q, r) {
    const ev = r.evidence || [];
    return ev.map((e, i) => `<div class="evrow"><select onchange="DP.evSet('${q.id}',${i},'type',this.value)">${S.fw.evidence_types.map((t) => `<option value="${t.id}" ${e.type === t.id ? 'selected' : ''}>${esc(t.name)}</option>`).join('')}</select><input type="text" value="${esc(e.ref)}" placeholder="Link or description of the evidence" oninput="DP.evSet('${q.id}',${i},'ref',this.value)"><button class="btn sm" onclick="DP.evDel('${q.id}',${i})" aria-label="Remove">✕</button></div>`).join('');
  }
  function enfNote(qid) {
    const q = Q(qid), x = res().questions[qid], r = (doc().responses || {})[qid] || {};
    if (!x || x.claimed == null) return '';
    if (q.kind === 'metric') return `<div class="small" style="margin-top:6px">Implies level <b>${x.claimed}</b> (${esc(LEVELNAME(x.claimed))}). Triangulates ${esc(q.dim)}: the dimension may not exceed ${x.claimed + 1} (ENF-03).</div>`;
    const notes = [];
    if (x.evidence_backed < x.claimed) {
      const need = x.claimed >= 4 && x.evidence_backed === 3 ? 'a system metric/log or a platform inspection' : (x.claimed === 5 && x.evidence_backed === 4 ? 'a second independent piece of evidence' : 'evidence stronger than verbal attestation');
      notes.push(doc().mode === 'validated' ? `Capped from ${x.claimed} to ${x.evidence_backed}: add ${need} (${x.claimed >= 4 ? 'ENF-02' : 'ENF-01'}).` : `Would be capped to ${x.evidence_backed} when validated: add ${need}.`);
    }
    if (x.claimed >= 4 && r.confidence === 'low') notes.push('Low confidence at level 4+: validate before relying on it (ENF-12).');
    return notes.map((n) => `<div class="enfnote">${esc(n)}</div>`).join('');
  }
  const LEVELNAME = (n) => (S.fw.levels[n] || {}).name || '';
  function qcard(q) {
    const r = (doc().responses || {})[q.id] || {};
    const wcls = { Critical: 'crit', High: 'high', Trajectory: 'traj' }[q.weight] || '';
    const head = `<div class="qhead"><span class="qid">${q.id}</span><span class="pill ${wcls}">${q.weight}</span>${q.velocity ? `<span class="pill">${q.velocity} velocity</span>` : ''}${q.kind === 'metric' ? '<span class="pill t2">Measured</span>' : ''}${(q.jobs || []).map((j) => `<span class="pill">${j}</span>`).join('')}<span class="tiny muted">${esc((q.roles || []).join(' · '))}</span></div>`;
    const more = (title, arr) => arr && arr.length ? `<details class="more"><summary>${title}</summary><ul>${arr.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></details>` : '';
    let body;
    if (q.kind === 'metric') {
      const bands = q.bands, dir = q.direction === 'lower_better';
      const scale = [1, 2, 3, 4, 5].map((n) => { const lo = n === 1 ? null : bands[n - 2], hi = n === 5 ? null : bands[n - 1]; return `L${n}: ${dir ? (n === 1 ? '> ' + bands[0] : n === 5 ? '≤ ' + bands[3] : '≤ ' + lo + ' and > ' + hi) : (n === 1 ? '< ' + bands[0] : n === 5 ? '≥ ' + bands[3] : '≥ ' + lo + ' and < ' + hi)}`; });
      body = `<div class="metric"><input type="number" step="any" value="${esc(r.value)}" oninput="DP.metric('${q.id}', this.value)" aria-label="value"><span class="muted">${esc(q.unit)}</span><label class="tiny muted" style="display:flex;gap:5px;align-items:center"><input type="checkbox" style="width:auto" ${r.na ? 'checked' : ''} onchange="DP.resp('${q.id}','na',this.checked,true)"> Not available</label></div>
        <div class="tiny muted" style="margin-top:6px">How to measure: ${esc(q.how_to_measure)}</div><div class="tiny muted mono" style="margin-top:3px">${esc(scale.join(' · '))}</div>
        <div class="field" style="margin-top:8px"><label>Source / note</label><input type="text" value="${esc(r.note)}" oninput="DP.resp('${q.id}','note',this.value)"></div>`;
    } else {
      body = `<div class="levels">${q.levels.map((t, i) => `<button class="lvl${r.level === i + 1 ? ' on' : ''}" onclick="DP.setLevel('${q.id}',${i + 1})"><b>L${i + 1}</b><span>${esc(t)}</span></button>`).join('')}</div>
        <div class="qfoot">
          <div class="field"><label>Confidence</label><select onchange="DP.resp('${q.id}','confidence',this.value,true)">${['', 'low', 'medium', 'high'].map((c) => `<option value="${c}" ${(r.confidence || '') === c ? 'selected' : ''}>${c || '–'}</option>`).join('')}</select>
            <label class="tiny muted" style="display:flex;gap:5px;align-items:center;margin-top:6px"><input type="checkbox" style="width:auto" ${r.na ? 'checked' : ''} onchange="DP.resp('${q.id}','na',this.checked,true)"> Not applicable</label></div>
          <div class="field"><label>Evidence <span class="muted" style="font-weight:400">· suggested: ${esc((q.evidence || []).join('; '))}</span></label>${evRows(q, r)}<button class="btn sm" onclick="DP.evAdd('${q.id}')">Add evidence</button></div>
        </div>
        <div class="field" style="margin-top:8px"><label>Notes / client quote</label><input type="text" value="${esc(r.note)}" oninput="DP.resp('${q.id}','note',this.value)"></div>`;
    }
    const answered = q.kind === 'metric' ? (r.value !== undefined && r.value !== '') : !!r.level;
    return `<div class="qcard${answered ? ' answered' : ''}" id="qc-${q.id}">${head}<div class="qprompt">${esc(q.prompt)}</div><div class="qintent">${esc(q.intent)}</div>${more('Follow-up probes', q.probes)}${more('Red flags: answers that usually signal inflation', q.red_flags)}${body}<div data-qenf="${q.id}">${enfNote(q.id)}</div></div>`;
  }
  function visibleQuestions() {
    let qs = S.role ? S.fw.questions.filter((q) => (q.roles || []).includes(S.role)) : S.fw.questions.filter((q) => q.dim === S.dim);
    if (S.onlyOpen) qs = qs.filter((q) => { const r = (doc().responses || {})[q.id] || {}; return !r.na && !(q.kind === 'metric' ? (r.value !== undefined && r.value !== '') : r.level); });
    return qs;
  }
  VIEWS.interview = () => {
    const qs = visibleQuestions();
    let header;
    if (S.role) header = `<div class="eyebrow">Interview · ${esc(S.role)}</div><h1 class="title">${qs.length} questions for this role</h1><p class="lede">Questions across all dimensions that this role is best placed to answer. Ask for the last real episode, not the policy.</p>`;
    else {
      const d = DIM(S.dim), t = S.fw.tiers[d.tier], x = res().dimensions[d.id];
      const deps = S.fw.dependencies.filter((p) => p.dim === d.id);
      header = `<div class="eyebrow">${d.tier} · ${esc(t.name)}${d.north_star ? ' · North Star' : ''}</div><h1 class="title">${d.id} ${esc(d.name)}</h1>
        <p class="lede">${esc(d.definition)} <span class="muted">Failure mode: ${esc(d.failure_mode)}</span></p>
        <div class="row small" style="margin:-8px 0 14px">Claimed <b>${f1(x.claimed)}</b> · Enforced <b style="color:${scoreColor(x.enforced)}">${f1(x.enforced)}</b>${x.caps.map((c) => ` <span class="sev cap" title="${esc(c.reason)}">${c.rule}</span>`).join('')}${deps.length ? ` · <span class="muted">Depends on ${deps.map((p) => p.upon.join(', ') + (p.slack ? ' +' + p.slack : '')).join('; ')}</span>` : ''}</div>`;
    }
    return `<div class="iv"><div class="dimnav" id="dimnav"></div><div>${header}${qs.map(qcard).join('') || '<div class="empty">Nothing to show with these filters.</div>'}
      ${!S.role ? `<div class="row" style="justify-content:space-between;margin-top:6px"><button class="btn" onclick="DP.stepDim(-1)">← Previous dimension</button><button class="btn primary" onclick="DP.stepDim(1)">Next dimension →</button></div>` : ''}</div></div>`;
  };
  const _origInterview = VIEWS.interview;
  VIEWS.interview = () => { setTimeout(renderDimNav, 0); return _origInterview(); };
  function setDim(d) { S.role = ''; S.dim = d; render(); }
  function setRole(r) { S.role = r; render(); }
  function setOpen(v) { S.onlyOpen = v; render(); }
  function stepDim(k) { const ids = S.fw.dimensions.map((d) => d.id); S.dim = ids[(ids.indexOf(S.dim) + k + ids.length) % ids.length]; render(); }
  function rr(qid) { const d = doc(); d.responses = d.responses || {}; return (d.responses[qid] = d.responses[qid] || {}); }
  function redraw(qid) { const el = $('qc-' + qid); if (el) el.outerHTML = qcard(Q(qid)); }
  function setLevel(qid, n) { const r = rr(qid); r.level = r.level === n ? null : n; if (r.level) r.na = false; dirty(); redraw(qid); }
  function resp(qid, k, v, re) { rr(qid)[k] = v; dirty(); if (re) redraw(qid); }
  function metric(qid, v) { rr(qid).value = v === '' ? '' : Number(v); dirty(); }
  function evAdd(qid) { const r = rr(qid); r.evidence = r.evidence || []; r.evidence.push({ type: 'document', ref: '' }); redraw(qid); }
  function evSet(qid, i, k, v) { rr(qid).evidence[i][k] = v; dirty(); }
  function evDel(qid, i) { rr(qid).evidence.splice(i, 1); dirty(); redraw(qid); }

  // ------------------------------------------------------------------ results
  function bars(r) {
    const tgt = Number(doc().target_level || 3);
    const pos = (v) => `${(Math.max(0, Math.min(5, v)) / 5) * 100}%`;
    const row = (d) => {
      const x = r.dimensions[d.id];
      const tip = `<b>${d.id} ${esc(d.name)}</b><br>Claimed ${f1(x.claimed)} · Evidence-backed ${f1(x.evidence_backed)} · Enforced ${f1(x.enforced)}${x.metric_level != null ? '<br>Measured metrics imply ' + f1(x.metric_level) : ''}<br>${x.answered}/${x.applicable} answered${x.provisional ? ' · provisional' : ''}${x.caps.map((c) => `<br>${c.rule}: ${esc(c.reason)}`).join('')}`;
      return `<div class="bar" data-tip="${esc(tip)}"><div class="lab"><span class="mono">${d.id}</span>${esc(d.name)}${x.provisional ? ' <span class="tiny muted">(prov.)</span>' : ''}</div>
        <div class="track">${x.enforced != null ? `<div class="fill" style="width:${pos(x.enforced)}"></div>` : ''}${x.evidence_backed != null && x.evidence_backed !== x.enforced ? `<div class="bk" style="left:${pos(x.evidence_backed)}"></div>` : ''}${x.claimed != null && x.claimed !== x.enforced ? `<div class="cl" style="left:${pos(x.claimed)}"></div>` : ''}<div class="tgt" style="left:${pos(tgt)}"></div></div>
        <div class="val">${f1(x.enforced)}${x.claimed != null && x.claimed - x.enforced >= 0.05 ? ` <span class="muted">(${f1(x.claimed)})</span>` : ''}</div></div>`;
    };
    return `<div class="legend"><span><i class="lg-enf"></i>Enforced</span><span><i class="lg-cl"></i>Claimed</span><span><i class="lg-bk"></i>Evidence-backed</span><span><i style="width:0;height:12px;border-left:2px dashed var(--faint)"></i>Target ${tgt}</span><span>Value column: enforced (claimed)</span></div>
      ${TIERS.map((t) => `<div class="tiny muted" style="font-weight:700;letter-spacing:.06em;text-transform:uppercase;margin:10px 6px 2px">${t} · ${esc(S.fw.tiers[t].name)}</div><div class="bars">${S.fw.dimensions.filter((d) => d.tier === t).map(row).join('')}</div>`).join('')}
      <div class="axis"><span></span><div class="ticks"><span>0</span><span>1</span><span>2</span><span>3</span><span>4</span><span>5</span></div><span></span></div>`;
  }
  function findingsList(r) {
    const fs = r.findings.filter((f) => !S.sevFilter || f.severity === S.sevFilter);
    return `<div class="filters"><select onchange="DP.sev(this.value)"><option value="">All severities (${r.findings.length})</option>${['blocker', 'cap', 'warning', 'info'].map((s) => `<option value="${s}" ${S.sevFilter === s ? 'selected' : ''}>${s} (${r.counts[s]})</option>`).join('')}</select></div>
      <div class="tbl"><table><thead><tr><th style="width:90px">Severity</th><th style="width:70px">Rule</th><th>Finding</th></tr></thead><tbody>${fs.map((f) => `<tr><td><span class="sev ${f.severity}">${f.severity}</span></td><td class="mono small" title="${esc((S.fw.rules.find((x) => x.id === f.rule) || {}).name || '')}">${f.rule}</td><td class="small">${esc(f.message)}</td></tr>`).join('') || '<tr><td colspan="3" class="muted">No findings.</td></tr>'}</tbody></table></div>`;
  }
  VIEWS.results = () => {
    const r = res(), t = r.tiers, d = doc();
    if (!r.progress.attested) return `<h1 class="title">Results &amp; enforcement</h1><div class="empty" style="margin-top:16px">No answers yet. <button class="btn primary" onclick="DP.go('interview')">Start the interview</button></div>`;
    const ucs = r.use_cases;
    return `<div class="eyebrow">${esc(d.mode)} mode · framework v${esc(r.framework_version)}</div><h1 class="title">Results &amp; enforcement</h1>
      <p class="lede">Enforced scores are what the evidence, metrics and dependencies support. The gap between claimed and enforced is where the conversation should go next.</p>
      <div class="tiles">
        <div class="tile"><div class="k">Readiness ceiling (A5)</div><div class="v" style="color:${scoreColor(t.T1.ceiling)}">${f1(t.T1.ceiling)}<small>/ 5</small></div><div class="d">Bound by <b>${esc(t.T1.binding.join(', ') || '–')}</b>${t.T1.ceiling_evidence_backed != null && t.T1.ceiling_evidence_backed < t.T1.ceiling ? ` · evidence-backed ${f1(t.T1.ceiling_evidence_backed)}` : ''}${t.T1.missing.length ? ` · not assessed: ${esc(t.T1.missing.join(', '))}` : ''}</div></div>
        <div class="tile"><div class="k">AI for Data</div><div class="v">${f1(t.T2.score)}<small>/ 5</small></div><div class="d">Flywheel: <b>${esc(t.T2.flywheel || '–')}</b></div></div>
        <div class="tile"><div class="k">Execution</div><div class="v">${f1(t.T3.score)}<small>/ 5</small></div><div class="d">${t.T3.critical.length ? `<b style="color:var(--crit)">Critical: ${esc(t.T3.critical.join(', '))}</b>` : 'No critical principles'}</div></div>
        <div class="tile"><div class="k">Coverage</div><div class="v">${r.progress.attested}<small>/ ${r.progress.attested_total}</small></div><div class="d">${r.progress.metrics}/${r.progress.metrics_total} metrics measured · ${r.counts.blocker} blockers · ${r.counts.cap} caps</div></div>
      </div>
      <h2 class="sub">Dimensions: claimed vs enforced</h2><div class="card white">${bars(r)}</div>
      <h2 class="sub">Velocity</h2>
      <div class="grid" style="grid-template-columns:repeat(5,minmax(0,1fr))">${S.fw.velocity.map((v) => { const x = r.velocity[v.id]; return `<div class="tile"><div class="k">${v.id}</div><div class="v" style="font-size:24px">${f1(x.level)}</div><div class="d">${x.source ? esc(x.source) + ' · ' + x.n : 'not assessed'}<br><span class="tiny">${esc(v.span)}</span></div></div>`; }).join('')}</div>
      <h2 class="sub">AI use-case readiness (ENF-08)</h2>
      ${ucs.length ? `<div class="tbl"><table><thead><tr><th>Use case</th><th>Job</th><th>Critical path</th><th>Status</th><th>Why</th><th>Unblock with</th></tr></thead><tbody>${ucs.map((u) => {
        const cls = { Go: 'go', Conditional: 'cond', Blocked: 'blocked' }[u.status] || 'none';
        const unblock = unblockers(u);
        return `<tr><td><b>${esc(u.name || '(unnamed)')}</b><div class="tiny muted">${esc(u.domain || '')}</div></td><td>${esc(u.job || '–')}</td><td class="mono small">${(u.path || []).map((p) => `${p} ${f1((u.path_scores || {})[p])}`).join('<br>')}</td><td><span class="status ${cls}">${esc(u.status)}</span></td><td class="small">${esc(u.reason)}</td><td class="small">${unblock.map((l) => `<a href="javascript:DP.openLever('${l}')">${l}</a>`).join(', ')}</td></tr>`;
      }).join('')}</tbody></table></div>` : `<div class="empty">No use cases scoped. <button class="btn sm" onclick="DP.go('setup')">Add use cases</button></div>`}
      <h2 class="sub">Enforcement findings</h2>${findingsList(r)}`;
  };
  function unblockers(u) {
    const pr = res().levers.priorities;
    const fromDims = S.fw.levers.filter((l) => (u.blocking || []).some((d) => l.targets[d]) && !['Enforced', 'Verified', 'Retired'].includes(pr[l.id].status))
      .sort((a, b) => pr[b.id].priority - pr[a.id].priority).slice(0, 3).map((l) => l.id);
    return [...new Set([...(u.gate_missing || []), ...fromDims])];
  }
  function sev(v) { S.sevFilter = v; render(); }

  // ------------------------------------------------------------------ levers
  function lcard(lid) {
    const l = LEV(lid), p = res().levers.priorities[lid], plan = res().levers.plan[lid];
    return `<div class="lcard" onclick="DP.openLever('${lid}')"><div class="row" style="justify-content:space-between"><span class="mono tiny muted">${lid}</span><span class="lst ${plan.status}">${plan.status}</span></div>
      <div class="nm">${esc(l.name)}</div>
      <div class="meta"><span class="pill">${l.mode}</span><span class="pill">${l.effort} · ~${l.ttv_days}d</span>${Object.keys(l.targets).map((t) => `<span class="pill mono">${t}+${l.targets[t]}</span>`).join('')}<span class="pill" title="Priority score">P ${p.priority.toFixed(1)}</span>${plan.stale ? '<span class="sev warning">stale</span>' : ''}${plan.issues.length && !plan.stale ? '<span class="sev warning">issue</span>' : ''}</div></div>`;
  }
  VIEWS.levers = () => {
    const r = res(), L = r.levers;
    const inEffect = S.fw.levers.filter((l) => ['Enforced', 'Verified'].includes(L.plan[l.id].status));
    const counts = {}; Object.values(L.plan).forEach((p) => { counts[p.status] = (counts[p.status] || 0) + 1; });
    return `<div class="eyebrow">Enforced levers · A3 governance is architecture</div><h1 class="title">Levers &amp; roadmap</h1>
      <p class="lede">Levers are ranked by how much they lift dimensions toward target, weighted toward the readiness ceiling's binding constraint, blocked use cases and critical execution principles, and divided by effort. They are sequenced so prerequisites come first, and every wave includes something that pays back within 90 days (ENF-10). A lever only counts once it is <b>Enforced</b>, with evidence of the mechanism, and <b>Verified</b> against its KPI (ENF-09).</p>
      <div class="row small" style="margin-bottom:12px">${S.fw.lever_statuses.map((s) => `<span class="lst ${s}">${s} ${counts[s] || 0}</span>`).join(' ')}</div>
      <div class="waves">${L.waves.map((w) => `<div class="wave"><div class="row" style="justify-content:space-between"><h3>${esc(w.name)}</h3><span class="tiny muted">${esc(w.window)}</span></div><div class="tiny muted">${esc(w.purpose)}</div>
        ${w.violations.map((v) => `<div class="enfnote">${esc(v.rule)}: ${esc(v.message)}</div>`).join('')}
        ${w.levers.map(lcard).join('') || '<div class="tiny muted" style="margin-top:8px">Nothing eligible.</div>'}
        <div class="tiny muted" style="margin-top:8px">Indicative projection once enforced: ${['R1', 'R2', 'R3', 'R4', 'R5', 'R6'].map((k) => `${k} ${f1(w.projected[k])}`).join(' · ')}</div></div>`).join('')}</div>
      <div class="grid g2" style="margin-top:16px;align-items:start">
        <div><h2 class="sub" style="margin-top:6px">In effect (${inEffect.length})</h2>${inEffect.map((l) => lcard(l.id)).join('') || '<div class="empty">No levers enforced yet.</div>'}</div>
        <div><h2 class="sub" style="margin-top:6px">Backlog (${L.backlog.length})</h2>${L.backlog.map((b) => `${lcard(b.id)}${b.blocked_by_levers.length || Object.keys(b.blocked_by_dims).length ? `<div class="tiny muted" style="margin:2px 0 0 4px">Waiting on ${esc([...b.blocked_by_levers, ...Object.entries(b.blocked_by_dims).map(([d, m]) => d + '≥' + m)].join(', '))}</div>` : ''}`).join('') || '<div class="empty">Nothing beyond the three waves.</div>'}</div>
      </div>`;
  };

  // lever drawer
  function openLever(lid) { S.drawer = lid; S.drawerErrors = []; drawRender(); $('drawer').classList.add('open'); $('scrim').classList.add('open'); $('drawer').setAttribute('aria-hidden', 'false'); }
  function closeDrawer() { S.drawer = null; $('drawer').classList.remove('open'); $('scrim').classList.remove('open'); $('drawer').setAttribute('aria-hidden', 'true'); }
  function ls(lid) { const d = doc(); d.levers = d.levers || {}; return (d.levers[lid] = d.levers[lid] || { status: 'Proposed' }); }
  function lset(k, v) { const st = ls(S.drawer); st[k] = v; dirty(); }
  function lexc(k, v) { const st = ls(S.drawer); st.exception = st.exception || {}; st.exception[k] = v; if (!st.exception.approver && !st.exception.justification && !st.exception.expires) delete st.exception; dirty(); }
  function implBlock(l, plat) {
    return `<div class="impl">${Object.entries(S.fw.platforms).map(([k, n]) => `<div class="p ${k === plat ? 'sel' : ''}">${esc(n)}</div><div class="${k === plat ? 'sel' : ''}">${esc(l.impl[k])}</div>`).join('')}</div>`;
  }
  function drawRender() {
    const lid = S.drawer; if (!lid) return;
    const l = LEV(lid), r = res(), p = r.levers.priorities[lid], plan = r.levers.plan[lid], st = ls(lid), dims = r.dimensions;
    const steps = ['Proposed', 'Committed', 'Enforced', 'Verified'];
    const idx = steps.indexOf(st.status);
    const allowed = S.fw.lever_transitions[st.status] || [];
    const ex = st.exception || {};
    const met = (d, m) => (dims[d].enforced || 0) + 1e-9 >= m;
    $('drawerBody').innerHTML = `<div class="row" style="justify-content:space-between"><span class="mono muted">${lid} · ${esc(l.category)}</span><button class="btn sm" onclick="DP.closeDrawer()">Close</button></div>
      <h1 class="title" style="font-size:21px;margin-top:6px">${esc(l.name)}</h1>
      <div class="row" style="margin:6px 0 10px"><span class="pill">${esc(l.mode)}</span><span class="pill">effort ${l.effort}</span><span class="pill">~${l.ttv_days} days to value</span><span class="pill">owner: ${esc(l.owner)}</span><span class="pill">priority ${p.priority.toFixed(1)}</span>${p.wave != null ? `<span class="pill">recommended Wave ${p.wave}</span>` : ''}</div>
      <p class="small">${esc(l.what)}</p>
      <div class="card" style="margin:10px 0"><div class="tiny muted" style="font-weight:700;text-transform:uppercase;letter-spacing:.06em">How it is enforced (${esc(l.mode)})</div><div class="small" style="margin-top:3px">${esc(l.enforcement)}</div><div class="tiny muted" style="margin-top:4px">${esc(S.fw.enforcement_modes[l.mode])}</div></div>
      ${p.reasons.length ? `<div class="small"><b>Why now:</b> ${esc(p.reasons.join('; '))}.</div>` : ''}
      <dl class="kv" style="margin:10px 0">
        <dt>Lifts</dt><dd>${Object.entries(l.targets).map(([d, v]) => `${d} +${v} <span class="muted">(now ${f1(dims[d].enforced)})</span>`).join(' · ')}</dd>
        <dt>Preconditions</dt><dd>${Object.entries(l.preconditions).map(([d, m]) => `<span style="color:${met(d, m) ? 'var(--good)' : 'var(--crit)'}">${met(d, m) ? '✓' : '✕'} ${d} ≥ ${m}</span> <span class="muted">(${f1(dims[d].enforced)})</span>`).join(' · ') || '<span class="muted">none</span>'}</dd>
        <dt>Requires</dt><dd>${l.requires.map((x) => { const s = r.levers.plan[x].status; const ok = ['Enforced', 'Verified'].includes(s); return `<a href="javascript:DP.openLever('${x}')" style="color:${ok ? 'var(--good)' : 'var(--crit)'}">${ok ? '✓' : '✕'} ${x}</a> <span class="muted">${s}</span>`; }).join(' · ') || '<span class="muted">none</span>'}</dd>
        ${l.pair_with.length ? `<dt>Pair with</dt><dd>${l.pair_with.map((x) => `<a href="javascript:DP.openLever('${x}')">${x}</a> <span class="muted">${r.levers.plan[x].status}</span>`).join(' · ')} <span class="tiny muted">(directive: one must be Enforced)</span></dd>` : ''}
        <dt>KPI</dt><dd>${esc(l.kpi.name)} <span class="muted">(${esc(l.kpi.unit)}, ${l.kpi.direction === 'lower_better' ? 'lower' : 'higher'} is better)</span></dd>
        <dt>Evidence</dt><dd>${l.evidence.map(esc).join('; ')}</dd>
        ${l.anti_patterns.length ? `<dt>Anti-patterns</dt><dd>${l.anti_patterns.map(esc).join('; ')}</dd>` : ''}
        <dt>Axioms</dt><dd>${l.axioms.map((a) => `${a} ${esc((S.fw.axioms.find((x) => x.id === a) || {}).name || '')}`).join(' · ')}</dd>
      </dl>
      <h2 class="sub" style="margin-top:14px">Lifecycle</h2>
      <div class="steps">${steps.map((s, i) => `<span class="${st.status === 'Retired' ? '' : i < idx ? 'done' : i === idx ? 'cur' : ''}">${s}</span>`).join('')}</div>
      ${st.status === 'Retired' ? '<div class="small muted">Retired.</div>' : ''}
      ${plan.issues.length ? `<div class="enfnote">${esc(plan.issues.join('; '))}</div>` : ''}
      <div class="grid g2" style="margin-top:8px">
        <div class="field"><label>Accountable owner</label><input type="text" value="${esc(st.owner)}" oninput="DP.lset('owner', this.value)" placeholder="${esc(l.owner)}"></div>
        <div class="field"><label>Wave</label><select onchange="DP.lset('wave', this.value)"><option value="">–</option>${[0, 1, 2].map((w) => `<option value="${w}" ${String(st.wave) === String(w) ? 'selected' : ''}>Wave ${w}</option>`).join('')}</select></div>
        <div class="field"><label>KPI baseline (${esc(l.kpi.unit)})</label><input type="number" step="any" value="${esc(st.kpi_baseline)}" oninput="DP.lset('kpi_baseline', this.value)"></div>
        <div class="field"><label>KPI target (${esc(l.kpi.unit)})</label><input type="number" step="any" value="${esc(st.kpi_target)}" oninput="DP.lset('kpi_target', this.value)"></div>
        <div class="field"><label>KPI current (${esc(l.kpi.unit)})</label><input type="number" step="any" value="${esc(st.kpi_current)}" oninput="DP.lset('kpi_current', this.value)"></div>
        <div class="field"><label>Verified at</label><input type="text" value="${esc(st.verified_at || '')}" disabled></div>
        <div class="field" style="grid-column:1/-1"><label>Enforcement evidence (one per line)</label><textarea oninput="DP.lset('enforcement_evidence', this.value.split('\\n'))" placeholder="${esc(l.evidence.join('\n'))}">${esc((st.enforcement_evidence || []).join('\n'))}</textarea></div>
      </div>
      <details class="more" ${ex.approver ? 'open' : ''}><summary>Time-bound exception for unmet preconditions (max 180 days)</summary>
        <div class="grid g3" style="margin-top:6px"><div class="field"><label>Approver</label><input type="text" value="${esc(ex.approver)}" oninput="DP.lexc('approver', this.value)"></div>
        <div class="field"><label>Expires</label><input type="date" value="${esc(ex.expires)}" oninput="DP.lexc('expires', this.value)"></div>
        <div class="field"><label>Justification</label><input type="text" value="${esc(ex.justification)}" oninput="DP.lexc('justification', this.value)"></div></div></details>
      <div class="field" style="margin-top:8px"><label>Reason (required to retire or move back)</label><input type="text" id="trReason"></div>
      ${S.drawerErrors.length ? `<div class="errs"><b>Transition rejected (ENF-09)</b><ul>${S.drawerErrors.map((e) => `<li>${esc(e)}</li>`).join('')}</ul></div>` : ''}
      <div class="row" style="margin-top:10px">${allowed.map((to) => `<button class="btn ${['Committed', 'Enforced', 'Verified'].includes(to) && steps.indexOf(to) > idx ? 'primary' : ''}" onclick="DP.transition('${to}')">${to === 'Retired' ? 'Retire' : steps.indexOf(to) < idx ? 'Back to ' + to : 'Mark ' + to}</button>`).join('')}</div>
      ${(st.history || []).length ? `<h2 class="sub">History</h2><ul class="hist">${st.history.slice().reverse().map((h) => `<li>${esc(h.ts)} · ${esc(h.actor)} · ${esc(h.from)} → <b>${esc(h.to)}</b>${h.reason ? ' · ' + esc(h.reason) : ''}</li>`).join('')}</ul>` : ''}
      <h2 class="sub">Reference implementations</h2>${implBlock(l, doc().platform)}`;
  }
  async function transition(to) {
    const lid = S.drawer, st = ls(lid);
    await flush();
    const fields = { owner: st.owner, wave: st.wave, kpi_baseline: st.kpi_baseline, kpi_target: st.kpi_target, kpi_current: st.kpi_current, enforcement_evidence: st.enforcement_evidence || [], exception: st.exception, reason: ($('trReason') || {}).value || '' };
    try {
      const r = await api('POST', `/api/assessments/${S.cur.id}/levers/${lid}/transition`, { version: S.cur.version, to, fields });
      S.cur.doc = r.doc; S.cur.version = r.version; S.cur.results = r.results; S.drawerErrors = [];
      setSave('Saved'); refreshLive(); drawRender();
    } catch (e) {
      S.drawerErrors = (e.data && e.data.errors) || [e.message]; drawRender();
    }
  }

  // ------------------------------------------------------------------ report
  VIEWS.report = () => {
    const id = S.cur.id;
    setTimeout(async () => {
      try { const t = await (await fetch(`/api/assessments/${id}/report.md`)).text(); const el = $('mdPrev'); if (el) el.textContent = t; } catch (e) { /* ignore */ }
      try { const a = await api('GET', `/api/assessments/${id}/audit`); const el = $('auditT'); if (el) el.innerHTML = a.map((x) => `<tr><td class="mono tiny">${esc(String(x.event_ts).slice(0, 19).replace('T', ' '))}</td><td class="small">${esc(x.actor)}</td><td class="small"><b>${esc(x.action)}</b></td><td class="tiny mono">${esc(JSON.stringify(x.detail))}</td></tr>`).join('') || '<tr><td colspan="4" class="muted">No events.</td></tr>'; } catch (e) { /* ignore */ }
    }, 0);
    return `<div class="eyebrow">Share &amp; trace</div><h1 class="title">Report &amp; audit</h1>
      <p class="lede">Exports always reflect the latest saved version. In Databricks, the same results are written to Unity Catalog tables for portfolio dashboards.</p>
      ${window.DP_ARTIFACT
        ? `<div class="row"><button class="btn primary" onclick="DP.copyExport('report.md')">Copy executive summary (Markdown)</button><button class="btn" onclick="DP.copyExport('export.csv')">Copy scores &amp; findings (CSV)</button><button class="btn" onclick="DP.copyExport('export.json')">Copy full payload (JSON)</button><span class="small muted" id="copyMsg"></span></div>`
        : `<div class="row"><a class="btn primary" href="/api/assessments/${id}/report.md">Executive summary (.md)</a><a class="btn" href="/api/assessments/${id}/export.csv">Scores &amp; findings (.csv)</a><a class="btn" href="/api/assessments/${id}/export.json">Full payload (.json)</a></div>`}
      <h2 class="sub">Executive summary preview</h2><pre class="card white small" id="mdPrev" style="white-space:pre-wrap;max-height:520px;overflow:auto;font-family:var(--mono);font-size:12px">Loading…</pre>
      <h2 class="sub">Audit log</h2><div class="tbl"><table><thead><tr><th style="width:150px">When (UTC)</th><th>Who</th><th>Action</th><th>Detail</th></tr></thead><tbody id="auditT"><tr><td colspan="4" class="muted">Loading…</td></tr></tbody></table></div>`;
  };

  // ------------------------------------------------------------------ reference
  VIEWS.framework = () => {
    const fw = S.fw;
    return `<div class="eyebrow">Reference · v${esc(fw.version)}</div><h1 class="title">Framework &amp; enforcement rules</h1>
      <p class="lede">Three tiers, twenty dimensions and five velocity measures, built on seven axioms. The rules below are applied the same way to every assessment, and every cap they produce is traceable.</p>
      <h2 class="sub">Seven axioms</h2><div class="grid g2">${fw.axioms.map((a) => `<div class="card"><b class="mono">${a.id}</b> <span class="muted small">${esc(a.name)}</span><div class="small" style="margin-top:3px">${esc(a.text)}</div></div>`).join('')}</div>
      <h2 class="sub">Enforcement rules</h2><div class="tbl"><table><thead><tr><th style="width:70px">Rule</th><th style="width:20%">Name</th><th>Rule</th><th style="width:28%">Effect</th></tr></thead><tbody>${fw.rules.map((r) => `<tr><td class="mono small">${r.id}</td><td class="small"><b>${esc(r.name)}</b><div class="tiny muted">${esc(r.applies)}</div></td><td class="small">${esc(r.text)}</td><td class="small muted">${esc(r.effect)}</td></tr>`).join('')}</tbody></table></div>
      <h2 class="sub">Dimensions</h2>${TIERS.map((t) => `<div class="card white" style="margin-bottom:10px"><h3>${t} · ${esc(fw.tiers[t].name)}</h3><div class="small muted">${esc(fw.tiers[t].question)} ${esc(fw.tiers[t].aggregation)}</div>
        <div class="tbl" style="margin-top:8px;border:none"><table><tbody>${fw.dimensions.filter((d) => d.tier === t).map((d) => `<tr><td class="mono small" style="width:40px">${d.id}</td><td style="width:22%"><b class="small">${esc(d.name)}</b>${d.north_star ? ' <span class="pill traj">North Star</span>' : ''}${d.weight ? ` <span class="pill">${d.weight * 100}%</span>` : ''}</td><td class="small">${esc(d.definition)}<div class="tiny muted">Failure mode: ${esc(d.failure_mode)}</div></td><td class="tiny muted" style="width:70px">${fw.questions.filter((q) => q.dim === d.id).length} questions</td></tr>`).join('')}</tbody></table></div></div>`).join('')}
      <h2 class="sub">Dimension precedence (ENF-05)</h2><div class="tbl"><table><thead><tr><th>Dimension</th><th>Capped at</th><th>Why</th></tr></thead><tbody>${fw.dependencies.map((d) => `<tr><td class="mono">${d.dim}</td><td class="mono small">min(${d.upon.join(', ')})${d.slack ? ' + ' + d.slack : ''}</td><td class="small">${esc(d.why)}</td></tr>`).join('')}</tbody></table></div>
      <h2 class="sub">Maturity levels &amp; evidence</h2><div class="grid g2"><div class="card white">${Object.entries(fw.levels).map(([n, l]) => `<div class="small" style="padding:4px 0;border-bottom:1px solid var(--border)"><b class="mono">${n}</b> <b>${esc(l.name)}</b> <span class="muted">${esc(l.summary)}</span></div>`).join('')}</div>
        <div class="card white">${fw.evidence_types.map((e) => `<div class="small" style="padding:4px 0;border-bottom:1px solid var(--border)"><b>${esc(e.name)}</b> <span class="pill">strength ${e.strength}</span><div class="tiny muted">${esc(e.desc)}</div></div>`).join('')}</div></div>
      <h2 class="sub">Question bank</h2><div class="filters"><input type="text" placeholder="Search questions…" oninput="DP.qsearch(this.value)" id="qs"></div><div id="qbank">${qbank('')}</div>`;
  };
  function qbank(q) {
    q = (q || '').toLowerCase();
    const qs = S.fw.questions.filter((x) => !q || (x.id + ' ' + x.prompt + ' ' + x.intent + ' ' + (x.levels || []).join(' ')).toLowerCase().includes(q));
    return `<div class="tbl"><table><thead><tr><th style="width:80px">ID</th><th>Question</th><th style="width:90px">Weight</th></tr></thead><tbody>${qs.map((x) => `<tr><td class="mono small">${x.id}</td><td class="small"><b>${esc(x.prompt)}</b><div class="tiny muted">${esc(x.intent)}</div>${x.kind === 'metric' ? `<div class="tiny mono muted">${esc(x.unit)} · ${x.direction.replace('_', ' ')} · bands ${x.bands.join(' / ')}</div>` : `<details class="more"><summary>Levels</summary><ul>${x.levels.map((l, i) => `<li><b>L${i + 1}</b> ${esc(l)}</li>`).join('')}</ul></details>`}</td><td class="small">${x.weight}</td></tr>`).join('')}</tbody></table></div>`;
  }
  function qsearch(v) { $('qbank').innerHTML = qbank(v); }
  VIEWS.catalog = () => {
    const f = S.catFilter, plat = (doc() && doc().platform) || 'generic';
    const ls_ = S.fw.levers.filter((l) => (!f.dim || l.targets[f.dim]) && (!f.mode || l.mode === f.mode) && (!f.q || (l.id + l.name + l.what + l.enforcement).toLowerCase().includes(f.q.toLowerCase())));
    return `<div class="eyebrow">Reference</div><h1 class="title">Lever catalog</h1>
      <p class="lede">Each lever states how it is enforced: preventive (blocks), detective (detects and routes), corrective (remediates) or directive (sets the standard, and counts only when paired with an enforced mechanism). The patterns are platform-agnostic, with reference implementations for common platforms.</p>
      <div class="filters"><input type="text" placeholder="Search levers…" value="${esc(f.q)}" onchange="DP.cat('q', this.value)"><select onchange="DP.cat('dim', this.value)"><option value="">All dimensions</option>${S.fw.dimensions.map((d) => `<option value="${d.id}" ${f.dim === d.id ? 'selected' : ''}>${d.id} ${esc(d.name)}</option>`).join('')}</select><select onchange="DP.cat('mode', this.value)"><option value="">All modes</option>${Object.keys(S.fw.enforcement_modes).map((m) => `<option ${f.mode === m ? 'selected' : ''}>${m}</option>`).join('')}</select><span class="muted small">${ls_.length} levers</span></div>
      ${ls_.map((l) => `<details class="card white" style="margin-bottom:8px"><summary style="cursor:pointer"><span class="mono muted small">${l.id}</span> <b>${esc(l.name)}</b> <span class="pill">${l.mode}</span> <span class="pill">${l.effort} · ~${l.ttv_days}d</span> ${Object.keys(l.targets).map((t) => `<span class="pill mono">${t}+${l.targets[t]}</span>`).join(' ')}</summary>
        <p class="small" style="margin-top:8px">${esc(l.what)}</p><p class="small"><b>Enforced by:</b> ${esc(l.enforcement)}</p>
        <p class="small"><b>KPI:</b> ${esc(l.kpi.name)} (${esc(l.kpi.unit)}) · <b>Requires:</b> ${l.requires.join(', ') || 'none'} · <b>Preconditions:</b> ${Object.entries(l.preconditions).map(([d, m]) => d + '≥' + m).join(', ') || 'none'}</p>
        <div style="margin-top:8px">${implBlock(l, plat)}</div></details>`).join('')}`;
  };
  function cat(k, v) { S.catFilter[k] = v; render(); }

  // ------------------------------------------------------------------ tooltip
  let tipEl = null;
  function tipOn(e) { const t = e.target.closest && e.target.closest('[data-tip]'); if (!t) return; if (!tipEl) { tipEl = document.createElement('div'); tipEl.className = 'tip'; document.body.appendChild(tipEl); } tipEl.innerHTML = t.dataset.tip; tipEl.style.display = 'block'; }
  function tipOff(e) { const t = e.target.closest && e.target.closest('[data-tip]'); if (t && tipEl && !(e.relatedTarget && t.contains(e.relatedTarget))) tipEl.style.display = 'none'; }
  function tipMove(e) { if (tipEl && tipEl.style.display === 'block') { const x = Math.min(e.clientX + 14, window.innerWidth - 350); tipEl.style.left = x + 'px'; tipEl.style.top = (e.clientY + 14) + 'px'; } }

  function toggleNav() { $('sidebar').classList.toggle('open'); }
  function open(id) { setHash(`#/results/${id}`); }
  async function copyExport(kind) {
    const msg = $('copyMsg');
    const text = await (await fetch(`/api/assessments/${S.cur.id}/${kind}`)).text();
    try { await navigator.clipboard.writeText(text); if (msg) msg.textContent = 'Copied to clipboard.'; }
    catch (e) { const pre = $('mdPrev'); if (pre) { pre.textContent = text; const r = document.createRange(); r.selectNodeContents(pre); const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r); } if (msg) msg.textContent = 'Clipboard unavailable: the text is selected below, press Ctrl/Cmd+C.'; }
  }

  document.addEventListener('DOMContentLoaded', init);
  return { go, open, copyExport, create, setField, ucSet, ucAdd, ucDel, del, setDim, setRole, setOpen, stepDim, setLevel, resp, metric, evAdd, evSet, evDel, sev, openLever, closeDrawer, lset, lexc, transition, qsearch, cat, toggleNav };
})();
