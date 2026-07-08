"""
State & Federal AI Legislation Tracker -- web app.

Every endpoint queries data/ai_legislation.db live, at request time. Nothing
here reads from a precomputed/static export -- rebuilding the DB (re-running
the scripts/build_*.py scripts) changes what these endpoints return on the
very next request, with no redeploy step.

Descriptive statistics only. No endpoint here ranks, scores, or comments on
the merits of any individual bill -- only aggregate counts/rates/breakdowns.
"""
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify, render_template

from reference_data import (
    ALL_US_JURISDICTIONS,
    ELECTION_SOURCE,
    POPULATION_SOURCE,
    STATE_2024_PRES_WINNER,
    STATE_NAMES,
    STATE_POPULATION,
)

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "ai_legislation.db"
DEDUPE_REPORT_PATH = ROOT / "data" / "dedupe_report_ncsl_fpf.json"

app = Flask(__name__)

ATTRIBUTION = (
    "Data sourced from the NCSL Artificial Intelligence Legislation Database, "
    "the Future of Privacy Forum 2026 Chatbot Legislation Tracker, the "
    "American Action Forum List of Proposed AI Bills, the Brennan Center "
    "for Justice Artificial Intelligence Legislation Tracker (118th and "
    "119th Congress), and the Center for Democracy & Technology (CDT) AI "
    "Policy Tracker. Figures reflect the state of these databases as of "
    "each source's scrape date shown below, and are only as current as each "
    "source's own updates. The Tech Policy Press Tracker could not be "
    "scraped (it renders its data client-side via JavaScript and was "
    "inaccessible without browser automation in the session that scraped "
    "NCSL/AAF/FPF). CDT's tracker is NOT a bill-level legislative database -- "
    "it is CDT's own log of its AI-related publications and activities "
    "(blog posts, comments, reports, briefs, testimony, letters, podcasts); "
    "see limitations below for what was actually captured."
)

# Which government level each bill-level source actually covers, and the
# full name behind each acronym. This is a factual classification of what
# each source's own data contains (e.g. FPF's tracker table is 100% state
# jurisdictions despite the source's own page prose mentioning federal
# proposals it doesn't actually list -- see LIMITATIONS) -- not an editorial
# grouping. CDT is intentionally absent: it is not bill-level data at all
# (see LIMITATIONS) so it has no "level" and is never included in the
# unified bill browser below.
SOURCE_META = {
    "ncsl": {"label": "NCSL", "full_name": "National Conference of State Legislatures", "level": "state"},
    "fpf": {"label": "FPF", "full_name": "Future of Privacy Forum", "level": "state"},
    "aaf": {"label": "AAF", "full_name": "American Action Forum", "level": "federal"},
    "brennan_center": {"label": "Brennan Center", "full_name": "Brennan Center for Justice", "level": "federal"},
}

STATUS_OUTCOME = {
    "Enacted": "positive-final",
    "Adopted": "positive-final",
    "Vetoed": "negative-final",
    "Failed": "negative-final",
    "Pending": "unresolved",
    "To Governor": "unresolved",
}

