"""
Builds data/cookie_cutter_partisan_report.json -- the merged dataset behind the
tracker's "Cookie-Cutter Clusters" section.

Combines three things that already exist as separate files/passes:
  1. data/cookie_cutter_clusters.json -- the authoritative text-similarity
     clustering output (which bills are in which cluster, and how similar).
  2. Live sponsor/party lookups against data/ai_legislation.db, joining
     ncsl_bills (primary author) + ncsl_bill_additional_authors (co-sponsors)
     for every bill in every cluster.
  3. data/cookie_cutter_external_research.md -- the sourced "who's behind
     this" research pass. Its "Bottom line" paragraphs and citations are
     reproduced verbatim below (not re-derived or paraphrased) to avoid
     introducing new claims outside what that research already verified.

One manual override: ME S 531's primary sponsor (Sen. Tipping) has no party
recorded in ncsl_bills (source data gap). Verified externally via the bill's
own text on the Maine Legislature site (LD 1301 / SP0531), cross-checked
against the Maine Senate Democrats caucus site and Ballotpedia.

Run this after re-scraping NCSL data, or after any change to
cookie_cutter_clusters.json, then commit the output JSON -- the Flask route
serves this file directly rather than re-deriving it per request, since the
clustering + external research portions cannot be recomputed live.
"""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "ai_legislation.db"
CLUSTERS_PATH = ROOT / "data" / "cookie_cutter_clusters.json"
OUT_PATH = ROOT / "data" / "cookie_cutter_partisan_report.json"

ME_S531_OVERRIDE = {
    "sponsor_party": "D",
    "sponsor_name": "Tipping",
    "override_note": (
        "Not recorded in the underlying NCSL dataset. Verified directly against "
        "the bill's own text on the Maine Legislature's site (LD 1301 / SP0531, "
        "\"Presented by Senator TIPPING of Penobscot\"), cross-checked against the "
        "Maine Senate Democrats caucus site and Ballotpedia."
    ),
}

THEMES = {
    1: "Algorithmic rent-fixing ban",
    2: "AI in mental health treatment",
    3: "Surveillance/algorithmic pricing ban",
    4: "AI eligibility-discrimination notice requirement",
    5: "\"AI can't be a legal person\" ban",
    6: "AI health-insurance utilization-review rules",
    7: "AI regulation by health insurers/providers (broad)",
    8: "\"AI in health care\" (lower-confidence grouping)",
}

