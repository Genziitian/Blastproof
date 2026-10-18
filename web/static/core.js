"use strict";
/* Blast Radius: shared client code for the landing page and the war room.
   Everything shown is read from FalkorDB through the JSON API (web/app.py).
   This file turns an incident's stored records into the story the pages tell:
   steps, checks, captions, takeovers and trust. Nothing here is scripted. */
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) =>
  ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const fmt = (x, d = 2) => (x === null || x === undefined || Number.isNaN(+x)) ? "—" : Number(x).toFixed(d);
const plural = (n, w, p) => `${n} ${n === 1 ? w : (p || w + "s")}`;
const secs = (ms) => `+${fmt((ms || 0) / 1000, 1)} s`;
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

const S = {
  settings: null, state: null, inc: null, map: null, memory: null, db: null,
  tab: "live", rail: "story", selected: null, follow: true, open: {},
  captions: true, seen: new Set(), dbDown: false, dbSince: 0, mapNode: null, armStep: 3,
};

async function api(path, body) {
  const opt = body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body)};
  let r;
  try { r = await fetch(path, opt); } catch (e) { window.setDbDown?.(true); throw e; }
  const data = await r.json().catch(() => ({}));
  if (data.db_down) { window.setDbDown?.(true); throw new Error(data.detail); }
  if (!r.ok) { window.toast?.(esc(data.detail || r.statusText)); throw new Error(data.detail || r.statusText); }
  window.setDbDown?.(false);
  return data;
}
const label = (fam) => (S.settings?.labels || {})[fam] || fam || "—";
const once = (key) => { if (S.seen.has(key)) return false; S.seen.add(key); return S.booted && !REDUCED; };

/* ------------------------------------------------------------ plain English */
// The investigator's own measure rules (memory/playbook.py: Check.measure_of), so
// the checks can be shown passing one by one before the decision is written.
function measureOf(measure, obs, target) {
  if (measure.startsWith("last:")) { const s = (obs || {})[measure.slice(5)]; return s && s.length ? s[s.length - 1] : null; }
  if (measure === "deploys") return (obs || []).filter((c) => c.kind === "deploy").length;
  if (measure.startsWith("healthy:")) { const d = (obs || []).find((x) => x.dep === target); return d ? d.healthy : null; }
  return null;
}
const OPS = {"==": (a, b) => a === b, ">=": (a, b) => a >= b, "<=": (a, b) => a <= b,
  "<": (a, b) => a < b, ">": (a, b) => a > b, "!=": (a, b) => a !== b};
function humanCheck(tool, arg, measure, op, value, target) {
  const m = measure.replace("$target", target);
  if (measure === "deploys") return op === "==" && value === 0 ? `No deploy on ${arg} in the last 2 h` : `${arg} was deployed in the last 2 h`;
  if (measure.startsWith("healthy:")) return value === false ? `${arg} sees ${target} as unhealthy` : `${arg} sees ${target} as healthy`;
  if (m.endsWith("db_connections_pct")) return `${arg} uses ${op === ">=" ? "≥" : op} ${value}% of its connections`;
  if (m.endsWith("error_rate_pct")) return `${arg} error rate ${op === ">=" ? "≥" : op} ${value}%`;
  if (m.endsWith("cache_hit_rate_pct")) return `${arg} cache hit rate ${op === "<" ? "below" : op} ${value}%`;
  return `${tool}(${arg}): ${m} ${op} ${value}`;
}
function humanObserved(measure, o) {
  if (o === null || o === undefined) return "no reading";
  if (measure === "deploys") return plural(o, "deploy");
  if (measure.startsWith("healthy:")) return o === false ? "unhealthy" : o === true ? "healthy" : String(o);
  if (measure.endsWith("_pct")) return `${o}%`;
  return typeof o === "object" ? JSON.stringify(o) : String(o);
}
const parseVal = (v) => v === "False" ? false : v === "True" ? true : (v !== "" && !Number.isNaN(+v)) ? +v : v;
// "inspect_recent_changes(payments-gw): deploys == 0"
function parseDesc(desc) {
  const m = /^(\w+)\(([^)]*)\): (\S+) (==|>=|<=|!=|<|>) (.+)$/.exec(desc || "");
  return m ? {tool: m[1], arg: m[2], measure: m[3], op: m[4], value: parseVal(m[5])} : null;
}
const raw = (c) => `${c.tool}(${c.arg}): ${c.measure} ${c.op} ${c.value === false ? "False" : c.value === true ? "True" : c.value}`;
function humanTool(cp) {
  const a = cp.args || {}; const r = cp.result;
  switch (cp.tool) {
    case "find_upstream_candidates": return [`Listed what the alerting services depend on`, Array.isArray(r) ? plural(r.length, "candidate") : ""];
    case "inspect_recent_changes": { const n = (r || []).filter((c) => c.kind === "deploy").length; return [`Recent changes on ${a.service}`, plural(n, "deploy")]; }
    case "check_dependency_health": { const bad = (r || []).filter((d) => d.healthy === false).map((d) => d.dep);
      return [`Health of what ${a.service} depends on`, bad.length ? `unhealthy: ${bad.join(", ")}` : "all healthy"]; }
    case "inspect_metrics": { const vals = Object.entries(r || {}).filter(([k, v]) => Array.isArray(v) && k !== "times_ms")
        .map(([k, v]) => `${k.replace("_pct", "")} ${v[v.length - 1]}${k.endsWith("_pct") ? "%" : ""}`);
      return [`Metrics for ${a.node}`, vals.join(", ")]; }
    case "inspect_logs": return [`Logs from ${a.node}`, Array.isArray(r) ? plural(r.length, "line") : ""];
    case "blast_radius": return [`Blast radius of ${a.node}`, Array.isArray(r) ? plural(r.length, "service") : ""];
    case "who_to_page": return [`Who is on call for ${a.node}`, r?.person || r?.handle || ""];
    default: return [cp.tool, ""];
  }
}
const shortTool = (cp) => humanTool(cp)[0];

