/* Browser-only backend for the claude.ai edition: answers the app's /api/* calls in the page.
   Data stays in this viewer's browser (localStorage when available, memory otherwise). */
(function () {
  const FW = window.DP_FRAMEWORK, E = window.DPEngine;
  E.init(FW);
  const KEY = 'everforth-datapulse-v2';
  const ACTOR = 'you (browser edition)';
  const now = () => new Date().toISOString().replace(/\.\d+Z$/, 'Z');
  const uuid = () => 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => { const r = (Math.random() * 16) | 0; return (c === 'x' ? r : (r & 3) | 8).toString(16); });
  let DB = null;
  function load() {
    if (DB) return DB;
    try { DB = JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (e) { DB = null; }
    if (!DB || !DB.assessments) {
      DB = { assessments: {}, audit: [] };
      const seed = window.DP_SEED;
      if (seed) { const id = 'demo-' + uuid().slice(0, 8);
        DB.assessments[id] = { doc: seed.doc, version: 1, created_by: 'Everforth demo', created_at: now(), updated_by: 'Everforth demo', updated_at: now() };
        (seed.history || []).forEach((h) => DB.audit.push(Object.assign({ assessment_id: id }, h))); }
      persist();
    }
    return DB;
  }
  function persist() { try { localStorage.setItem(KEY, JSON.stringify(DB)); } catch (e) { /* storage unavailable: keep in memory */ } }
  function audit(id, action, detail) { DB.audit.push({ event_ts: now(), assessment_id: id, actor: ACTOR, action, detail }); }
  function summary(id, r) { return { id, name: r.doc.name, org: r.doc.org, mode: r.doc.mode, version: r.version, created_by: r.created_by, created_at: r.created_at, updated_by: r.updated_by, updated_at: r.updated_at }; }
  function sanitize(doc) {
    const base = E.newAssessment(), out = {};
    Object.keys(base).forEach((k) => { out[k] = k in doc ? doc[k] : base[k]; });
    if (!FW.modes[out.mode]) out.mode = 'attested';
    out.target_level = Math.min(5, Math.max(2, Number(out.target_level) || 3));
    out.wave_capacity = Math.min(15, Math.max(2, parseInt(out.wave_capacity, 10) || 6));
    const qids = new Set(FW.questions.map((q) => q.id)), lids = new Set(FW.levers.map((l) => l.id));
    out.responses = {}; Object.entries(doc.responses || {}).forEach(([k, v]) => { if (qids.has(k) && v && typeof v === 'object') out.responses[k] = v; });
    out.levers = {}; Object.entries(doc.levers || {}).forEach(([k, v]) => { if (lids.has(k) && v && typeof v === 'object') out.levers[k] = v; });
    out.use_cases = (doc.use_cases || []).filter((u) => u && typeof u === 'object').slice(0, 50);
    return out;
  }
  const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  const text = (body, type) => new Response(body, { status: 200, headers: { 'Content-Type': type } });
  const f1 = (x) => (x === null || x === undefined ? 'n/a' : Number(x).toFixed(1));
  const LEV = {}; FW.levers.forEach((l) => { LEV[l.id] = l; });
  const DIMI = {}; FW.dimensions.forEach((d) => { DIMI[d.id] = d; });

  function report(doc, res) {
    const t = res.tiers, L = [], m = doc.meta || {};
    L.push(`# DataPulse assessment: ${doc.name || 'Untitled'}`, '', '*Everforth Apex · Data & AI Modernization Standard · Confidential: client assessment data*', '');
    L.push(`**Organisation:** ${doc.org || 'n/a'}  `, `**Mode:** ${doc.mode} (${FW.modes[doc.mode] || ''})  `, `**Target level:** ${doc.target_level}  `);
    if (m.date) L.push(`**Date:** ${m.date}  `); if (m.assessor) L.push(`**Assessor:** ${m.assessor}  `);
    L.push(`**Framework:** v${res.framework_version}, evaluated ${res.evaluated_at}`, '', '## Headline', '');
    L.push(`- **Readiness ceiling (A5): ${f1(t.T1.ceiling)}**, bound by ${t.T1.binding.join(', ') || 'n/a'}. No AI outcome can exceed this until the binding dimension improves.`);
    if (t.T1.ceiling_evidence_backed !== null && t.T1.ceiling !== null && t.T1.ceiling_evidence_backed < t.T1.ceiling) L.push(`- Evidence-backed ceiling is ${f1(t.T1.ceiling_evidence_backed)}: claims above this still need evidence.`);
    L.push(`- **AI for Data: ${f1(t.T2.score)}**, flywheel ${t.T2.flywheel || 'n/a'}.`, `- **Execution: ${f1(t.T3.score)}**` + (t.T3.critical.length ? `, critical: ${t.T3.critical.join(', ')}` : '') + '.');
    if (res.inflation.length) L.push(`- Claimed scores were reduced by enforcement on: ${res.inflation.join(', ')}.`);
    L.push(`- Findings: ${res.counts.blocker} blockers, ${res.counts.cap} caps, ${res.counts.warning} warnings.`, '', '## Velocity', '', '| Dimension | Level | Source |', '|---|---|---|');
    FW.velocity.forEach((v) => { const x = res.velocity[v.id]; L.push(`| ${v.id} | ${f1(x.level)} | ${x.source || 'not assessed'} |`); });
    L.push('', '## Dimensions: claimed vs enforced', '', '| Dim | Name | Claimed | Evidence-backed | Enforced | Why it was capped |', '|---|---|---|---|---|---|');
    FW.dimensions.forEach((d) => { const r = res.dimensions[d.id]; let why = r.caps.map((c) => `${c.rule} ${c.reason}`).join('; '); if (r.provisional) why = ('provisional (coverage). ' + why).trim();
      L.push(`| ${d.id} | ${d.name} | ${f1(r.claimed)} | ${f1(r.evidence_backed)} | ${f1(r.enforced)} | ${why} |`); });
    if (res.use_cases.length) { L.push('', '## AI use-case readiness', '', '| Use case | Job | Readiness | Status | Why |', '|---|---|---|---|---|');
      res.use_cases.forEach((u) => L.push(`| ${u.name} | ${u.job} | ${f1(u.readiness)} | **${u.status}** | ${u.reason || ''} |`)); }
    L.push('', '## Roadmap of enforced levers', '');
    res.levers.waves.forEach((w) => { L.push(`### ${w.name} (${w.window}): ${w.purpose}`, '');
      w.levers.forEach((lid) => { const lv = LEV[lid]; L.push(`- **${lid} ${lv.name}** [${lv.mode}, ${lv.effort}, ~${lv.ttv_days}d, ${res.levers.plan[lid].status}]`, `  - Enforced by: ${lv.enforcement}`, `  - KPI: ${lv.kpi.name} (${lv.kpi.unit}, ${lv.kpi.direction.replace('_', ' ')})`); });
      w.violations.forEach((v) => L.push(`- Warning (${v.rule}): ${v.message}`)); L.push(''); });
    const bl = res.findings.filter((f) => f.severity === 'blocker' || f.severity === 'cap');
    if (bl.length) { L.push('## Blockers and caps', ''); bl.forEach((f) => L.push(`- **${f.rule}** (${f.severity}): ${f.message}`)); L.push(''); }
    L.push('---', 'Generated by Everforth DataPulse. Scores are enforced: claims need evidence, dimensions respect their dependencies, and levers count only once a system enforces them.');
    return L.join('\n') + '\n';
  }
  function csv(doc, res) {
    const q = (x) => { const s = String(x === null || x === undefined ? '' : x); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
    const rows = [['section', 'id', 'name', 'claimed', 'evidence_backed', 'enforced', 'detail']];
    Object.entries(res.dimensions).forEach(([k, d]) => rows.push(['dimension', k, DIMI[k].name, d.claimed, d.evidence_backed, d.enforced, d.caps.map((c) => `${c.rule}: ${c.reason}`).join('; ') + (d.provisional ? ' [provisional]' : '')]));
    Object.entries(res.questions).forEach(([k, x]) => { const qq = FW.questions.find((y) => y.id === k), r = (doc.responses || {})[k] || {}; rows.push(['question', k, qq.prompt, x.claimed, x.evidence_backed, x.enforced, (x.na ? 'N/A ' : '') + (r.note || '')]); });
    res.levers.waves.forEach((w) => w.levers.forEach((l) => rows.push(['roadmap', l, LEV[l].name, '', '', '', w.name])));
    res.findings.forEach((f) => rows.push(['finding', f.rule, f.severity, '', '', '', f.message]));
    return rows.map((r) => r.map(q).join(',')).join('\n');
  }
  function diff(a, b) {
    const ch = (x, y) => [...new Set([...Object.keys(x || {}), ...Object.keys(y || {})])].filter((k) => JSON.stringify((x || {})[k]) !== JSON.stringify((y || {})[k])).sort();
    const d = { responses: ch(a.responses, b.responses), levers: ch(a.levers, b.levers) };
    if (JSON.stringify(a.use_cases) !== JSON.stringify(b.use_cases)) d.use_cases = true;
    return d;
  }

  async function handle(method, path, body) {
    const db = load();
    if (path === '/api/framework') return json(200, FW);
    if (path === '/api/me') return json(200, { user: ACTOR });
    if (path === '/api/health') return json(200, { ok: true, store: { kind: 'browser', location: 'this browser only' }, framework: FW.version });
    if (path === '/api/assessments' && method === 'GET') return json(200, Object.entries(db.assessments).filter(([, r]) => !r.deleted).map(([id, r]) => summary(id, r)).sort((x, y) => (x.updated_at < y.updated_at ? 1 : -1)));
    if (path === '/api/assessments' && method === 'POST') {
      if (!body || !String(body.name || '').trim()) return json(422, { detail: 'Name is required.' });
      const id = uuid(), doc = E.newAssessment(body.name, body.org, body.mode, body.target_level, body.platform);
      db.assessments[id] = { doc, version: 1, created_by: ACTOR, created_at: now(), updated_by: ACTOR, updated_at: now() };
      audit(id, 'create', { name: doc.name }); persist(); return json(200, { id, version: 1 });
    }
    const m = path.match(/^\/api\/assessments\/([^/]+)(?:\/(.*))?$/);
    if (!m) return json(404, { detail: 'Not found' });
    const id = m[1], sub = m[2] || '', rec = db.assessments[id];
    if (!rec || rec.deleted) return json(404, { detail: 'Assessment not found' });
    if (!sub && method === 'GET') return json(200, { meta: summary(id, rec), version: rec.version, doc: rec.doc, results: E.evaluate(rec.doc) });
    if (!sub && method === 'PUT') {
      if (body.version !== rec.version) return json(409, { detail: `This assessment was changed elsewhere (version ${body.version} is stale; current is ${rec.version}). Reload to continue.` });
      const doc = E.protectStatus(sanitize(body.doc), rec.doc);
      audit(id, 'save', diff(rec.doc, doc));
      Object.assign(rec, { doc, version: rec.version + 1, updated_by: ACTOR, updated_at: now() }); persist();
      return json(200, { version: rec.version, doc, results: E.evaluate(doc) });
    }
    if (!sub && method === 'DELETE') { rec.deleted = true; audit(id, 'delete', {}); persist(); return json(200, { ok: true }); }
    const t = sub.match(/^levers\/([^/]+)\/transition$/);
    if (t && method === 'POST') {
      if (body.version !== rec.version) return json(409, { detail: 'This assessment changed since you loaded it. Reload to continue.' });
      const [doc, errors] = E.transition(rec.doc, t[1], body.to, body.fields || {}, ACTOR);
      if (errors.length) { audit(id, 'lever_transition_rejected', { lever: t[1], to: body.to, errors }); persist(); return json(422, { errors }); }
      audit(id, 'lever_transition', { lever: t[1], from: E.leverState(rec.doc, t[1]).status, to: body.to, reason: (body.fields || {}).reason || '' });
      Object.assign(rec, { doc, version: rec.version + 1, updated_by: ACTOR, updated_at: now() }); persist();
      return json(200, { version: rec.version, doc, results: E.evaluate(doc) });
    }
    if (sub === 'audit') return json(200, db.audit.filter((a) => a.assessment_id === id).slice(-200).reverse());
    if (sub === 'report.md') return text(report(rec.doc, E.evaluate(rec.doc)), 'text/markdown');
    if (sub === 'export.csv') return text(csv(rec.doc, E.evaluate(rec.doc)), 'text/csv');
    if (sub === 'export.json') return text(JSON.stringify({ meta: summary(id, rec), framework_version: FW.version, doc: rec.doc, results: E.evaluate(rec.doc) }, null, 2), 'application/json');
    return json(404, { detail: 'Not found' });
  }

  const realFetch = window.fetch ? window.fetch.bind(window) : null;
  window.fetch = async function (url, opts) {
    const u = String(url);
    if (!u.startsWith('/api/')) return realFetch(url, opts);
    opts = opts || {};
    let body = null; try { body = opts.body ? JSON.parse(opts.body) : null; } catch (e) { body = null; }
    try { return await handle((opts.method || 'GET').toUpperCase(), u.split('?')[0], body); }
    catch (e) { return json(500, { detail: String(e && e.message || e) }); }
  };
  window.DP_RESET = function () { try { localStorage.removeItem(KEY); } catch (e) { /* ignore */ } DB = null; location.reload(); };
})();
