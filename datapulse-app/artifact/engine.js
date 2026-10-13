/* DataPulse engine, JavaScript port of server/engine.py for the browser-only edition.
   Kept line-for-line equivalent; tests/check_js_engine.py compares both on random assessments. */
(function (root) {
  let FW = null, DIM = {}, LEVER = {}, QS = [];
  const EFFORT_COST = { S: 1.0, M: 1.6, L: 2.4 };
  const ENFORCED = ['Enforced', 'Verified'];
  const VERIFY_DAYS = 90, MAX_EXCEPTION_DAYS = 180;
  const SEV = { blocker: 0, cap: 1, warning: 2, info: 3 };

  function init(fw) {
    FW = fw; QS = fw.questions; DIM = {}; LEVER = {};
    fw.dimensions.forEach((d) => { DIM[d.id] = d; });
    fw.levers.forEach((l) => { LEVER[l.id] = l; });
  }
  const r2 = (x) => (x == null ? null : Math.round((x + Number.EPSILON) * 100) / 100);
  const f1 = (x) => Number(x).toFixed(1);
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const isoToday = () => new Date().toISOString().slice(0, 10);
  const parseDate = (s) => (s && /^\d{4}-\d{2}-\d{2}/.test(String(s)) ? String(s).slice(0, 10) : null);
  const daysBetween = (a, b) => Math.round((Date.parse(b) - Date.parse(a)) / 86400000);
  const addDays = (a, n) => new Date(Date.parse(a) + n * 86400000).toISOString().slice(0, 10);
  const wmean = (pairs) => { const tw = pairs.reduce((s, p) => s + p[1], 0); return tw ? pairs.reduce((s, p) => s + p[0] * p[1], 0) / tw : null; };
  const nowZ = () => new Date().toISOString().replace(/\.\d+Z$/, 'Z');

  function newAssessment(name, org, mode, target, platform) {
    return { name: name || '', org: org || '', mode: FW.modes[mode] ? mode : 'attested', target_level: Number(target || 3), wave_capacity: 6,
      platform: platform || 'generic', meta: { date: '', assessor: '', attendees: '', scope: '', notes: '' }, responses: {}, use_cases: [], levers: {} };
  }
  function leverState(a, lid) { const st = ((a.levers || {})[lid]) || {}; if (!st.status) st.status = 'Proposed'; return st; }
  function exceptionActive(st, today) { const ex = st.exception || {}; const exp = parseDate(ex.expires); return !!(ex.approver && ex.justification && exp && exp >= today); }

  function metricLevel(q, value) {
    if (value === null || value === undefined || value === '') return null;
    const v = Number(value); if (Number.isNaN(v)) return null;
    const b = q.bands;
    if (q.direction === 'lower_better') { for (let i = 0; i < 4; i++) if (v > b[i]) return i + 1; return 5; }
    for (let i = 0; i < 4; i++) if (v < b[i]) return i + 1; return 5;
  }

  function scoreQuestion(q, resp, mode) {
    resp = resp || {};
    const out = { id: q.id, dim: q.dim, kind: q.kind, na: !!resp.na, claimed: null, evidence_backed: null, enforced: null, findings: [] };
    if (out.na) return out;
    if (q.kind === 'metric') { const l = metricLevel(q, resp.value); Object.assign(out, { claimed: l, evidence_backed: l, enforced: l, value: resp.value }); return out; }
    let lvl = resp.level;
    if (lvl === null || lvl === undefined || lvl === '') return out;
    lvl = Math.max(1, Math.min(5, parseInt(lvl, 10)));
    const strengths = (resp.evidence || []).filter((e) => String(e.ref || '').trim()).map((e) => { const t = FW.evidence_types.find((x) => x.id === e.type); return t ? t.strength : 0; });
    const strong = strengths.filter((s) => s >= 1), operating = strengths.filter((s) => s >= 2);
    let cap = 5, rule = null, why = null;
    if (lvl >= 3 && !strong.length) { cap = 2; rule = 'ENF-01'; why = 'Level 3+ claimed with no evidence beyond verbal attestation.'; }
    else if (lvl >= 4 && !operating.length) { cap = 3; rule = 'ENF-02'; why = 'Level 4+ claimed without a system metric or platform inspection.'; }
    else if (lvl === 5 && strong.length < 2) { cap = 4; rule = 'ENF-02'; why = 'Level 5 needs two independent pieces of evidence.'; }
    const backed = Math.min(lvl, cap), enforced = mode === 'validated' ? backed : lvl;
    Object.assign(out, { claimed: lvl, evidence_backed: backed, enforced });
    if (rule) out.findings.push({ rule, severity: mode === 'validated' ? 'cap' : 'warning', scope: 'question', ref: q.id, dim: q.dim,
      message: `${q.id}: ${why} ` + (mode === 'validated' ? `Capped ${lvl} to ${backed}.` : `Would cap ${lvl} to ${backed} when validated.`) });
    if (lvl >= 4 && resp.confidence === 'low') out.findings.push({ rule: 'ENF-12', severity: 'warning', scope: 'question', ref: q.id, dim: q.dim,
      message: `${q.id}: level ${lvl} recorded with low confidence. Validate before relying on it.` });
    return out;
  }

  function dimensionBase(dim, qs) {
    const all = QS.filter((q) => q.dim === dim), att = all.filter((q) => q.kind === 'attested'), met = all.filter((q) => q.kind === 'metric');
    const applicable = att.filter((q) => !qs[q.id].na), answered = applicable.filter((q) => qs[q.id].claimed !== null);
    const W = FW.weights;
    const res = { id: dim, total: att.length, applicable: applicable.length, answered: answered.length,
      coverage: applicable.length ? answered.length / applicable.length : 0,
      claimed: wmean(answered.map((q) => [qs[q.id].claimed, W[q.weight]])),
      evidence_backed: wmean(answered.map((q) => [qs[q.id].evidence_backed, W[q.weight]])),
      enforced: wmean(answered.map((q) => [qs[q.id].enforced, W[q.weight]])), metric_level: null, metrics: [], caps: [] };
    const mlv = met.filter((q) => qs[q.id].claimed !== null).map((q) => [qs[q.id].claimed, q.id]);
    if (mlv.length) { res.metric_level = mlv.reduce((s, x) => s + x[0], 0) / mlv.length; res.metrics = mlv.map((x) => ({ id: x[1], level: x[0] })); }
    res.provisional = res.answered === 0 || res.coverage < 0.5;
    res.critical_floor = answered.filter((q) => q.weight === 'Critical' && qs[q.id].enforced === 1).map((q) => q.id);
    res.critical_floor_backed = answered.filter((q) => q.weight === 'Critical' && qs[q.id].evidence_backed === 1).map((q) => q.id);
    return res;
  }
  function cap(dr, key, limit, rule, reason, findings, severity, record) {
    const cur = dr[key];
    if (cur === null || cur <= limit + 1e-9) return;
    dr[key] = limit;
    if (record) { dr.caps.push({ rule, from: r2(cur), to: r2(limit), reason });
      findings.push({ rule, severity: severity || 'cap', scope: 'dimension', ref: dr.id, dim: dr.id, message: `${dr.id} capped ${f1(cur)} to ${f1(limit)}: ${reason}` }); }
  }
  function scoreDimensions(qs, findings) {
    const dims = {}; FW.dimensions.forEach((d) => { dims[d.id] = dimensionBase(d.id, qs); });
    ['enforced', 'evidence_backed'].forEach((key) => {
      const record = key === 'enforced';
      Object.values(dims).forEach((dr) => {
        const floor = key === 'enforced' ? dr.critical_floor : dr.critical_floor_backed;
        if (floor.length) cap(dr, key, 2.0, 'ENF-04', `critical question(s) ${floor.join(', ')} at level 1.`, findings, 'blocker', record);
        if (dr.metric_level !== null) cap(dr, key, dr.metric_level + 1.0, 'ENF-03', `measured metrics imply level ${f1(dr.metric_level)}; attested score may not exceed it by more than 1.`, findings, 'cap', record);
      });
      FW.dependencies.forEach((dep) => {
        const dr = dims[dep.dim];
        const ups = dep.upon.filter((u) => dims[u][key] !== null && !dims[u].provisional).map((u) => dims[u][key]);
        if (ups.length !== dep.upon.length) return;
        cap(dr, key, Math.min(...ups) + dep.slack, 'ENF-05', `depends on ${dep.upon.join(', ')}. ${dep.why}`, findings, 'cap', record);
      });
    });
    Object.values(dims).forEach((dr) => { if (dr.provisional && dr.answered) findings.push({ rule: 'ENF-11', severity: 'warning', scope: 'dimension', ref: dr.id, dim: dr.id,
      message: `${dr.id} is provisional: ${dr.answered} of ${dr.applicable} applicable questions answered. Excluded from tier scores.` }); });
    return dims;
  }
  function scoreTiers(dims, findings) {
    const scored = (ids, key) => { const o = {}; ids.forEach((i) => { if (dims[i][key || 'enforced'] !== null && !dims[i].provisional) o[i] = dims[i][key || 'enforced']; }); return o; };
    const rIds = ['R1', 'R2', 'R3', 'R4', 'R5', 'R6'];
    const t1 = scored(rIds), t1b = scored(rIds, 'evidence_backed');
    const vals = Object.values(t1), ceiling = vals.length ? Math.min(...vals) : null;
    const binding = Object.keys(t1).filter((k) => ceiling !== null && t1[k] - ceiling < 0.05).sort();
    const missing = rIds.filter((i) => !(i in t1));
    const tiers = { T1: { ceiling: r2(ceiling), ceiling_evidence_backed: r2(Object.values(t1b).length ? Math.min(...Object.values(t1b)) : null), binding,
      mean: r2(vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null), r7: r2(dims.R7.enforced), missing, complete: !missing.length } };
    if (ceiling !== null) findings.push({ rule: 'ENF-06', severity: 'info', scope: 'tier', ref: 'T1',
      message: `Readiness ceiling ${f1(ceiling)}, bound by ${binding.join(', ')}. No AI outcome can exceed this until ${binding.join(', ')} improve.` + (missing.length ? ` Not yet assessed: ${missing.join(', ')}.` : '') });
    const d = scored(['D1', 'D2', 'D3', 'D4', 'D5', 'D6']);
    let t2 = null;
    if (Object.keys(d).length) { const ws = Object.keys(d).reduce((s, k) => s + DIM[k].weight, 0); t2 = Object.keys(d).reduce((s, k) => s + d[k] * DIM[k].weight, 0) / ws; }
    const fly = t2 === null ? null : (t2 >= 4 && ceiling !== null && ceiling >= 4 ? 'Compounding' : t2 >= 3 ? 'Active' : t2 >= 2 ? 'Emerging' : 'Not Engaged');
    tiers.T2 = { score: r2(t2), flywheel: fly, scored: Object.keys(d).sort() };
    const p = scored(['P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7']);
    const crit = Object.keys(p).filter((k) => p[k] < 1.5).sort();
    const pv = Object.values(p);
    tiers.T3 = { score: r2(pv.length ? pv.reduce((a, b) => a + b, 0) / pv.length : null), critical: crit, scored: Object.keys(p).sort() };
    crit.forEach((c) => findings.push({ rule: 'ENF-07', severity: 'blocker', scope: 'tier', ref: c, dim: c, message: `Execution principle ${c} (${DIM[c].name}) is critical (below 1.5). Wave 0 must address it.` }));
    return tiers;
  }
  function scoreVelocity(qs) {
    const out = {};
    FW.velocity.forEach((v) => {
      const mets = QS.filter((q) => q.kind === 'metric' && q.velocity === v.id && qs[q.id].claimed !== null).map((q) => qs[q.id].claimed);
      if (mets.length) { out[v.id] = { level: r2(mets.reduce((a, b) => a + b, 0) / mets.length), source: 'measured', n: mets.length }; return; }
      const att = QS.filter((q) => q.kind === 'attested' && q.velocity === v.id && qs[q.id].enforced !== null).map((q) => qs[q.id].enforced);
      out[v.id] = att.length ? { level: r2(att.reduce((a, b) => a + b, 0) / att.length), source: 'attested', n: att.length } : { level: null, source: null, n: 0 };
    });
    return out;
  }
  function scoreUseCases(a, dims, findings) {
    return (a.use_cases || []).map((uc) => {
      const job = uc.job;
      if (!FW.jobs[job]) return Object.assign({}, uc, { status: 'Unscoped', readiness: null, blocking: [], gate_missing: [], reason: 'Choose an AI job type (Inference, Training or Agent) to evaluate readiness.' });
      const path = FW.jobs[job].path, vals = {}; path.forEach((d) => { vals[d] = dims[d].enforced; });
      const unknown = path.filter((d) => vals[d] === null);
      const gate = (FW.job_lever_gates[job] || []).filter((l) => !ENFORCED.includes(leverState(a, l).status));
      if (unknown.length) return Object.assign({}, uc, { status: 'Insufficient data', readiness: null, path, blocking: unknown, gate_missing: gate, reason: `Assess ${unknown.join(', ')} to evaluate this use case.` });
      const readiness = Math.min(...path.map((d) => vals[d]));
      const blocking = path.filter((d) => vals[d] < 3).sort((x, y) => vals[x] - vals[y]);
      const status = readiness < 2 || gate.length ? 'Blocked' : readiness < 3 ? 'Conditional' : 'Go';
      const reason = [];
      if (blocking.length) reason.push('Below 3 on ' + blocking.map((d) => `${d} (${f1(vals[d])})`).join(', ') + '.');
      if (gate.length) reason.push(`${job} gate: lever(s) ${gate.join(', ')} not yet Enforced (ENF-08).`);
      const ps = {}; path.forEach((d) => { ps[d] = r2(vals[d]); });
      if (status !== 'Go') findings.push({ rule: 'ENF-08', severity: status === 'Blocked' ? 'blocker' : 'warning', scope: 'use_case', ref: uc.id || uc.name,
        message: `Use case '${uc.name || uc.id}' (${job}) is ${status}. ${reason.join(' ')}` });
      return Object.assign({}, uc, { status, readiness: r2(readiness), path, path_scores: ps, blocking, gate_missing: gate, reason: reason.join(' ') || 'All critical-path dimensions at 3 or above.' });
    });
  }
  function current(dims) { const o = {}; Object.keys(dims).forEach((k) => { o[k] = dims[k].enforced !== null ? dims[k].enforced : 1.0; }); return o; }
  function importance(dims, tiers, ucs) {
    const imp = {}, binding = new Set(tiers.T1.binding), crit = new Set(tiers.T3.critical);
    FW.dimensions.forEach((d) => {
      let i = 1.0;
      if (binding.has(d.id)) i += 1.5;
      i += 0.5 * ucs.filter((u) => (u.blocking || []).includes(d.id)).length;
      if (d.tier === 'T2') i += d.weight * 2;
      if (crit.has(d.id)) i += 1.0;
      if (dims[d.id].enforced === null) i *= 0.5;
      imp[d.id] = i;
    });
    return imp;
  }
  function prioritise(a, dims, tiers, ucs) {
    const target = Number(a.target_level || 3.0), cur = current(dims), imp = importance(dims, tiers, ucs);
    const gateJobs = new Set(ucs.filter((u) => (u.gate_missing || []).length).map((u) => u.job));
    const gateLevers = new Set(); gateJobs.forEach((j) => (FW.job_lever_gates[j] || []).forEach((l) => gateLevers.add(l)));
    const crit = new Set(tiers.T3.critical), binding = new Set(tiers.T1.binding);
    const pr = {};
    FW.levers.forEach((lv) => {
      const st = leverState(a, lv.id).status;
      const tg = Object.keys(lv.targets);
      const applicable = tg.some((t) => cur[t] < lv.trigger_below);
      let v = 0; const reasons = [];
      tg.forEach((t) => {
        const lift = lv.targets[t], gap = Math.max(0, target - cur[t]), head = Math.max(0, 5 - cur[t]), toT = Math.min(lift, gap);
        v += imp[t] * toT + 0.2 * Math.min(lift, head);
        if (toT > 0) reasons.push(`lifts ${t} toward target (${f1(cur[t])} to ${Math.round(target)})`);
      });
      if (gateLevers.has(lv.id)) { v += 2.0; reasons.push('required by a use-case gate (ENF-08)'); }
      if (tg.some((t) => crit.has(t))) reasons.push('addresses a critical execution principle (ENF-07)');
      if (tg.some((t) => binding.has(t))) reasons.push("moves the readiness ceiling's binding constraint (ENF-06)");
      pr[lv.id] = { id: lv.id, status: st, applicable: applicable || gateLevers.has(lv.id), own_priority: v / EFFORT_COST[lv.effort], reasons };
    });
    let eff = {}; Object.keys(pr).forEach((k) => { eff[k] = pr[k].own_priority; });
    for (let it = 0; it < 3; it++) {
      const nxt = {}; Object.keys(pr).forEach((k) => { nxt[k] = pr[k].own_priority; });
      FW.levers.forEach((lv) => {
        if (!pr[lv.id].applicable || ENFORCED.concat(['Retired']).includes(pr[lv.id].status)) return;
        lv.requires.forEach((r) => { if (!ENFORCED.includes(pr[r].status)) nxt[r] += 0.5 * eff[lv.id]; });
      });
      eff = nxt;
    }
    Object.keys(pr).forEach((k) => { const p = pr[k]; p.priority = r2(eff[k]); p.rank_score = eff[k];
      if (eff[k] - p.own_priority > 0.05) { p.reasons.push('prerequisite that unblocks other high-value levers'); p.applicable = true; } });
    return pr;
  }
  function planWaves(a, dims, tiers, pr, findings) {
    const capN = parseInt(a.wave_capacity || 6, 10), proj = current(dims);
    const done = new Set(FW.levers.filter((l) => ENFORCED.includes(leverState(a, l.id).status)).map((l) => l.id));
    const retired = new Set(FW.levers.filter((l) => leverState(a, l.id).status === 'Retired').map((l) => l.id));
    const planned = {}, waves = [];
    const pending = Object.keys(pr).filter((l) => pr[l].applicable && !done.has(l) && !retired.has(l));
    const eligible = (lid, avail, projection) => { const lv = LEVER[lid];
      const missL = lv.requires.filter((r) => !avail.has(r)); const missD = {};
      Object.keys(lv.preconditions).forEach((d) => { if (projection[d] + 1e-9 < lv.preconditions[d]) missD[d] = lv.preconditions[d]; });
      return [missL, missD]; };
    const blocked = (e) => e[0].length || Object.keys(e[1]).length;
    FW.waves.forEach((w) => {
      const wid = w.id;
      const avail = new Set([...done, ...Object.keys(planned).filter((k) => planned[k] < wid)]);
      let chosen = []; const violations = [];
      pending.forEach((lid) => { const st = leverState(a, lid);
        if (st.status === 'Committed' && String(st.wave) === String(wid) && !(lid in planned)) {
          const e = eligible(lid, avail, proj);
          if (blocked(e)) violations.push({ rule: 'ENF-09', lever: lid, message: `${lid} committed to ${w.name} before its prerequisites: ` + e[0].concat(Object.keys(e[1]).map((d) => `${d}>=${e[1][d]}`)).join(', ') });
          chosen.push(lid);
        } });
      let cands = pending.filter((lid) => { const st = leverState(a, lid);
        return !(lid in planned) && !chosen.includes(lid) && !(st.status === 'Committed' && ![undefined, null, '', wid, String(wid)].includes(st.wave)); });
      cands = cands.filter((lid) => !blocked(eligible(lid, avail, proj)));
      cands.sort((x, y) => pr[y].rank_score - pr[x].rank_score);
      for (const lid of cands) { if (chosen.length >= capN) break; chosen.push(lid); }
      if (wid === 0) tiers.T3.critical.forEach((c) => {
        if (!chosen.some((l) => c in LEVER[l].targets)) {
          const fix = cands.find((l) => c in LEVER[l].targets && !chosen.includes(l));
          if (fix) { if (chosen.length >= capN) chosen.pop(); chosen.push(fix); }
          else violations.push({ rule: 'ENF-07', message: `No eligible lever for critical principle ${c} in Wave 0.` });
        } });
      if (chosen.length && !chosen.some((l) => LEVER[l].ttv_days <= 90)) {
        const quick = cands.find((l) => LEVER[l].ttv_days <= 90 && !chosen.includes(l));
        if (quick) chosen[chosen.length - 1] = quick; else violations.push({ rule: 'ENF-10', message: `${w.name} has no lever with time-to-value of 90 days or less.` });
      }
      if (chosen.length > capN) violations.push({ rule: 'ENF-10', message: `${w.name} exceeds capacity (${chosen.length} > ${capN}).` });
      chosen.forEach((lid) => { planned[lid] = wid;
        Object.entries(LEVER[lid].targets).forEach(([t, lift]) => { proj[t] = Math.min(5, proj[t] + lift * (5 - proj[t]) / 4); }); });
      const pj = {}; Object.keys(proj).forEach((k) => { pj[k] = r2(proj[k]); });
      waves.push(Object.assign({}, w, { levers: chosen, violations, projected: pj }));
      violations.forEach((v) => findings.push({ rule: v.rule, severity: 'warning', scope: 'roadmap', ref: w.name, message: v.message }));
    });
    const finalAvail = new Set([...done, ...Object.keys(planned)]);
    const backlog = pending.filter((l) => !(l in planned)).map((l) => { const e = eligible(l, finalAvail, proj); return { id: l, blocked_by_levers: e[0], blocked_by_dims: e[1] }; });
    return [waves, backlog, planned];
  }
  function planFindings(a, dims, findings, today) {
    const status = {};
    FW.levers.forEach((lv) => {
      const lid = lv.id, st = leverState(a, lid);
      const info = { status: st.status, stale: false, exception_active: exceptionActive(st, today), issues: [] };
      if (st.status === 'Verified') { const va = parseDate(st.verified_at);
        if (!va || daysBetween(va, today) > VERIFY_DAYS) { info.stale = true; info.issues.push('verification older than 90 days');
          findings.push({ rule: 'ENF-13', severity: 'warning', scope: 'lever', ref: lid, message: `${lid} ${lv.name}: verification is stale. Re-measure the KPI.` }); } }
      if (ENFORCED.includes(st.status)) {
        const reg = lv.requires.filter((r) => !ENFORCED.includes(leverState(a, r).status));
        if (reg.length) { info.issues.push('prerequisite regressed: ' + reg.join(', '));
          findings.push({ rule: 'ENF-09', severity: 'warning', scope: 'lever', ref: lid, message: `${lid} is ${st.status} but prerequisite(s) ${reg.join(', ')} are no longer enforced.` }); }
        const unmet = Object.keys(lv.preconditions).filter((d) => (dims[d].enforced || 0) + 1e-9 < lv.preconditions[d]);
        if (unmet.length && !info.exception_active) {
          const ex = st.exception && Object.keys(st.exception).length;
          const msg = (ex ? 'exception expired' : 'preconditions no longer met') + ': ' + unmet.map((d) => `${d} >= ${lv.preconditions[d]}`).join(', ');
          info.issues.push(msg);
          findings.push({ rule: ex ? 'ENF-13' : 'ENF-09', severity: ex ? 'blocker' : 'warning', scope: 'lever', ref: lid, message: `${lid} ${lv.name}: ${msg}.` });
        }
        if (lv.mode === 'directive' && !lv.pair_with.some((p) => ENFORCED.includes(leverState(a, p).status))) info.issues.push('directive lever without an enforced pair');
      }
      status[lid] = info;
    });
    return status;
  }

  function evaluate(a, today) {
    today = today || isoToday();
    const mode = a.mode || 'attested', findings = [], responses = a.responses || {}, qs = {};
    QS.forEach((q) => { qs[q.id] = scoreQuestion(q, responses[q.id], mode); });
    Object.values(qs).forEach((x) => { findings.push(...x.findings); delete x.findings; });
    const dims = scoreDimensions(qs, findings), tiers = scoreTiers(dims, findings), velocity = scoreVelocity(qs);
    const ucs = scoreUseCases(a, dims, findings), pr = prioritise(a, dims, tiers, ucs), plan = planFindings(a, dims, findings, today);
    const [waves, backlog, planned] = planWaves(a, dims, tiers, pr, findings);
    Object.keys(pr).forEach((l) => { pr[l].wave = l in planned ? planned[l] : null; });
    const att = QS.filter((q) => q.kind === 'attested'), met = QS.filter((q) => q.kind === 'metric');
    const inflation = Object.keys(dims).filter((d) => dims[d].claimed !== null && dims[d].enforced !== null && dims[d].claimed - dims[d].enforced >= 0.5);
    findings.sort((x, y) => (SEV[x.severity] - SEV[y.severity]) || (x.rule < y.rule ? -1 : x.rule > y.rule ? 1 : 0));
    Object.values(dims).forEach((d) => { ['claimed', 'evidence_backed', 'enforced', 'metric_level', 'coverage'].forEach((k) => { d[k] = r2(d[k]); }); delete d.critical_floor_backed; });
    const counts = {}; Object.keys(SEV).forEach((s) => { counts[s] = findings.filter((f) => f.severity === s).length; });
    return { evaluated_at: nowZ(), framework_version: FW.version, mode,
      progress: { attested: att.filter((q) => qs[q.id].claimed !== null || qs[q.id].na).length, attested_total: att.length,
        metrics: met.filter((q) => qs[q.id].claimed !== null).length, metrics_total: met.length },
      questions: qs, dimensions: dims, tiers, velocity, use_cases: ucs, levers: { priorities: pr, waves, backlog, plan }, inflation, findings, counts };
  }

  function kpiMet(dir, c, t) { const cc = Number(c), tt = Number(t); if (c === '' || t === '' || c == null || t == null || Number.isNaN(cc) || Number.isNaN(tt)) return false; return dir === 'lower_better' ? cc <= tt : cc >= tt; }
  function transition(a0, lid, to, fields, actor, today) {
    today = today || isoToday(); fields = fields || {};
    const lv = LEVER[lid]; if (!lv) return [a0, [`Unknown lever ${lid}.`]];
    const a = clone(a0); a.levers = a.levers || {};
    const st = clone(leverState(a, lid)), frm = st.status;
    if (!(FW.lever_transitions[frm] || []).includes(to)) return [a0, [`${frm} to ${to} is not an allowed transition. Allowed: ${(FW.lever_transitions[frm] || []).join(', ')}.`]];
    ['owner', 'wave', 'kpi_baseline', 'kpi_target', 'kpi_current', 'notes'].forEach((k) => { if (k in fields && fields[k] !== null && fields[k] !== undefined) st[k] = fields[k]; });
    if ('enforcement_evidence' in fields) st.enforcement_evidence = (fields.enforcement_evidence || []).filter((e) => String(e).trim());
    if (fields.exception) st.exception = fields.exception;
    const reason = String(fields.reason || '').trim(), errors = [];
    const S = FW.lever_statuses, backward = to !== 'Retired' && S.indexOf(to) < S.indexOf(frm);
    if (to === 'Committed' && !backward) {
      if (!String(st.owner || '').trim()) errors.push('An accountable owner is required to commit.');
      if (!['0', '1', '2'].includes(String(st.wave === undefined ? '' : st.wave))) errors.push('Choose a wave (0, 1 or 2).');
      if (st.kpi_target === undefined || st.kpi_target === null || st.kpi_target === '') errors.push(`Set a KPI target for '${lv.kpi.name}' (${lv.kpi.unit}).`);
    }
    if (to === 'Enforced' && !backward) {
      if (!(st.enforcement_evidence || []).length) errors.push('Record at least one piece of enforcement evidence, for example: ' + lv.evidence.join('; ') + '.');
      if (st.kpi_baseline === undefined || st.kpi_baseline === null || st.kpi_baseline === '') errors.push('Record the KPI baseline before enforcement, so the effect can be verified.');
      const reqs = lv.requires.filter((r) => !ENFORCED.includes(leverState(a, r).status));
      if (reqs.length) errors.push('Prerequisite lever(s) not yet Enforced: ' + reqs.map((r) => `${r} ${LEVER[r].name}`).join(', ') + '.');
      if (lv.mode === 'directive' && !lv.pair_with.some((p) => ENFORCED.includes(leverState(a, p).status)))
        errors.push('Directive lever: at least one paired detective/preventive lever must be Enforced first (' + lv.pair_with.join(', ') + '). A standard without a mechanism is a suggestion (A3).');
      if (Object.keys(lv.preconditions).length) {
        const res = evaluate(a, today);
        const unmet = Object.keys(lv.preconditions).filter((d) => (res.dimensions[d].enforced || 0) + 1e-9 < lv.preconditions[d]);
        if (unmet.length) {
          const ex = st.exception || null, exp = ex ? parseDate(ex.expires) : null;
          if (ex) {
            if (!(ex.approver && ex.justification)) errors.push('Exception needs an approver and a justification.');
            else if (!exp || exp < today) errors.push('Exception expiry must be a future date.');
            else if (exp > addDays(today, MAX_EXCEPTION_DAYS)) errors.push(`Exception expiry may be at most ${MAX_EXCEPTION_DAYS} days away.`);
          } else errors.push('Precondition level(s) not met: ' + unmet.map((d) => `${d} is ${res.dimensions[d].enforced || 'unassessed'}, needs ${lv.preconditions[d]}`).join(', ') + '. Raise them first or record a time-bound exception.');
        }
      }
    }
    if (to === 'Verified') {
      if (st.kpi_current === undefined || st.kpi_current === null || st.kpi_current === '') errors.push('Record the current KPI value to verify.');
      else if (!kpiMet(lv.kpi.direction, st.kpi_current, st.kpi_target)) errors.push(`KPI not at target: current ${st.kpi_current} vs target ${st.kpi_target} (${lv.kpi.direction === 'lower_better' ? 'lower' : 'higher'} is better).`);
      st.verified_at = today;
    }
    if ((to === 'Retired' || backward) && !reason) errors.push('A reason is required to retire a lever or move it backwards.');
    if (errors.length) return [a0, errors];
    st.status = to; st.history = st.history || []; st.history.push({ ts: nowZ(), actor: actor || 'you', from: frm, to, reason });
    a.levers[lid] = st;
    return [a, []];
  }
  function protectStatus(incoming, stored) {
    const out = clone(incoming); out.levers = out.levers || {};
    const sl = (stored || {}).levers || {};
    new Set([...Object.keys(out.levers), ...Object.keys(sl)]).forEach((lid) => {
      const prev = sl[lid] || {}, cur = out.levers[lid] = out.levers[lid] || {};
      cur.status = prev.status || 'Proposed'; cur.history = prev.history || [];
      if ('verified_at' in prev) cur.verified_at = prev.verified_at; else delete cur.verified_at;
    });
    return out;
  }

  root.DPEngine = { init, evaluate, transition, protectStatus, newAssessment, metricLevel, leverState };
  if (typeof module !== 'undefined') module.exports = root.DPEngine;
})(typeof window !== 'undefined' ? window : globalThis);