/* ------------------------------------------------------------ the story */
// Turns one incident (head, lens, tasks, checkpoints, actions, messages) into
// what the page shows: the stepper, the caption, node states and recall paths.
function candidatesOf(x) {
  const pbs = Object.fromEntries((S.memory?.playbooks || []).map((p) => [p.id, p]));
  if (x.lens.length) {
    return x.lens.map((l) => {
      const rows = l.checks.map((c) => { const p = parseDesc(c.description) || {tool: "", arg: "", measure: "", op: "", value: ""};
        return {...p, text: p.tool ? humanCheck(p.tool, p.arg, p.measure, p.op, p.value, l.target) : c.description,
          raw: c.description, observed: c.observed, obsText: humanObserved(p.measure, c.observed),
          state: c.passed ? "pass" : "fail", step: c.step_n, phase: c.phase}; });
      const pb = pbs[l.memory];
      const total = pb ? pb.preconditions.length + pb.steps.length : rows.length;
      return {key: l.memory + ">" + l.target, memory: l.memory, signature: l.signature, target: l.target, path: l.path || [],
        hops: l.hops, score: l.score, viaKind: !(l.pinned_to || []).includes(l.target), pinned: l.pinned_to || [],
        learnedPath: l.learned_path || null, trust: l.trust_at_use, trustAfter: l.trust_after, verdict: l.verdict, learned: l.learned_from || [], status: l.status,
        rows, total, outcome: l.applied ? "holds" : "ruled", final: true};
    });
  }
  let active = false;
  return (x.recalling || []).map((r) => {
    const pb = pbs[r.memory_id];
    const path = r.path || [];
    const b = {alerting: path[0], caller: path.length >= 2 ? path[path.length - 2] : null, target: r.target};
    const bind = (v) => typeof v === "string" && v.startsWith("$") ? b[v.slice(1)] : v;
    const checks = pb ? [...pb.preconditions.map((c) => ({...c, phase: "precondition"})), ...pb.steps.map((c) => ({...c, phase: "step"}))] : [];
    const rows = []; let failed = false, waiting = false;
    for (const c of checks) {
      const args = Object.fromEntries(Object.entries(c.args).map(([k, v]) => [k, bind(v)]));
      const arg = Object.values(args)[0];
      const text = humanCheck(c.tool, arg, c.measure, c.op, c.value, r.target);
      const rr = raw({tool: c.tool, arg, measure: c.measure.replace("$target", r.target), op: c.op, value: c.value});
      if (failed || waiting) { rows.push({text, raw: rr, state: "wait", phase: c.phase, measure: c.measure}); continue; }
      const cp = x.checkpoints.find((k) => k.task.endsWith(":investigate") && k.tool === c.tool &&
        JSON.stringify(k.args) === JSON.stringify(args));
      if (!cp) { waiting = true; rows.push({text, raw: rr, state: "pend", phase: c.phase, measure: c.measure}); continue; }
      const o = measureOf(c.measure, cp.result, r.target);
      const ok = o !== null && OPS[c.op](o, c.value);
      rows.push({text, raw: rr, observed: o, obsText: humanObserved(c.measure, o), state: ok ? "pass" : "fail", step: cp.n, phase: c.phase, measure: c.measure});
      if (!ok) failed = true;
    }
    let outcome = failed ? "ruled" : waiting ? "checking" : "holds";
    if (outcome === "checking") {
      if (active) { outcome = "queued"; rows.forEach((q) => { if (q.state === "pend") q.state = "wait"; }); }
      active = true;
    }
    return {key: r.memory_id + ">" + r.target, memory: r.memory_id, signature: pb?.signature || r.memory_id, target: r.target, path,
      hops: r.hops, score: r.score, viaKind: !!r.via_kind, pinned: pb?.about || [], trust: r.trust, learned: pb?.learned_from || [],
      status: pb?.status, rows, total: checks.length, outcome, final: false};
  });
}

