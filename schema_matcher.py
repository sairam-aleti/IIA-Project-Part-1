"""
Algorithmic Schema Matcher
==========================
Uses sentence-transformers (all-MiniLM-L6-v2) and Levenshtein distance
to automatically discover which local column in each source database
maps to the global key `vehicle_identifier`.

No column joins are hardcoded — the mapping is discovered at runtime
by reflecting each database's schema and scoring columns against
a semantic concept.
"""

import os
from itertools import product

from sqlalchemy import create_engine, inspect
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import Levenshtein
import numpy as np

# ==========================================
# Configuration
# ==========================================

# The semantic concept we want to match against
TARGET_CONCEPT = "vehicle identifier registration license plate number"

# Reference terms for Levenshtein string matching
REFERENCE_TERMS = [
    "vehicle_id", "vehicle_identifier", "plate", "plate_id",
    "registration", "reg_num", "reg_no", "vehicle_reg",
    "license", "license_tag", "license_plate"
]

# Suffixes/substrings that indicate a column is a date/timestamp,
# NOT an identifier key.  These columns get a score penalty.
DATE_INDICATORS = ["_date", "_at", "time", "timestamp", "created", "updated"]
DATE_PENALTY = 0.35  # subtracted from combined score for date-like columns

# Database file paths (relative)
DB_SOURCES = {
    "camera_db":    "camera.db",
    "rto_db":       "rto.db",
    "insurance_db": "insurance.db",
    "police_db":    "police.db",
}

# Weights for combining similarity scores
SEMANTIC_WEIGHT = 0.6
STRING_WEIGHT = 0.4


# ==========================================
# Schema Reflection
# ==========================================

def reflect_schemas(db_sources: dict) -> dict:
    """
    Reflect all table/column metadata from each SQLite database.

    Returns:
        {
            "camera_db": {"Capture": ["capture_id", "plate_id", ...]},
            ...
        }
    """
    schemas = {}
    for source_name, db_path in db_sources.items():
        if not os.path.exists(db_path):
            print(f"  [WARNING] {db_path} not found, skipping {source_name}")
            continue
        engine = create_engine(f"sqlite:///{db_path}")
        inspector = inspect(engine)
        tables = {}
        for table_name in inspector.get_table_names():
            columns = [col["name"] for col in inspector.get_columns(table_name)]
            tables[table_name] = columns
        schemas[source_name] = tables
        engine.dispose()
    return schemas


# ==========================================
# Similarity Computation
# ==========================================

def compute_semantic_similarity(column_names: list, model: SentenceTransformer) -> np.ndarray:
    """
    Compute cosine similarity between each column name and the TARGET_CONCEPT
    using sentence-transformer embeddings.

    Returns:
        1-D numpy array of similarity scores, one per column.
    """
    # Convert column names to natural language phrases for better embedding
    phrases = [col.replace("_", " ") for col in column_names]
    target_embedding = model.encode([TARGET_CONCEPT])
    column_embeddings = model.encode(phrases)
    similarities = cosine_similarity(column_embeddings, target_embedding).flatten()
    return similarities


def compute_string_similarity(column_names: list) -> np.ndarray:
    """
    Compute the best normalized Levenshtein similarity between each column name
    and the set of REFERENCE_TERMS.

    Returns:
        1-D numpy array of similarity scores (0..1), one per column.
    """
    scores = []
    for col in column_names:
        col_lower = col.lower()
        # Best match against any reference term
        best = max(
            Levenshtein.ratio(col_lower, ref) for ref in REFERENCE_TERMS
        )
        scores.append(best)
    return np.array(scores)


def compute_combined_scores(
    column_names: list,
    model: SentenceTransformer,
    semantic_weight: float = SEMANTIC_WEIGHT,
    string_weight: float = STRING_WEIGHT,
) -> np.ndarray:
    """
    Weighted combination of semantic and string similarity,
    with a penalty for date/timestamp columns that cannot be identifiers.
    """
    semantic = compute_semantic_similarity(column_names, model)
    string = compute_string_similarity(column_names)
    combined = semantic_weight * semantic + string_weight * string

    # Penalize date-like columns — they are never identifier keys
    for i, col in enumerate(column_names):
        col_lower = col.lower()
        if any(indicator in col_lower for indicator in DATE_INDICATORS):
            combined[i] = max(0, combined[i] - DATE_PENALTY)

    return combined, semantic, string


# ==========================================
# Schema Matching Engine
# ==========================================

def match_schemas(db_sources: dict = None) -> dict:
    """
    Main entry point.  Reflects all source schemas, scores every column,
    and returns the mapping dictionary.

    Returns:
        SCHEMA_MAPPING dict, e.g.:
        {
            "camera_db": {"local_key": "plate_id", "table": "Capture"},
            ...
        }
    """
    if db_sources is None:
        db_sources = DB_SOURCES

    print("=" * 60)
    print("  Algorithmic Schema Matcher")
    print("=" * 60)
    print(f"\n  Target concept : \"{TARGET_CONCEPT}\"")
    print(f"  Scoring weights: semantic={SEMANTIC_WEIGHT}, string={STRING_WEIGHT}\n")

    # Load the sentence-transformer model
    print("  Loading sentence-transformer model (all-MiniLM-L6-v2)...")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    print("  Model loaded.\n")

    # Reflect schemas
    print("  Reflecting database schemas...")
    schemas = reflect_schemas(db_sources)
    print(f"  Found {len(schemas)} sources.\n")

    schema_mapping = {}

    for source_name, tables in schemas.items():
        print(f"  -- Source: {source_name} --")

        best_score = -1
        best_column = None
        best_table = None

        for table_name, columns in tables.items():
            combined, semantic, string = compute_combined_scores(columns, model)

            # Print similarity matrix for this table
            print(f"     Table: {table_name}")
            print(f"     {'Column':<25} {'Semantic':>10} {'String':>10} {'Combined':>10}")
            print(f"     {'-'*25} {'-'*10} {'-'*10} {'-'*10}")
            for i, col in enumerate(columns):
                marker = " <-- BEST" if combined[i] == max(combined) and combined[i] > best_score else ""
                print(f"     {col:<25} {semantic[i]:>10.4f} {string[i]:>10.4f} {combined[i]:>10.4f}{marker}")

            # Track the best column across all tables in this source
            idx = int(np.argmax(combined))
            if combined[idx] > best_score:
                best_score = combined[idx]
                best_column = columns[idx]
                best_table = table_name

        schema_mapping[source_name] = {
            "local_key": best_column,
            "table": best_table,
            "confidence": round(float(best_score), 4),
        }
        print(f"     -> Matched: {best_table}.{best_column} (score={best_score:.4f})\n")

    print("=" * 60)
    print("  Final Schema Mapping (SCHEMA_MAPPING)")
    print("=" * 60)
    for src, info in schema_mapping.items():
        print(f"    {src:<18} -> {info['table']}.{info['local_key']}  (conf={info['confidence']})")
    print()

    return schema_mapping


# ==========================================
# Module-level export
# ==========================================

# When imported, run matching and export the result
# This is lazily evaluated — call generate_mapping() to trigger it.

_cached_mapping = None

def generate_mapping() -> dict:
    """Generate (or return cached) schema mapping."""
    global _cached_mapping
    if _cached_mapping is None:
        _cached_mapping = match_schemas()
    return _cached_mapping


if __name__ == "__main__":
    mapping = match_schemas()
    print("\nExported SCHEMA_MAPPING:")
    import json
    print(json.dumps(mapping, indent=2))
