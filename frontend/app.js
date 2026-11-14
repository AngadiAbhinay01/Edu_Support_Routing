"use strict";
/* PRESENTATION TIER: renders JSON from /api. All dynamic text goes through textContent (no innerHTML), so it is XSS-safe. */
const $app = document.getElementById("app");
const API = async (method, path, body) => {
  const r = await fetch("/api" + path, {method, headers: {"Content-Type": "application/json"}, body: body === undefined ? undefined : JSON.stringify(body)});
  const j = await r.json().catch(() => ({error: {code: "BAD_RESPONSE", message: "server returned non-JSON"}}));
  if (!r.ok) { const e = new Error((j.error && j.error.message) || "request failed"); e.info = j.error || {}; throw e; }
  return j;
};
function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") e.className = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v); else if (v !== null && v !== undefined && v !== false) e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined && k !== false) e.append(k.nodeType ? k : document.createTextNode(String(k)));
  return e;
}
const badge = (t) => h("span", {class: "badge b-" + t}, t);
function toast(msg, bad) { const t = document.getElementById("toast"); t.textContent = msg; t.className = bad ? "bad" : ""; t.style.display = "block"; clearTimeout(toast.t); toast.t = setTimeout(() => (t.style.display = "none"), 6000); }
function fail(e) { const d = e.info && e.info.details; toast((e.info && e.info.code ? e.info.code + ": " : "") + e.message + (d ? " " + JSON.stringify(d) : ""), true); }
function mount(...nodes) { $app.replaceChildren(...nodes); }
function table(cols, rows, onclick) {
  return h("table", {}, h("thead", {}, h("tr", {}, cols.map((c) => h("th", {}, c[0])))),
    h("tbody", {}, rows.map((r) => h("tr", onclick ? {class: "click", onclick: () => onclick(r)} : {}, cols.map((c) => h("td", {}, c[1](r)))))));
}
function bars(items) {
  const max = Math.max(1, ...items.map((i) => i.n));
  return items.map((i) => h("div", {class: "barrow"}, h("span", {}, i.k), h("div", {}, (() => { const b = h("div", {class: "bar"}); b.style.width = (100 * i.n / max) + "%"; return b; })()), h("span", {}, i.n)));
}
const kv = (o) => h("pre", {}, JSON.stringify(o, null, 2));

/* ---------------- pages ---------------- */
async function dashboard() {
  const m = await API("GET", "/metrics");
  const kpi = (l, v) => h("div", {class: "card"}, h("div", {class: "mute"}, l), h("div", {class: "kpi"}, v));
  const pct = (arr, k) => { const t = arr.reduce((a, x) => a + x.n, 0), b = (arr.find((x) => x.k === k) || {n: 0}).n; return t ? (100 * b / t).toFixed(1) + "%" : "-"; };
  mount(h("h2", {}, "Dashboard"),
    h("div", {class: "grid"}, kpi("Tickets", m.totals.tickets), kpi("Open", m.totals.open_tickets), kpi("Escalated", m.escalation.escalated_tickets),
      kpi("First-response SLA breached", pct(m.sla.first_response, "breached")), kpi("Resolution SLA breached", pct(m.sla.resolution, "breached")), kpi("Avg CSAT", m.feedback.avg_csat)),
    h("div", {class: "grid"}, h("div", {class: "card"}, h3("By status"), bars(m.by_status)), h("div", {class: "card"}, h3("By domain"), bars(m.by_domain)),
      h("div", {class: "card"}, h3("Escalation reasons"), bars(m.escalation.reasons)), h("div", {class: "card"}, h3("By priority"), bars(m.by_priority))));
}
function h3(t) { return h("h3", {}, t); }

