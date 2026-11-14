"""Static master data & text templates for the generator (all synthetic)."""
from datetime import date

ROLES = [
    ("ROLE-LEARNER", "Learner", "learner", 1, 0, "Enrolled student who raises requests"),
    ("ROLE-INSTRUCTOR", "Instructor", "instructor", 1, 0, "Faculty member who raises requests"),
    ("ROLE-ACADEMIC-ADMIN", "Academic Administrator", "academic_administrator", 0, 1, "Takes tier-2 decisions on escalations"),
    ("ROLE-SUPPORT-STAFF", "Support Staff", "support_staff", 0, 1, "Tier-1 desk agent"),
    ("ROLE-PLATFORM-ADMIN", "Platform Administrator", "platform_administrator", 0, 1, "Handles platform / security escalations"),
]

TERMS = [
    # id, name, start, end, reg_opens, add_drop, aid_deadline
    ("TERM-2025-FALL", "Fall 2025", date(2025, 8, 25), date(2025, 12, 12), date(2025, 7, 14), date(2025, 9, 8), date(2025, 10, 15)),
    ("TERM-2026-SPR", "Spring 2026", date(2026, 1, 12), date(2026, 5, 8), date(2025, 11, 17), date(2026, 1, 26), date(2026, 3, 1)),
    ("TERM-2026-SUM", "Summer 2026", date(2026, 5, 18), date(2026, 8, 7), date(2026, 4, 6), date(2026, 5, 29), date(2026, 6, 19)),
    ("TERM-2026-FALL", "Fall 2026", date(2026, 8, 24), date(2026, 12, 11), date(2026, 7, 13), date(2026, 9, 7), date(2026, 10, 14)),
    ("TERM-2027-SPR", "Spring 2027", date(2027, 1, 11), date(2027, 5, 7), date(2026, 11, 16), date(2027, 1, 25), date(2027, 2, 26)),
]

# team_id, name, tier, domain, base staff count, role
TEAMS = [
    ("TEAM-FIN", "Financial Aid Office", 1, "FIN", 6, "ROLE-SUPPORT-STAFF"),
    ("TEAM-REG", "Registrar Support", 1, "REG", 6, "ROLE-SUPPORT-STAFF"),
    ("TEAM-IT", "IT Service Desk", 1, "IT", 8, "ROLE-SUPPORT-STAFF"),
    ("TEAM-ACC", "Accessibility Services", 1, "ACC", 4, "ROLE-SUPPORT-STAFF"),
    ("TEAM-TRIAGE", "General Support Desk", 1, "GEN", 6, "ROLE-SUPPORT-STAFF"),
    ("TEAM-ADMIN", "Academic Administration", 2, None, 5, "ROLE-ACADEMIC-ADMIN"),
    ("TEAM-PLAT", "Platform Administration", 2, None, 4, "ROLE-PLATFORM-ADMIN"),
]
DOMAIN_TEAM = {"FIN": "TEAM-FIN", "REG": "TEAM-REG", "IT": "TEAM-IT", "ACC": "TEAM-ACC", "GEN": "TEAM-TRIAGE"}
ESCALATION_TEAM = {"FIN": "TEAM-ADMIN", "REG": "TEAM-ADMIN", "ACC": "TEAM-ADMIN", "IT": "TEAM-PLAT", "GEN": "TEAM-ADMIN"}

DOMAIN_NAMES = {"FIN": "Financial Aid", "REG": "Registration", "IT": "IT Support", "ACC": "Accessibility"}

# Domain-level (level 1) generic keywords: the evidence a ticket is "about" a domain
DOMAIN_KEYWORDS = {
    "FIN": ["financial aid", "aid"],
    "REG": ["registrar", "registration", "enrollment"],
    "IT": ["it helpdesk", "it support", "university account"],
    "ACC": ["accessibility", "accommodation", "disability", "disability services"],
}