# External-research bottom lines, keyed by this project's cluster_id (JSON
# file numbering). Reproduced verbatim from
# data/cookie_cutter_external_research.md so this section never states a
# partisan/organizational attribution that document didn't already verify.
EXTERNAL_RESEARCH = {
    1: {
        "bottom_line": (
            "Real, heavily-covered, nationwide legislative wave (RealPage antitrust fallout) with "
            "identifiable advocacy-side voices (Consumer Federation of America, NLIHC/NHLP/Tenant Union "
            "Federation) and industry-side opposition (RealPage, National Apartment Association) -- but "
            "no citable source was found naming a specific organization as the drafter/template-author of "
            "the identical \"algorithmic rent fixing in the rental housing market\" language shared by MA, "
            "NC, and WA specifically."
        ),
        "sources": [
            {"label": "Shelterforce, \"Legislators Push Back Against 'Rent-Setting' Software\" (2025)", "url": "https://shelterforce.org/2025/07/11/legislators-push-back-against-rent-setting-software/"},
            {"label": "Consumer Reports, 2025 algorithmic pricing bill tracker", "url": "https://innovation.consumerreports.org/how-u-s-states-are-tackling-algorithmic-pricing-2025-bill-tracker-and-analysis/"},
            {"label": "National Housing Law Project / NLIHC / Tenant Union Federation, \"National Tenants Bill of Rights\"", "url": "https://www.nhlp.org/press-release/national-housing-law-project-national-low-income-housing-coalition-and-tenant-union-federation-release-national-tenants-bill-of-rights-a-practical-policy-agenda-for-renters/"},
        ],
    },
    2: {
        "bottom_line": (
            "No public reporting found connecting this cluster to a specific organization. The "
            "Transparency Coalition's legislative tracker reports on both RI and WV bills but explicitly "
            "does not claim authorship or coordination of them, and its own published model bill targets a "
            "different subject (chatbot safety for minors, not licensed providers' use of AI in therapy)."
        ),
        "sources": [
            {"label": "Transparency Coalition legislative update (Mar. 20, 2026)", "url": "https://www.transparencycoalition.ai/news/ai-legislative-update-march20-2026"},
        ],
    },
    3: {
        "bottom_line": (
            "No source found naming a specific organization as drafter of the IA/NJ bill language. The "
            "shared term \"surveillance pricing\" itself traces to a specific, citable, named source -- the "
            "FTC's 2024 6(b) study, which coverage says \"popularized the term\" -- plausibly explaining why "
            "it appears in both states' bill summaries, though no source ties the actual bill text to any "
            "drafting organization."
        ),
        "sources": [
            {"label": "FTC, \"Behind the FTC's Inquiry into Surveillance Pricing Practices\" (2024)", "url": "https://www.ftc.gov/policy/advocacy-research/tech-at-ftc/2024/07/behind-ftcs-inquiry-surveillance-pricing-practices"},
            {"label": "FTC, \"Issue Spotlight: The Rise of Surveillance Pricing\" (PDF)", "url": "https://www.ftc.gov/system/files/ftc_gov/pdf/sp6b-issue-spotlight.pdf"},
        ],
    },
    4: {
        "bottom_line": (
            "DC's bill has a well-documented, named origin (DC Attorney General Karl Racine's office, 2021, "
            "which called it \"the first comprehensive bill of its type across the country\") and a named "
            "advocacy supporter across multiple sessions (EPIC). No citable source ties Hawaii's companion "
            "bill to that DC lineage, despite the two bills' near-identical text -- that specific cross-state "
            "link remains undocumented in public reporting."
        ),
        "sources": [
            {"label": "DC Office of the Attorney General press release (Dec. 9, 2021)", "url": "https://oag.dc.gov/release/ag-racine-introduces-legislation-stop"},
            {"label": "EPIC, \"EPIC Urges DC Council to Pass Algorithmic Discrimination Bill\"", "url": "https://epic.org/epic-urges-dc-council-to-pass-algorithmic-discrimination-bill/"},
        ],
    },
    5: {
        "bottom_line": (
            "The strongest documented evidence of genuine cross-state coordination of any cluster researched "
            "-- though still without a single named \"author\" organization. A 2026 academic paper (Smith, "
            "Caviola & Alexander, SSRN) finds that AI-personhood-exclusion bills nationally (a group that "
            "includes MO H721 and SC H3796) \"follow one of three common templates\" and reflect \"coordinated "
            "legislative diffusion rather than independent development,\" with a co-author's public post adding "
            "that bills \"share near-verbatim text\" with \"ample evidence of coordination across state lines.\" "
            "Even here, no source names who is doing the coordinating."
        ),
        "sources": [
            {"label": "Smith, Caviola & Alexander, \"Denying Personhood to AI\" (SSRN, 2026)", "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6829981"},
            {"label": "\"Can AI Be Conscious in Ohio?\" (Effective Altruism Forum)", "url": "https://forum.nunosempere.com/posts/GkuaqSsGpMzf6dtmd/can-ai-be-conscious-in-ohio"},
        ],
    },
    6: {
        "bottom_line": (
            "There is a real, named, multi-organization ecosystem producing model language in this exact "
            "policy area -- the California Medical Association's Physicians Make Decisions Act (spreading to "
            "other states per a vendor source), NAIC's Model Bulletin (adopted by roughly two dozen states, "
            "though not confirmed for NY/TN), and AMA/NCOIL's draft model act -- but no source found makes a "
            "direct, citable claim that NY A3991 or TN S1261/H1382 specifically originated from any one of "
            "these."
        ),
        "sources": [
            {"label": "California Medical Association press release on the Physicians Make Decisions Act", "url": "https://www.cmadocs.org/newsroom/news/view/ArticleId/50708/"},
            {"label": "Machinify, \"A Closer Look at the Physicians Make Decisions Act\" (industry vendor blog)", "url": "https://www.machinify.com/resources/a-closer-look-at-the-physicians-make-decisions-act-pmda"},
        ],
    },
    7: {
        "bottom_line": (
            "No citable source names a specific organization as the common drafter of this six-state cluster. "
            "The broader policy movement (\"AI can't deny your claim\" bills) is well documented and traces "
            "conceptually to California's CMA-sponsored Physicians Make Decisions Act as the first mover, with "
            "medical associations in various states actively advocating for similar bills -- but that is "
            "evidence of a shared policy movement, not a documented shared drafting source for this specific "
            "cluster's bill text."
        ),
        "sources": [
            {"label": "California Medical Association press release on the Physicians Make Decisions Act", "url": "https://www.cmadocs.org/newsroom/news/view/ArticleId/50708/"},
        ],
    },
    8: {
        "bottom_line": (
            "No source found connecting this cluster's specific bills to a common drafting organization. Given "
            "this cluster's already lower internal similarity (flagged as lower-confidence in the original "
            "data-only pass), that is an expected outcome rather than a surprising gap."
        ),
        "sources": [],
    },
}

# ncsl_bills' author_party can be None even when the primary author is a
# named individual (data gap) or when the "author" is actually a committee
# (e.g. MA S 2632: "Joint Cmt on Advanced Information Tech") -- neither case
# should be silently counted as a party value.
COMMITTEE_MARKERS = ("cmte", "cmt", "committee", "joint")


def is_committee(author_raw):
    if not author_raw:
        return False
    low = author_raw.lower()
    return any(m in low for m in COMMITTEE_MARKERS)


def classify_sponsorship(parties):
    if not parties:
        return "unknown_no_party_data"
    if len(parties) == 1:
        return "single_party"
    return "bipartisan_multi_party"