function storyOf(x) {
  const T = (k) => x.tasks.find((t) => t.type === k);
  const inv = T("investigate"), resp = T("respond"), learn = T("learn");
  const h = x.head, tl = x.timeline;
  const tOf = (pred) => { const e = tl.find(pred); return e ? secs(e.t_ms) : ""; };
  const lastOf = (pred) => { const e = [...tl].reverse().find(pred); return e ? secs(e.t_ms) : ""; };
  const alive = Object.fromEntries((S.state?.workers || []).map((w) => [w.name, w.alive]));
  const cands = candidatesOf(x);
  const invCps = x.checkpoints.filter((c) => c.task.endsWith(":investigate"));
  const claims = inv?.claimed_by || [];
  const takeover = claims.length > 1 ? {from: claims[claims.length - 2], to: claims[claims.length - 1], epoch: claims.length,
    step: (invCps.find((c) => c.epoch === claims.length) || {}).n || (invCps.length + 1)} : null;
  const held = x.tasks.find((t) => t.status === "leased");
  const deadHolder = held && alive[held.owner] === false ? held : null;
  const stuck = x.tasks.find((t) => t.status === "stuck");
  const pending = (S.state?.pending || []).find((p) => p.incident_key === h.key);
  const action = x.actions[0];
  const owner = (S.map?.org || []).find((t) => h.root && t.owns.includes(h.root));
  const newPb = (S.memory?.playbooks || []).find((p) => (p.learned_from || []).includes(h.id));
  const helped = cands.find((c) => c.verdict === "helped"), misled = cands.find((c) => c.verdict === "misled");
  const applied = cands.find((c) => c.outcome === "holds");
  const checking = cands.find((c) => c.outcome === "checking") || (!h.decision_id && cands.find((c) => c.outcome === "queued"));
  const allRuled = cands.length && cands.every((c) => c.outcome === "ruled");

  let phase = "queued";
  if (stuck) phase = "stuck";
  else if (h.status === "needs_review") phase = "rejected";
  else if (learn?.status === "done") phase = "learned";
  else if (h.verdict) phase = "confirmed";
  else if (action) phase = pending ? "review" : "paged";
  else if (h.decision_id) phase = "diagnosed";
  else if (claims.length) phase = cands.length ? (allRuled ? "investigating" : "checking") : "investigating";

  const steps = [];
  const st = (state, title, o = {}) => steps.push({state, title, ...o});
  // 1 alerts
  st("done", `Alerts on ${plural(h.alerting.length, "service")}`, {time: secs(0), id: "alerts",
    kv: h.alert_texts.map((t) => { const i = t.indexOf(": "); return [t.slice(0, i), t.slice(i + 2)]; })});
  // 2 recall
  if (!claims.length) st("current", "Recalling playbooks from memory", {id: "recall"});
  // One playbook can match twice (pinned here, and same kind elsewhere): say both numbers.
  else if (cands.length) st("done", `Recalled ${plural(cands.length, "match", "matches")} of ${plural(new Set(cands.map((c) => c.memory || c.signature)).size, "playbook")} from memory`, {time: tOf((e) => e.kind === "claim" && e.task === "investigate"), id: "recall",
    kv: cands.map((c) => [`${c.signature}`, `${c.target} · ${plural(c.hops, "hop")} · ${c.viaKind ? "same kind of datastore" : "pinned here"} · trust ${fmt(c.trust)}`])});
  else st("done", "Nothing in memory near these alerts", {time: tOf((e) => e.kind === "claim" && e.task === "investigate"), id: "recall",
    kv: [["what happens", "first time here: investigate step by step; if confirmed, it becomes a playbook"]]});
  // 3 check / investigate
  const toNote = takeover ? {noteTag: `e${takeover.epoch - 1} → e${takeover.epoch}`, note: `${takeover.to} took over at step ${takeover.step}, not from scratch`} : {};
  if (!claims.length) st("pending", "Check against live evidence");
  else if (cands.length) {
    let title, state = "done";
    if (h.decision_id || phase === "investigating") {
      if (applied) title = `Checked ${applied.target}: ${applied.rows.filter((r) => r.state === "pass").length} of ${applied.total} hold`;
      else { title = allRuled ? `Ruled out ${cands.length === 1 ? "the recalled playbook" : "all " + cands.length + " matches"}: the evidence didn't fit` : "Checked against live evidence"; state = "ruled"; }
      if (!applied && phase === "investigating") { title = title + ", investigating"; state = "current"; }
    } else if (checking) { title = `Checking ${checking.signature} on ${checking.target} against live evidence`; state = "current"; }
    else { title = "Checking against live evidence"; state = "current"; }
    st(state, title, {time: lastOf((e) => e.kind === "checkpoint"), id: "check", lens: cands, ...toNote,
      extra: (() => { const used = new Set(cands.flatMap((c) => c.rows.map((r) => r.step).filter(Boolean)));
        const rest = invCps.filter((c) => !used.has(c.n)); return !applied && rest.length ? rest : null; })()});
  } else {
    st(h.decision_id ? "done" : "current", h.decision_id ? `Investigated in ${plural(invCps.length, "step")}` : `Investigating step by step${invCps.length ? ` · step ${invCps.length}` : ""}`,
      {time: lastOf((e) => e.kind === "checkpoint"), id: "check", cps: invCps, ...toNote});
  }
  // 4 diagnosis
  if (h.decision_id) st("done", `Diagnosis: ${h.root}, ${label(h.family)}`, {time: tOf((e) => e.kind === "done" && e.task === "investigate"), id: "diag",
    kv: [["decided by", `${h.decided_by} · epoch e${h.decided_epoch}`],
      ["how", applied ? "from memory, after every check held (no model call)" : (S.settings.model === "rule-based" ? "step by step (rule-based planner)" : `step by step with ${S.settings.model}`)],
      ...(x.impact.length ? [["customers affected via", x.impact.map((r) => `${r.service} (${plural(r.hops, "hop")})`).join(", ")]] : []),
      ...(h.summary && !applied ? [["finding", h.summary]] : [])]});
  else st("pending", "Diagnosis");
  // 5 page
  if (action) {
    const n = x.actions.length;
    st("done", `${n === 1 ? "1" : n} ${action.channel}${n === 1 ? "" : "s"} sent to ${action.recipient}`, {time: tOf((e) => e.kind === "action"), id: "page",
      kv: [["why " + action.recipient, owner ? `on call for ${owner.team}, which owns ${h.root}` : `on call for the owner of ${h.root}`],
        ["how", (action.payload?.applied_preferences || []).length ? `${action.channel}, ${action.payload.applied_preferences[0]}` : `${action.channel} (team default)`],
        ["sent once", `intent ${action.key}`]], action});
  } else st(resp?.status === "leased" ? "current" : "pending", resp?.status === "leased" ? "Notifying the on-call engineer" : "Page on-call");
  // 6 human
  if (h.verdict) st(h.verdict === "confirmed" ? "ok" : "bad", `${h.verdict === "confirmed" ? "Confirmed" : "Rejected"} by ${h.verdict_by}`, {id: "human", time: "", chat: true});
  else st(pending ? "current" : "pending", pending ? `Waiting for ${action?.recipient || "the engineer"} to confirm` : "Engineer confirms", {id: "human", chat: !!action});
  // 7 learn
  if (learn?.status === "done") {
    const parts = [], kv = [];
    if (helped) { parts.push(`trust ${fmt(helped.trust)} → ${fmt(helped.trustAfter)}`); kv.push([helped.signature, `helped · trust ${fmt(helped.trust)} → ${fmt(helped.trustAfter)}`]); }
    if (misled) { parts.push(`trust lowered ${fmt(misled.trust)} → ${fmt(misled.trustAfter)}`); kv.push([misled.signature, `misled · trust ${fmt(misled.trust)} → ${fmt(misled.trustAfter)}${misled.status === "retired" ? " · retired" : ""}`]); }
    cands.filter((c) => c.verdict === "not_applicable").forEach((c) => kv.push([`${c.signature} on ${c.target}`, `not applicable · trust unchanged`]));
    if (newPb) { parts.push(`new playbook pinned to ${newPb.about.join(", ")}`); kv.push(["new playbook", `${newPb.signature} on ${newPb.about.join(", ")} · trust ${fmt(newPb.trust)}`]); }
    st(helped ? "ok" : misled ? "bad" : "done", parts.length ? `Learned: ${parts.join("; ")}` : "Learned: verdicts recorded", {time: tOf((e) => e.kind === "done" && e.task === "learn"), id: "learn", kv});
  } else st(learn?.status === "leased" ? "current" : "pending", "Learn");
  if (stuck) steps.splice(3, 0, {state: "bad", title: `Stuck: ${stuck.type} failed ${stuck.attempts} times, a human needs to look`, id: "stuck"});

  // caption: one plain sentence for what is happening now
  const who = action?.recipient || owner?.on_call?.[0] || "the on-call engineer";
  let cap;
  const recentTake = takeover && phase === "checking" || (takeover && phase === "investigating");
  if (deadHolder) cap = `${deadHolder.owner} was killed mid-task. Its lease runs out in ${fmt(Math.max(0, deadHolder.lease_left_ms) / 1000, 1)} s; until then nobody else can claim the task.`;
  else if (phase === "queued") cap = `${plural(h.alerting.length, "service")} start breaching their SLO. Triage opens an incident and queues a task in the graph.`;
  else if (recentTake && !h.decision_id) cap = `${takeover.to} took over from the last checkpoint, at step ${takeover.step}, under a new fencing epoch. Not from scratch.`;
  else if (phase === "checking") cap = invCps.length ? "Before trusting a recalled playbook, the agent checks it against live evidence." : "Agents recall playbooks by walking the dependency graph from the alerting services.";
  else if (phase === "investigating") cap = allRuled ? "The recalled playbook doesn't match the evidence, so it is ruled out, trust unchanged. The agent digs in." : "Nothing in memory near these alerts, so the investigator works it out step by step, checkpointing each step to the graph.";
  else if (phase === "diagnosed") cap = `Diagnosis: ${h.root}. The responder takes over through the graph and looks up who is on call.`;
  else if (phase === "review") cap = `Exactly one ${action.channel} went to ${who}. The agents now ask ${who} to confirm.`;
  else if (phase === "paged") cap = `Exactly one ${action.channel} goes to ${who}${(action.payload?.applied_preferences || []).length ? ", the way they asked in an earlier incident" : ""}.`;
  else if (phase === "confirmed") cap = `${h.verdict_by} confirmed. The learner records what each memory did.`;
  else if (phase === "learned") cap = helped ? `The playbook helped, so its trust went up: ${fmt(helped.trust)} → ${fmt(helped.trustAfter)}.`
    : misled ? `The playbook misled the agent, so its trust went down${misled.status === "retired" ? " and it retired" : ""}.`
    : newPb ? `The confirmed fix becomes a playbook pinned to ${newPb.about.join(", ")}. Next time it is recalled.` : "Verdicts recorded.";
  else if (phase === "rejected") cap = `${h.verdict_by} rejected the diagnosis. Any memory that led to it loses trust.`;
  else if (phase === "stuck") cap = "A task failed three times. The stuck sweep took it out of rotation so a human can look.";

  return {steps, phase, cap, cands, applied, checking, allRuled, takeover, deadHolder, action, pending, helped, misled, newPb, invCps, held};
}