# Leaf categories: (domain, code, name, default_priority, requires_human, [specific keywords])
LEAVES = [
    ("FIN", "01", "Aid Eligibility & Applications", "normal", 0, ["scholarship eligibility", "aid application", "grant", "work-study", "loan"]),
    ("FIN", "02", "Verification & Documents", "normal", 0, ["verification", "income document", "tax return", "dependency"]),
    ("FIN", "03", "Disbursement & Refunds", "normal", 0, ["scholarship payout", "disbursement", "refund", "tuition", "bursar", "payment"]),
    ("FIN", "04", "Appeals & Satisfactory Progress", "high", 1, ["satisfactory academic progress", "suspension", "probation", "reinstatement", "special circumstances"]),
    ("REG", "01", "Add/Drop & Enrollment", "normal", 0, ["course add", "course drop", "waitlist", "withdrawal", "credit load"]),
    ("REG", "02", "Transcripts & Records", "low", 0, ["transcript", "enrollment verification", "student record", "name change"]),
    ("REG", "03", "Holds & Clearance", "normal", 0, ["registration hold", "advising hold", "library fine", "immunization", "graduation clearance"]),
    ("REG", "04", "Overrides & Grade Appeals", "high", 1, ["prerequisite", "override", "grade appeal", "petition", "course repeat"]),
    ("IT", "01", "Account & Password", "normal", 0, ["password", "mfa", "multi-factor", "mailbox", "software license", "locked account"]),
    ("IT", "02", "LMS Access", "normal", 0, ["lms", "course site", "course shell", "gradebook", "upload limit"]),
    ("IT", "03", "Network & Wi-Fi", "low", 0, ["wifi", "vpn", "network", "bandwidth", "guest network"]),
    ("IT", "04", "Security Incidents", "high", 1, ["phishing", "compromised", "unauthorized access", "suspicious login", "lost device", "security report"]),
    ("ACC", "01", "Exam Accommodations", "normal", 0, ["extended time", "testing center", "exam room", "exam break", "interpreter"]),
    ("ACC", "02", "Accessible Materials", "normal", 0, ["accessible", "screen reader", "captions", "alt text"]),
    ("ACC", "03", "Assistive Technology", "normal", 0, ["assistive", "text-to-speech", "adaptive"]),
    ("ACC", "04", "Accommodation Requests", "high", 1, ["accommodation request", "accommodation plan", "accommodation appeal", "documentation requirements", "disability documentation"]),
]

SLA_POLICIES = [
    # id, priority, first_response_h, resolution_h
    ("SLAP-URGENT", "urgent", 1, 16),
    ("SLAP-HIGH", "high", 4, 40),
    ("SLAP-NORMAL", "normal", 8, 72),
    ("SLAP-LOW", "low", 16, 120),
]

# ---- value patterns for numeric policy facts ------------------------------------------------------
PATTERNS = {
    "DEADLINE": ("calendar days", list(range(5, 46)), "The deadline is {v} calendar days {anchor}."),
    "PROCESS": ("business days", list(range(2, 16)), "Requests are processed within {v} business days."),
    "FEE": ("USD", list(range(10, 121, 5)), "The standard fee is ${v}."),
    "LIMIT": ("requests per term", [1, 2, 3, 4, 5], "You may submit up to {v} requests per term."),
    "DOCS": ("documents", [1, 2, 3, 4], "You must provide {v} supporting documents."),
    "HOURS": ("business hours", list(range(4, 49, 2)), "Requests of this type are resolved within {v} business hours."),
    "CREDITS": ("credits per term", list(range(15, 25)), "The maximum course load is {v} credits per term."),
    "DEVICES": ("devices", [2, 3, 4, 5], "You may register up to {v} devices."),
    "GB": ("GB", list(range(5, 101, 5)), "The limit is {v} GB."),
    "MB": ("MB", list(range(50, 501, 50)), "The upload limit is {v} MB per file."),
    "DAYS": ("days", list(range(3, 31)), "Access is granted for {v} days."),
}
STEP_TEXT = {
    "FIN": ["Submit the form in the Student Finance Portal under 'My Aid'.",
            "Upload the required items in the Student Finance Portal.",
            "Contact the Financial Aid Office through the support portal if anything is unclear."],
    "REG": ["Submit the request in the Student Records Portal.",
            "Complete the form in the Registrar self-service page.",
            "Contact Registrar Support through the support portal for exceptions."],
    "IT": ["Follow the self-service guide on the IT portal first.",
           "Raise the request through the IT Service Desk portal.",
           "Keep your university ID ready when contacting the IT Service Desk."],
    "ACC": ["Submit the request in the Accessibility Services portal.",
            "Share your accommodation plan reference with Accessibility Services.",
            "Contact Accessibility Services through the support portal to discuss options."],
}

