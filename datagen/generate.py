"""Synthetic data generator for the student / faculty support routing platform.

Pipeline (see docs/GENERATOR.md):
  1. master data  (role, term, team, category, sla_policy, holiday, policy_document, knowledge_article, requester, staff, rules)
  2. PASS 1: simulate every ticket's life-cycle with the documented business rules -> valid baseline
  3. PASS 2: choose tickets and RE-simulate them with exactly one labelled defect (edge case injection)
  4. top-up internal notes to hit the exact message volume, assign deterministic IDs, derive SLA / feedback
  5. ground truth (separate files), validation, export CSV / JSON / SQL

Run:  python -m datagen.generate --out data/full --tickets 5000 --articles 200 --messages 20000 --seed 20261022
"""
import argparse
import bisect
import json
import math
import os
import random
import sys
import zlib
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta, date

from edu_support import config as C
from edu_support import dictionary
from edu_support import rules
from edu_support.bizhours import add_business_hours, business_hours_between, sla_due, is_business_day
from edu_support import audit
from . import catalog as K

AS_OF = C.AS_OF


def d_(x):
    return x.date() if isinstance(x, datetime) else x


# ===================================================================================================
# MASTER DATA
# ===================================================================================================
class Master:
    """Holds every parent table plus lookups used by the simulator."""

    def __init__(self, seed, n_tickets, n_articles):
        self.seed = seed
        self.n_tickets = n_tickets
        self.rng = random.Random("%d:master" % seed)
        self.rows = OrderedDict((t, []) for t in dictionary.TABLES)
        self._roles_terms_teams()
        self._categories()
        self._policies()
        self._articles(n_articles)
        self._people()
        self._auth_and_rules()
        self._lookups()

    # ---- simple reference tables ------------------------------------------------------------------
    def _roles_terms_teams(self):
        for r in K.ROLES:
            self.rows["role"].append(dict(zip(["role_id", "role_name", "actor_type", "can_raise_ticket", "can_handle_ticket", "description"], r)))
        for t in K.TERMS:
            self.rows["term"].append(dict(zip(["term_id", "term_name", "start_date", "end_date", "registration_opens", "add_drop_deadline", "aid_deadline"], t)))
        for t in K.TEAMS:
            self.rows["team"].append({"team_id": t[0], "team_name": t[1], "tier": t[2], "domain": t[3]})
        for pid, pr, fr, res in K.SLA_POLICIES:
            self.rows["sla_policy"].append({"sla_policy_id": pid, "priority": pr, "first_response_hours": fr, "resolution_hours": res,
                                            "uses_business_hours": 1, "effective_from": date(2026, 1, 1), "effective_to": None})
        for d, name in sorted(C.HOLIDAYS.items()):
            self.rows["holiday"].append({"holiday_date": d, "holiday_name": name})

    def _categories(self):
        rows = [{"category_id": "CAT-GEN", "parent_category_id": None, "name": "General / Needs Triage", "domain": "GEN", "level": 1,
                 "default_priority": "normal", "requires_human_review": 0, "routing_keywords": "", "default_team_id": "TEAM-TRIAGE", "is_active": 1}]
        for dom, kws in K.DOMAIN_KEYWORDS.items():
            rows.append({"category_id": "CAT-%s" % dom, "parent_category_id": None, "name": K.DOMAIN_NAMES[dom], "domain": dom, "level": 1,
                         "default_priority": "normal", "requires_human_review": 0, "routing_keywords": "|".join(kws),
                         "default_team_id": K.DOMAIN_TEAM[dom], "is_active": 1})
        for dom, code, name, prio, human, kws in K.LEAVES:
            rows.append({"category_id": "CAT-%s-%s" % (dom, code), "parent_category_id": "CAT-%s" % dom, "name": name, "domain": dom, "level": 2,
                         "default_priority": prio, "requires_human_review": human, "routing_keywords": "|".join(kws),
                         "default_team_id": K.DOMAIN_TEAM[dom], "is_active": 1})
        rows.sort(key=lambda r: r["category_id"])
        self.rows["category"] = rows

    def _policies(self):
        rows = []
        for dom in ["FIN", "REG", "IT", "ACC"]:
            leaves = [l for l in K.LEAVES if l[0] == dom]
            for li, (_, code, name, *_r) in enumerate(leaves):
                ids = []
                for rev in (1, 2):
                    pid = "POL-%s-2026-%03d" % (dom, li * 2 + rev)
                    ids.append(pid)
                    rows.append({
                        "policy_id": pid, "domain": dom, "category_id": "CAT-%s-%s" % (dom, code),
                        "title": "%s Policy" % name,
                        "version_label": "AY2025-26 R1" if rev == 1 else "AY2026-27 R2",
                        "effective_from": date(2025, 9, 1) if rev == 1 else date(2026, 7, 1),
                        "effective_to": date(2026, 6, 30) if rev == 1 else None,
                        "status": "superseded" if rev == 1 else "active",
                        "supersedes_policy_id": ids[0] if rev == 2 else None,
                        "owner_team_id": K.DOMAIN_TEAM[dom], "source_type": "synthetic",
                        "source_note": "Synthetic policy text written for this exercise; no external source."})
        rows.sort(key=lambda r: r["policy_id"])
        self.rows["policy_document"] = rows

    def _articles(self, n_articles):
        rng = self.rng
        topics = K.ordered_topics()
        if n_articles < 40:
            raise ValueError("--articles must be >= 40 (so that every category has at least one topic)")
        T = max(math.ceil(n_articles / 5), min(round(n_articles / 2.5), len(topics), n_articles // 2))
        T = max(1, min(T, len(topics)))
        extra = n_articles - 2 * T
        cand = [(i, "A") for i in range(T)] + [(i, "B") for i in range(T)] + [(i, "C") for i in range(T) if i % 4 == 1]
        if extra > len(cand) or extra < 0:
            raise ValueError("articles=%d not reachable with %d topics (need %d..%d)" % (n_articles, T, 2 * T, 2 * T + len(cand)))
        rng.shuffle(cand)
        picked = set(cand[:extra])
        pol_by_cat = {}
        for p in self.rows["policy_document"]:
            pol_by_cat.setdefault(p["category_id"], []).append(p)
        slot_dates = {"V1": date(2025, 9, 1), "A": date(2026, 3, 1), "R": date(2026, 7, 1), "B": date(2026, 10, 1), "C": date(2026, 12, 1)}
        arts = []
        for ti in range(T):
            dom, code, idx, title, pat, anchor = topics[ti]
            unit, allowed, sentence = K.PATTERNS[pat]
            slots = ["V1"] + (["A"] if (ti, "A") in picked else []) + ["R"] + (["B"] if (ti, "B") in picked else []) + (["C"] if (ti, "C") in picked else [])
            cat_id = "CAT-%s-%s" % (dom, code)
            topic_key = "%s-%s-%d" % (dom, code, idx)
            value = rng.choice(allowed)
            aud = "faculty" if "Instructor" in title else rng.choice(["both", "both", "both", "student"])
            versions = []
            for vi, slot in enumerate(slots):
                if vi > 0 and rng.random() < 0.85:
                    value = rng.choice([x for x in allowed if x != value])
                eff_from = slot_dates[slot]
                pol = pol_by_cat[cat_id][0 if eff_from < date(2026, 7, 1) else 1]
                fact = sentence.format(v=value, anchor=anchor)
                step = K.STEP_TEXT[dom][idx % 3]
                team_name = dict((t[0], t[1]) for t in K.TEAMS)[K.DOMAIN_TEAM[dom]]
                body = "%s: %s %s For help contact the %s through the support portal." % (title, fact, step, team_name)
                versions.append({"topic_key": topic_key, "version_no": vi + 1, "policy_id": pol["policy_id"], "category_id": cat_id,
                                 "title": title, "body": body, "key_fact_value": float(value), "key_fact_unit": unit,
                                 "effective_from": eff_from, "effective_to": None, "audience": aud, "_fact": fact, "_step": step,
                                 "_domain": dom, "_order": ti})
            for a, b in zip(versions, versions[1:]):
                a["effective_to"] = b["effective_from"] - timedelta(days=1)
            arts += versions
        arts.sort(key=lambda a: (a["_order"], a["version_no"]))
        for i, a in enumerate(arts, 1):
            a["article_id"] = "KB-%06d" % i
        by_topic = defaultdict(list)
        for a in arts:
            by_topic[a["topic_key"]].append(a)
        for vs in by_topic.values():
            for prev, cur in zip(vs, vs[1:]):
                cur["supersedes_article_id"] = prev["article_id"]
            vs[0]["supersedes_article_id"] = None
        for a in arts:
            if a["effective_from"] > AS_OF.date():
                a["status"] = "draft"
            elif a["effective_to"] is not None and a["effective_to"] < AS_OF.date():
                a["status"] = "superseded"
            else:
                a["status"] = "current"
        self.rows["knowledge_article"] = arts

    def _people(self):
        rng = self.rng
        n_req = max(60, round(self.n_tickets * 0.3))
        used = set()
        reqs = []
        for i in range(1, n_req + 1):
            learner = rng.random() < 0.87
            while True:
                first, last = rng.choice(K.FIRST), rng.choice(K.LAST)
                email = "%s.%s%d@example.edu" % (first.lower(), last.lower(), rng.randint(1, 99))
                if email not in used:
                    used.add(email)
                    break
            if learner:
                ey = rng.randint(2021, 2025)
                active_from = date(ey, 8, 1) + timedelta(days=rng.randint(0, 30))
            else:
                ey = None
                active_from = date(rng.randint(2012, 2024), 8, 1) + timedelta(days=rng.randint(0, 30))
            active_to, status = None, "active"
            if rng.random() < 0.05:
                active_to = date(2026, 2, 1) + timedelta(days=rng.randint(0, 240))
                status = "inactive"
            reqs.append({"requester_id": "REQ-%06d" % i, "role_id": "ROLE-LEARNER" if learner else "ROLE-INSTRUCTOR",
                         "full_name": "%s %s" % (first, last), "email": email, "department": rng.choice(K.DEPARTMENTS),
                         "program_level": rng.choice(["UG", "UG", "UG", "PG"]) if learner else None,
                         "enrollment_year": ey, "active_from": active_from, "active_to": active_to, "status": status})
        self.rows["requester"] = reqs
        scale = self.n_tickets / 5000.0
        staff, n = [], 1
        for tid, tname, tier, dom, base, role in K.TEAMS:
            cnt = max(2, round(base * scale))
            marked = False
            for j in range(cnt):
                first, last = rng.choice(K.FIRST), rng.choice(K.LAST)
                email = "%s.%s.staff%d@example.edu" % (first.lower(), last.lower(), n)
                active_to = None
                if cnt >= 4 and not marked and j == cnt - 1 and tier == 1:
                    marked = True
                    active_to = date(2026, 3, 1) + timedelta(days=rng.randint(0, 200))
                staff.append({"staff_id": "STF-%04d" % n, "full_name": "%s %s" % (first, last), "email": email, "role_id": role,
                              "team_id": tid, "active_from": date(2024, 1, 1) + timedelta(days=rng.randint(0, 600)), "active_to": active_to})
                n += 1
        self.rows["staff"] = staff

    def _auth_and_rules(self):
        auth, rrows, n = [], [], 1
        cats = self.rows["category"]
        for c in cats:
            dom = c["domain"]
            auth.append({"team_id": K.DOMAIN_TEAM[dom], "category_id": c["category_id"], "access_level": "handle"})
            auth.append({"team_id": K.ESCALATION_TEAM[dom], "category_id": c["category_id"], "access_level": "escalation"})
            for typ, team in (("initial", K.DOMAIN_TEAM[dom]), ("escalation", K.ESCALATION_TEAM[dom])):
                rrows.append({"rule_id": "RULE-%03d" % n, "category_id": c["category_id"], "team_id": team, "rule_type": typ,
                              "effective_from": date(2026, 1, 1), "effective_to": None})
                n += 1
        auth.sort(key=lambda r: (r["team_id"], r["category_id"]))
        self.rows["team_category_authorization"] = auth
        self.rows["routing_rule"] = rrows

    def _lookups(self):
        self.cat = {c["category_id"]: c for c in self.rows["category"]}
        self.prepared_cats = rules.prepare_categories(self.rows["category"])
        self.policy = {p["policy_id"]: p for p in self.rows["policy_document"]}
        self.team = {t["team_id"]: t for t in self.rows["team"]}
        self.articles = {a["article_id"]: a for a in self.rows["knowledge_article"]}
        self.art_by_topic = defaultdict(list)
        for a in self.rows["knowledge_article"]:
            self.art_by_topic[a["topic_key"]].append(a)
        topics = []
        seen = set()
        for a in self.rows["knowledge_article"]:
            if a["topic_key"] not in seen:
                seen.add(a["topic_key"])
                topics.append({"topic_key": a["topic_key"], "domain": a["_domain"], "title": a["title"], "category_id": a["category_id"]})
        self.topics = rules.prepare_topics(topics)
        self.topic_title = {t["topic_key"]: t["title"] for t in topics}
        self.topic_cat = {t["topic_key"]: t["category_id"] for t in topics}
        self.topics_by_leaf = defaultdict(list)
        for t in topics:
            self.topics_by_leaf[t["category_id"]].append(t["topic_key"])
        self.sla_by_prio = {s["priority"]: s for s in self.rows["sla_policy"]}
        self.rule_id = {(r["category_id"], r["rule_type"]): r["rule_id"] for r in self.rows["routing_rule"]}
        self.auth = {(a["team_id"], a["category_id"]): a["access_level"] for a in self.rows["team_category_authorization"]}
        self.staff_by_team = defaultdict(list)
        for s in self.rows["staff"]:
            self.staff_by_team[s["team_id"]].append(s)
        self.staff = {s["staff_id"]: s for s in self.rows["staff"]}
        self.requester = {r["requester_id"]: r for r in self.rows["requester"]}
        self.always_active = [r for r in self.rows["requester"] if r["active_to"] is None]
        self.initial_team = {c["category_id"]: K.DOMAIN_TEAM[c["domain"]] for c in self.rows["category"]}

    def pick_staff(self, team_id, at, salt):
        day = at.date()
        horizon = day + timedelta(days=45)
        cands = [s for s in self.staff_by_team[team_id] if s["active_from"] <= day and (s["active_to"] is None or horizon <= s["active_to"])]
        if not cands:
            cands = self.staff_by_team[team_id]
        return cands[(salt + zlib.crc32(team_id.encode())) % len(cands)]

    def term_for(self, d):
        best = None
        for t in self.rows["term"]:
            if t["start_date"] - timedelta(days=30) <= d <= t["end_date"]:
                if best is None or t["start_date"] > best["start_date"]:
                    best = t
        return best or self.rows["term"][-1]


# ===================================================================================================
# TICKET SPECIFICATION (latent truth)  -- drawn from its own RNG so re-simulation never changes the text
# ===================================================================================================
class Spec:
    pass


def build_calendar():
    days, w = [], []
    month_w = {1: 1.6, 2: 1.0, 3: 0.9, 4: 0.8, 5: 0.9, 6: 0.7, 7: 0.8, 8: 1.6, 9: 1.4, 10: 1.1}
    d = date(2026, 1, 5)
    while d <= date(2026, 10, 30):
        x = month_w[d.month] * (1.0 if d.weekday() < 5 else 0.12)
        if d in C.HOLIDAYS:
            x *= 0.1
        days.append(d)
        w.append(x)
        d += timedelta(days=1)
    cum, s = [], 0.0
    for x in w:
        s += x
        cum.append(s)
    return days, cum


CAL_DAYS, CAL_CUM = build_calendar()


def make_spec(G, no):
    rng = random.Random("%d:spec:%d" % (G.seed, no))
    sp = Spec()
    sp.no = no
    sp.tid = "TKT-2026-%06d" % no
    # --- created_at -------------------------------------------------------------------------------
    day = CAL_DAYS[bisect.bisect_left(CAL_CUM, rng.random() * CAL_CUM[-1])]
    if day.weekday() >= 5 or rng.random() > 0.88:
        hour = rng.choice(list(range(0, 9)) + list(range(17, 24))) if day.weekday() < 5 else rng.randint(8, 22)
    else:
        hour = rng.choices(range(9, 17), weights=[8, 12, 12, 9, 7, 10, 11, 6])[0]
    sp.created_at = datetime(day.year, day.month, day.day, hour, rng.randint(0, 59), rng.randint(0, 59))
    term = G.term_for(day)
    sp.term_id = term["term_id"]
    # --- requester (must be active on created date) ----------------------------------------------
    reqs = G.rows["requester"]
    for _ in range(40):
        r = reqs[rng.randrange(len(reqs))]
        if r["active_from"] <= day and (r["active_to"] is None or day <= r["active_to"]):
            break
    if not (r["active_from"] <= day and (r["active_to"] is None or day <= r["active_to"])):
        r = G.always_active[rng.randrange(len(G.always_active))]
    sp.requester = r
    instr = r["role_id"] == "ROLE-INSTRUCTOR"
    # --- kind ------------------------------------------------------------------------------------
    x = rng.random()
    sp.kind = "ambiguous" if x < 0.06 else "novel" if x < 0.09 else "followup" if x < 0.12 else "normal"
    dw = {"IT": .40, "REG": .25, "ACC": .30, "FIN": .05} if instr else {"FIN": .30, "REG": .28, "IT": .30, "ACC": .12}
    domain = rng.choices(list(dw), weights=list(dw.values()))[0]
    sp.channel = rng.choices(["portal", "email", "phone", "walk_in"], weights=[60, 25, 10, 5])[0]
    year, dept = rng.choice(K.YEAR_WORDS), r["department"]
    ctx = rng.choice(K.CONTEXT_INSTRUCTOR if instr else K.CONTEXT_LEARNER).format(year=year, dept=dept)
    closer = rng.choice(K.CLOSERS)
    # --- deadline --------------------------------------------------------------------------------
    sp.deadline = None
    if rng.random() < 0.25:
        cls = rng.choices(["near", "mid", "far"], weights=[14, 24, 62])[0]
        off = {"near": rng.randint(0, 2), "mid": rng.randint(3, 7), "far": rng.randint(8, 30)}[cls]
        sp.deadline = day + timedelta(days=off)
    dl_text = (" My deadline is %s." % sp.deadline.strftime("%d %B %Y")) if sp.deadline else ""
    urgent_text = rng.choices(K.URGENT_SUFFIX, weights=[1, 1, 1, 57])[0]
    sp.true_topic, sp.true_leaf, sp.true_domain = None, None, domain
    sp.ambiguous_template = None
    # --- text by kind ----------------------------------------------------------------------------
    if sp.kind == "ambiguous":
        text, tdom = rng.choice(K.AMBIGUOUS)
        if tdom:
            domain = tdom
        sp.true_domain = domain
        leaves = [l for l in G.topics_by_leaf if G.cat[l]["domain"] == domain]
        leaf = rng.choice(sorted(leaves))
        sp.true_topic = rng.choice(G.topics_by_leaf[leaf])
        sp.true_leaf = leaf
        sp.subject = rng.choice(K.AMBIGUOUS_SUBJECTS)
        sp.body = (text + " " + ctx + dl_text + urgent_text + " " + closer).replace("  ", " ").strip()
    elif sp.kind == "novel":
        sp.subject = rng.choice(K.NOVEL_SUBJECTS)
        sp.body = (rng.choice(K.NOVEL[domain]) + " " + ctx + dl_text + urgent_text + " " + closer).replace("  ", " ").strip()
    else:
        leaves = sorted(l for l in G.topics_by_leaf if G.cat[l]["domain"] == domain)
        if sp.kind == "followup":
            leaves = [l for l in leaves if not G.cat[l]["requires_human_review"]] or leaves
        weights = [{"01": .30, "02": .30, "03": .28, "04": .12}[l[-2:]] for l in leaves]
        leaf = rng.choices(leaves, weights=weights)[0]
        sp.true_leaf = leaf
        sp.true_topic = rng.choice(G.topics_by_leaf[leaf])
        title = G.topic_title[sp.true_topic]
        sp.subject = rng.choice(K.SUBJECT_FORMS).format(title=title, title_l=title.lower())
        frame = rng.choice(K.FRAMES).format(phrase=title.lower())
        marker = rng.choice(K.MARKERS[domain])
        sp.body = " ".join(x for x in [frame, marker, ctx, dl_text.strip(), urgent_text.strip(), closer] if x).strip()
    sp.subject = sp.subject[:200]
    sp.clarity = rng.choices(["clear", "vague", "none"], weights=[50, 25, 25])[0]
    sp.true_marker = rng.choice(K.MARKERS[sp.true_domain])
    return sp


# ===================================================================================================
# LIFE-CYCLE SIMULATOR
# ===================================================================================================
P_BREACH = {"urgent": 0.15, "high": 0.10, "normal": 0.08, "low": 0.06}
P_CONFIRM = 0.45
P_REOPEN = 0.04
P_STALL = 0.05          # tier-1 backlog: answered + confirmed but never marked resolved
P_T2_STALL = 0.06       # tier-2 backlog: escalated ticket waits for a decision


class Bundle:
    """All rows of one ticket (plain dicts, datetimes still python objects)."""

    def __init__(self, spec):
        self.spec = spec
        self.ticket = None
        self.messages, self.events, self.assigns, self.links = [], [], [], []
        self.sla = None
        self.feedback = None
        self.meta = {}
        self.applied = {}      # issue_type -> info dict


class Sim:
    def __init__(self, G, spec, flags=()):
        self.G, self.sp, self.flags = G, spec, set(flags)
        self.rng = random.Random("%d:sim:%d" % (G.seed, spec.no))
        self.frng = random.Random("%d:flag:%d" % (G.seed, spec.no))
        self.B = Bundle(spec)
        self.status = None
        self.ord = 0
        self.h = None
        self.cat_id = None
        self.escalated = False
        self.suppressed = False
        self.cited_first = None
        self.last_resolved_code = None
        self.stalled = False
        self.reqs = G.requester[spec.requester["requester_id"]]

    # ---- low-level recorders -------------------------------------------------------------------
    def ev(self, etype, at, to_status, actor_type, actor_id=None, details=None):
        frm = self.status
        if etype in ("recategorized", "reassigned"):
            to_status = frm
        else:
            assert to_status in C.TRANSITIONS[frm], "illegal %s->%s (%s) %s" % (frm, to_status, etype, self.sp.tid)
        self.ord += 1
        self.B.events.append({"_ord": self.ord, "ticket_id": self.sp.tid, "event_type": etype, "from_status": frm, "to_status": to_status,
                              "event_at": at, "actor_type": actor_type, "actor_id": actor_id, "details": details or {}})
        self.status = to_status

    def msg(self, mtype, at, sender, body, internal=False, cites=None):
        self.ord += 1
        key = "m%d" % self.ord
        stype, sid = sender
        self.B.messages.append({"_ord": self.ord, "_key": key, "ticket_id": self.sp.tid, "sender_type": stype,
                                "requester_id": sid if stype == "requester" else None, "staff_id": sid if stype == "staff" else None,
                                "message_type": mtype, "is_internal": 1 if internal else 0, "body": body, "created_at": at})
        for art, score, role in (cites or []):
            self.B.links.append({"_key": key, "article_id": art["article_id"], "cited_version_no": art["version_no"],
                                 "relevance_score": round(score, 2), "citation_role": role})
        return key

    def assign(self, at, team_id, atype, by="system", force_manual=False):
        for a in self.B.assigns:
            if a["unassigned_at"] is None:
                a["unassigned_at"] = at
        st = self.G.pick_staff(team_id, at, self.sp.no)
        rule = None
        if by == "system":
            rule = self.G.rule_id[(self.cat_id, "escalation" if atype == "escalation" else "initial")]
        self.B.assigns.append({"ticket_id": self.sp.tid, "team_id": team_id, "staff_id": st["staff_id"], "assignment_type": atype,
                               "category_id_at_assignment": self.cat_id, "routing_rule_id": rule, "assigned_at": at, "unassigned_at": None,
                               "assigned_by": by})
        self.h = st
        return st

    def escalate(self, at, reasons):
        """Escalate to the tier-2 team. In 'suppress' mode (injected defect) nothing happens."""
        if self.escalated:
            return False
        if "suppress_escalation" in self.flags:
            if not self.suppressed:
                self.suppressed = True
                self.B.applied["ESCALATION_NOT_TRIGGERED"] = {"entity_type": "ticket", "entity": self.sp.tid, "reasons": list(reasons)}
            return False
        dom = self.G.cat[self.cat_id]["domain"]
        team = K.ESCALATION_TEAM[dom]
        self.escalated = True
        self.assign(at, team, "escalation")
        self.ev("escalated", at, "escalated", "system", None, {"reasons": list(reasons), "to_team": team, "category": self.cat_id})
        labels = "; ".join(C.ESCALATION_REASONS[r] for r in reasons)
        self.msg("escalation_notice", at, ("system", None),
                 "Your request %s has been escalated to %s for further review. Reason: %s." % (self.sp.tid, self.G.team[team]["team_name"], labels))
        return True

    def staff_msg(self, mtype, at, body, cites=None, awaiting=False, internal=False):
        if self.status in ("assigned", "escalated"):
            self.ev("started", at, "in_progress", "staff", self.h["staff_id"])
        key = self.msg(mtype, at, ("staff", self.h["staff_id"]), body, internal, cites)
        if awaiting:
            self.ev("awaiting_requester", at, "awaiting_requester", "staff", self.h["staff_id"])
        return key

    def req_msg(self, mtype, at, body):
        key = self.msg(mtype, at, ("requester", self.sp.requester["requester_id"]), body)
        if self.status == "awaiting_requester":
            self.ev("requester_replied", at, "in_progress", "requester", self.sp.requester["requester_id"])
        return key

    def req_delay(self, at, lo=0.5, hi=30.0):
        t = at + timedelta(hours=self.rng.uniform(lo, hi))
        if t.hour < 7:
            t = t.replace(hour=8, minute=self.rng.randint(0, 59))
        elif t.hour >= 23:
            t = (t + timedelta(days=1)).replace(hour=8, minute=self.rng.randint(0, 59))
        return t

    def bh(self, at, lo, hi):
        return add_business_hours(at, self.rng.uniform(lo, hi))

    # ---- answer composition -----------------------------------------------------------------------
    def compose(self, art, at, kind="answer", coverage=1.0):
        rng, G = self.rng, self.G
        pol = G.policy[art["policy_id"]]
        team = G.team[self.h["team_id"]]["team_name"]
        first = self.sp.requester["full_name"].split()[0]
        if kind == "answer":
            tmpl = rng.choice(K.ANSWER_TEMPLATES)
        else:
            tmpl = rng.choice(K.DECISION_CITED)
        outcome = rng.choice(K.OUTCOMES)
        return tmpl.format(first=first, title_l=art["title"].lower(), policy_title=pol["title"], policy_id=art["policy_id"],
                           fact=art["_fact"], step=art["_step"], article_id=art["article_id"], v=art["version_no"],
                           staff=self.h["full_name"], team=team, outcome=outcome)

    def cited_answer(self, topic_key, at, coverage, kind="answer", awaiting=False):
        """Answer message that cites the article version in force at `at` (defect flags applied to the FIRST cited answer)."""
        G = self.G
        versions = G.art_by_topic[topic_key]
        art = rules.effective_article(versions, at)
        correct = art
        first_cited = self.cited_first is None
        if first_cited and "expired_cite" in self.flags and art["version_no"] > 1:
            prev = versions[art["version_no"] - 2]
            if prev["key_fact_value"] != art["key_fact_value"]:
                art = prev
        body = self.compose(art, at, kind, coverage)
        applied_unsupported = None
        if first_cited and "unsupported_claim" in self.flags:
            allowed = rules.numeric_tokens(art["body"])
            n = next(v for v in [175, 240, 365, 480, 650, 910, 1250] if str(v) not in allowed)
            sent = self.frng.choice(K.UNSUPPORTED_SENTENCES).format(n=n)
            body = body.replace("\n\nSource:", " " + sent + "\n\nSource:", 1) if "\n\nSource:" in body else body + " " + sent
            applied_unsupported = n
        key = self.staff_msg("answer", at, body, [(art, coverage, "primary")], awaiting=awaiting)
        if first_cited:
            self.cited_first = {"key": key, "article": art, "correct": correct, "topic_key": topic_key}
            if art is not correct:
                self.B.applied["EXPIRED_POLICY_CITATION"] = {"entity_type": "message", "key": key, "expected": correct["article_id"], "observed": art["article_id"]}
            if applied_unsupported is not None:
                self.B.applied["UNSUPPORTED_CLAIM"] = {"entity_type": "message", "key": key, "claim": str(applied_unsupported)}
        return art

    # ---- the life cycle ----------------------------------------------------------------------------
    def run(self):
        G, sp, rng = self.G, self.sp, self.rng
        t0 = sp.created_at
        text = sp.subject + " " + sp.body
        cls = rules.classify(text, G.prepared_cats)
        self.cat_id = cls["category_id"]
        cat = G.cat[self.cat_id]
        prio, preasons = rules.derive_priority(cat["default_priority"], t0, sp.deadline, text)
        self.priority = prio
        self.ev("created", t0, "new", "requester", sp.requester["requester_id"])
        self.msg("question", t0, ("requester", sp.requester["requester_id"]), sp.body)
        if sp.channel == "portal":
            pol0 = G.sla_by_prio[prio]
            self.msg("acknowledgement", t0 + timedelta(minutes=1), ("system", None),
                     "Thanks for contacting Student & Faculty Support. Request %s was received, categorised as '%s' with %s priority. "
                     "First response expected within %g business hours." % (sp.tid, cat["name"], prio, pol0["first_response_hours"]))
        self.ev("triaged", t0 + timedelta(minutes=2), "triaged", "system", None,
                {"rule": "KEYWORD-ROUTER-v1", "category": self.cat_id, "domain": cls["domain"], "ambiguous": cls["ambiguous"],
                 "reason": cls["reason"], "confidence": cls["confidence"], "domain_scores": cls["domain_scores"],
                 "priority": prio, "priority_reasons": preasons})
        # ---- routing ---------------------------------------------------------------------------
        team = G.initial_team[self.cat_id]
        by = "system"
        if "wrong_team" in self.flags and not cls["ambiguous"]:
            wrong = [t for t in ["TEAM-FIN", "TEAM-REG", "TEAM-IT", "TEAM-ACC"] if (t, self.cat_id) not in G.auth]
            team = self.frng.choice(wrong)
            by = "staff"
        at_assign = t0 + timedelta(minutes=3)
        asg_t = at_assign
        st = self.assign(asg_t, team, "initial", by=by)
        if by == "staff":
            self.B.assigns[-1]["routing_rule_id"] = None
            self.B.applied["UNAUTHORIZED_ROUTING"] = {"entity_type": "assignment", "index": len(self.B.assigns) - 1,
                                                      "expected": G.initial_team[self.cat_id], "observed": team}
        self.ev("assigned", asg_t, "assigned", "system" if by == "system" else "staff", None if by == "system" else st["staff_id"],
                {"team": team, "staff": st["staff_id"], "rule": self.B.assigns[-1]["routing_rule_id"]})
        # ---- SLA -------------------------------------------------------------------------------
        pol = G.sla_by_prio[prio]
        fr_due_true = add_business_hours(t0, pol["first_response_hours"])
        res_due_true = add_business_hours(t0, pol["resolution_hours"])
        fr_cal = t0 + timedelta(hours=pol["first_response_hours"])
        res_cal = t0 + timedelta(hours=pol["resolution_hours"])
        cal_diff = abs((fr_cal - fr_due_true).total_seconds()) >= 3600 or abs((res_cal - res_due_true).total_seconds()) >= 3600
        mode = "business"
        fr_due, res_due = fr_due_true, res_due_true
        if "calendar_clock" in self.flags and cal_diff:
            mode, fr_due, res_due = "calendar", fr_cal, res_cal
            self.B.applied["SLA_IGNORES_BUSINESS_HOURS"] = {"entity_type": "sla", "expected": fr_due_true, "observed": fr_due}
        self.sla_info = {"policy": pol, "mode": mode, "fr_due": fr_due, "res_due": res_due}
        # ---- first response timing -----------------------------------------------------------------
        m = rng.uniform(1.05, 2.5) if rng.random() < P_BREACH[prio] else rng.uniform(0.08, 0.9)
        fr_time = add_business_hours(at_assign, m * pol["first_response_hours"])
        e4 = prio == "urgent" and fr_time > fr_due_true
        if e4:
            self.escalate(fr_due_true, ["E4_URGENT_SLA_BREACH"])
        # ---- scenario ----------------------------------------------------------------------------
        if cls["ambiguous"]:
            scenario = "ambiguous"
        else:
            mt = rules.match_topic(text, G.topics, cls["domain"])
            if not mt["found"]:
                scenario = "novel"
            elif cat["requires_human_review"]:
                scenario = "human"
            elif sp.kind == "followup":
                scenario = "followup"
            else:
                scenario = "plain"
        self.B.meta.update({"scenario": scenario, "e4": e4, "cal_diff": cal_diff, "initial_cls": cls})
        getattr(self, "flow_" + scenario)(fr_time, cls, text, mt if scenario != "ambiguous" else None)
        self.finish()
        return self.B

    # ---- scenario flows -----------------------------------------------------------------------------
    def decision_msg(self, topic_key, at, cited):
        rng, G = self.rng, self.G
        if cited:
            return self.cited_answer(topic_key, at, 1.0, kind="decision", awaiting=True)
        first = self.sp.requester["full_name"].split()[0]
        body = rng.choice(K.DECISION_UNCITED).format(first=first, staff=self.h["full_name"], team=G.team[self.h["team_id"]]["team_name"])
        self.staff_msg("answer", at, body, awaiting=True)
        return None

    def finish_with_confirm(self, at, p_confirm, code, close_note_after=True):
        """After an answer that left the ticket awaiting_requester: confirmation -> resolved, or auto-resolve."""
        rng = self.rng
        stall = rng.random() < P_STALL
        if rng.random() < p_confirm:
            ct = self.req_delay(at)
            self.req_msg("confirmation", ct, rng.choice(K.CONFIRMS))
            rt = self.bh(ct, 0.3, 5)
            if stall:
                self.stalled = True
                return rt, False
            self.resolve(rt, code, "staff")
            return rt, True
        rt = at + timedelta(days=3)
        self.resolve(rt, code, "system")
        return rt, False

    def resolve(self, at, code, actor):
        self.ev("resolved", at, "resolved", actor, self.h["staff_id"] if actor == "staff" else None, {"resolution_code": code})
        self.last_resolved_code = code
        self.resolved_at = at

    def t2_stalls(self):
        """Escalated ticket never receives a decision before the snapshot (backlog)."""
        stall = self.rng.random() < P_T2_STALL
        if stall and self.escalated:
            self.stalled = True
            return True
        return False

    def code_for_escalated(self):
        return "resolved_by_staff" if "suppress_escalation" in self.flags and self.suppressed else "resolved_by_escalation"

    def flow_plain(self, fr_time, cls, text, mt):
        art = self.cited_answer(mt["topic_key"], fr_time, mt["coverage"], awaiting=True)
        rt, confirmed = self.finish_with_confirm(fr_time, P_CONFIRM, "answered_from_kb")
        if confirmed and self.rng.random() < P_REOPEN:
            ro = rt + timedelta(days=self.rng.uniform(1, 5))
            self.ev("reopened", ro, "in_progress", "requester", self.sp.requester["requester_id"])
            self.msg("reopen_request", ro, ("requester", self.sp.requester["requester_id"]), self.rng.choice(K.REOPEN))
            at = self.bh(ro, 1, 6)
            self.cited_answer(mt["topic_key"], at, mt["coverage"])
            self.resolve(at + timedelta(minutes=30), "answered_from_kb", "staff")
            self.B.meta["reopened"] = True

    def flow_human(self, fr_time, cls, text, mt):
        self.cited_answer(mt["topic_key"], fr_time, mt["coverage"])
        et = fr_time + timedelta(minutes=2)
        self.escalate(et, ["E3_HUMAN_DECISION_REQUIRED"])
        dt = self.bh(et, 3, 20)
        if self.t2_stalls():
            return
        self.decision_msg(mt["topic_key"], dt, True)
        self.finish_with_confirm(dt, 0.7, self.code_for_escalated())

    def flow_novel(self, fr_time, cls, text, mt):
        rng, G = self.rng, self.G
        first = self.sp.requester["full_name"].split()[0]
        body = rng.choice(K.NO_SOURCE_ANSWERS).format(first=first, staff=self.h["full_name"], team=G.team[self.h["team_id"]]["team_name"])
        self.staff_msg("answer", fr_time, body)
        et = fr_time + timedelta(minutes=2)
        self.escalate(et, ["E2_NO_POLICY_SOURCE"])
        dt = self.bh(et, 3, 20)
        if self.t2_stalls():
            return
        self.decision_msg(None, dt, False)
        self.finish_with_confirm(dt, 0.7, self.code_for_escalated())

    def flow_followup(self, fr_time, cls, text, mt):
        rng = self.rng
        self.cited_answer(mt["topic_key"], fr_time, mt["coverage"], awaiting=True)
        f1 = self.req_delay(fr_time, 1, 30)
        self.req_msg("followup", f1, rng.choice(K.FOLLOWUPS))
        a2 = self.bh(f1, 1, 6)
        self.cited_answer(mt["topic_key"], a2, mt["coverage"], awaiting=True)
        f2 = self.req_delay(a2, 1, 30)
        self.req_msg("followup", f2, rng.choice(K.FOLLOWUPS))
        et = f2 + timedelta(minutes=2)
        self.escalate(et, ["E5_REPEATED_FOLLOWUPS"])
        dt = self.bh(et, 3, 20)
        if self.t2_stalls():
            return
        self.decision_msg(mt["topic_key"], dt, True)
        self.finish_with_confirm(dt, 0.85, self.code_for_escalated())

    def flow_ambiguous(self, fr_time, cls, text, mt):
        rng, G, sp = self.rng, self.G, self.sp
        first = sp.requester["full_name"].split()[0]
        clar_t = fr_time
        self.staff_msg("clarification_request", clar_t, rng.choice(K.CLARIFICATION_REQUESTS).format(first=first), awaiting=True)
        clarity = sp.clarity
        reply = None
        if clarity == "clear":
            phrase = G.topic_title[sp.true_topic].lower()
            reply = rng.choice(K.CLEAR_REPLIES).format(phrase=phrase, marker=sp.true_marker)
            if rules.classify(text + " " + reply, G.prepared_cats)["ambiguous"]:
                clarity = "vague"          # the reply did not help the router -> behaves like a vague reply
        if clarity == "vague":
            reply = rng.choice(K.AMBIGUOUS_VAGUE_REPLIES)
        self.B.meta["clarity"] = clarity
        if clarity == "none":
            et = add_business_hours(clar_t, C.CLARIFICATION_WAIT_BH)
            self.escalate(et, ["E1_AMBIGUOUS_UNRESOLVED"])
            body = rng.choice(K.NO_RESPONSE_CLOSE).format(first=first, staff=self.h["full_name"], team=G.team[self.h["team_id"]]["team_name"])
            mt_ = self.bh(et, 3, 20)
            self.staff_msg("answer", mt_, body)
            self.resolve(mt_ + timedelta(minutes=1), "no_response_closed", "staff")
            return
        rt = self.req_delay(clar_t, 2, 30)
        self.req_msg("clarification_reply", rt, reply)
        if clarity == "vague":
            et = rt + timedelta(minutes=2)
            self.escalate(et, ["E1_AMBIGUOUS_UNRESOLVED"])
            dt = self.bh(et, 3, 20)
            if self.t2_stalls():
                return
            self.decision_msg(None, dt, False)
            self.finish_with_confirm(dt, 0.5, self.code_for_escalated())
            return
        # clarified: recategorise, re-route, answer from KB
        full = text + " " + reply
        cls2 = rules.classify(full, G.prepared_cats)
        old = self.cat_id
        self.cat_id = cls2["category_id"]
        t1 = rt + timedelta(minutes=1)
        self.ev("recategorized", t1, None, "system", None, {"from_category": old, "to_category": self.cat_id, "domain_scores": cls2["domain_scores"]})
        if not self.escalated:
            t2 = rt + timedelta(minutes=2)
            team = G.initial_team[self.cat_id]
            self.assign(t2, team, "reassignment")
            self.ev("reassigned", t2, None, "system", None, {"team": team, "staff": self.h["staff_id"]})
        mt2 = rules.match_topic(full, G.topics, cls2["domain"])
        at = self.bh(rt + timedelta(minutes=2), 1, 6)
        cat2 = G.cat[self.cat_id]
        if not mt2["found"]:
            self.flow_novel(at, cls2, full, mt2)
        elif cat2["requires_human_review"]:
            self.flow_human(at, cls2, full, mt2)
        else:
            self.cited_answer(mt2["topic_key"], at, mt2["coverage"], awaiting=True)
            self.finish_with_confirm(at, P_CONFIRM + 0.1, "answered_from_kb")

    # ---- finalise: close, cut at as-of, ticket row --------------------------------------------------
    def finish(self):
        B, sp = self.B, self.sp
        if self.status == "resolved":
            ct = self.resolved_at + timedelta(days=C.AUTO_CLOSE_DAYS)
            self.ev("closed", ct, "closed", "system")
            for a in B.assigns:
                if a["unassigned_at"] is None:
                    a["unassigned_at"] = ct
        # monotonic time check
        for lst, k in ((B.events, "event_at"), (B.messages, "created_at")):
            for x, y in zip(lst, lst[1:]):
                assert x[k] <= y[k], "time order violated for %s: %s then %s (%s)" % (sp.tid, x, y, k)
        # cut at as-of
        B.events = [e for e in B.events if e["event_at"] <= AS_OF]
        B.messages = [m for m in B.messages if m["created_at"] <= AS_OF]
        keys = {m["_key"] for m in B.messages}
        B.links = [l for l in B.links if l["_key"] in keys]
        kept = []
        for a in B.assigns:
            if a["assigned_at"] > AS_OF:
                continue
            if a["unassigned_at"] is not None and a["unassigned_at"] > AS_OF:
                a["unassigned_at"] = None
            kept.append(a)
        B.assigns = kept
        B.meta.update({"escalated": any(e["event_type"] == "escalated" for e in B.events), "suppressed": self.suppressed,
                       "cited_first": self.cited_first, "sla_info": self.sla_info, "priority": self.priority,
                       "last_resolved_code": self.last_resolved_code, "final_cat": self.cat_id})
        last = B.events[-1]
        B.ticket = {"ticket_id": sp.tid, "requester_id": sp.requester["requester_id"], "term_id": sp.term_id, "category_id": None,
                    "priority": self.priority, "status": last["to_status"], "channel": sp.channel, "subject": sp.subject, "body": sp.body,
                    "deadline_date": sp.deadline, "created_at": sp.created_at, "updated_at": last["event_at"],
                    "current_team_id": B.assigns[-1]["team_id"]}
        cat = rules_cat_at(B.events, self.cat_id)
        B.ticket["category_id"] = cat
        # anomalies whose entity was cut off cannot be labelled
        for k in list(B.applied):
            info = B.applied[k]
            if info.get("key") and info["key"] not in keys:
                del B.applied[k]


def rules_cat_at(events, fallback):
    cat = None
    for e in events:
        if e["event_type"] == "triaged":
            cat = e["details"]["category"]
        elif e["event_type"] == "recategorized":
            cat = e["details"]["to_category"]
    return cat or fallback


# ===================================================================================================
# GENERATOR
# ===================================================================================================
class Generator:
    def __init__(self, tickets, articles, messages, seed):
        self.n, self.A, self.M, self.seed = tickets, articles, messages, seed
        self.G = Master(seed, tickets, articles)
        self.bundles = {}

    def pass1(self):
        for no in range(1, self.n + 1):
            sp = make_spec(self.G, no)
            self.bundles[no] = Sim(self.G, sp).run()

    # ---- eligibility for each injected defect -------------------------------------------------------
    def eligible(self, issue):
        out = []
        for no, b in self.bundles.items():
            m = b.meta
            cf = m["cited_first"]
            if b.applied:
                continue
            if issue == "EXPIRED_POLICY_CITATION":
                if cf and cf["article"]["version_no"] > 1:
                    prev = self.G.art_by_topic[cf["topic_key"]][cf["article"]["version_no"] - 2]
                    if prev["key_fact_value"] != cf["article"]["key_fact_value"]:
                        out.append(no)
            elif issue == "UNAUTHORIZED_ROUTING":
                if m["scenario"] != "ambiguous":
                    out.append(no)
            elif issue == "UNSUPPORTED_CLAIM":
                if cf:
                    out.append(no)
            elif issue == "SLA_IGNORES_BUSINESS_HOURS":
                if m["cal_diff"]:
                    out.append(no)
            elif issue == "ESCALATION_NOT_TRIGGERED":
                if m["escalated"]:
                    out.append(no)
        return out

    FLAG = {"EXPIRED_POLICY_CITATION": "expired_cite", "UNAUTHORIZED_ROUTING": "wrong_team", "UNSUPPORTED_CLAIM": "unsupported_claim",
            "SLA_IGNORES_BUSINESS_HOURS": "calendar_clock", "ESCALATION_NOT_TRIGGERED": "suppress_escalation"}

    def pass2(self, share=0.012):
        rng = random.Random("%d:inject" % self.seed)
        quota = max(3, round(self.n * share))
        self.quota = quota
        for issue in C.ISSUE_TYPES:
            cands = sorted(self.eligible(issue))
            chosen = rng.sample(cands, min(quota, len(cands)))
            for no in sorted(chosen):
                sp = self.bundles[no].spec
                b = Sim(self.G, sp, [self.FLAG[issue]]).run()
                if issue in b.applied and len(b.applied) == 1:
                    self.bundles[no] = b
                # else: defect not applicable at runtime -> keep the baseline bundle untouched

    # ---- message volume, IDs, derived tables ------------------------------------------------------------
    def topup_and_number(self):
        rng = random.Random("%d:topup" % self.seed)
        total = sum(len(b.messages) for b in self.bundles.values())
        need = self.M - total
        self.baseline_messages = total
        if need < 0:
            raise ValueError("messages=%d is below the natural thread volume (%d) for %d tickets; raise --messages" % (self.M, total, self.n))
        elig = [no for no, b in sorted(self.bundles.items())
                if any(m["sender_type"] == "staff" and m["message_type"] in ("answer", "clarification_request") for m in b.messages)]
        if need > 3 * len(elig):
            raise ValueError("messages=%d is above the maximum (%d) for %d tickets" % (self.M, total + 3 * len(elig), self.n))
        counts = defaultdict(int)
        picks = []
        while len(picks) < need:
            no = rng.choice(elig)
            if counts[no] < 3:
                counts[no] += 1
                picks.append(no)
        ord_base = 100000
        for i, no in enumerate(sorted(picks)):
            b = self.bundles[no]
            frs = [m for m in b.messages if m["sender_type"] == "staff" and m["message_type"] in ("answer", "clarification_request")]
            start = frs[0]["created_at"]
            end = max(b.messages[-1]["created_at"], start + timedelta(minutes=5))
            end = min(end, AS_OF)
            span = max(60, int((end - start).total_seconds()))
            at = start + timedelta(seconds=rng.randint(1, span))
            at = min(at, AS_OF)
            asg = [a for a in b.assigns if a["assigned_at"] <= at and (a["unassigned_at"] is None or a["unassigned_at"] >= at)]
            st = asg[-1]["staff_id"] if asg else b.assigns[0]["staff_id"]
            b.messages.append({"_ord": ord_base + i, "_key": "n%d" % i, "ticket_id": b.ticket["ticket_id"], "sender_type": "staff", "requester_id": None,
                               "staff_id": st, "message_type": "internal_note", "is_internal": 1, "body": rng.choice(K.INTERNAL_NOTES), "created_at": at})
        # numbering
        for no, b in self.bundles.items():
            b.messages.sort(key=lambda m: (m["created_at"], m["_ord"]))
            idmap = {}
            for i, m in enumerate(b.messages, 1):
                m["seq_no"] = i
                m["message_id"] = "MSG-%s-%03d" % (b.ticket["ticket_id"], i)
                idmap[m["_key"]] = m["message_id"]
            for l in b.links:
                l["message_id"] = idmap[l["_key"]]
            for i, e in enumerate(b.events, 1):
                e["seq_no"] = i
                e["event_id"] = "EVT-%s-%03d" % (b.ticket["ticket_id"], i)
            for i, a in enumerate(b.assigns, 1):
                a["assignment_id"] = "ASG-%s-%02d" % (b.ticket["ticket_id"], i)
            for k, info in b.applied.items():
                if info.get("key"):
                    info["entity"] = idmap[info["key"]]
                elif info.get("index") is not None:
                    info["entity"] = b.assigns[info["index"]]["assignment_id"]
                elif info["entity_type"] == "sla":
                    info["entity"] = "SLA-%s" % b.ticket["ticket_id"]

    def derive(self):
        G = self.G
        for no, b in self.bundles.items():
            t = b.ticket
            si = b.meta["sla_info"]
            msgs = [m for m in b.messages]
            fr = next((m["created_at"] for m in msgs if m["sender_type"] == "staff" and not m["is_internal"]
                       and m["message_type"] in ("clarification_request", "answer")), None)
            resolved = None
            if t["status"] in ("resolved", "closed"):
                resolved = [e for e in b.events if e["event_type"] == "resolved"][-1]["event_at"]

            def stat(at, due):
                if at is not None:
                    return "met" if at <= due else "breached"
                return "breached" if AS_OF > due else "pending"
            b.sla = {"sla_id": "SLA-%s" % t["ticket_id"], "ticket_id": t["ticket_id"], "sla_policy_id": si["policy"]["sla_policy_id"],
                     "priority": t["priority"], "clock_mode": si["mode"], "clock_start": t["created_at"],
                     "first_response_due": si["fr_due"], "resolution_due": si["res_due"], "first_response_at": fr, "resolved_at": resolved,
                     "first_response_status": stat(fr, si["fr_due"]), "resolution_status": stat(resolved, si["res_due"]),
                     "first_response_business_hours": business_hours_between(t["created_at"], fr) if fr else None,
                     "resolution_business_hours": business_hours_between(t["created_at"], resolved) if resolved else None}
            if resolved:
                rng = random.Random("%d:fb:%d" % (self.seed, no))
                last_res = [e for e in b.events if e["event_type"] == "resolved"][-1]
                code = last_res["details"]["resolution_code"]
                reopen = sum(1 for e in b.events if e["event_type"] == "reopened")
                csat = fb_at = helpful = comment = None
                if rng.random() < 0.65:
                    fb_at = resolved + timedelta(days=rng.uniform(0.1, 3))
                    if fb_at <= AS_OF:
                        score = 4.4 - (0.9 if b.sla["resolution_status"] == "breached" else 0) - (0.5 if b.sla["first_response_status"] == "breached" else 0) \
                            - (0.6 if b.meta["escalated"] else 0) + rng.gauss(0, 0.7)
                        csat = int(min(5, max(1, round(score))))
                        helpful = 1 if csat >= 4 else 0
                        if csat <= 2 and rng.random() < 0.5:
                            comment = "Took too long and the answer did not fully help."
                        fb_at = fb_at.replace(microsecond=0)
                    else:
                        fb_at = None
                b.feedback = {"feedback_id": "FB-%s" % t["ticket_id"], "ticket_id": t["ticket_id"], "resolution_code": code, "resolved_at": resolved,
                              "resolution_calendar_hours": round((resolved - t["created_at"]).total_seconds() / 3600, 2),
                              "resolution_business_hours": business_hours_between(t["created_at"], resolved), "reopen_count": reopen,
                              "csat": csat, "answer_helpful": helpful, "comment": comment, "feedback_at": fb_at}

    # ---- assemble tables -------------------------------------------------------------------------------
    def tables(self):
        G = self.G
        rows = OrderedDict((k, list(v)) for k, v in G.rows.items())
        for k in ("ticket", "message", "message_article_link", "assignment", "sla", "ticket_event", "resolution_feedback"):
            rows[k] = []
        for no in sorted(self.bundles):
            b = self.bundles[no]
            rows["ticket"].append(b.ticket)
            rows["message"] += b.messages
            rows["message_article_link"] += b.links
            rows["assignment"] += b.assigns
            rows["sla"].append(b.sla)
            for e in b.events:
                rows["ticket_event"].append({**e, "details": e["details"]})
            if b.feedback:
                rows["resolution_feedback"].append(b.feedback)
        rows["message_article_link"].sort(key=lambda l: (l["message_id"], l["article_id"]))
        return rows

    def ground_truth(self):
        G = self.G
        ref = audit.Reference.from_master(G)
        gt, anomalies = [], []
        n_issue = 0
        for no in sorted(self.bundles):
            b = self.bundles[no]
            sp = b.spec
            t = b.ticket
            if sp.kind == "ambiguous":
                exp_cat = "CAT-GEN"
            elif sp.kind == "novel":
                exp_cat = "CAT-%s" % sp.true_domain
            else:
                exp_cat = sp.true_leaf
            exp_team = G.initial_team[exp_cat]
            exp_prio = rules.derive_priority(G.cat[exp_cat]["default_priority"], sp.created_at, sp.deadline, sp.subject + " " + sp.body)[0]
            reasons = audit.expected_escalation(ref, t, b.messages, b.sla, AS_OF)
            cf = b.meta["cited_first"]
            exp_art = cf["correct"]["article_id"] if cf else ""
            issue = ""
            ent = ""
            for it, info in b.applied.items():
                n_issue += 1
                issue, ent = it, info["entity"]
                obs = info.get("observed", info.get("claim", ""))
                exp = info.get("expected", "")
                if hasattr(obs, "strftime"):
                    obs = obs.strftime(C.FMT_DT)
                if hasattr(exp, "strftime"):
                    exp = exp.strftime(C.FMT_DT)
                desc = {"EXPIRED_POLICY_CITATION": "Answer cites a superseded article version (its effective_to is before the message date)",
                        "UNAUTHORIZED_ROUTING": "Initial assignment went to a team with no authorization for the ticket category",
                        "UNSUPPORTED_CLAIM": "Answer states a numeric fact that is not in the cited article",
                        "SLA_IGNORES_BUSINESS_HOURS": "SLA due times computed on a 24x7 wall clock instead of business hours",
                        "ESCALATION_NOT_TRIGGERED": "Escalation rule fired (%s) but no escalation happened" % ",".join(info.get("reasons", []))}[it]
                anomalies.append({"issue_id": "ISS-%06d" % n_issue, "ticket_id": t["ticket_id"], "issue_type": it, "entity_type": info["entity_type"],
                                  "entity_id": ent, "expected_value": exp, "observed_value": obs, "description": desc})
            gt.append({"ticket_id": t["ticket_id"], "scenario": b.meta["scenario"], "kind": sp.kind, "true_domain": sp.true_domain,
                       "true_topic_key": sp.true_topic or "", "expected_initial_category_id": exp_cat, "expected_initial_team_id": exp_team,
                       "expected_priority": exp_prio, "true_ambiguous": 1 if sp.kind == "ambiguous" else 0,
                       "expected_article_id": exp_art, "expected_escalation": 1 if reasons else 0,
                       "expected_escalation_reasons": "|".join(reasons), "issue_type": issue or "NONE", "issue_entity_id": ent})
        return gt, anomalies

    def build(self):
        self.pass1()
        self.pass2()
        self.topup_and_number()
        self.derive()
        return self.tables()


def main(argv=None):
    from . import export
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data/full")
    ap.add_argument("--tickets", type=int, default=C.DEFAULT_TICKETS)
    ap.add_argument("--articles", type=int, default=C.DEFAULT_ARTICLES)
    ap.add_argument("--messages", type=int, default=C.DEFAULT_MESSAGES)
    ap.add_argument("--seed", type=int, default=C.DEFAULT_SEED)
    a = ap.parse_args(argv)
    gen = Generator(a.tickets, a.articles, a.messages, a.seed)
    tables = gen.build()
    gt, anomalies = gen.ground_truth()
    cmd = "python -m datagen.generate --out %s --tickets %d --articles %d --messages %d --seed %d" % (a.out, a.tickets, a.articles, a.messages, a.seed)
    export.write_all(a.out, tables, gt, anomalies, {"command": cmd, "seed": a.seed, "tickets": a.tickets, "articles": a.articles, "messages": a.messages,
                                                       "baseline_messages_before_internal_notes": gen.baseline_messages,
                                                       "anomaly_quota_per_type": gen.quota})
    print("generated -> %s  (%s)" % (a.out, ", ".join("%s=%d" % (k, len(v)) for k, v in tables.items() if k in ("ticket", "message", "knowledge_article"))))
    print("anomalies labelled:", len(anomalies))
    return gen


if __name__ == "__main__":
    main()