/* ------------------------------------------------------------ graph layout */
const GW = 1200, ROWY = [70, 220, 370, 545], NH = 34;
const nodeW = (name) => Math.max(96, Math.round(name.length * 8.1 + 30));
function layout(nodes) {
  const callers = {}; nodes.forEach((n) => n.depends_on.forEach((d) => (callers[d] ||= []).push(n.name)));
  const depth = {};
  const deep = (n) => depth[n] ??= Math.max(0, ...(callers[n] || []).map((c) => deep(c) + 1));
  nodes.forEach((n) => deep(n.name));
  const svc = nodes.filter((n) => !n.kind), ds = nodes.filter((n) => n.kind);
  const maxSvc = Math.max(...svc.map((n) => depth[n.name]));
  const layers = []; svc.forEach((n) => (layers[depth[n.name]] ||= []).push(n.name));
  layers[maxSvc + 1] = ds.map((n) => n.name);
  const pos = {};
  const place = () => layers.forEach((l, y) => l.forEach((n, i) => pos[n] = {i, y, n: l.length}));
  place();
  for (let pass = 0; pass < 4; pass++) layers.forEach((l, y) => {
    if (y === 0) return;
    const bc = (n) => { const ps = (callers[n] || []).map((c) => (pos[c].i + .5) / pos[c].n); return ps.length ? ps.reduce((a, b) => a + b) / ps.length : .5; };
    l.sort((a, b) => bc(a) - bc(b)); place();
  });
  const xy = {};
  layers.forEach((l, y) => l.forEach((n, i) => {
    xy[n] = {x: 60 + (GW - 120) * (i + .5) / l.length, y: ROWY[Math.min(y, ROWY.length - 1)] + (y >= ROWY.length ? 0 : 0), db: !!nodes.find((q) => q.name === n).kind, i};
  }));
  return xy;
}
const edgeD = (a, b) => `M${a.x},${a.y + NH / 2} C${a.x},${(a.y + b.y) / 2 + 10} ${b.x},${(a.y + b.y) / 2 - 10} ${b.x},${b.y - NH / 2}`;


function graphModel(x, s) {
  // node states, captions, paths, check card for the selected incident
  const nodes = {}, paths = [];
  const set = (n, st, cap) => { nodes[n] = {st, cap: cap ?? nodes[n]?.cap}; };
  if (!x) return {nodes, paths, dim: false};
  const h = x.head;
  const over = ["learned", "confirmed"].includes(s.phase);
  h.alerting.forEach((a) => set(a, over ? "path" : "alert"));
  s.cands.forEach((c) => {
    const kind = c.outcome === "ruled" ? "ruled" : (c === s.checking || c === s.applied) ? "main" : "faint";
    paths.push({hops: c.path, kind, key: `${h.key}|${c.key}`, label: kind === "main" || (kind === "ruled" && s.allRuled && c === s.cands[0])
      ? `${plural(c.hops, "hop")} · ${c.viaKind ? "same kind of datastore" : "pinned here"}` : null});
    c.path.slice(1, -1).forEach((n) => { if (!nodes[n]) set(n, "path"); });
    set(c.target, c.outcome === "ruled" ? "ruled" : kind === "main" ? "target" : "target2");
  });
  if (!s.cands.length && !h.decision_id && s.invCps.length) {
    const last = s.invCps[s.invCps.length - 1]; const n = last.args?.node || last.args?.service;
    if (n && !h.alerting.includes(n)) set(n, "probe", `step ${last.n}: ${shortTool(last).split(" ")[0].toLowerCase()} ${""}`.trim());
  }
  if (h.root) set(h.root, h.verdict === "confirmed" ? "root" : "suspect",
    h.verdict === "confirmed" ? `root cause · ${label(h.family)}` : `diagnosis · ${label(h.family)}`);
  if (s.applied && !h.root) nodes[s.applied.target].cap = `checks ${s.applied.rows.filter((r) => r.state === "pass").length} / ${s.applied.total} hold`;
  // check card: the memory being checked now, or the last one ruled out
  let card = null;
  const c = s.checking || (!h.verdict && s.applied) || (s.allRuled && !h.verdict ? s.cands[0] : null);
  if (c && s.phase !== "learned") card = c;
  return {nodes, paths, card, dim: true};
}


