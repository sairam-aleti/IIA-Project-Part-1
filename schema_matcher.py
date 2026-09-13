"""
Schema matcher
==============
Discovers, at run time, which local column in each autonomous source carries
each attribute of the global schema. Nothing about the sources is hardcoded:
the matcher reflects their metadata and scores it against a description of the
global schema written in plain language.

Three things this matcher does that a naive one does not:

1. It matches *every* global attribute, not just the join key. The wrappers
   therefore contain no column names at all — rename `holder_name` to
   `owner_of_record` and the system keeps working.

2. Its vocabulary contains no local column names. The concept descriptions
   below were written against the global schema, not against the databases, so
   a high score is evidence the matcher works rather than evidence it was told
   the answer. (An earlier version listed `reg_num`, `plate_id` and
   `license_tag` as reference terms — which were verbatim the column names it
   was meant to discover. That is a lookup table, not a matcher.)

3. It uses the reflected column *type* as well as the name. A concept expecting
   a date will not be assigned to a text column, which is what keeps
   `observed_mark` from being mistaken for a sighting timestamp.

Scoring is a weighted sum of a semantic score (sentence-transformer cosine
similarity) and a lexical score (token-level Levenshtein), less a penalty when
the column's SQL type contradicts the concept's expected kind. Assignment is
greedy and one-to-one per source, and any match below MATCH_THRESHOLD is left
unmapped rather than forced — an unmapped attribute is reported as unavailable
instead of being silently wrong.

If sentence-transformers or its model cannot be loaded (no network on demo day,
for instance) the matcher degrades to lexical plus type scoring and says so.
Set IIA_MATCHER_MODE=lexical to force that path.
"""

import os
import re

import Levenshtein
from sqlalchemy import create_engine, inspect, text

# ======================================================================
# The global schema, described in plain language
# ======================================================================
# kind: the sort of value expected, used for the type-compatibility check.
#       'mark' and 'text' are both textual; 'mark' additionally signals that
#       this is the attribute the linkage index is built on.

GLOBAL_SCHEMA = {
    "vehicle_mark": {
        "kind": "mark",
        "description": "registration mark number plate identifying the vehicle",
    },
    "owner": {
        "kind": "text",
        "description": "full name of the person who holds the vehicle",
    },
    "vehicle_category": {
        "kind": "text",
        "description": "category or type of vehicle body such as car or motorcycle",
    },
    "registered_on": {
        "kind": "date",
        "description": "calendar date when the vehicle was first registered",
    },
    "chassis": {
        "kind": "text",
        "description": "chassis or frame serial number stamped on the vehicle",
    },
    "propulsion": {
        "kind": "text",
        "description": "fuel or energy source the vehicle runs on",
    },
    "policy_id": {
        "kind": "text",
        "description": "reference number of the insurance policy document",
    },
    "insurer": {
        "kind": "text",
        "description": "insurance company underwriting the cover",
    },
    "cover_begins": {
        "kind": "date",
        "description": "calendar date on which insurance cover commences",
    },
    "cover_ends": {
        "kind": "date",
        "description": "calendar date on which insurance cover expires",
    },
    "declared_policy_state": {
        "kind": "text",
        "description": "status label recorded against the policy such as active or lapsed",
    },
    "cover_type": {
        "kind": "text",
        "description": "extent of insurance cover comprehensive or third party",
    },
    "theft_flag": {
        "kind": "bool",
        "description": "whether the vehicle has been reported as stolen",
    },
    "theft_case": {
        "kind": "text",
        "description": "police case or first information report reference",
    },
    "recovered_on": {
        "kind": "date",
        "description": "calendar date a stolen vehicle was recovered",
    },
    "scrap_flag": {
        "kind": "bool",
        "description": "whether the vehicle has been scrapped shredded destroyed",
    },
    "scrap_certificate": {
        "kind": "text",
        "description": "certificate of destruction issued when scrapped",
    },
    "record_amended_on": {
        "kind": "datetime",
        "description": "moment this record was last amended or updated",
    },
    "sighting_id": {
        "kind": "int",
        "description": "sequence number of an individual roadside observation",
    },
    "sighting_time": {
        "kind": "datetime",
        "description": "moment at which the vehicle was observed on the road",
    },
    "sighting_place": {
        "kind": "text",
        "description": "place or gantry where the vehicle was observed",
    },
    "read_quality": {
        "kind": "float",
        "description": "numeric confidence of the automatic plate reading",
    },
    "finding": {
        "kind": "text",
        "description": "compliance finding raised against the vehicle",
    },
    "severity": {
        "kind": "text",
        "description": "seriousness assigned to the finding",
    },
    "finding_confidence": {
        "kind": "float",
        "description": "numeric confidence attached to the finding",
    },
    "evidence": {
        "kind": "text",
        "description": "supporting evidence recorded with the finding",
    },
    "raised_on": {
        "kind": "datetime",
        "description": "moment the finding was raised",
    },
    "source_sighting": {
        "kind": "int",
        "description": "observation that triggered the finding",
    },
}

