"""
External reference data NOT present in any scraped source (NCSL/AAF/FPF).
Added only to support two specific Step-6-required metrics that the scraped
trackers structurally cannot answer on their own: per-capita bill volume and
red/blue state grouping. Kept isolated in this module so it's never confused
with scraped data, and every table below states its own source and vintage.

Approved by user 2026-07-07: (1) add a Census population reference table for
per-capita counts, (2) use 2024 presidential statewide popular-vote winner as
the red/blue classification, cited as external public-record reference data
-- not this app's characterization of any state or bill.
"""

# Approximate population, U.S. Census Bureau Vintage 2024 population estimates
# (release Dec 2024), rounded to the nearest thousand. For descriptive
# per-capita ratios only -- not exact to the person.
STATE_POPULATION = {
    "AL": 5158, "AK": 733, "AZ": 7582, "AR": 3089, "CA": 39431,
    "CO": 5957, "CT": 3676, "DE": 1032, "DC": 704, "FL": 23372,
    "GA": 11180, "HI": 1446, "ID": 2027, "IL": 12710, "IN": 6924,
    "IA": 3241, "KS": 2974, "KY": 4588, "LA": 4597, "ME": 1410,
    "MD": 6275, "MA": 7132, "MI": 10140, "MN": 5793, "MS": 2943,
    "MO": 6246, "MT": 1150, "NE": 2006, "NV": 3268, "NH": 1410,
    "NJ": 9500, "NM": 2131, "NY": 19867, "NC": 11046, "ND": 800,
    "OH": 11883, "OK": 4096, "OR": 4272, "PA": 13079, "RI": 1113,
    "SC": 5478, "SD": 924, "TN": 7227, "TX": 31290, "UT": 3503,
    "VT": 648, "VA": 8811, "WA": 7958, "WV": 1769, "WI": 5960,
    "WY": 587,
    # Territories tracked by NCSL that also have Census population estimates
    "PR": 3205, "GU": 168, "VI": 87,
}
POPULATION_SOURCE = "U.S. Census Bureau, Vintage 2024 Population Estimates (approximate, rounded to nearest thousand)"

# 2024 U.S. presidential election, statewide popular-vote winner (not
# district-split electoral votes in ME/NE). Public record. Territories do not
# vote in presidential elections and are marked as such, not classified.
STATE_2024_PRES_WINNER = {
    "AL": "R", "AK": "R", "AZ": "R", "AR": "R", "CA": "D",
    "CO": "D", "CT": "D", "DE": "D", "DC": "D", "FL": "R",
    "GA": "R", "HI": "D", "ID": "R", "IL": "D", "IN": "R",
    "IA": "R", "KS": "R", "KY": "R", "LA": "R", "ME": "D",
    "MD": "D", "MA": "D", "MI": "R", "MN": "D", "MS": "R",
    "MO": "R", "MT": "R", "NE": "R", "NV": "R", "NH": "D",
    "NJ": "D", "NM": "D", "NY": "D", "NC": "R", "ND": "R",
    "OH": "R", "OK": "R", "OR": "D", "PA": "R", "RI": "D",
    "SC": "R", "SD": "R", "TN": "R", "TX": "R", "UT": "R",
    "VT": "D", "VA": "D", "WA": "D", "WV": "R", "WI": "R",
    "WY": "R",
    # Territories: no presidential electoral vote
    "PR": "N/A - territory, no presidential vote",
    "GU": "N/A - territory, no presidential vote",
    "VI": "N/A - territory, no presidential vote",
}
ELECTION_SOURCE = "2024 U.S. presidential election, statewide popular-vote winner (public record)"

# Full universe of jurisdictions NCSL's own database covers (50 states + DC +
# 5 populated territories), used only to compute which have zero bills in the
# scraped NCSL data -- not itself scraped, just the standard list of US
# states/DC/territories.
ALL_US_JURISDICTIONS = sorted(list(STATE_POPULATION.keys()) + ["AS", "MP"])