# 5 topics per leaf: (title, pattern, anchor).  ORDER matters: interleaved so scaled-down datasets cover all leaves.
TOPICS = {
    ("FIN", "01"): [("Financial aid application deadline", "DEADLINE", "after the term start date"),
                    ("Scholarship eligibility review", "PROCESS", ""),
                    ("Need-based grant eligibility", "DOCS", ""),
                    ("Student loan application", "LIMIT", ""),
                    ("Work-study placement application", "DEADLINE", "after the term start date")],
    ("FIN", "02"): [("Aid verification documents", "DOCS", ""),
                    ("Income document submission", "DEADLINE", "after the verification notice"),
                    ("Tax return documents for aid", "PROCESS", ""),
                    ("Dependency status verification", "DOCS", ""),
                    ("Verification status review", "PROCESS", "")],
    ("FIN", "03"): [("Aid disbursement schedule", "PROCESS", ""),
                    ("Tuition refund request", "PROCESS", ""),
                    ("Refund payment to bank account", "PROCESS", ""),
                    ("Late tuition payment fee", "FEE", ""),
                    ("Scholarship payout timeline", "PROCESS", "")],
    ("FIN", "04"): [("Satisfactory academic progress appeal", "DEADLINE", "after the notice date"),
                    ("Aid suspension appeal", "DOCS", ""),
                    ("Financial aid probation plan", "LIMIT", ""),
                    ("Special circumstances aid review", "PROCESS", ""),
                    ("Aid reinstatement request", "DEADLINE", "after the suspension notice")],
    ("REG", "01"): [("Course add deadline", "DEADLINE", "after the term start date"),
                    ("Course drop deadline", "DEADLINE", "after the term start date"),
                    ("Waitlist enrollment process", "PROCESS", ""),
                    ("Late course withdrawal fee", "FEE", ""),
                    ("Course credit load limit", "CREDITS", "")],
    ("REG", "02"): [("Official transcript request", "PROCESS", ""),
                    ("Transcript delivery fee", "FEE", ""),
                    ("Enrollment verification letter", "PROCESS", ""),
                    ("Student record correction", "DOCS", ""),
                    ("Name change on records", "DOCS", "")],
    ("REG", "03"): [("Registration hold removal", "PROCESS", ""),
                    ("Advising hold clearance", "PROCESS", ""),
                    ("Library fine hold", "FEE", ""),
                    ("Immunization record hold", "DEADLINE", "after the hold notice"),
                    ("Graduation clearance review", "PROCESS", "")],
    ("REG", "04"): [("Prerequisite override request", "DOCS", ""),
                    ("Class capacity override", "LIMIT", ""),
                    ("Grade appeal petition", "DEADLINE", "after the grade posting date"),
                    ("Course repeat petition", "LIMIT", ""),
                    ("Late registration petition", "FEE", "")],
    ("IT", "01"): [("Password reset request", "HOURS", ""),
                   ("Locked account recovery", "HOURS", ""),
                   ("Multi-factor authentication setup", "DEVICES", ""),
                   ("Email mailbox quota", "GB", ""),
                   ("Software license request", "PROCESS", "")],
    ("IT", "02"): [("LMS course site access", "HOURS", ""),
                   ("Course shell enrollment sync", "HOURS", ""),
                   ("Gradebook visibility issue", "HOURS", ""),
                   ("Assignment upload limit", "MB", ""),
                   ("Instructor course site request", "PROCESS", "")],
    ("IT", "03"): [("Campus wifi connection", "DEVICES", ""),
                   ("VPN access request", "PROCESS", ""),
                   ("Guest network access", "DAYS", ""),
                   ("Dorm network device registration", "DEVICES", ""),
                   ("Wifi bandwidth quota", "GB", "")],
    ("IT", "04"): [("Phishing email report", "HOURS", ""),
                   ("Compromised account response", "HOURS", ""),
                   ("Unauthorized access investigation", "PROCESS", ""),
                   ("Lost device security report", "HOURS", ""),
                   ("Suspicious login alert", "HOURS", "")],
    ("ACC", "01"): [("Exam extended time accommodation", "DEADLINE", "before the exam date"),
                    ("Testing center scheduling", "DEADLINE", "before the exam date"),
                    ("Separate exam room request", "DEADLINE", "before the exam date"),
                    ("Exam break time accommodation", "DEADLINE", "before the exam date"),
                    ("Exam interpreter booking", "DEADLINE", "before the exam date")],
    ("ACC", "02"): [("Accessible textbook formats", "PROCESS", ""),
                    ("Lecture captions request", "HOURS", ""),
                    ("Screen reader compatible documents", "PROCESS", ""),
                    ("Alt text for course images", "PROCESS", ""),
                    ("Accessible slides request", "HOURS", "")],
    ("ACC", "03"): [("Assistive technology loan", "DAYS", ""),
                    ("Text-to-speech software access", "PROCESS", ""),
                    ("Adaptive keyboard loan", "DAYS", ""),
                    ("Assistive software training", "LIMIT", ""),
                    ("Assistive device repair", "PROCESS", "")],
    ("ACC", "04"): [("Accommodation request intake", "PROCESS", ""),
                    ("Disability documentation requirements", "DOCS", ""),
                    ("Accommodation plan renewal", "DEADLINE", "before the plan expiry date"),
                    ("Accommodation appeal process", "DEADLINE", "after the decision notice"),
                    ("Temporary accommodation request", "DAYS", "")],
}