async function tickets(qs) {
  const p = new URLSearchParams(qs || ""); const d = await API("GET", "/tickets?" + p.toString());
  const sel = (name, opts) => h("select", {id: "f_" + name}, h("option", {value: ""}, "any " + name), opts.map((o) => h("option", {value: o, selected: p.get(name) === o}, o)));
  const meta = await API("GET", "/meta");
  const go = (page) => { const q = new URLSearchParams(); for (const n of ["status", "priority", "domain", "q"]) { const v = document.getElementById("f_" + n); if (v && v.value) q.set(n, v.value); } for (const n of ["escalated", "sla_breached"]) if (document.getElementById("f_" + n).checked) q.set(n, "1"); q.set("page", page); location.hash = "#/tickets?" + q; };
  mount(h("h2", {}, "Tickets (" + d.total + ")"), h("div", {class: "card"}, h("div", {class: "row"},
    h("input", {id: "f_q", placeholder: "search subject / body / id", value: p.get("q") || ""}), sel("status", meta.statuses), sel("priority", meta.priorities), sel("domain", ["ACC", "FIN", "GEN", "IT", "REG"]),
    h("label", {}, h("input", {type: "checkbox", id: "f_escalated", checked: p.get("escalated") === "1"}), " escalated"), h("label", {}, h("input", {type: "checkbox", id: "f_sla_breached", checked: p.get("sla_breached") === "1"}), " SLA breached"),
    h("button", {onclick: () => go(1)}, "Filter")),
    table([["Ticket", (r) => r.ticket_id], ["Subject", (r) => r.subject], ["Status", (r) => badge(r.status)], ["Priority", (r) => badge(r.priority)], ["Category", (r) => r.category_name], ["Team", (r) => r.current_team_id],
      ["SLA", (r) => [badge(r.first_response_status), " ", badge(r.resolution_status)]], ["Created", (r) => r.created_at]], d.items, (r) => (location.hash = "#/t/" + r.ticket_id)),
    h("div", {class: "pager"}, h("button", {class: "sec", disabled: d.page <= 1, onclick: () => go(d.page - 1)}, "Prev"), "page " + d.page + " / " + d.pages, h("button", {class: "sec", disabled: d.page >= d.pages, onclick: () => go(d.page + 1)}, "Next"))));
}

function decisionCard(d) {
  const c = d.classification;
  return h("div", {class: "card"}, h3("Routing decision (explainable)"),
    h("p", {}, "Category ", h("b", {}, d.category.category_id + " " + d.category.name), " · priority ", badge(d.priority), " · team ", h("b", {}, d.team_id)),
    h("p", {class: "mute"}, "Router: " + c.reason + " (confidence " + c.confidence + ", top score " + c.top_score + ", margin " + c.margin + ")"),
    d.priority_reasons && d.priority_reasons.length ? h("p", {class: "small"}, "Priority reasons: " + d.priority_reasons.join(", ")) : null,
    h("p", {}, "SLA: first response by ", h("b", {}, d.sla.first_response_due), ", resolution by ", h("b", {}, d.sla.resolution_due), " (business hours only)"),
    h("p", {}, "Knowledge: " + (d.retrieval ? (d.retrieval.found ? d.retrieval.article_id + " v" + d.retrieval.version_no : "no matching article") : "n/a")),
    h("p", {}, h("b", {}, "Next action: "), d.next_action));
}

async function newTicket() {
  const out = h("div"); const f = {};
  const field = (id, label, el) => { f[id] = el; return [h("label", {}, label), el]; };
  const preview = async () => { out.replaceChildren(); try { out.append(decisionCard(await API("POST", "/route-preview", {subject: f.subject.value, body: f.body.value, deadline_date: f.deadline.value || undefined}))); } catch (e) { fail(e); } };
  mount(h("h2", {}, "New ticket"), h("div", {class: "card"},
    field("req", "Requester id (e.g. REQ-000001)", h("input", {value: "REQ-000001"})), field("subject", "Subject", h("input", {})), field("body", "Describe your request", h("textarea", {})),
    h("div", {class: "row"}, h("div", {}, field("deadline", "Deadline (optional)", h("input", {type: "date"}))), h("div", {}, field("channel", "Channel", h("select", {}, ["portal", "email", "phone", "walk_in"].map((c) => h("option", {value: c}, c)))))),
    h("p", {}, h("button", {class: "sec", onclick: preview}, "Preview routing"), " ", h("button", {onclick: async () => {
      try { const t = await API("POST", "/tickets", {requester_id: f.req.value, subject: f.subject.value, body: f.body.value, channel: f.channel.value, deadline_date: f.deadline.value || undefined}); toast("Created " + t.ticket.ticket_id); location.hash = "#/t/" + t.ticket.ticket_id; } catch (e) { fail(e); } }}, "Create ticket"))), out);
}