LIMITATIONS = [
    "AAF (American Action Forum) provides no legislative-status/outcome field "
    "at all -- the source site's own column labeled \"Status\" is populated "
    "with a bill identifier (e.g. \"S4476\"), not a status word, and is "
    "preserved verbatim as bill_status_field. Passage rate, time-to-passage, "
    "and status breakdowns cannot be computed for AAF bills.",
    "AAF is federal-only and has no state field, so it is excluded from every "
    "state-level metric (per-capita volume, red/blue grouping, category "
    "concentration by state, first-mover states, zero-legislation states, "
    "outlier states, carryover).",
    "NCSL topics, AAF classifications, and FPF policy-area columns are three "
    "different, non-aligned taxonomies from three different organizations. "
    "No single unified \"category\" comparison is computed across all three "
    "sources -- each source's categories are reported only within that "
    "source.",
    "date_introduced is missing for 28 of 2,655 NCSL bills (~1%); those bills "
    "are excluded from the time-to-passage calculation rather than estimated.",
    "\"Repeat-bill/carryover\" is only traceable via bills whose NCSL status "
    "text literally contains the word \"Carryover\" (240 bills). True "
    "bill-to-bill lineage across legislative sessions is not otherwise "
    "linkable in the source data, so this is a lower bound, not a full "
    "carryover census.",
    "State population figures (for per-capita bill volume) and the 2024 "
    "presidential-election state classification (for red/blue grouping) are "
    "external reference data added to this app for those two specific "
    "metrics -- neither figure comes from NCSL, AAF, or FPF. See sources: "
    f"{POPULATION_SOURCE}; {ELECTION_SOURCE}.",
    "Tech Policy Press's tracker was not scraped (it renders tables "
    "client-side via JavaScript; browser automation was unavailable in the "
    "session that scraped NCSL/AAF/FPF). It does not appear anywhere in "
    "this app's data.",
    "CDT's 'AI Policy Tracker' compiles CDT's own AI-related publications "
    "and activities, not third-party bill records -- it has no bill number, "
    "state, sponsor, session, or legislative-status field of any kind. It "
    "is a chronological log with: date, title, an item-type tag (Blog, "
    "Letter, Comments, Report, Brief, Testimony, Podcast, Press Release, "
    "Newsletter, and a handful of rarer values -- CDT's own free-text "
    "labels, not a controlled taxonomy), a link to the primary document, an "
    "optional separate 'Blog Post' announcement link, and the CDT staff "
    "member credited as creator. Because it isn't bill-level data, it is "
    "not joined or compared against NCSL/AAF/FPF/Brennan Center anywhere in "
    "this app, and has no passage rate, status breakdown, or state-level "
    "metrics -- only its own overview/type/creator/timeline endpoints "
    "(see /api/cdt/*).",
    "73 of 638 CDT items (~11%) carry no item-type tag at all in the source "
    "site's own markup -- preserved as null, not guessed from context. "
    "39 primary_url values are repeated across more than one row in CDT's "
    "own source table, including at least one case where two rows with "
    "completely different titles point at the same PDF URL. These are "
    "preserved verbatim as separate rows rather than deduplicated or "
    "corrected, consistent with how this project handles other sources' "
    "own data-quality issues (see Brennan Center limitations below).",
    "Brennan Center's tracker also renders client-side via JavaScript (two "
    "embedded Datawrapper tables), but was scraped in a later session using "
    "browser automation to locate the underlying Datawrapper CSV export "
    "URLs, which are then re-fetchable via plain HTTP without a browser "
    "going forward. Its 118th and 119th Congress tables use two different, "
    "non-aligned schemas from the source site itself -- see the Brennan "
    "Center-specific limitations below.",
    "Brennan Center's 119th Congress table has a 'Status' field, but it is "
    "nearly non-informative (51 of 53 records are 'Pending'). Its 118th "
    "Congress table has no 'Status' field at all -- only a free-text 'Last "
    "Action' (populated for 91 of 154 records) and a separate, "
    "non-controlled 'Regulatory Approach' taxonomy with inconsistent "
    "capitalization/pluralization across rows (e.g. 'Limits on use in "
    "certain contexts' vs 'Limitations on use in certain contexts' appear "
    "as distinct literal strings, not normalized). No passage rate, "
    "status breakdown, or category comparison against NCSL/AAF/FPF "
    "taxonomies is computed for Brennan Center bills for this reason.",
    "Brennan Center's tracker is Congress-only (118th/119th), like AAF -- "
    "it has no per-state field and is excluded from every state-level "
    "metric.",
    "One Brennan Center 119th-Congress record (H.R. 2444) has a "
    "congress.gov URL truncated to '.../tex' instead of '.../text' in the "
    "source site's own HTML -- preserved verbatim as a broken link rather "
    "than corrected. Two records' displayed bill-number text disagrees "
    "with the chamber encoded in that same row's congress.gov URL (e.g. "
    "displayed 'S.1213' links to a house-bill URL) -- both values are kept "
    "on the record rather than one being treated as authoritative.",
    "FPF's own page prose claims \"98 chatbot-specific bills across 34 states, "
    "as well as three federal proposals\" (101 total), but the actual "
    "rendered tracker table contains only 32 rows, all state-level, zero "
    "federal. This is a discrepancy in FPF's source page itself -- reported, "
    "not reconciled or approximated.",
    "A bill's \"passage\" here is defined explicitly as: Enacted or Adopted "
    "status prefix = positive-final; Vetoed or Failed = negative-final; "
    "Pending or To Governor = unresolved (excluded from passage-rate "
    "denominators, since their outcome isn't yet known). This definition is "
    "stated so it can be checked, not left implicit.",
]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def status_prefix(status):
    if not status or " - " not in status:
        return status or "Unknown"
    return status.split(" - ", 1)[0]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/meta")
def api_meta():
    conn = get_db()
    cur = conn.cursor()
    ncsl_meta = dict(cur.execute("SELECT * FROM ncsl_scrape_meta").fetchone())
    aaf_meta = dict(cur.execute("SELECT * FROM aaf_scrape_meta").fetchone())
    fpf_meta = dict(cur.execute("SELECT * FROM fpf_scrape_meta").fetchone())
    brennan_meta = dict(cur.execute("SELECT * FROM brennan_center_scrape_meta").fetchone())
    cdt_meta = dict(cur.execute("SELECT * FROM cdt_scrape_meta").fetchone())
    conn.close()
    return jsonify({
        "attribution": ATTRIBUTION,
        "sources": {
            "ncsl": ncsl_meta, "aaf": aaf_meta, "fpf": fpf_meta,
            "brennan_center": brennan_meta, "cdt": cdt_meta,
        },
        "source_meta": SOURCE_META,
        "state_names": STATE_NAMES,
        "limitations": LIMITATIONS,
    })


@app.route("/api/ncsl/overview")
def ncsl_overview():
    conn = get_db()
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(*) FROM ncsl_bills").fetchone()[0]
    states = cur.execute("SELECT COUNT(DISTINCT state_abbr) FROM ncsl_bills").fetchone()[0]
    rows = cur.execute("SELECT status FROM ncsl_bills").fetchall()
    conn.close()
    breakdown = Counter(status_prefix(r["status"]) for r in rows)
    return jsonify({
        "total_bills": total,
        "states_covered": states,
        "status_breakdown": dict(breakdown.most_common()),
    })


