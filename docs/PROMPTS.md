# Prompt plan: building this project stage by stage with an AI assistant

**How to read this file (honest note).** The project was built with Claude in one long working session. Stage 0 is the message I actually sent. Stages 1-12 are the prompts I would use to rebuild it one stage at a time, in the same order the work was done. They are a reproducible plan for working with an AI assistant, not a transcript of twelve separate chats. Each stage lists what I check before moving on, because I should never accept generated code that I have not run.

---

## Stage 0 - The real starting message

> I was given this task in a hackathon round. They asked me to build the project. They also asked me to do the Zabbix thing, but my laptop is a company laptop and it will not install properly. It creates a candidateworkspace folder and they monitor everything, so all local executable files must be inside that folder and pushed to GitHub. I took permission from them and they told me to go ahead. Please give me the project in a way that I can properly understand it. They told me to use a three-tier architecture: frontend, backend and database connection. They also told me to check all the edge cases and validation cases.
>
> (problem statement attached)

---

## Stage 1 - Understand before building

> Before writing any code, read the problem statement again and tell me in simple words what they actually want. List the deliverables, the numbers I must hit (5,000 tickets, 200 articles, 20,000 messages, seed 20261022) and anything that is easy to miss. I want to be sure I understand it before we start.

**Check:** I can explain the five injected defects and the "ground truth must be separate" rule in my own words.

## Stage 2 - Choose a stack that works on my laptop

> My laptop is locked down, so I cannot install anything or run an installer. Suggest a stack that needs no installs, keeps everything inside one folder, and still gives a proper frontend, backend and database. Tell me the trade-offs of your choice.

**Check:** `python --version` works and nothing needs `pip install`.

## Stage 3 - Design the data model

> Design the tables for the 11 entities in the problem statement. Add bridge tables for the many-to-many relations and an event history table. Show me each table with its fields, types and constraints, and explain how the tables connect. I want one dictionary that everything else is generated from, so the schema and the documentation cannot disagree.

**Check:** every ID format from the statement (TKT-2026-000001, MSG-..., KB-000001, POL-..., SLA-...) is in the dictionary.

## Stage 4 - Write the rules before the data

> Before generating any data, write down the business rules as plain functions: business hours, SLA due times, how a ticket is classified into a category, how priority is chosen, how an article version is chosen for a date, and when a ticket must escalate. Keep them in one module so the generator, the app and the checker all use the same rules. Add small tests for the tricky parts, such as a ticket raised on Friday evening.

**Check:** the business-hours tests pass, including weekend, holiday and exactly-at-closing cases.

## Stage 5 - Build the clean baseline data generator

> Now write the synthetic data generator. First produce only valid, clean data: roles, terms, teams, categories, policy documents with several versions, articles, requesters, staff, tickets, messages, assignments, SLAs and feedback. Use the fixed seed 20261022 and make sure ticket number 7 never depends on ticket number 6. Derive SLA breaches and resolution hours from the timestamps instead of inventing them.

**Check:** exact row counts, and running it twice gives the same files.

## Stage 6 - Inject the five labelled defects

> Add a second pass that takes a small share of tickets and re-creates each with exactly one defect: citing an expired policy, routing to an unauthorized team, an unsupported claim, an SLA clock that ignores business hours, and a missing escalation. Save which tickets were changed in a separate ground-truth folder that the normal tables never reference.

**Check:** 60 of each type at 5,000 tickets, and no label column appears in any input table.

## Stage 7 - Validate the data and export it

> Write a validator with checks for primary keys, foreign keys, enums, ranges, date ordering, SLA arithmetic, lifecycle order, duplicates and ID formats. Export CSV, JSON and SQL, plus a manifest with row counts and SHA-256 checksums and a source manifest. Write a validation summary file.

**Check:** all checks pass, and I deliberately break one row to see the validator catch it.

## Stage 8 - Prove it is reproducible

> Write a script that regenerates the data twice with the same seed, in separate processes with different PYTHONHASHSEED values, and compares row counts and checksums. Add a third run with a different seed as a negative control.

**Check:** zero differing files between runs 1 and 2, and differences in run 3.

## Stage 9 - Build an independent auditor

> Write an auditor that looks only at the normal tables and finds the five defect types without reading the ground truth. Then write an evaluation step that compares its findings against the ground truth and prints precision and recall. Be honest in the notes about why the score is so high on synthetic data.

**Check:** the auditor never imports the ground-truth files, only the evaluation does.

## Stage 10 - Database layer and backend

> Now the three tiers. Build the data tier first: load the CSVs into SQLite with foreign keys on, and put every SQL statement in one repository file. Then build the backend with a service layer for the rules and an API layer for the HTTP routes. I need endpoints to create a ticket, preview routing, list and view tickets, send messages, change status, assign, give feedback, view articles, metrics and the audit. Return clear JSON error codes.

**Check:** I can call `/api/health` and `/api/tickets` in the browser, and the first start builds `app.db`.

## Stage 11 - Edge cases and validation in the backend

> Go through the backend and enforce every edge case. Reject duplicate tickets within 24 hours, bad input, oversized bodies and unknown ids. Reject answers that cite an expired article, have no citation when a source exists, or state a number the source does not contain. Reject assignment to an unauthorized team, illegal status transitions, resolving before a reply, and resolving while an escalation rule has fired. Write a test for each case.

**Check:** the full test suite passes, and I try three of the cases by hand in the app.

## Stage 12 - Frontend

> Build the frontend with plain HTML, CSS and JavaScript. I need a dashboard, a tickets table with filters, a new-ticket page with a routing preview that explains its decision, a ticket page showing the conversation, history and assignments with staff actions, a knowledge-base page showing article versions, and an audit and evaluation page. Make sure nothing a user types can inject HTML.

**Check:** I create a ticket in the browser, see it in the table, answer it, resolve it and rate it.

## Stage 13 - Documentation I can defend

> Write the README with exact run commands, then an architecture document, a rules document, an edge-case list, a generator description and a generated data dictionary. Also write a plain-language guide that explains the whole project to me, with one ticket followed from start to finish and the questions a reviewer is likely to ask.

**Check:** I can explain every file's job without opening it.

## Stage 14 - Final check and submission

> Give me a final checklist. Run the tests, validate the data, regenerate twice and compare, start the server from a fresh copy of the folder, and confirm the README commands work exactly as written. Tell me anything that is still weak or that I should be honest about when I present it.

**Check:** the run works from a fresh unzip, then I commit and push to a public GitHub repo before the deadline.