async function ticket(id) {
  const g = await API("GET", "/tickets/" + id); const t = g.ticket; const meta = await API("GET", "/meta");
  const staff = (await API("GET", "/staff?team=" + t.current_team_id)).filter((s) => !s.active_to);
  const reload = () => route();
  const act = (fn) => async () => { try { await fn(); toast("Done"); reload(); } catch (e) { fail(e); } };
  const sid = h("select", {}, staff.map((s) => h("option", {value: s.staff_id}, s.staff_id + " " + s.full_name)));
  const body = h("textarea", {placeholder: "Reply text…"}), arts = h("input", {placeholder: "cited article ids, comma separated (e.g. KB-000131)"});
  const mtype = h("select", {}, ["answer", "clarification_request", "internal_note"].map((x) => h("option", {value: x}, x)));
  const to = h("select", {}, meta.statuses.filter((s) => (meta.transitions[t.status] || []).includes(s)).map((s) => h("option", {value: s}, s)));
  const code = h("select", {}, meta.resolution_codes.map((c) => h("option", {value: c}, c))), reason = h("input", {placeholder: "reason / note"});
  const team = h("select", {}, meta.teams.map((x) => h("option", {value: x.team_id}, x.team_id)));
  const sugg = h("div");
  const closed = ["resolved", "closed"].includes(t.status);
  mount(h("p", {}, h("a", {href: "#/tickets"}, "← tickets")), h("h2", {}, t.ticket_id + " — " + t.subject),
    h("div", {class: "card"}, badge(t.status), " ", badge(t.priority), " · ", g.category ? g.category.name : t.category_id, " · team ", h("b", {}, t.current_team_id), " · requester ", t.requester_id + " " + g.requester.full_name,
      h("p", {class: "small mute"}, "created " + t.created_at + " · SLA first response due " + g.sla.first_response_due + " (" + g.sla.first_response_status + "), resolution due " + g.sla.resolution_due + " (" + g.sla.resolution_status + ")"),
      g.expected_escalation.length ? h("p", {class: "err"}, "Escalation rules fired: " + g.expected_escalation.join(", ")) : null),
    g.audit_findings.length ? h("div", {class: "card"}, h3("Audit findings on this ticket"), g.audit_findings.map((x) => h("div", {class: "finding"}, h("b", {}, x.issue_type), " — " + x.detail))) : null,
    h("div", {class: "card"}, h3("Conversation"), g.messages.map((m) => h("div", {class: "msg " + m.sender_type + (m.is_internal ? " internal" : "")}, h("div", {class: "small mute"}, m.message_id + " · " + m.sender_type + " · " + m.message_type + (m.is_internal ? " · internal" : "") + " · " + m.created_at),
      h("div", {style: null}, m.body), g.citations.filter((c) => c.message_id === m.message_id).map((c) => h("div", {class: "small"}, "📎 " + c.article_id + " v" + c.cited_version_no + " — " + c.title + " ", badge(c.effective_at_message_date ? "ok" : "error"), c.effective_at_message_date ? "" : " not in force on message date"))))),
    closed ? (t.status === "resolved" ? h("div", {class: "card"}, h3("Feedback"), h("button", {onclick: act(() => API("POST", "/tickets/" + id + "/feedback", {requester_id: t.requester_id, csat: 5, answer_helpful: true}))}, "Submit 5★ as requester")) : null) :
    h("div", {class: "card"}, h3("Staff actions"), h("div", {class: "row"}, sid, mtype), body, arts,
      h("p", {}, h("button", {class: "sec", onclick: async () => { try { const s = await API("GET", "/tickets/" + id + "/suggested-answer"); body.value = s.body; arts.value = s.citations.map((c) => c.article_id).join(","); mtype.value = s.message_type; toast("Suggested: " + s.action); } catch (e) { fail(e); } }}, "Fill suggested answer"), " ",
        h("button", {onclick: act(() => API("POST", "/tickets/" + id + "/messages", {sender_type: "staff", sender_id: sid.value, message_type: mtype.value, body: body.value, article_ids: arts.value.split(",").map((x) => x.trim()).filter(Boolean)}))}, "Send")),
      h("div", {class: "row"}, to, code, reason, h("button", {onclick: act(() => API("POST", "/tickets/" + id + "/transition", {to_status: to.value, actor_id: sid.value, resolution_code: to.value === "resolved" ? code.value : undefined, reason: reason.value || undefined}))}, "Change status")),
      h("div", {class: "row"}, team, h("button", {class: "sec", onclick: act(() => API("POST", "/tickets/" + id + "/assign", {team_id: team.value, actor_id: sid.value, reason: reason.value}))}, "Reassign (uses reason box)"))),
    h("div", {class: "card"}, h3("History"), table([["#", (e) => e.seq_no], ["When", (e) => e.event_at], ["Event", (e) => e.event_type], ["From → to", (e) => (e.from_status || "") + " → " + e.to_status], ["Actor", (e) => e.actor_type + (e.actor_id ? " " + e.actor_id : "")], ["Details", (e) => e.details ? JSON.stringify(e.details) : ""]], g.events)),
    h("div", {class: "card"}, h3("Assignments"), table([["Id", (a) => a.assignment_id], ["Team", (a) => a.team_id], ["Staff", (a) => a.staff_id], ["Type", (a) => a.assignment_type], ["Rule", (a) => a.routing_rule_id || ""], ["From", (a) => a.assigned_at], ["To", (a) => a.unassigned_at || ""]], g.assignments)), sugg);
}