def ordered_topics():
    """Interleaved (round-robin across the 16 leaves) list of (domain, leaf_code, idx, title, pattern, anchor)."""
    out = []
    for idx in range(5):
        for (dom, code), lst in TOPICS.items():
            t, pat, anchor = lst[idx]
            out.append((dom, code, idx + 1, t, pat, anchor or "after the term start date"))
    return out


# ---- people ---------------------------------------------------------------------------------------
FIRST = ["Aarav", "Vivaan", "Aditya", "Arjun", "Ishaan", "Kabir", "Rohan", "Karthik", "Siddharth", "Rahul", "Ananya", "Diya", "Isha",
         "Kavya", "Meera", "Neha", "Priya", "Riya", "Sneha", "Tanvi", "Maya", "Noah", "Liam", "Emma", "Olivia", "Sofia", "Lucas",
         "Mateo", "Amara", "Chen", "Wei", "Yuki", "Hana", "Omar", "Fatima", "Zara", "Ibrahim", "Leila", "Daniel", "Grace"]
LAST = ["Sharma", "Verma", "Reddy", "Rao", "Nair", "Iyer", "Menon", "Gupta", "Patel", "Singh", "Das", "Bose", "Kulkarni", "Joshi",
        "Chopra", "Malhotra", "Khan", "Ahmed", "Fernandes", "Dsouza", "Thomas", "George", "Wang", "Li", "Tanaka", "Kim", "Silva",
        "Garcia", "Brown", "Wilson", "Taylor", "Clark", "Lewis", "Walker", "Young"]
DEPARTMENTS = ["Computer Science", "Electronics", "Mechanical Engineering", "Civil Engineering", "Business Administration", "Economics",
               "Physics", "Chemistry", "Mathematics", "Biotechnology", "English Literature", "Psychology"]
YEAR_WORDS = ["first-year", "second-year", "third-year", "final-year"]

# ---- ticket text ------------------------------------------------------------------------------------
FRAMES = [
    "Hello, I have a question about {phrase}.",
    "Could you please explain {phrase}?",
    "I need help with {phrase} and I am not sure what the current rule is.",
    "Requesting guidance regarding {phrase}.",
    "Can someone confirm the current policy on {phrase}?",
]
MARKERS = {
    "FIN": ["This is about my financial aid.", "It affects my financial aid file.", "I want to confirm this for my aid package."],
    "REG": ["This concerns my registration with the registrar.", "The registrar should check my registration.", "Please look into my registration and enrollment."],
    "IT": ["I already contacted the IT helpdesk and IT support about this.", "Please route this to the IT helpdesk and IT support.", "The IT support page sent me to the IT helpdesk."],
    "ACC": ["This is an accessibility and disability services matter.", "It relates to my accessibility needs and disability services.", "This is an accessibility and accommodation matter for me."],
}
CONTEXT_LEARNER = ["I am a {year} student in {dept}.", "I study {dept} this term.", "I am enrolled in {dept}.", ""]
CONTEXT_INSTRUCTOR = ["I teach {dept} courses this term.", "A student in my {dept} class asked about this.", "I am faculty in {dept}.", ""]
CLOSERS = ["Thank you.", "Please advise on the next steps.", "I would appreciate a reply soon.", "Thanks in advance.", ""]
SUBJECT_FORMS = ["{title}", "Question: {title}", "Help with {title_l}", "{title} - need guidance"]
URGENT_SUFFIX = [" This is urgent.", " Please reply asap.", " I need this immediately.", ""]

