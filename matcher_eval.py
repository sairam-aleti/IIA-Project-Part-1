"""
Matcher robustness evaluation
=============================
    python matcher_eval.py

The obvious objection to any schema matcher that scores 100% is that it was
told the answer. The concept descriptions in schema_matcher.py inevitably share
some domain vocabulary with the local columns — "cover" appears both in the
description of cover_ends and in the column cover_upto — so a perfect score on
the shipped schema proves less than it looks.

This harness answers the objection by measurement. It copies the databases,
renames every column to vocabulary the matcher has never seen, re-runs
discovery, and scores it. Three regimes:

    abbreviated  clipped forms a DBA would actually type  (regn_mk, hldr_nm)
    synonymous   different words for the same concept     (licence_tag, keeper)
    opaque       names carrying no meaning at all         (c1, c2, c3)

The third regime is expected to fail, and reporting that is the point. A
matcher that cannot see the answer should decline to map rather than guess, and
what this harness checks is that failures show up as unmapped attributes rather
than as confident wrong answers. Wrong-but-confident is the only outcome that
would actually be dangerous.

Instance-level evidence — looking at the *values* in a column, not just its
name — is what recovers the opaque case. That is Part B work.
"""

import os
import shutil
import sqlite3
import tempfile
from collections import Counter

from schema_matcher import SOURCE_SCOPE, match_schemas
from verify import GROUND_TRUTH

DB_FILES = ["rto.db", "insurance.db", "police.db", "camera.db", "mot.db"]

TABLES = {
    "rto.db": "vehicle_register",
    "insurance.db": "motor_policy",
    "police.db": "theft_and_scrap_register",
    "camera.db": "anpr_read",
    "mot.db": "compliance_report",
}

# Each regime maps original column name -> replacement.
REGIMES = {
    "abbreviated": {
        "registration_mark": "regn_mk", "holder_name": "hldr_nm",
        "body_type": "bdy_typ", "first_reg_on": "reg_dt",
        "frame_serial": "frm_srl", "fuel": "fl",
        "policy_ref": "pol_rf", "insured_vehicle_no": "insd_veh_no",
        "underwriter": "undrwrtr", "cover_from": "cov_frm",
        "cover_upto": "cov_upto", "policy_state": "pol_st",
        "cover_kind": "cov_knd",
        "plate_marking": "plt_mrk", "reported_stolen": "rptd_stln",
        "case_ref": "cs_rf", "recovered_on": "rcvrd_dt",
        "shredded": "shrdd", "shred_cert": "shrd_crt",
        "last_amended": "lst_amnd",
        "read_id": "rd_id", "observed_mark": "obsv_mk",
        "gantry_location": "gntry_loc", "observed_on": "obsv_dt",
        "read_score": "rd_scr",
        "subject_mark": "subj_mk", "finding": "fndng", "severity": "svrty",
        "decision_confidence": "dcsn_conf", "evidence_json": "evdnc",
        "raised_on": "rsd_dt", "triggering_read": "trg_rd",
    },
    "synonymous": {
        "registration_mark": "licence_tag", "holder_name": "keeper",
        "body_type": "segment", "first_reg_on": "inducted_date",
        "frame_serial": "vin", "fuel": "energy_source",
        "policy_ref": "contract_id", "insured_vehicle_no": "asset_tag",
        "underwriter": "carrier", "cover_from": "effective_date",
        "cover_upto": "termination_date", "policy_state": "contract_status",
        "cover_kind": "protection_level",
        "plate_marking": "tag_number", "reported_stolen": "larceny_flag",
        "case_ref": "docket_no", "recovered_on": "retrieval_date",
        "shredded": "dismantled", "shred_cert": "disposal_doc",
        "last_amended": "revision_ts",
        "read_id": "capture_seq", "observed_mark": "detected_tag",
        "gantry_location": "post_name", "observed_on": "detection_ts",
        "read_score": "certainty",
        "subject_mark": "target_tag", "finding": "verdict",
        "severity": "gravity", "decision_confidence": "assurance",
        "evidence_json": "substantiation", "raised_on": "lodged_ts",
        "triggering_read": "origin_capture",
    },
    "opaque": {},   # filled in programmatically: c1, c2, c3, ...
}


def _build_opaque():
    """Rename every column to a meaningless positional name."""
    mapping = {}
    for columns in GROUND_TRUTH.values():
        for original in columns.values():
            mapping.setdefault(original, None)
    for index, original in enumerate(sorted(mapping), start=1):
        mapping[original] = f"c{index}"
    return mapping


REGIMES["opaque"] = _build_opaque()


