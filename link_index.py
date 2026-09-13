"""
Linkage index
=============
Entity resolution is a *table*, not a join condition.

Each source records the registration mark in its own format, so no equi-join
across the raw columns will work. This module builds, per source, a mapping
from canonical mark to the raw values that source actually holds:

    canonical DL3CAB1234
        rto        "DL-3C-AB-1234"      exact_canonical   1.0
        insurance  "dl 3c ab 1234"      exact_canonical   1.0
        police     "DL3CAB1234"         exact_canonical   1.0
        camera     "DL3CAB1234"         exact_canonical   1.0
                   "  DL3CAB1234 "      exact_canonical   1.0

Every link carries a method and a score. In Part A the only method is
`exact_canonical` and every score is 1.0 — canonicalisation is deterministic,
so a link either exists or it does not. The columns are there so Part B can add
`confusable_block` and `probabilistic` links with scores below 1.0 without
anything downstream changing shape.

Raw values that canonicalise to a mark no source recognises are kept as
`orphans`. Those are the corrupted ANPR reads, and they are why the mediator
needs an INSUFFICIENT_EVIDENCE outcome.
"""

import os
from collections import defaultdict

from sqlalchemy import create_engine, text

import plate as plate_util

LINK_METHOD_EXACT = "exact_canonical"


class LinkIndex:
    """Canonical-mark index across all sources, built once at startup."""

    def __init__(self, mapping, db_dir="."):
        """
        Args:
            mapping: the full result from schema_matcher.match_schemas()
            db_dir:  directory holding the .db files
        """
        self.mapping = mapping
        self.db_dir = db_dir
        # canonical mark -> source -> list of {raw, method, score}
        self.links = defaultdict(lambda: defaultdict(list))
        # source -> raw value -> canonical mark
        self.raw_to_canonical = defaultdict(dict)
        self.stats = {}
        self._build()

    # ------------------------------------------------------------------
    def _build(self):
        from data_generator import DB_FILES

        filenames = {label: name for name, (_, label) in DB_FILES.items()}
        malformed_total = 0

        for source, conf in self.mapping["sources"].items():
            mark_attr = conf["attributes"].get("vehicle_mark")
            if not mark_attr:
                # the matcher could not find an identifier column in this
                # source, so it cannot participate in linkage at all
                self.stats[source] = {"rows": 0, "linked": 0, "malformed": 0,
                                      "unavailable": True}
                continue

            column = mark_attr["column"]
            table = conf["table"]
            path = os.path.join(self.db_dir, filenames.get(source, f"{source}.db"))
            if not os.path.exists(path):
                self.stats[source] = {"rows": 0, "linked": 0, "malformed": 0,
                                      "unavailable": True}
                continue

            engine = create_engine(f"sqlite:///{path}")
            with engine.connect() as conn:
                rows = conn.execute(text(f"SELECT {column} FROM {table}")).fetchall()
            engine.dispose()

            linked = malformed = 0
            for (raw,) in rows:
                mark = plate_util.canonical(raw)
                if mark is None:
                    malformed += 1
                    continue
                if not plate_util.is_wellformed(mark):
                    # canonicalised cleanly but does not match the national
                    # plate grammar — a garbled read, not a vehicle
                    malformed += 1
                self.links[mark][source].append(
                    {"raw": raw, "method": LINK_METHOD_EXACT, "score": 1.0}
                )
                self.raw_to_canonical[source][raw] = mark
                linked += 1

            malformed_total += malformed
            self.stats[source] = {
                "rows": len(rows),
                "linked": linked,
                "malformed": malformed,
                "distinct_marks": len({plate_util.canonical(r[0]) for r in rows}) - 0,
            }

        # A mark is "known" if any authoritative register holds it. Camera
        # reads alone do not establish that a vehicle exists.
        authoritative = {"rto", "insurance", "police"}
        self.known_marks = {
            mark for mark, by_source in self.links.items()
            if authoritative & set(by_source)
        }
        self.orphan_marks = {
            mark for mark, by_source in self.links.items()
            if not (authoritative & set(by_source))
        }
        self.stats["_totals"] = {
            "canonical_marks": len(self.links),
            "known_marks": len(self.known_marks),
            "orphan_marks": len(self.orphan_marks),
            "malformed_values": malformed_total,
        }

    # ------------------------------------------------------------------
    def resolve(self, query):
        """
        Canonicalise a user-supplied plate and report what is known about it.

        Returns a dict describing the identity decision itself, which the
        mediator records as provenance for the linkage step.
        """
        mark = plate_util.canonical(query)
        return {
            "query": query,
            "canonical_mark": mark,
            "wellformed": plate_util.is_wellformed(mark),
            "known": mark in self.known_marks,
            "sources_holding": sorted(self.links.get(mark, {}).keys()),
            "method": LINK_METHOD_EXACT,
            "score": 1.0 if mark in self.links else 0.0,
        }

    def raw_values(self, mark, source):
        """The raw strings this source uses for a canonical mark."""
        return [link["raw"] for link in self.links.get(mark, {}).get(source, [])]

    def all_known(self):
        return sorted(self.known_marks)

    def orphans(self):
        """
        Canonical marks seen only by the cameras.

        Each is a read that cannot be tied to any registered vehicle. Some are
        genuinely unregistered vehicles; most are OCR corruptions of a real
        plate. Part A cannot tell which, and says so.
        """
        return sorted(self.orphan_marks)

    def link_records(self, mark):
        """Flat link rows for one mark — the audit trail for identity."""
        out = []
        for source, links in self.links.get(mark, {}).items():
            for link in links:
                out.append({
                    "canonical_mark": mark,
                    "source": source,
                    "raw_value": link["raw"],
                    "match_method": link["method"],
                    "match_score": link["score"],
                })
        return out