# Which sources are expected to be able to supply which attributes. This is the
# GAV mapping's scope, not a column mapping — it says "the insurer may know
# about cover dates", never "cover dates live in cover_upto".
SOURCE_SCOPE = {
    "rto": ["vehicle_mark", "owner", "vehicle_category", "registered_on",
            "chassis", "propulsion"],
    "insurance": ["vehicle_mark", "policy_id", "insurer", "cover_begins",
                  "cover_ends", "declared_policy_state", "cover_type"],
    "police": ["vehicle_mark", "theft_flag", "theft_case", "recovered_on",
               "scrap_flag", "scrap_certificate", "record_amended_on"],
    "camera": ["vehicle_mark", "sighting_id", "sighting_time",
               "sighting_place", "read_quality"],
    "mot": ["vehicle_mark", "finding", "severity", "finding_confidence",
            "evidence", "raised_on", "source_sighting"],
}

DB_SOURCES = {
    "rto": "rto.db",
    "insurance": "insurance.db",
    "police": "police.db",
    "camera": "camera.db",
    "mot": "mot.db",
}

SEMANTIC_WEIGHT = 0.55
LEXICAL_WEIGHT = 0.45
TYPE_PENALTY = 0.45
MATCH_THRESHOLD = 0.34

_STOPWORDS = {"the", "of", "a", "an", "on", "at", "in", "or", "and", "such",
              "as", "which", "this", "was", "has", "been", "is", "it", "that"}


# ======================================================================
# Type compatibility
# ======================================================================

def _sql_kind(sql_type):
    """Collapse a reflected SQLAlchemy type into one of our coarse kinds."""
    name = str(sql_type).upper()
    if "BOOL" in name:
        return "bool"
    if "DATETIME" in name or "TIMESTAMP" in name:
        return "datetime"
    if "DATE" in name:
        return "date"
    if "FLOAT" in name or "REAL" in name or "NUMERIC" in name or "DECIMAL" in name:
        return "float"
    if "INT" in name:
        return "int"
    return "text"


_COMPATIBLE = {
    "mark": {"text"},
    "text": {"text"},
    "date": {"date", "datetime"},
    "datetime": {"datetime", "date"},
    "bool": {"bool", "int"},
    "int": {"int"},
    "float": {"float", "int"},
}


def _type_ok(concept_kind, column_kind):
    return column_kind in _COMPATIBLE.get(concept_kind, {"text"})


# ======================================================================
# Lexical scoring
# ======================================================================

def _tokens(text):
    parts = re.split(r"[^a-z0-9]+", str(text).lower())
    return [p for p in parts if p and p not in _STOPWORDS]


def lexical_score(column_name, description):
    """
    Token-level similarity between a column name and a concept description.

    Every column token is matched to its best description token by Levenshtein
    ratio; the score is the mean of those best matches, so a two-token column
    name where both tokens land well scores higher than one where only half of
    the name is meaningful.
    """
    col_tokens = _tokens(column_name)
    desc_tokens = _tokens(description)
    if not col_tokens or not desc_tokens:
        return 0.0
    best = []
    for ct in col_tokens:
        best.append(max(Levenshtein.ratio(ct, dt) for dt in desc_tokens))
    return sum(best) / len(best)


# ======================================================================
# Semantic scoring
# ======================================================================