/* ------------------------------------------------------------ replay */
// The incident as it stood `t` ms after it opened, rebuilt from its stored
// records (claims, checkpoints, sends, decision). Used by the replay controls
// and the landing page; the live view never calls this.
function incidentAt(x, t) {
  const t0 = Math.min(...x.tasks.map((k) => k.created_at));
  const T = t0 + t;
  const inv = x.tasks.find((k) => k.type === "investigate");
  const learn = x.tasks.find((k) => k.type === "learn");
  const decided = inv?.done_at && inv.done_at <= T;
  const learned = learn?.done_at && learn.done_at <= T;
  const confirmed = learn && learn.created_at <= T;
  const tasks = x.tasks.filter((k) => k.created_at <= T).map((k) => {
    const n = (k.claimed_at || []).filter((c) => c <= T).length;
    const done = k.done_at && k.done_at <= T;
    return {...k, claimed_by: (k.claimed_by || []).slice(0, n), claimed_at: (k.claimed_at || []).slice(0, n), epoch: n || k.epoch,
      owner: n ? k.claimed_by[n - 1] : null, status: done ? "done" : n ? "leased" : "open",
      lease_left_ms: done ? -1 : (S.settings?.lease_ms || 6000), done_at: done ? k.done_at : null};
  });
  const head = {...x.head};
  if (!decided) Object.assign(head, {decision_id: null, root: null, family: null, summary: null, decided_by: null, decided_epoch: null, status: "open"});
  if (!confirmed) Object.assign(head, {verdict: null, verdict_by: null});
  if (!learned && decided) head.status = "diagnosed";
  const lens = decided ? x.lens.map((l) => learned ? l : {...l, verdict: null, trust_after: null}) : [];
  return {...x, head, tasks, lens,
    recalling: (inv?.claimed_at?.[0] || Infinity) <= T ? (x.recalling?.length ? x.recalling : x.lens.map((l) => ({memory_id: l.memory, target: l.target,
      score: l.score, trust: l.trust_at_use, hops: l.hops, path: l.path, via_kind: !(l.pinned_to || []).includes(l.target)}))) : [],
    checkpoints: x.checkpoints.filter((c) => c.at <= T),
    actions: x.actions.filter((a) => (a.sent_at || a.created_at) <= T),
    messages: confirmed ? x.messages : [],
    timeline: x.timeline.filter((e) => (e.t_ms || 0) <= t),
    impact: decided ? x.impact : []};
}
// Workers as they stood at `t`: whoever lost a task to a takeover is shown dead
// from its last checkpoint until the takeover (the lease draining).
function workersAt(x, t) {
  const t0 = Math.min(...x.tasks.map((k) => k.created_at));
  const names = ["inv-1", "inv-2"];
  const inv = x.tasks.find((k) => k.type === "investigate");
  const dead = new Set();
  (inv?.claimed_by || []).forEach((who, i) => {
    const next = inv.claimed_at[i + 1];
    if (next !== undefined) { const lastCp = Math.max(...x.checkpoints.filter((c) => c.agent === who).map((c) => c.at), inv.claimed_at[i]);
      if (t0 + t > lastCp) dead.add(who); }
  });
  return names.map((n) => ({name: n, alive: !dead.has(n), killed: dead.has(n)}));
}
// The moments worth stopping at, in order (ms after the incident opened).
function replayStops(x) {
  const ts = new Set([0]);
  x.timeline.forEach((e) => { if (["claim", "takeover", "checkpoint", "action", "done"].includes(e.kind)) ts.add(e.t_ms || 0); });
  const inv = x.tasks.find((k) => k.type === "investigate");
  if (inv?.claimed_by?.length > 1) {   // show the dead worker's lease draining
    const t0 = Math.min(...x.tasks.map((k) => k.created_at));
    const killedCp = Math.max(...x.checkpoints.filter((c) => c.agent === inv.claimed_by[0]).map((c) => c.at));
    ts.add(killedCp - t0 + 1500);
  }
  return [...ts].sort((a, b) => a - b);
}
// Story at a moment: swaps in the workers of that moment, then restores.
function storyAt(x, t) {
  const keep = S.state; S.state = {...(S.state || {}), workers: workersAt(x, t), pending: []};
  try { const xi = incidentAt(x, t); return {x: xi, s: storyOf(xi)}; } finally { S.state = keep; }
}

/* ------------------------------------------------------------ headline + stages */
function headlineOf(x, s) {
  const h = x.head, who = s.action?.recipient;
  if (s.deadHolder) return `${s.deadHolder.owner} was killed. Its lease is draining.`;
  if (s.takeover && !h.decision_id && ["checking", "investigating"].includes(s.phase)) return `${s.takeover.to} took over at step ${s.takeover.step}, not from scratch.`;
  switch (s.phase) {
    case "queued": return `Alerts on ${plural(h.alerting.length, "service")}.`;
    case "checking": return s.invCps.length ? "Checking the playbook against live evidence." : "Recalling playbooks from memory.";
    case "investigating":
      if (s.takeover && !h.decision_id) return `Taken over at step ${s.takeover.step}, not from scratch.`;
      return s.allRuled ? "Memory didn't fit. Investigating step by step." : "Nothing in memory. Investigating step by step.";
    case "diagnosed": return `Diagnosis: ${h.root}, ${label(h.family)}.`;
    case "paged": return `One ${s.action.channel} to ${who}.`;
    case "review": return `One ${s.action.channel} to ${who}. Waiting for a confirmation.`;
    case "confirmed": return `${h.verdict_by} confirmed.`;
    case "learned": return s.helped ? `The playbook helped. Trust ${fmt(s.helped.trust)} → ${fmt(s.helped.trustAfter)}.`
      : s.misled ? "The playbook misled. Trust went down." : s.newPb ? `Learned a playbook for ${s.newPb.about.join(", ")}.` : "Verdicts recorded.";
    case "rejected": return `${h.verdict_by} rejected the diagnosis.`;
    case "stuck": return "A task is stuck. A human needs to look.";
  }
  if (s.takeover && !h.decision_id) return `Taken over at step ${s.takeover.step}, not from scratch.`;
  return "Working.";
}
function stagesOf(x, s) {
  const pbs = (S.memory?.playbooks || []).filter((p) => p.status === "active").length;
  const main = s?.applied || s?.checking || s?.cands?.[0];
  const idx = !x ? 0 : s.phase === "learned" ? 4 : ["diagnosed", "paged", "review", "confirmed", "rejected"].includes(s.phase) ? 3
    : (s.invCps.length || s.phase === "investigating") ? 2 : s.phase === "queued" ? 0 : 1;
  return {idx, items: [
    ["Remember", plural(pbs, "playbook")],
    ["Recall", !x ? "graph walk" : s.cands.length ? `${plural(main.hops, "hop")}` : "nothing near"],
    ["Check", !x ? "live evidence" : s.applied ? `${s.applied.rows.filter((r) => r.state === "pass").length} of ${s.applied.total} hold`
      : main ? `${plural(main.total || 0, "check")}` : plural(s.invCps.length, "step")],
    ["Act", s?.action ? `${plural(x.actions.length, s.action.channel)}` : "one page"],
    ["Learn", s?.helped ? `${fmt(s.helped.trust)} → ${fmt(s.helped.trustAfter)}` : s?.newPb ? "new playbook" : "trust"]]};
}