@app.route("/api/ncsl/bills_per_state")
def ncsl_bills_per_state():
    conn = get_db()
    rows = conn.execute(
        "SELECT state_abbr, state, COUNT(*) as n FROM ncsl_bills GROUP BY state_abbr ORDER BY n DESC"
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        pop = STATE_POPULATION.get(r["state_abbr"])
        per_100k = round(r["n"] / pop * 100, 3) if pop else None
        out.append({
            "state_abbr": r["state_abbr"],
            "state": r["state"],
            "bill_count": r["n"],
            "population_thousands": pop,
            "bills_per_100k_population": per_100k,
        })
    return jsonify({"population_source": POPULATION_SOURCE, "states": out})


@app.route("/api/ncsl/topics")
def ncsl_topics():
    conn = get_db()
    total_bills = conn.execute("SELECT COUNT(*) FROM ncsl_bills").fetchone()[0]
    rows = conn.execute(
        "SELECT topic, COUNT(*) as n FROM ncsl_bill_topics GROUP BY topic ORDER BY n DESC"
    ).fetchall()
    conn.close()
    return jsonify({
        "note": "Bills may carry multiple topics, so percentages are share-of-bills-tagged, not a partition -- they do not sum to 100%.",
        "total_bills": total_bills,
        "topics": [
            {"topic": r["topic"], "bill_count": r["n"], "pct_of_bills": round(r["n"] / total_bills * 100, 2)}
            for r in rows
        ],
    })


@app.route("/api/ncsl/momentum")
def ncsl_momentum():
    conn = get_db()
    ref_date_str = conn.execute("SELECT scraped_at FROM ncsl_scrape_meta").fetchone()[0]
    ref_date = datetime.fromisoformat(ref_date_str.replace("Z", "+00:00")).date()
    rows = conn.execute(
        "SELECT date_of_last_action_iso FROM ncsl_bills WHERE date_of_last_action_iso IS NOT NULL"
    ).fetchall()
    conn.close()
    counts = {"last_30_days": 0, "last_90_days": 0, "last_365_days": 0}
    for r in rows:
        d = date.fromisoformat(r["date_of_last_action_iso"])
        delta = (ref_date - d).days
        if 0 <= delta <= 30:
            counts["last_30_days"] += 1
        if 0 <= delta <= 90:
            counts["last_90_days"] += 1
        if 0 <= delta <= 365:
            counts["last_365_days"] += 1
    return jsonify({
        "reference_date": ref_date.isoformat(),
        "reference_date_meaning": "NCSL scrape timestamp -- not necessarily today's calendar date -- used so results are reproducible against the exact snapshot in the database.",
        "counts": counts,
    })


@app.route("/api/ncsl/sponsorship_type")
def ncsl_sponsorship_type():
    conn = get_db()
    bills = conn.execute("SELECT id, author_party FROM ncsl_bills").fetchall()
    extra = conn.execute("SELECT bill_id, author_party FROM ncsl_bill_additional_authors").fetchall()
    conn.close()
    extra_by_bill = defaultdict(list)
    for r in extra:
        extra_by_bill[r["bill_id"]].append(r["author_party"])

    result = Counter()
    for b in bills:
        parties = {b["author_party"]} if b["author_party"] else set()
        parties.update(p for p in extra_by_bill.get(b["id"], []) if p)
        if not parties:
            result["unknown_no_party_data"] += 1
        elif len(parties) == 1:
            result["single_party"] += 1
        else:
            result["bipartisan_multi_party"] += 1
    return jsonify({
        "method": "A bill is bipartisan_multi_party if the distinct set of parties across its primary author + all additional authors has more than one value; single_party if exactly one; unknown_no_party_data if no author on the bill has a recorded party.",
        "counts": dict(result),
    })


@app.route("/api/ncsl/author_party_split")
def ncsl_author_party_split():
    conn = get_db()
    rows = conn.execute(
        "SELECT COALESCE(author_party, 'Unknown') as party, COUNT(*) as n FROM ncsl_bills GROUP BY party ORDER BY n DESC"
    ).fetchall()
    conn.close()
    return jsonify({"primary_sponsor_party": {r["party"]: r["n"] for r in rows}})


def _passage_rows(conn):
    return conn.execute("SELECT id, state_abbr, status, author_party FROM ncsl_bills").fetchall()


@app.route("/api/ncsl/passage")
def ncsl_passage():
    conn = get_db()
    rows = _passage_rows(conn)
    topics = conn.execute("SELECT bill_id, topic FROM ncsl_bill_topics").fetchall()
    conn.close()
    topics_by_bill = defaultdict(list)
    for t in topics:
        topics_by_bill[t["bill_id"]].append(t["topic"])

    def outcome(status):
        return STATUS_OUTCOME.get(status_prefix(status), "unresolved")

    def rate(rows_subset):
        pos = sum(1 for r in rows_subset if outcome(r["status"]) == "positive-final")
        neg = sum(1 for r in rows_subset if outcome(r["status"]) == "negative-final")
        concluded = pos + neg
        return {
            "positive_final": pos,
            "negative_final": neg,
            "unresolved_excluded": len(rows_subset) - concluded,
            "passage_rate_pct_of_concluded": round(pos / concluded * 100, 2) if concluded else None,
        }

    by_state = defaultdict(list)
    by_party = defaultdict(list)
    by_topic = defaultdict(list)
    for r in rows:
        by_state[r["state_abbr"]].append(r)
        by_party[r["author_party"] or "Unknown"].append(r)
        for t in topics_by_bill.get(r["id"], []):
            by_topic[t].append(r)

    return jsonify({
        "method": (
            "positive_final = status prefix Enacted or Adopted. negative_final = "
            "status prefix Vetoed or Failed. Pending and To Governor are "
            "unresolved and excluded from the passage-rate denominator, since "
            "their eventual outcome is not yet known."
        ),
        "overall": rate(rows),
        "by_state": {k: rate(v) for k, v in sorted(by_state.items())},
        "by_sponsor_party": {k: rate(v) for k, v in sorted(by_party.items())},
        "by_topic": {k: rate(v) for k, v in sorted(by_topic.items())},
    })


@app.route("/api/ncsl/time_to_passage")
def ncsl_time_to_passage():
    conn = get_db()
    rows = conn.execute(
        """SELECT date_introduced_iso, date_of_last_action_iso, year, state_abbr
           FROM ncsl_bills
           WHERE status LIKE 'Enacted%' OR status LIKE 'Adopted%'"""
    ).fetchall()
    conn.close()
    enacted_total = len(rows)
    days = []
    by_year = defaultdict(list)
    for r in rows:
        if not r["date_introduced_iso"] or not r["date_of_last_action_iso"]:
            continue
        d0 = date.fromisoformat(r["date_introduced_iso"])
        d1 = date.fromisoformat(r["date_of_last_action_iso"])
        delta = (d1 - d0).days
        if delta < 0:
            continue  # last action before introduction date is not a valid duration; excluded, not clamped
        days.append(delta)
        by_year[r["year"]].append(delta)

    def summarize(vals):
        if not vals:
            return None
        vals_sorted = sorted(vals)
        n = len(vals_sorted)
        median = vals_sorted[n // 2] if n % 2 else (vals_sorted[n // 2 - 1] + vals_sorted[n // 2]) / 2
        return {
            "n": n,
            "mean_days": round(sum(vals_sorted) / n, 1),
            "median_days": median,
            "min_days": vals_sorted[0],
            "max_days": vals_sorted[-1],
        }

    return jsonify({
        "method": (
            "Computed only for bills with status prefix Enacted or Adopted, "
            "and only where both date_introduced and date_of_last_action are "
            "present (excludes the ~1% of NCSL bills missing an introduction "
            "date, and any record where the last action predates introduction, "
            "rather than estimating either)."
        ),
        "enacted_or_adopted_total": enacted_total,
        "excluded_missing_dates_or_invalid": enacted_total - len(days),
        "overall": summarize(days),
        "by_year": {y: summarize(v) for y, v in sorted(by_year.items())},
    })


@app.route("/api/ncsl/red_blue")
def ncsl_red_blue():
    conn = get_db()
    rows = conn.execute(
        "SELECT state_abbr, COUNT(*) as n FROM ncsl_bills GROUP BY state_abbr"
    ).fetchall()
    conn.close()
    grouped = defaultdict(int)
    detail = []
    for r in rows:
        winner = STATE_2024_PRES_WINNER.get(r["state_abbr"], "Unknown")
        grouped[winner] += r["n"]
        detail.append({"state_abbr": r["state_abbr"], "bill_count": r["n"], "2024_pres_winner": winner})
    return jsonify({
        "source": ELECTION_SOURCE,
        "note": "Grouping is by each state's own bill count, classified using the external reference above -- not a characterization of any bill's content.",
        "totals_by_group": dict(grouped),
        "by_state": detail,
    })


@app.route("/api/ncsl/category_concentration")
def ncsl_category_concentration():
    conn = get_db()
    rows = conn.execute(
        """SELECT b.state_abbr as state_abbr, t.topic as topic, COUNT(*) as n
           FROM ncsl_bill_topics t JOIN ncsl_bills b ON b.id = t.bill_id
           GROUP BY b.state_abbr, t.topic"""
    ).fetchall()
    conn.close()
    by_state = defaultdict(dict)
    for r in rows:
        by_state[r["state_abbr"]][r["topic"]] = r["n"]

    out = {}
    for state, topic_counts in by_state.items():
        total = sum(topic_counts.values())
        top3 = sorted(topic_counts.items(), key=lambda kv: -kv[1])[:3]
        hhi = round(sum((n / total) ** 2 for n in topic_counts.values()) * 10000, 1)
        out[state] = {
            "top_topics": [{"topic": t, "n": n} for t, n in top3],
            "herfindahl_index": hhi,
        }
    return jsonify({
        "method": "Herfindahl-Hirschman Index (0-10000) over each state's topic-tag shares; higher = that state's AI bills concentrate in fewer topics.",
        "by_state": out,
    })


@app.route("/api/ncsl/first_movers")
def ncsl_first_movers():
    conn = get_db()
    rows = conn.execute(
        """SELECT t.topic as topic, b.state_abbr as state_abbr, b.date_introduced_iso as d
           FROM ncsl_bill_topics t JOIN ncsl_bills b ON b.id = t.bill_id
           WHERE b.date_introduced_iso IS NOT NULL"""
    ).fetchall()
    conn.close()
    earliest = {}
    for r in rows:
        cur = earliest.get(r["topic"])
        if cur is None or r["d"] < cur["date_introduced"]:
            earliest[r["topic"]] = {"state_abbr": r["state_abbr"], "date_introduced": r["d"]}
    return jsonify({
        "method": "Earliest date_introduced among bills carrying each topic tag; ties broken by row order (first is not evidence of causal precedence -- policy diffusion attribution needs more than this).",
        "first_mover_by_topic": dict(sorted(earliest.items())),
    })


@app.route("/api/ncsl/zero_legislation_states")
def ncsl_zero_legislation_states():
    conn = get_db()
    present = {r[0] for r in conn.execute("SELECT DISTINCT state_abbr FROM ncsl_bills").fetchall()}
    conn.close()
    zero = sorted(set(ALL_US_JURISDICTIONS) - present)
    return jsonify({
        "universe": "50 states + DC + 5 populated U.S. territories (AS, GU, MP, PR, VI) -- the full jurisdiction set NCSL's database purports to cover.",
        "zero_legislation_jurisdictions": zero,
    })


@app.route("/api/ncsl/outlier_states")
def ncsl_outlier_states():
    conn = get_db()
    rows = conn.execute("SELECT state_abbr, COUNT(*) as n FROM ncsl_bills GROUP BY state_abbr").fetchall()
    conn.close()
    counts = sorted(r["n"] for r in rows)
    n = len(counts)
    q1 = counts[n // 4]
    q3 = counts[(3 * n) // 4]
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    outliers = [
        {"state_abbr": r["state_abbr"], "bill_count": r["n"], "direction": "high" if r["n"] > hi else "low"}
        for r in rows if r["n"] > hi or r["n"] < lo
    ]
    return jsonify({
        "method": f"IQR outlier rule on per-state bill counts: Q1={q1}, Q3={q3}, IQR={iqr}, bounds=[{lo}, {hi}].",
        "outliers": sorted(outliers, key=lambda o: -o["bill_count"]),
    })


@app.route("/api/ncsl/category_trend")
def ncsl_category_trend():
    conn = get_db()
    rows = conn.execute(
        """SELECT t.topic as topic, b.year as year, COUNT(*) as n
           FROM ncsl_bill_topics t JOIN ncsl_bills b ON b.id = t.bill_id
           GROUP BY t.topic, b.year"""
    ).fetchall()
    conn.close()
    by_topic = defaultdict(dict)
    for r in rows:
        by_topic[r["topic"]][r["year"]] = r["n"]
    return jsonify({
        "note": "Only two years of data are present in the source (2025, 2026), so this shows a single year-over-year comparison, not a multi-year trend line.",
        "by_topic": dict(sorted(by_topic.items())),
    })


@app.route("/api/ncsl/failed_graveyard")
def ncsl_failed_graveyard():
    conn = get_db()
    rows = conn.execute(
        """SELECT t.topic as topic, COUNT(*) as n
           FROM ncsl_bill_topics t JOIN ncsl_bills b ON b.id = t.bill_id
           WHERE b.status LIKE 'Failed%'
           GROUP BY t.topic ORDER BY n DESC"""
    ).fetchall()
    conn.close()
    return jsonify({"topics_among_failed_bills": [{"topic": r["topic"], "n": r["n"]} for r in rows]})


@app.route("/api/ncsl/carryover")
def ncsl_carryover():
    conn = get_db()
    rows = conn.execute(
        "SELECT state_abbr, COUNT(*) as n FROM ncsl_bills WHERE status LIKE '%Carryover%' GROUP BY state_abbr ORDER BY n DESC"
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM ncsl_bills WHERE status LIKE '%Carryover%'").fetchone()[0]
    conn.close()
    return jsonify({
        "method": "Bills whose NCSL status text literally contains the word \"Carryover\" -- a lower bound on carried-over bills, not a full census (see limitations).",
        "total_carryover_bills": total,
        "by_state": [{"state_abbr": r["state_abbr"], "n": r["n"]} for r in rows],
    })


@app.route("/api/ncsl/sponsor_concentration")
def ncsl_sponsor_concentration():
    conn = get_db()
    rows = conn.execute(
        """SELECT state_abbr, author_name, COUNT(*) as n FROM ncsl_bills
           WHERE author_name IS NOT NULL
           GROUP BY state_abbr, author_name ORDER BY n DESC LIMIT 25"""
    ).fetchall()
    conn.close()
    return jsonify({
        "method": "Top 25 (state, primary-author-name) pairs by bill count. Keyed by state+name together since two different legislators in different states can share a surname.",
        "top_sponsors": [{"state_abbr": r["state_abbr"], "author_name": r["author_name"], "bill_count": r["n"]} for r in rows],
    })


@app.route("/api/aaf/overview")
def aaf_overview():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM aaf_bills").fetchone()[0]
    classification = conn.execute(
        "SELECT classification, COUNT(*) as n FROM aaf_bills GROUP BY classification ORDER BY n DESC"
    ).fetchall()
    chamber = conn.execute("SELECT chamber, COUNT(*) as n FROM aaf_bills GROUP BY chamber").fetchall()
    conn.close()
    return jsonify({
        "total_bills": total,
        "classification_breakdown": {r["classification"]: r["n"] for r in classification},
        "chamber_breakdown": {r["chamber"]: r["n"] for r in chamber},
        "note": "AAF has no usable legislative-status field (see limitations) -- no passage rate or status breakdown is computed here.",
    })


@app.route("/api/fpf/overview")
def fpf_overview():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM fpf_chatbot_bills").fetchone()[0]
    category = conn.execute("SELECT category, COUNT(*) as n FROM fpf_chatbot_bills GROUP BY category").fetchall()
    status = conn.execute("SELECT status, COUNT(*) as n FROM fpf_chatbot_bills GROUP BY status ORDER BY n DESC").fetchall()
    jurisdiction = conn.execute(
        "SELECT jurisdiction, COUNT(*) as n FROM fpf_chatbot_bills GROUP BY jurisdiction ORDER BY n DESC"
    ).fetchall()
    conn.close()
    return jsonify({
        "total_bills": total,
        "category_breakdown": {r["category"]: r["n"] for r in category},
        "status_breakdown": {r["status"]: r["n"] for r in status},
        "jurisdiction_breakdown": {r["jurisdiction"]: r["n"] for r in jurisdiction},
    })


FPF_PROVISION_COLUMNS = [
    "regular_disclosures", "professional_services", "risk_assessment", "independent_audit",
    "transparency_reporting", "age_assurance", "minor_access_bans", "parental_consent_tools",
    "prohibited_content_minors", "professional_services_restrictions", "testing_requirements",
    "humanized_emotional_systems", "harm_detection_response", "harm_to_others",
    "user_engagement_optimization", "training_restrictions", "advertising_restrictions",
    "limits_on_collection_sharing",
]


@app.route("/api/fpf/provision_prevalence")
def fpf_provision_prevalence():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM fpf_chatbot_bills").fetchone()[0]
    out = {}
    for col in FPF_PROVISION_COLUMNS:
        n = conn.execute(
            f"SELECT COUNT(*) FROM fpf_chatbot_bills WHERE {col} IS NOT NULL AND TRIM({col}) != ''"
        ).fetchone()[0]
        out[col] = {"bill_count": n, "pct_of_bills": round(n / total * 100, 1)}
    conn.close()
    return jsonify({
        "note": "A non-blank cell in a policy-area column means FPF flagged that bill as addressing that provision (values are FPF's own shorthand codes, e.g. X/T/MN); this reports prevalence, not the specific code's meaning.",
        "total_bills": total,
        "provisions": out,
    })


@app.route("/api/brennan_center/overview")
def brennan_center_overview():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM brennan_center_bills").fetchone()[0]
    by_congress = conn.execute(
        "SELECT congress, COUNT(*) as n FROM brennan_center_bills GROUP BY congress"
    ).fetchall()
    by_chamber = conn.execute(
        "SELECT COALESCE(url_derived_chamber, 'Unknown') as chamber, COUNT(*) as n "
        "FROM brennan_center_bills GROUP BY chamber"
    ).fetchall()
    status_119 = conn.execute(
        "SELECT COALESCE(status, 'Unknown') as status, COUNT(*) as n FROM brennan_center_bills "
        "WHERE congress = '119th' GROUP BY status ORDER BY n DESC"
    ).fetchall()
    conn.close()
    return jsonify({
        "note": (
            "119th and 118th Congress use different, non-aligned source "
            "schemas -- see limitations. No passage rate or cross-source "
            "category comparison is computed here for that reason."
        ),
        "total_bills": total,
        "by_congress": {r["congress"]: r["n"] for r in by_congress},
        "by_chamber": {r["chamber"]: r["n"] for r in by_chamber},
        "status_119th_congress_only": {r["status"]: r["n"] for r in status_119},
    })


@app.route("/api/brennan_center/last_action_118th")
def brennan_center_last_action_118th():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM brennan_center_bills WHERE congress = '118th'").fetchone()[0]
    with_action = conn.execute(
        "SELECT COUNT(*) FROM brennan_center_bills WHERE congress = '118th' "
        "AND last_action_text IS NOT NULL"
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT bill_number_display, title, last_action_text, last_action_date_raw "
        "FROM brennan_center_bills WHERE congress = '118th' AND last_action_text IS NOT NULL "
        "ORDER BY last_action_date_iso DESC"
    ).fetchall()
    conn.close()
    return jsonify({
        "note": "118th Congress has no controlled status field -- 'Last Action' is free text, populated for a minority of records.",
        "total_118th_congress_bills": total,
        "with_last_action_text": with_action,
        "bills": [
            {
                "bill_number": r["bill_number_display"],
                "title": r["title"],
                "last_action_text": r["last_action_text"],
                "last_action_date": r["last_action_date_raw"],
            }
            for r in rows
        ],
    })


@app.route("/api/brennan_center/regulatory_approach_118th")
def brennan_center_regulatory_approach_118th():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM brennan_center_bills WHERE congress = '118th'").fetchone()[0]
    rows = conn.execute(
        """SELECT a.approach as approach, COUNT(*) as n
           FROM brennan_center_bill_regulatory_approach a
           JOIN brennan_center_bills b ON b.id = a.bill_id
           WHERE b.congress = '118th'
           GROUP BY a.approach ORDER BY n DESC"""
    ).fetchall()
    conn.close()
    return jsonify({
        "note": (
            "118th Congress only (119th has no Regulatory Approach field). "
            "Values are Brennan Center's own free-text shorthand, preserved "
            "verbatim -- NOT a controlled taxonomy. Near-duplicate values "
            "with different capitalization/pluralization are reported as "
            "separate literal strings, not merged, since we cannot know "
            "which spelling the source intended as canonical."
        ),
        "total_118th_congress_bills": total,
        "approach_counts_verbatim": [{"approach": r["approach"], "bill_count": r["n"]} for r in rows],
    })


@app.route("/api/cdt/overview")
def cdt_overview():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM cdt_items").fetchone()[0]
    distinct_creators = conn.execute("SELECT COUNT(DISTINCT creator_name) FROM cdt_items").fetchone()[0]
    types = conn.execute(
        "SELECT COALESCE(item_type, 'Untagged') as t, COUNT(*) as n FROM cdt_items GROUP BY t ORDER BY n DESC"
    ).fetchall()
    date_range = conn.execute("SELECT MIN(date_iso), MAX(date_iso) FROM cdt_items").fetchone()
    conn.close()
    return jsonify({
        "note": (
            "CDT's tracker logs CDT's own AI-related publications/activities, "
            "not third-party bills -- there is no passage rate, status "
            "breakdown, or state-level metric to compute here (see "
            "limitations)."
        ),
        "total_items": total,
        "distinct_creators": distinct_creators,
        "earliest_date": date_range[0],
        "latest_date": date_range[1],
        "item_type_breakdown": {r["t"]: r["n"] for r in types},
    })


@app.route("/api/cdt/creators")
def cdt_creators():
    conn = get_db()
    rows = conn.execute(
        "SELECT creator_name, COUNT(*) as n FROM cdt_items GROUP BY creator_name ORDER BY n DESC LIMIT 25"
    ).fetchall()
    conn.close()
    return jsonify({
        "method": "Top 25 CDT staff by number of credited items in the tracker.",
        "top_creators": [{"creator_name": r["creator_name"], "item_count": r["n"]} for r in rows],
    })


@app.route("/api/cdt/timeline")
def cdt_timeline():
    conn = get_db()
    rows = conn.execute(
        "SELECT SUBSTR(date_iso, 1, 4) as year, COUNT(*) as n FROM cdt_items GROUP BY year ORDER BY year"
    ).fetchall()
    conn.close()
    return jsonify({
        "note": "Item count per calendar year, by the tracker's own listed date for each item.",
        "by_year": {r["year"]: r["n"] for r in rows},
    })


@app.route("/api/highlights")
def api_highlights():
    """
    Curated headline numbers for the top-of-page 'Key Findings' cards.
    Every figure here is a live re-query of tables already exposed by the
    more detailed endpoints below (bills_per_state, passage, momentum,
    sponsorship_type, topics, red_blue) -- nothing is precomputed, cached,
    or hand-typed. This endpoint exists only to assemble a small, curated
    subset of those same numbers in one call for the hero section; it adds
    no new derived metric and no opinion about any bill's merits.
    """
    conn = get_db()
    cur = conn.cursor()

    ncsl_total = cur.execute("SELECT COUNT(*) FROM ncsl_bills").fetchone()[0]
    ncsl_states = cur.execute("SELECT COUNT(DISTINCT state_abbr) FROM ncsl_bills").fetchone()[0]

    rows = cur.execute("SELECT status FROM ncsl_bills").fetchall()

    def outcome(status):
        return STATUS_OUTCOME.get(status_prefix(status), "unresolved")

    pos = sum(1 for r in rows if outcome(r["status"]) == "positive-final")
    neg = sum(1 for r in rows if outcome(r["status"]) == "negative-final")
    concluded = pos + neg
    passage_rate = round(pos / concluded * 100, 1) if concluded else None

    top_state = cur.execute(
        "SELECT state_abbr, state, COUNT(*) as n FROM ncsl_bills GROUP BY state_abbr ORDER BY n DESC LIMIT 1"
    ).fetchone()

    present = {r[0] for r in cur.execute("SELECT DISTINCT state_abbr FROM ncsl_bills").fetchall()}
    zero_count = len(set(ALL_US_JURISDICTIONS) - present)

    ref_date_str = cur.execute("SELECT scraped_at FROM ncsl_scrape_meta").fetchone()[0]
    ref_date = datetime.fromisoformat(ref_date_str.replace("Z", "+00:00")).date()
    last_action_rows = cur.execute(
        "SELECT date_of_last_action_iso FROM ncsl_bills WHERE date_of_last_action_iso IS NOT NULL"
    ).fetchall()
    last_90 = 0
    for r in last_action_rows:
        d = date.fromisoformat(r["date_of_last_action_iso"])
        if 0 <= (ref_date - d).days <= 90:
            last_90 += 1

    bills = cur.execute("SELECT id, author_party FROM ncsl_bills").fetchall()
    extra = cur.execute("SELECT bill_id, author_party FROM ncsl_bill_additional_authors").fetchall()
    extra_by_bill = defaultdict(list)
    for r in extra:
        extra_by_bill[r["bill_id"]].append(r["author_party"])
    bipartisan = 0
    for b in bills:
        parties = {b["author_party"]} if b["author_party"] else set()
        parties.update(p for p in extra_by_bill.get(b["id"], []) if p)
        if len(parties) > 1:
            bipartisan += 1
    bipartisan_pct = round(bipartisan / ncsl_total * 100, 1) if ncsl_total else None

    top_topic = cur.execute(
        "SELECT topic, COUNT(*) as n FROM ncsl_bill_topics GROUP BY topic ORDER BY n DESC LIMIT 1"
    ).fetchone()

    per_state_all = cur.execute("SELECT state_abbr, COUNT(*) as n FROM ncsl_bills GROUP BY state_abbr").fetchall()
    red = blue = unknown = 0
    for r in per_state_all:
        winner = STATE_2024_PRES_WINNER.get(r["state_abbr"], "Unknown")
        if winner == "D":
            blue += r["n"]
        elif winner == "R":
            red += r["n"]
        else:
            unknown += r["n"]

    aaf_total = cur.execute("SELECT COUNT(*) FROM aaf_bills").fetchone()[0]
    brennan_total = cur.execute("SELECT COUNT(*) FROM brennan_center_bills").fetchone()[0]

    conn.close()

    return jsonify({
        "note": "Every number here is a live re-aggregation of the same NCSL/AAF/Brennan Center tables the detailed endpoints below use -- see /api/meta for full source attribution and /api/ncsl/passage etc. for the underlying breakdowns.",
        "state_bills_total": ncsl_total,
        "jurisdictions_with_activity": ncsl_states,
        "zero_legislation_jurisdictions": zero_count,
        "passage_rate_pct_of_concluded": passage_rate,
        "positive_final": pos,
        "negative_final": neg,
        "most_active_state": {
            "state_abbr": top_state["state_abbr"],
            "state": top_state["state"],
            "bill_count": top_state["n"],
        } if top_state else None,
        "bills_touched_last_90_days": last_90,
        "bipartisan_pct": bipartisan_pct,
        "bipartisan_count": bipartisan,
        "top_topic": {"topic": top_topic["topic"], "bill_count": top_topic["n"]} if top_topic else None,
        "red_state_bills": red,
        "blue_state_bills": blue,
        "unclassified_state_bills": unknown,
        "federal_bills_aaf": aaf_total,
        "federal_bills_brennan_center": brennan_total,
    })


@app.route("/api/bills/all")
def api_bills_all():
    """
    One flat, live-queried list of every individual bill record across the
    four bill-level sources (NCSL, AAF, Brennan Center, FPF), each row
    flagged with its source and government level. This is the "everything
    in one place, source flagged" browse view -- it does NOT merge or
    normalize any source's own status/category text (each source's
    taxonomy is non-aligned with the others -- see LIMITATIONS), it only
    tags each row with where it came from so it can be filtered.

    CDT is intentionally excluded -- it is not bill-level data (see
    LIMITATIONS) and has no state/status/bill-number fields to flag here.
    """
    conn = get_db()
    cur = conn.cursor()
    out = []

    for r in cur.execute(
        "SELECT state_abbr, state, bill_number, status, date_of_last_action_iso, description "
        "FROM ncsl_bills"
    ):
        out.append({
            "source": "ncsl", "level": "state",
            "jurisdiction": r["state_abbr"], "jurisdiction_full": r["state"],
            "bill_number": r["bill_number"], "title": r["description"],
            "status_raw": r["status"], "date": r["date_of_last_action_iso"],
            "url": None,
        })

    for r in cur.execute(
        "SELECT jurisdiction, bill_number, category, status FROM fpf_chatbot_bills"
    ):
        out.append({
            "source": "fpf", "level": "state",
            "jurisdiction": r["jurisdiction"],
            "jurisdiction_full": STATE_NAMES.get(r["jurisdiction"], r["jurisdiction"]),
            "bill_number": r["bill_number"], "title": r["category"],
            "status_raw": r["status"], "date": None,
            "url": None,
        })

    for r in cur.execute(
        "SELECT bill_name, classification, chamber, bill_status_field FROM aaf_bills"
    ):
        out.append({
            "source": "aaf", "level": "federal",
            "jurisdiction": "US-Congress",
            "jurisdiction_full": f"U.S. Congress ({r['chamber']})" if r["chamber"] else "U.S. Congress",
            "bill_number": r["bill_status_field"], "title": r["bill_name"],
            "status_raw": None, "date": None,
            "url": None,
        })

    for r in cur.execute(
        "SELECT congress, bill_number_display, title, status, last_action_text, "
        "last_action_date_iso, date_introduced_iso, congress_gov_url, url_derived_chamber "
        "FROM brennan_center_bills"
    ):
        out.append({
            "source": "brennan_center", "level": "federal",
            "jurisdiction": "US-Congress",
            "jurisdiction_full": (
                f"U.S. Congress ({r['congress']}, {r['url_derived_chamber']})"
                if r["url_derived_chamber"] else f"U.S. Congress ({r['congress']})"
            ),
            "bill_number": r["bill_number_display"], "title": r["title"],
            "status_raw": r["status"] or r["last_action_text"],
            "date": r["last_action_date_iso"] or r["date_introduced_iso"],
            "url": r["congress_gov_url"],
        })

    conn.close()

    level_counts = Counter(row["level"] for row in out)
    source_counts = Counter(row["source"] for row in out)

    return jsonify({
        "note": (
            "Every row is a live, unaltered read from its own source table -- "
            "flagged with source and level so this list can be filtered, not "
            "merged into a single taxonomy (the four sources use non-aligned "
            "status/category schemas; see /api/meta limitations)."
        ),
        "source_meta": SOURCE_META,
        "total": len(out),
        "level_counts": dict(level_counts),
        "source_counts": dict(source_counts),
        "bills": out,
    })


@app.route("/api/dedupe")
def api_dedupe():
    import json
    with open(DEDUPE_REPORT_PATH) as f:
        report = json.load(f)
    return jsonify({
        "method": report["method"],
        "notes": report["notes"],
        "summary": report["summary"],
        "unmatched_fpf_records": report["unmatched_fpf_records"],
    })


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5050))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