async function kb(qs) {
  const p = new URLSearchParams(qs || ""); const d = await API("GET", "/articles?" + p.toString());
  const go = (page) => { const q = new URLSearchParams(); const v = document.getElementById("kq").value, s = document.getElementById("ks").value; if (v) q.set("q", v); if (s) q.set("status", s); q.set("page", page); location.hash = "#/kb?" + q; };
  mount(h("h2", {}, "Knowledge base (" + d.total + " articles)"), h("div", {class: "card"}, h("div", {class: "row"}, h("input", {id: "kq", placeholder: "search", value: p.get("q") || ""}),
    h("select", {id: "ks"}, [["", "any status"], ["current", "current"], ["superseded", "superseded"], ["draft", "draft"]].map((o) => h("option", {value: o[0], selected: p.get("status") === o[0]}, o[1]))), h("button", {onclick: () => go(1)}, "Search")),
    table([["Id", (a) => a.article_id], ["Topic", (a) => a.topic_key], ["Ver", (a) => a.version_no], ["Title", (a) => a.title], ["Status", (a) => badge(a.status)], ["Valid", (a) => a.effective_from + " → " + (a.effective_to || "open")], ["Policy", (a) => a.policy_id]], d.items, (a) => (location.hash = "#/a/" + a.article_id)),
    h("div", {class: "pager"}, h("button", {class: "sec", disabled: d.page <= 1, onclick: () => go(d.page - 1)}, "Prev"), "page " + d.page + " / " + d.pages, h("button", {class: "sec", disabled: d.page >= d.pages, onclick: () => go(d.page + 1)}, "Next"))));
}
async function article(id) {
  const d = await API("GET", "/articles/" + id);
  mount(h("p", {}, h("a", {href: "#/kb"}, "← knowledge base")), h("h2", {}, d.article.article_id + " " + d.article.title), h("div", {class: "card"}, h("p", {}, d.article.body), h("p", {class: "mute"}, "Cited by " + d.cited_by_messages + " messages")),
    h("div", {class: "card"}, h3("All versions of " + d.article.topic_key), table([["Id", (a) => a.article_id], ["Ver", (a) => a.version_no], ["Status", (a) => badge(a.status)], ["Valid", (a) => a.effective_from + " → " + (a.effective_to || "open")], ["Key fact", (a) => a.key_fact_value + " " + (a.key_fact_unit || "")]], d.versions)));
}
async function auditPage() {
  const a = await API("GET", "/audit?limit=60"); let ev = null; try { ev = await API("GET", "/evaluation"); } catch (e) { /* ground truth is optional */ }
  mount(h("h2", {}, "Audit (re-derived from tables only) as of " + a.as_of), h("div", {class: "card"}, h("p", {}, a.total + " findings"), bars(Object.entries(a.counts).map(([k, n]) => ({k, n})))),
    h("div", {class: "card"}, table([["Type", (f) => f.issue_type], ["Ticket", (f) => h("a", {href: "#/t/" + f.ticket_id}, f.ticket_id)], ["Entity", (f) => f.entity_id], ["Detail", (f) => f.detail]], a.findings)),
    ev ? h("div", {class: "card"}, h3("Evaluation against separate ground truth"), kv(ev)) : h("div", {class: "card mute"}, "No ground_truth folder configured."));
}

/* ---------------- router ---------------- */
async function route() {
  const hash = location.hash || "#/"; const [path, qs] = hash.slice(1).split("?"); let m;
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("on", a.getAttribute("href") === "#" + path || (path.startsWith("/t") && a.getAttribute("href") === "#/tickets")));
  try {
    if (path === "/") await dashboard(); else if (path === "/tickets") await tickets(qs); else if (path === "/new") await newTicket(); else if (path === "/kb") await kb(qs); else if (path === "/audit") await auditPage();
    else if ((m = path.match(/^\/t\/(TKT-2026-\d{6})$/))) await ticket(m[1]); else if ((m = path.match(/^\/a\/(KB-\d{6})$/))) await article(m[1]);
    else mount(h("p", {class: "err"}, "Page not found."));
  } catch (e) { mount(h("p", {class: "err"}, e.message)); }
}
window.addEventListener("hashchange", route);
API("GET", "/meta").then((m) => (document.getElementById("clock").textContent = "app time " + m.now)).catch(() => {});
route();