/* ------------------------------------------------------------ graph (v2 look) */
const sigShort = (sig) => String(sig || "").split(":")[0].replace(/_/g, "-");
// Draws the dependency graph into `el`. Re-renders only when the picture changes;
// a path, pulse or pin animates only the first time it appears.
function drawGraph(el, {x, s, card = true, tag = "g", k = 1, quiet = false}) {
  if (!S.map) return;
  const xy = layout(S.map.nodes); S.xy = xy;
  const g = graphModel(x, s || {cands: [], invCps: []});
  const pins = [];
  (S.memory?.playbooks || []).filter((p) => p.status === "active" || (s?.cands || []).some((c) => c.memory === p.id)).forEach((p) => {
    const c = (s?.cands || []).find((q) => q.memory === p.id && q.final && q.verdict === "helped");
    const used = (s?.cands || []).filter((q) => q.memory === p.id);
    let txt = fmt(used[0]?.trust ?? p.trust), cls = "";
    if (c && s.phase === "learned") { txt = `${fmt(c.trust)} → ${fmt(c.trustAfter)}`; cls = "grn"; }
    else if (used.length && used.every((q) => q.outcome === "ruled")) cls = "neu";
    if (p.status === "retired") cls = "ret";
    p.about.forEach((a) => pins.push({node: a, sig: sigShort(p.signature), txt, cls, id: p.id}));
  });
  const kind = (s?.cands || []).filter((c) => c.viaKind && c.outcome !== "ruled" && (c === s.checking || c === s.applied))
    .flatMap((c) => c.pinned.filter((pn) => xy[pn] && pn !== c.target).map((pn) => [c.target, pn]));
  const sig = JSON.stringify([tag, k, x?.head.key, g, pins, kind, S.mapNode]);
  if (el.dataset.sig === sig) return;
  el.dataset.sig = sig;
  const W = GW, line = (a, b) => `M${a.x},${a.y} L${b.x},${b.y}`;
  let out = "";
  S.map.nodes.forEach((n) => n.depends_on.forEach((d) => { out += `<path class="ge" d="${line(xy[n.name], xy[d])}"/>`; }));
  g.paths.forEach((p) => {
    const fresh = once(`${tag}:path:${p.key}:${p.kind}`);
    for (let i = 1; i < p.hops.length; i++) {
      const a = xy[p.hops[i - 1]], b = xy[p.hops[i]]; if (!a || !b) continue;
      out += `<path pathLength="1" class="gp ${p.kind} ${fresh ? "draw" : ""}" style="animation-delay:${(i - 1) * .35}s" d="${line(a, b)}"/>`;
    }
    if (p.label && p.hops.length >= 2) {
      const b = xy[p.hops[p.hops.length - 1]];
      out += `<text class="gpl ${p.kind}" x="${b.x}" y="${b.y + 66 * k}" text-anchor="middle" ${fresh ? 'style="animation:brFade .3s .5s both"' : ""}>${esc(p.label)}</text>`;
    }
  });
  kind.forEach(([a, b]) => { out += `<path class="gk ${once(`${tag}:kind:${x.head.key}:${a}`) ? "draw" : ""}" pathLength="1" d="${line(xy[a], xy[b])}"/>`; });
  let ai = 0;
  S.map.nodes.forEach((n) => {
    const p = xy[n.name], st = g.nodes[n.name]?.st || "base", cap = g.nodes[n.name]?.cap;
    const faded = g.dim && !g.nodes[n.name] ? " faded" : "";
    const sel = S.mapNode === n.name ? " sel" : "";
    const pulse = st === "alert" && once(`${tag}:pulse:${x.head.key}:${n.name}`);
    const shape = p.db ? `<rect class="gn" x="${p.x - 4.5 * k}" y="${p.y - 4.5 * k}" width="${9 * k}" height="${9 * k}" rx="1.5"/>` : `<circle class="gn" cx="${p.x}" cy="${p.y}" r="${5 * k}"/>`;
    const lw = (n.name.length * 7.2 + 14) * k;
    const tagged = ["alert", "root", "suspect", "probe"].includes(st);
    // Enlarged graphs (the landing hero): stagger every other datastore label so
    // neighbours like postgres-payments and postgres-orders don't overlap.
    const dy = k > 1.2 && p.db && p.i % 2 ? 19 * k : 0;
    out += `<g class="gnode s-${st}${faded}${sel}" data-node="${esc(n.name)}">
      ${st === "alert" ? `<circle class="halo ${pulse ? "pulse" : ""}" style="--d:${.15 + (ai++) * .08}s" cx="${p.x}" cy="${p.y}" r="${11 * k}"/>` : ""}
      ${shape}
      ${tagged ? `<rect class="gtag" x="${p.x - lw / 2}" y="${p.y + 10 * k + dy}" width="${lw}" height="${19 * k}" rx="5"/>` : ""}
      <text class="glab" x="${p.x}" y="${p.y + 23.5 * k + dy}" text-anchor="middle">${esc(n.name)}</text>
      ${cap ? `<text class="gcap" x="${p.x}" y="${p.y + 45 * k + dy}" text-anchor="middle">${esc(cap)}</text>` : ""}
      <rect class="ghit" x="${p.x - lw / 2}" y="${p.y - 12 * k}" width="${lw}" height="${44 * k}"/></g>`;
  });
  const byNode = {};
  pins.forEach((pn) => {
    const p = xy[pn.node]; if (!p) return;
    const i = (byNode[pn.node] = (byNode[pn.node] || 0) + 1) - 1;
    const text = `${pn.sig}  ${pn.txt}`, w = (text.length * 7 + 26) * k;
    const fresh = once(`${tag}:pin:${pn.id}:${pn.node}:${pn.txt}`);
    out += `<g transform="translate(${Math.max(4, p.x - w - 10)},${p.y - 34 * k - i * 24 * k})"><g class="gpin ${pn.cls} ${fresh ? "pin-in" : ""}">
      <rect width="${w}" height="${20 * k}" rx="6"/><text x="${10 * k}" y="${14 * k}"><tspan class="dia">◆</tspan> ${esc(pn.sig)} <tspan class="tv">${esc(pn.txt)}</tspan></text></g></g>`;
  });
  if (card && g.card && xy[g.card.target]) out += checkCardFO(g.card, xy, g, x, tag);
  el.innerHTML = `<svg viewBox="0 20 ${W} ${Math.round(600 + Math.max(0, k - 1.2) * 160)}" preserveAspectRatio="xMidYMid meet" class="gsvg ${g.dim ? "dim" : ""} ${quiet ? "quiet" : ""}" style="--k:${k}" role="img" aria-label="Service dependency graph">${out}</svg>`;
}
function checkRowsHtml(c, tag, key) {
  const rows = c.outcome === "ruled" ? c.rows.filter((r) => r.state !== "wait" && r.state !== "pend") : c.rows;
  return rows.map((r) => {
    const fresh = key && once(`${tag}:row:${key}:${c.key}:${r.text}:${r.state}`);
    const o = r.state === "pass" || r.state === "fail" ? esc(r.obsText) : r.state === "pend" ? "reading…" : "—";
    return `<div class="crow ${fresh ? "new" : ""}"><span class="gl g-${r.state}">${r.state === "pass" ? "✓" : r.state === "fail" ? "✕" : ""}</span>
      <span class="ct">${esc(r.text)}</span><span class="co ${r.state === "fail" ? "bad" : ""}">${o}</span></div>`;
  }).join("");
}
function checkCardFO(c, xy, g, x, tag) {
  const p = xy[c.target], cw = 400;
  const rows = c.outcome === "ruled" ? c.rows.filter((r) => r.state !== "wait" && r.state !== "pend") : c.rows;
  const ch = 50 + rows.length * 48;
  // place the card where it covers nothing in play: nodes in the story, their
  // labels, the recall paths and the pins; then as close to its node as possible
  const busy = [];
  Object.keys(g.nodes).filter((n) => xy[n]).forEach((n) => { const q = xy[n], w = n.length * 8.4 + 30; busy.push([q.x - w / 2, q.y - 24, q.x + w / 2, q.y + 60, 3]); });
  g.paths.forEach((pa) => { for (let i = 1; i < pa.hops.length; i++) { const a = xy[pa.hops[i - 1]], b = xy[pa.hops[i]]; if (!a || !b) continue;
    for (let f = 0; f <= 1; f += .1) { const px = a.x + (b.x - a.x) * f, py = a.y + (b.y - a.y) * f; busy.push([px - 8, py - 8, px + 8, py + 8, 2]); } } });
  (c.pinned || []).forEach((n) => { const q = xy[n]; if (q) busy.push([q.x - 260, q.y - 60, q.x, q.y - 20, 2]); });
  const ov = (a, b) => Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
  let best = null;
  for (let x0 = 10; x0 <= GW - cw - 10; x0 += 30) for (let y0 = 30; y0 <= 612 - ch; y0 += 20) {
    const r = [x0, y0, x0 + cw, y0 + ch];
    const cost = busy.reduce((n, bx) => n + ov(r, bx) * bx[4] * 10, 0) + Math.hypot(x0 + cw / 2 - p.x, y0 + ch / 2 - p.y);
    if (!best || cost < best.cost) best = {cost, x0, y0};
  }
  const done = rows.filter((r) => r.state === "pass").length;
  const head = c.outcome === "ruled" ? `<span class="cs bad">Not applicable · trust unchanged</span>` : c.outcome === "holds" ? `<span class="cs ok">Applies · ${done} of ${c.total}</span>` : `<span class="cs">${done} of ${c.total} passed</span>`;
  return `<foreignObject x="${best.x0}" y="${best.y0}" width="${cw}" height="${ch + 40}"><div xmlns="http://www.w3.org/1999/xhtml" class="ccard ${once(`${tag}:card:${x.head.key}:${c.key}`) ? "in" : ""}">
    <div class="ch"><b>${esc(sigShort(c.signature))}</b><span class="cm">on ${esc(c.target)}</span>${head}</div>${checkRowsHtml(c, tag, x.head.key)}</div></foreignObject>`;
}