def main():
    clusters = json.loads(CLUSTERS_PATH.read_text())
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    out_clusters = []
    for c in clusters:
        cluster_id = c["cluster_id"]
        bills_out = []
        cluster_parties = set()
        for b in c["bills"]:
            row = conn.execute(
                "SELECT id, author_name, author_party, author_raw FROM ncsl_bills "
                "WHERE state_abbr=? AND bill_number=? AND year=?",
                (b["state_abbr"], b["bill_number"], b["year"]),
            ).fetchone()
            if row is None:
                raise RuntimeError(f"Bill not found in DB: {b}")

            sponsor_name = row["author_name"]
            sponsor_party = row["author_party"]
            sponsor_is_committee = is_committee(row["author_raw"])
            override_note = None

            if b["state_abbr"] == "ME" and b["bill_number"] == "S 531":
                sponsor_name = ME_S531_OVERRIDE["sponsor_name"]
                sponsor_party = ME_S531_OVERRIDE["sponsor_party"]
                override_note = ME_S531_OVERRIDE["override_note"]

            cosponsor_rows = conn.execute(
                "SELECT author_name, author_party FROM ncsl_bill_additional_authors WHERE bill_id=?",
                (row["id"],),
            ).fetchall()
            cosponsors = [
                {"name": r["author_name"], "party": r["author_party"]}
                for r in cosponsor_rows
            ]

            bill_parties = set()
            if sponsor_party:
                bill_parties.add(sponsor_party)
            for cs in cosponsors:
                if cs["party"]:
                    bill_parties.add(cs["party"])

            if not sponsor_is_committee:
                cluster_parties.update(bill_parties)

            bills_out.append({
                "state_abbr": b["state_abbr"],
                "bill_number": b["bill_number"],
                "year": b["year"],
                "summary": b["summary"],
                "sponsor_name": sponsor_name,
                "sponsor_party": sponsor_party,
                "sponsor_is_committee": sponsor_is_committee,
                "sponsor_raw": row["author_raw"],
                "sponsor_party_override_note": override_note,
                "cosponsors": cosponsors,
                "bill_sponsorship_type": classify_sponsorship(bill_parties) if not sponsor_is_committee else "unattributable_committee_sponsor",
            })

        states_by_party = {}
        for b in bills_out:
            if b["sponsor_is_committee"]:
                continue
            party = b["sponsor_party"] or "Unknown"
            states_by_party.setdefault(party, set()).add(b["state_abbr"])
        states_by_party = {k: sorted(v) for k, v in states_by_party.items()}

        out_clusters.append({
            "cluster_id": cluster_id,
            "theme": THEMES[cluster_id],
            "similarity_score": c["similarity_score"],
            "min_similarity_score": c["min_similarity_score"],
            "max_similarity_score": c["max_similarity_score"],
            "states_involved": c["states_involved"],
            "representative_summary": c["representative_summary"],
            "bills": bills_out,
            "distinct_parties_across_cluster": sorted(cluster_parties),
            "states_by_sponsor_party": states_by_party,
            "external_research": EXTERNAL_RESEARCH[cluster_id],
        })

    conn.close()

    report = {
        "method": (
            "Clusters and similarity scores come from a prior text-similarity pass (difflib.SequenceMatcher "
            "on NCSL's `summary` field, threshold 0.72; see data/cookie_cutter_report.md). Sponsor and "
            "co-sponsor party come from live joins of ncsl_bills + ncsl_bill_additional_authors, with one "
            "manual override (ME S 531 primary sponsor party, undocumented in NCSL data, verified against "
            "the Maine Legislature's own bill text). Organizational attribution ('who wrote this') is not "
            "inferred from party or state political lean -- it is reproduced from a separate, sourced "
            "research pass (data/cookie_cutter_external_research.md) and stated as 'not found' wherever that "
            "pass found no citable source."
        ),
        "note": (
            "A bill's sponsor party is a verifiable, registered fact (matched against this tracker's own "
            "database). A cluster's overall party pattern (e.g. 'all sponsors are Democrats,' 'split "
            "between states') is a description of who introduced these specific bills, not a claim about "
            "which party 'owns' the underlying issue -- correlation with a state's overall political lean "
            "is not asserted here."
        ),
        "limitations": [
            "Bill-level 'summary' fields (used for clustering) are NCSL's own short paraphrases, not the "
            "full statutory text -- similarity scores reflect summary-level, not verified bill-text, "
            "overlap.",
            "Sponsor party reflects the primary author's registered party at the time NCSL's data was "
            "captured; it does not reflect every co-sponsor's stance on the bill's substance.",
            "One bill in this dataset (MA S 2632) is sponsored by a legislative committee, not an "
            "individual, and is excluded from party tallies as unattributable.",
            "'No source found' in the external-research notes below means no citable public source was "
            "located during that research pass -- it is not a claim that no such source exists.",
        ],
        "clusters": out_clusters,
    }

    OUT_PATH.write_text(json.dumps(report, indent=2))
    print(f"Wrote {OUT_PATH} with {len(out_clusters)} clusters.")


if __name__ == "__main__":
    main()