# ----------------------------------------------------------------------
# Diagnostic: what a naive join would have achieved
# ----------------------------------------------------------------------

def naive_join_count(mapping, db_dir="."):
    """
    Count vehicles an equi-join on the raw identifier columns would recover.

    Used by verify.py to show that canonicalisation is load-bearing rather
    than decorative.
    """
    from data_generator import DB_FILES

    filenames = {label: name for name, (_, label) in DB_FILES.items()}
    raw_sets = {}
    for source, conf in mapping["sources"].items():
        mark_attr = conf["attributes"].get("vehicle_mark")
        if not mark_attr:
            continue
        path = os.path.join(db_dir, filenames.get(source, f"{source}.db"))
        if not os.path.exists(path):
            continue
        engine = create_engine(f"sqlite:///{path}")
        with engine.connect() as conn:
            rows = conn.execute(
                text(f"SELECT DISTINCT {mark_attr['column']} FROM {conf['table']}")
            ).fetchall()
        engine.dispose()
        raw_sets[source] = {r[0] for r in rows if r[0] is not None}

    if not raw_sets:
        return {"pairs": {}, "per_source_rows": {}}

    canon_sets = {
        source: {plate_util.canonical(v) for v in values}
        for source, values in raw_sets.items()
    }

    # Pairwise, because a five-way intersection is empty by construction: the
    # police register and the reporting sink only hold a small subset of
    # vehicles. Comparing pairs isolates the effect of canonicalisation from
    # the effect of ragged coverage.
    interesting = [("rto", "insurance"), ("rto", "camera"),
                   ("insurance", "camera"), ("rto", "police")]
    pairs = {}
    for left, right in interesting:
        if left not in raw_sets or right not in raw_sets:
            continue
        pairs[f"{left} n {right}"] = {
            "raw": len(raw_sets[left] & raw_sets[right]),
            "canonical": len(canon_sets[left] & canon_sets[right]),
        }

    return {
        "per_source_rows": {s: len(v) for s, v in raw_sets.items()},
        "pairs": pairs,
    }