class _SemanticScorer:
    """Wraps the sentence-transformer, degrading to a no-op if unavailable."""

    def __init__(self):
        self.model = None
        self.reason = None
        if os.environ.get("IIA_MATCHER_MODE", "").lower() == "lexical":
            self.reason = "forced by IIA_MATCHER_MODE=lexical"
            return
        try:
            from sentence_transformers import SentenceTransformer
            cache = os.environ.get("IIA_MODEL_DIR") or None
            self.model = SentenceTransformer("all-MiniLM-L6-v2", cache_folder=cache)
        except Exception as exc:                       # noqa: BLE001
            self.reason = f"{type(exc).__name__}: {exc}"[:140]

    @property
    def available(self):
        return self.model is not None

    def score_matrix(self, column_names, descriptions):
        """Cosine similarity of every column name against every description."""
        if not self.available:
            return None
        import numpy as np
        phrases = [c.replace("_", " ") for c in column_names]
        col_vecs = self.model.encode(phrases, normalize_embeddings=True)
        desc_vecs = self.model.encode(descriptions, normalize_embeddings=True)
        return np.asarray(col_vecs) @ np.asarray(desc_vecs).T


# ======================================================================
# Reflection
# ======================================================================

def reflect(db_sources=None, db_dir="."):
    """Read table and column metadata, with types, from every source."""
    db_sources = db_sources or DB_SOURCES
    schemas = {}
    for source, filename in db_sources.items():
        path = os.path.join(db_dir, filename)
        if not os.path.exists(path):
            continue
        engine = create_engine(f"sqlite:///{path}")
        inspector = inspect(engine)
        tables = {}
        for table in inspector.get_table_names():
            tables[table] = [
                {"name": col["name"], "kind": _sql_kind(col["type"])}
                for col in inspector.get_columns(table)
            ]
        schemas[source] = tables
        engine.dispose()
    return schemas


# ======================================================================
# Instance-level evidence for the join key
# ======================================================================
# Name-based matching is enough for ordinary attributes: if `severity` is
# mismapped, one field reads wrong and the mediator reports it as unavailable.
# The identifier is different. A wrong join key links nothing, so every
# downstream fact is lost and no amount of care further down recovers it.
#
# For that one attribute the matcher therefore also looks at the data: it
# samples the column's values and measures what fraction canonicalise into a
# valid registration mark. A column of plates is recognisable as plates
# whatever it happens to be called, which keeps linkage working even when the
# column names carry no meaning at all.
#
# Extending this to every attribute — value distributions, formats, ranges — is
# Part B work. Here it is applied only where a mistake is unrecoverable.

INSTANCE_SAMPLE = 60
INSTANCE_WEIGHT = 0.60


def sample_column(db_path, table, column, limit=INSTANCE_SAMPLE):
    """Read up to `limit` non-null values from a column."""
    try:
        engine = create_engine(f"sqlite:///{db_path}")
        with engine.connect() as conn:
            rows = conn.execute(text(
                f'SELECT "{column}" FROM {table} '
                f'WHERE "{column}" IS NOT NULL LIMIT {int(limit)}')).fetchall()
        engine.dispose()
        return [r[0] for r in rows]
    except Exception:                                  # noqa: BLE001
        return []


def plate_likeness(values):
    """
    Fraction of sampled values that canonicalise into a valid plate.

    Returns 0.0 for an empty sample, so a column with no data earns no bonus.
    """
    import plate as plate_util

    if not values:
        return 0.0
    hits = 0
    for value in values:
        mark = plate_util.canonical(value)
        if mark and plate_util.is_wellformed(mark):
            hits += 1
    return hits / len(values)


# ======================================================================
# Matching
# ======================================================================