/* Completed evals and independently dated benchmark evidence, shared by both pages. */
function resultSource(source, name) {
  if (!source) return "No saved run";
  const at = new Date(source.at);
  const date = Number.isNaN(at.getTime()) ? source.at : at.toLocaleString(undefined, {timeZoneName: "short"});
  return `${esc(name || source.file)} · ${esc(date)}${source.time_basis === "file modified" ? " · legacy file date" : ""}`;
}
function evaluationHtml(r) {
  const ev = r.eval, load = r.load || [];
  let comparison = `<h2>No completed comparison yet.</h2><p>Run make eval or make eval-rules for the full benchmark.</p>`;
  if (ev) {
    const arms = ["A", "B", "C"].filter((a) => ev.summary[a]?.all);
    const stats = arms.map((a) => ev.summary[a].all), A = ev.summary.A.all, C = ev.summary.C.all;
    const requests = (s) => Math.round(s.mean_llm_requests * s.n), correct = (s) => Math.round(s.accuracy * s.n);
    const hasModel = requests(A) > 0, cut = hasModel ? Math.round((1 - requests(C) / requests(A)) * 100) : null;
    const headline = hasModel ? `${Math.abs(cut)}%` : `${Math.round(C.accuracy * 100)}%`;
    const caption = hasModel ? (cut < 0 ? "more model calls." : cut > 0 ? "fewer model calls." : "change in model calls.") : "graph diagnosis accuracy.";
    const names = {A: "No memory", B: "Text memory", C: "Graph memory"}, colors = {A: "#DDDBD5", B: "#8E8C86", C: "#111111"};
    const metric = (title, values, sub) => {
      const max = Math.max(1, ...values);
      return `<div class="metric"><h5>${title}<span>${sub}</span></h5>${values.map((v, i) => `<div class="hrow"><span class="tr"><i style="width:${Math.max(0, v / max * 100)}%;background:${colors[arms[i]]}"></i></span><b class="${arms[i] === "C" ? "me" : ""}">${Number.isInteger(v) ? v : fmt(v, 2)}</b></div>`).join("")}</div>`;
    };
    const m2 = ev.summary.m2, m5 = ev.m5;
    comparison = `<div class="result-layout"><div><div class="eyebrow">Latest complete comparison · ${C.n} incidents · ${arms.length} memory arms</div>
      <div class="big">${headline}</div><div class="big2">${caption}</div>
      <p class="result-copy">${hasModel ? `Graph memory used ${requests(C)} model requests; no memory used ${requests(A)}.` : "No model calls in this run. Compare tool calls and accuracy below."}
      Correct diagnoses: graph ${correct(C)}/${C.n}; no memory ${correct(A)}/${A.n}.</p>
      <p class="result-source">${resultSource(ev.source, ev.name)}<br>Model: ${esc(ev.meta.model || "unspecified")} · ${esc(ev.meta.max_steps ?? 12)}-step budget · ${ev.meta.cached ? "cached (timings excluded)" : "uncached"}</p></div>
      <div><div class="legend">${arms.map((a) => `<span><i style="background:${colors[a]}"></i>${names[a]}</span>`).join("")}</div>
      ${metric(hasModel ? "Model requests" : "Tool calls", stats.map((s) => hasModel ? requests(s) : s.mean_steps), hasModel ? `across ${C.n} incidents` : "mean per incident")}
      ${metric("Incidents helped by memory", stats.map((s) => s.memory_helped ?? 0), `of ${C.n}`)}
      ${metric("Correct diagnoses", stats.map(correct), `of ${C.n}`)}
      <div class="stats3">${m2 ? `<div><b>${Math.round(m2.graph_recall_at_5 * 100)}%</b><span>graph recall@5; text ${Math.round(m2.text_recall_at_5 * 100)}% · ${m2.n} eligible incidents</span></div>` : ""}
      <div><b>${stats.reduce((n, s) => n + s.duplicate_notifications, 0)}</b><span>duplicate logical notifications in this evaluation</span></div>
      ${m5 ? `<div><b>${m5.misleading_uses_before_retirement} uses</b><span>before the seeded wrong playbook retired</span></div>` : ""}</div></div></div>
      <p class="result-note">Synthetic 15-node company, three failure families. Text baseline: ${esc(ev.meta.embedder || "not recorded")}. Checking memories also costs tool calls; read the accuracy beside the savings.</p>`;
  }
  const iso = r.isolation, fencing = r.fencing;
  const markers = iso ? Object.values(iso.leaks).reduce((n, row) => n + (row.other_company_markers_found || []).length, 0) : null;
  const proof = `<div class="result-proof"><div class="card result-check"><h3>Tenant isolation</h3><b class="${!iso ? "" : iso.ok ? "result-pass" : "result-fail"}">${!iso ? "Not run yet" : `${iso.ok ? "Passed" : "Failed"} · ${markers} leaked markers`}</b>
      <p>Canary scan across company graphs, preference separation and trusted tenant selection.</p><p class="result-source">${resultSource(r.isolation_source)}</p></div>
    <div class="card result-check"><h3>Stale writes rejected</h3><b class="${!fencing ? "" : fencing.ok ? "result-pass" : "result-fail"}">${!fencing ? "Not run yet" : `${fencing.stale_writes_rejected}/${fencing.stale_writes_attempted} · ${fencing.ok ? "passed" : "failed"}`}</b>
      <p>Direct attempts to heartbeat, checkpoint, hand off, complete and notify using the old lease after takeover.</p><p class="result-source">${resultSource(r.fencing_source)}</p></div></div>`;
  const table = load.length ? `<div class="card result-load"><h3>Latest load run</h3><p class="result-source">${resultSource(r.load_source)}</p><table><thead><tr><th>Pairs / tenant</th><th>Lease expiry</th><th>Completed</th><th>Per min</th><th>Read p50 / p95 ms</th><th>Write p50 / p95 ms</th><th>Duplicates</th><th>Re-sends absorbed</th><th>Takeovers</th><th>Lease losses</th><th>Needs human</th></tr></thead><tbody>
    ${load.map((l) => `<tr><td>${l.worker_pairs_per_company}</td><td>${l.chaos_ms ? `${l.chaos_ms} ms` : "none"}</td><td class="${l.completed === l.incidents ? "" : "result-fail"}">${l.completed}/${l.incidents}</td><td>${l.incidents_per_minute ?? "—"}</td><td>${l.memory_reads.p50_ms ?? "—"} / ${l.memory_reads.p95_ms ?? "—"}</td><td>${l.memory_writes.p50_ms ?? "—"} / ${l.memory_writes.p95_ms ?? "—"}</td><td>${l.duplicate_notifications}</td><td>${l.duplicate_sends_absorbed ?? "—"}</td><td>${l.takeovers ?? "—"}</td><td>${l.lost_leases ?? "—"}</td><td>${l.stuck_for_a_human ?? "—"}</td></tr>`).join("")}</tbody></table>
    ${load.some((l) => l.errors?.length) ? `<p class="result-fail">This run reported worker errors. Review the saved load artifact.</p>` : ""}</div>` : `<p class="result-note">No load run saved yet.</p>`;
  return `${comparison}${proof}${table}<p class="result-source">Updates automatically after a completed run. Rerun: make eval · make eval-rules · make bench · make isolation · make fencing.</p>`;
}