# Ambiguous requests: (text, implied domain or None for random)
AMBIGUOUS = [
    ("Something is wrong with my account and I do not know who handles it.", None),
    ("I need help from someone as soon as possible. Please call me back.", None),
    ("I was told to write here but I am not sure what to ask.", None),
    ("There is some kind of problem and nobody has replied to me yet.", None),
    ("Need assistance with the portal and related matters, please contact me.", None),
    ("My password and mfa stopped working, and my tuition refund seems missing too. Which office should I contact?", "FIN"),
    ("I need an official transcript for my scholarship eligibility, and my vpn also fails.", "REG"),
    ("The wifi in the testing center is unusable during my exam.", "ACC"),
    ("Please help with my course add and also a screen reader problem on the lms.", "REG"),
]
AMBIGUOUS_SUBJECTS = ["Need help", "Question", "Please assist", "Issue", "Urgent matter please read", "Not sure who to ask"]
AMBIGUOUS_VAGUE_REPLIES = ["I am not sure how to explain it better, it is just not working.",
                           "I do not know the details, I only know there is a problem.",
                           "Same as before, please just look into it."]

# Requests without matching KB article (domain recognised, topic not covered)
NOVEL = {
    "FIN": ["I need guidance on my financial aid for a study abroad exchange semester."],
    "REG": ["The registrar should advise how my registration works for a joint degree program."],
    "IT": ["I contacted the IT helpdesk and IT support about a smart classroom projector that will not start."],
    "ACC": ["This is an accessibility and disability services matter about transport for a field trip."],
}
NOVEL_SUBJECTS = ["Unusual situation", "Special case", "Guidance needed for a special case"]

FOLLOWUPS = ["I tried that but it is still not working. Could you check again?",
             "That did not fully answer my question. Can you clarify?",
             "I followed the steps but nothing changed on my side."]
CONFIRMS = ["Thank you, that answers my question.", "Thanks, this resolves it for me.", "Great, thank you for the quick help."]
REOPEN = ["The problem has come back, please reopen my request.", "I am still facing this issue, could you reopen the ticket?"]
INTERNAL_NOTES = ["Reviewed the request and verified the applicable policy article.",
                  "Checked the requester's record; nothing unusual found.",
                  "Contacted the department coordinator for confirmation.",
                  "Waiting for confirmation from the owning team.",
                  "Documented the case details for the escalation reviewer."]
CLARIFICATION_REQUESTS = ["Hello {first}, thank you for contacting us. Could you tell us exactly what you need help with and which office or system it relates to?",
                          "Hello {first}, we could not tell what this request is about. Please describe the issue in a few sentences so we can route it correctly."]
CLEAR_REPLIES = ["Thanks for asking. My question is about {phrase}. {marker}", "Sorry for the confusion. I need help with {phrase}. {marker}"]
ANSWER_TEMPLATES = [
    "Hello {first},\n\nThanks for your question about {title_l}. According to {policy_title} ({policy_id}): {fact} {step}\n\nSource: {article_id} (version {v}).\n\n{staff}, {team}",
    "Hi {first},\n\nHere is what the current policy says on {title_l} ({policy_id}). {fact} {step}\n\nReference: {article_id}, version {v}.\n\nRegards,\n{staff} - {team}",
    "Dear {first},\n\nOn {title_l}: {fact} {step} This is based on {policy_title}.\n\nSource: {article_id} (version {v}).\n\n{staff}, {team}",
]
NO_SOURCE_ANSWERS = ["Hello {first},\n\nThank you for your request. We could not find a published policy article that covers your situation, so we are asking a senior colleague to review it.\n\n{staff}, {team}"]
DECISION_CITED = ["Hello {first},\n\nI reviewed your case as {team}. Under {policy_title} ({policy_id}) the applicable rule is: {fact} Your case has been {outcome}.\n\nSource: {article_id} (version {v}).\n\n{staff}, {team}"]
DECISION_UNCITED = ["Hello {first},\n\nI reviewed the details with the relevant offices and arranged the next steps. You will receive an e-mail shortly with the outcome.\n\n{staff}, {team}"]
NO_RESPONSE_CLOSE = ["Hello {first},\n\nWe could not determine what this request is about and did not hear back, so we are closing it. Please submit a new request with more details.\n\n{staff}, {team}"]
OUTCOMES = ["approved", "forwarded to the committee", "declined under the current policy", "scheduled for review"]
UNSUPPORTED_SENTENCES = ["Additionally, a fee waiver of ${n} will be credited to your account automatically.",
                         "You will also receive an expedited fast-track within {n} hours without any further steps.",
                         "A one-time exception allowing {n} additional days has already been applied for you."]