def match_source(source, tables, scorer, verbose=False, db_path=None):
    """
    Produce an attribute-level mapping for one source.

    Returns
        {
          "table": "<the table the attributes were found in>",
          "attributes": { "<global attr>": {"column","score","semantic",
                                            "lexical","type_ok","kind"} },
          "unmapped": ["<global attr>", ...]
        }
    """
    wanted = SOURCE_SCOPE.get(source, list(GLOBAL_SCHEMA))
    descriptions = [GLOBAL_SCHEMA[a]["description"] for a in wanted]

    # Choose the table with the most columns — in these sources each database
    # has exactly one table, but scoring every table and keeping the best keeps
    # the matcher honest if a source later grows a second one.
    best_table, best_total, best_scores = None, -1.0, None
    for table, columns in tables.items():
        col_names = [c["name"] for c in columns]
        col_kinds = [c["kind"] for c in columns]
        semantic = scorer.score_matrix(col_names, descriptions)

        # score[i][j] = fitness of column i for attribute j
        grid = []
        for i, name in enumerate(col_names):
            row = []
            for j, attr in enumerate(wanted):
                sem = float(semantic[i][j]) if semantic is not None else 0.0
                lex = lexical_score(name, descriptions[j])
                if semantic is not None:
                    combined = SEMANTIC_WEIGHT * sem + LEXICAL_WEIGHT * lex
                else:
                    combined = lex
                ok = _type_ok(GLOBAL_SCHEMA[attr]["kind"], col_kinds[i])
                if not ok:
                    combined -= TYPE_PENALTY
                row.append({"score": combined, "semantic": sem,
                            "lexical": lex, "type_ok": ok})
            grid.append(row)

        # Instance evidence for the identifier column only.
        if "vehicle_mark" in wanted and db_path:
            j = wanted.index("vehicle_mark")
            for i, name in enumerate(col_names):
                if col_kinds[i] != "text":
                    continue
                likeness = plate_likeness(sample_column(db_path, table, name))
                grid[i][j]["instance"] = round(likeness, 4)
                grid[i][j]["score"] += INSTANCE_WEIGHT * likeness

        total = sum(max(row[j]["score"] for row in grid) for j in range(len(wanted)))
        if total > best_total:
            best_table, best_total, best_scores = table, total, (grid, col_names, col_kinds)

    grid, col_names, col_kinds = best_scores

    # Greedy one-to-one assignment: take the strongest remaining
    # (column, attribute) pair until nothing clears the threshold.
    pairs = sorted(
        ((grid[i][j]["score"], i, j) for i in range(len(col_names)) for j in range(len(wanted))),
        key=lambda t: -t[0],
    )
    taken_cols, taken_attrs, attributes = set(), set(), {}
    for score, i, j in pairs:
        if score < MATCH_THRESHOLD:
            break
        if i in taken_cols or j in taken_attrs:
            continue
        cell = grid[i][j]
        attributes[wanted[j]] = {
            "column": col_names[i],
            "kind": col_kinds[i],
            "score": round(score, 4),
            "semantic": round(cell["semantic"], 4),
            "lexical": round(cell["lexical"], 4),
            "instance": cell.get("instance"),
            "type_ok": cell["type_ok"],
        }
        taken_cols.add(i)
        taken_attrs.add(j)

    unmapped = [a for a in wanted if a not in attributes]

    if verbose:
        print(f"  {source} -> {best_table}")
        for attr in wanted:
            if attr in attributes:
                info = attributes[attr]
                extra = ""
                if info.get("instance") is not None:
                    extra = f" / inst {info['instance']:.2f}"
                print(f"      {attr:<24} = {info['column']:<22} "
                      f"score {info['score']:.3f}  "
                      f"(sem {info['semantic']:.3f} / lex {info['lexical']:.3f}{extra})")
            else:
                print(f"      {attr:<24} = UNMAPPED (no column above threshold)")

    return {"table": best_table, "attributes": attributes, "unmapped": unmapped}


def match_schemas(db_sources=None, db_dir=".", verbose=True):
    """Match every source. Returns the full mapping plus matcher metadata."""
    scorer = _SemanticScorer()
    schemas = reflect(db_sources, db_dir)

    if verbose:
        mode = "semantic + lexical + type" if scorer.available else "lexical + type"
        print(f"Schema matching ({mode})")
        if not scorer.available:
            print(f"  sentence-transformers unavailable: {scorer.reason}")
            print("  falling back to lexical scoring — mapping is still derived, "
                  "not hardcoded")
        print()

    sources = db_sources or DB_SOURCES
    mapping = {
        source: match_source(
            source, tables, scorer, verbose,
            db_path=os.path.join(db_dir, sources.get(source, f"{source}.db")))
        for source, tables in schemas.items()
    }

    return {
        "mode": "semantic+lexical" if scorer.available else "lexical",
        "semantic_available": scorer.available,
        "semantic_unavailable_reason": scorer.reason,
        "threshold": MATCH_THRESHOLD,
        "weights": {"semantic": SEMANTIC_WEIGHT, "lexical": LEXICAL_WEIGHT,
                    "type_penalty": TYPE_PENALTY},
        "global_schema": {a: GLOBAL_SCHEMA[a]["description"] for a in GLOBAL_SCHEMA},
        "sources": mapping,
    }


_cached = None


def generate_mapping(db_dir=".", verbose=True):
    global _cached
    if _cached is None:
        _cached = match_schemas(db_dir=db_dir, verbose=verbose)
    return _cached


if __name__ == "__main__":
    import json
    result = match_schemas()
    print()
    print(json.dumps({s: v["attributes"] for s, v in result["sources"].items()},
                     indent=2))
