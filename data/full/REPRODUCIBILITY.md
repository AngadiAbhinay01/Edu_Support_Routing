# Reproducibility report

Seed **20261022**, scale: 5000 tickets / 200 articles / 20000 messages.

| run | seed | PYTHONHASHSEED | tickets | messages | files hashed |
|---|---:|---:|---:|---:|---:|
| 1 | 20261022 | 1 | 5000 | 20000 | 43 |
| 2 | 20261022 | 777 | 5000 | 20000 | 43 |
| 3 | 20261023 | 1 | 5000 | 20000 | 43 |

* Row counts identical for run 1 vs run 2: **True**
* Files whose SHA-256 differs between run 1 and run 2: **0** of 43
* Negative control (seed+1) changes 24 of 43 files, so the checksums are sensitive.

**Result: REPRODUCIBLE**

Checksums of run 1 (excerpt):

* `csv/assignment.csv` `1f663a523a8ee170`
* `csv/category.csv` `30f94c90e97f9ca9`
* `csv/holiday.csv` `25fe65c3eb5deda1`
* `csv/knowledge_article.csv` `6563902c53fb65e5`
* `csv/message.csv` `80b914f06adac44a`
* `csv/message_article_link.csv` `f09dec5decefb674`
* `csv/policy_document.csv` `bfb6ad345a827f0f`
* `csv/requester.csv` `3a5ae4b1568a4a13`
* `csv/resolution_feedback.csv` `2e6f343cdd73d22c`
* `csv/role.csv` `199524c500066392`
* `csv/routing_rule.csv` `91060fcb690b28ca`
* `csv/sla.csv` `d108a2498aebbd21`