def perturb(regime, src_dir=".", dst_dir=None):
    """Copy the databases and rename their columns under a regime."""
    renames = REGIMES[regime]
    dst_dir = dst_dir or tempfile.mkdtemp(prefix=f"iia_{regime}_")
    for filename in DB_FILES:
        src = os.path.join(src_dir, filename)
        if not os.path.exists(src):
            continue
        dst = os.path.join(dst_dir, filename)
        shutil.copy2(src, dst)
        table = TABLES[filename]
        conn = sqlite3.connect(dst)
        existing = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
        for column in existing:
            new = renames.get(column)
            if new and new != column:
                conn.execute(f'ALTER TABLE {table} RENAME COLUMN "{column}" TO "{new}"')
        conn.commit()
        conn.close()
    return dst_dir


def expected_for(regime):
    """Ground truth translated into the regime's column names."""
    renames = REGIMES[regime]
    return {
        source: {attr: renames.get(col, col) for attr, col in columns.items()}
        for source, columns in GROUND_TRUTH.items()
    }


def score(regime, db_dir):
    mapping = match_schemas(db_dir=db_dir, verbose=False)
    truth = expected_for(regime)
    tally = Counter()
    misses = []

    for source, conf in mapping["sources"].items():
        for attribute in SOURCE_SCOPE[source]:
            expected = truth[source].get(attribute)
            found = conf["attributes"].get(attribute, {}).get("column")
            if found == expected:
                tally["correct"] += 1
            elif found is None:
                tally["unmapped"] += 1
                misses.append((source, attribute, expected, "unmapped"))
            else:
                tally["wrong"] += 1
                misses.append((source, attribute, expected, found))
    return mapping, tally, misses


def main():
    if not os.path.exists("rto.db"):
        print("Run data_generator.py first.")
        return

    print("=" * 74)
    print("Schema matcher robustness under column renaming")
    print("=" * 74)


    # baseline on the shipped schema
    mapping, tally, misses = score_baseline()
    _report("as shipped", mapping, tally, misses)

    for regime in ("abbreviated", "synonymous", "opaque"):
        db_dir = perturb(regime)
        try:
            # the matcher caches its result, so clear it between regimes
            import schema_matcher
            schema_matcher._cached = None
            mapping, tally, misses = score(regime, db_dir)
            _report(regime, mapping, tally, misses)
        finally:
            shutil.rmtree(db_dir, ignore_errors=True)

    print("\n" + "=" * 74)
    print("Reading the results")
    print("=" * 74)
    print("""
The abbreviated and synonymous regimes test whether discovery survives
vocabulary the matcher has never seen. The opaque regime removes all signal
from the column names, and the matcher is expected to fail there.

What matters in the opaque regime is *how* it fails. Unmapped attributes are a
safe failure: the mediator reports the attribute as unavailable and the
assessment degrades to INSUFFICIENT_EVIDENCE rather than asserting something
false. Confidently wrong mappings are the dangerous failure, because they
produce a report against a citizen built on the wrong column.

Recovering the opaque case needs instance-level evidence — inspecting the
values a column holds rather than its name, so that a column of strings
matching the plate grammar is recognisable as the identifier whatever it is
called. That is Part B work, and this harness is the measurement it will be
judged against.
""")


def score_baseline():
    import schema_matcher
    schema_matcher._cached = None
    mapping = match_schemas(db_dir=".", verbose=False)
    tally = Counter()
    misses = []
    for source, conf in mapping["sources"].items():
        for attribute in SOURCE_SCOPE[source]:
            expected = GROUND_TRUTH[source].get(attribute)
            found = conf["attributes"].get(attribute, {}).get("column")
            if found == expected:
                tally["correct"] += 1
            elif found is None:
                tally["unmapped"] += 1
                misses.append((source, attribute, expected, "unmapped"))
            else:
                tally["wrong"] += 1
                misses.append((source, attribute, expected, found))
    return mapping, tally, misses


def _report(label, mapping, tally, misses):
    total = sum(tally.values())
    print(f"\n{'-' * 74}")
    print(f"{label}   (mode: {mapping['mode']})")
    print(f"{'-' * 74}")
    print(f"  correct  {tally['correct']:>3} / {total}   "
          f"({100 * tally['correct'] / total:.1f}%)")
    print(f"  unmapped {tally['unmapped']:>3}        (safe failure — reported "
          f"as unavailable)")
    print(f"  wrong    {tally['wrong']:>3}        (unsafe failure — confidently "
          f"incorrect)")
    if misses:
        print("\n  misses:")
        for source, attribute, expected, found in misses[:14]:
            print(f"      {source}.{attribute:<22} expected {str(expected):<18} "
                  f"got {found}")
        if len(misses) > 14:
            print(f"      ... and {len(misses) - 14} more")


if __name__ == "__main__":
    main()
