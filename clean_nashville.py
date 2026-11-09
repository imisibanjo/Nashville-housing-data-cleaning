"""
Nashville housing data cleaning pipeline
========================================

Every cleaning step is a small, single-purpose function that takes a DataFrame
and returns a DataFrame, so the steps can be run one at a time in the notebook
or all together from the command line:

    python src/clean_nashville.py

Each step appends a record to a log (rows before/after, cells changed, notes)
that is written to ``reports/cleaning_log.csv``.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = ROOT / "data" / "raw" / "Nashville_housing_data_2013_2016.csv"
CLEAN_PATH = ROOT / "data" / "processed" / "nashville_housing_clean.csv"
LOG_PATH = ROOT / "reports" / "cleaning_log.csv"

# A legal reference is "<recording date YYYYMMDD>-<7 digit instrument number>"
LEGAL_REF_PATTERN = re.compile(r"^\d{8}-\d{7}$")

# Typos / inconsistent labels found in the Land Use column
LAND_USE_FIXES = {
    "VACANT RES LAND": "VACANT RESIDENTIAL LAND",
    "VACANT RESIENTIAL LAND": "VACANT RESIDENTIAL LAND",
    "GREENBELT/RES\r\nGRRENBELT/RES": "GREENBELT/RES",
    "RESTURANT/CAFETERIA": "RESTAURANT/CAFETERIA",
}
# NOTE: the bare label "CONDO" is deliberately NOT merged into "RESIDENTIAL CONDO".
# Its price profile is very different (median ~$385k vs ~$220k, up to $4.25M), so it
# looks like a different population rather than a typo.

RESIDENTIAL = {
    "SINGLE FAMILY", "RESIDENTIAL CONDO", "DUPLEX", "ZERO LOT LINE", "TRIPLEX",
    "QUADPLEX", "RESIDENTIAL COMBO/MISC", "MOBILE HOME", "DORMITORY/BOARDING HOUSE",
}
VACANT = {
    "VACANT RESIDENTIAL LAND", "VACANT COMMERCIAL LAND", "VACANT RURAL LAND",
    "VACANT ZONED MULTI FAMILY", "GREENBELT", "GREENBELT/RES", "FOREST", "PARKING LOT",
}

VALID_GRADES = {"A", "B", "C", "D", "E", "X"}


# --------------------------------------------------------------------------- #
# Logging helper
# --------------------------------------------------------------------------- #
class CleaningLog:
    """Collects one row per cleaning step so the work is auditable."""

    def __init__(self) -> None:
        self.records: list[dict] = []

    def add(self, step: str, before: pd.DataFrame, after: pd.DataFrame,
            cells_changed: int | None, note: str) -> None:
        self.records.append(
            {
                "step": step,
                "rows_before": len(before),
                "rows_after": len(after),
                "cells_changed": cells_changed,
                "note": note,
            }
        )

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.records)


def _collapse_ws(s: pd.Series) -> pd.Series:
    """Strip and collapse repeated whitespace (incl. \\r\\n) inside strings."""
    return s.str.replace(r"\s+", " ", regex=True).str.strip()


def _n_changed(old: pd.Series, new: pd.Series) -> int:
    """Number of cells that differ, treating NaN == NaN."""
    return int((~((old == new) | (old.isna() & new.isna()))).sum())


# --------------------------------------------------------------------------- #
# Cleaning steps
# --------------------------------------------------------------------------- #
def load_raw(path: Path = RAW_PATH) -> pd.DataFrame:
    return pd.read_csv(path)


def tidy_columns(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """Drop junk columns and give every column a clean snake_case name."""
    before = df
    df = df.copy()
    # Two identical exported index columns and a Windows file path to a photo
    junk = ["Unnamed: 0.1", "Unnamed: 0", "image"]
    df = df.drop(columns=junk)
    df.columns = [
        re.sub(r"[^0-9a-z]+", "_", " ".join(c.split()).lower()).strip("_")
        for c in df.columns
    ]
    df = df.rename(
        columns={
            "suite_condo": "suite_condo_no",
            "multiple_parcels_involved_in_sale": "multiple_parcels_in_sale",
            "address": "assessor_address",
            "city": "assessor_city",
        }
    )
    log.add("tidy_columns", before, df, None,
            f"Dropped {junk}; renamed all columns to snake_case.")
    return df


def clean_text_fields(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """Collapse stray whitespace in address / owner fields and upper-case text."""
    before = df
    df = df.copy()
    changed = 0
    for col in ["property_address", "assessor_address", "owner_name",
                "property_city", "assessor_city", "tax_district",
                "foundation_type", "exterior_wall", "parcel_id"]:
        new = _collapse_ws(df[col]).str.upper()
        changed += _n_changed(df[col], new)
        df[col] = new
    log.add("clean_text_fields", before, df, changed,
            "Collapsed repeated spaces (e.g. '1208  3RD AVE S') and trimmed whitespace.")
    return df


def standardise_land_use(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """Merge duplicate / misspelled Land Use labels and add a coarse group."""
    before = df
    df = df.copy()
    cleaned = _collapse_ws(df["land_use"]).str.upper()
    cleaned = cleaned.replace({k.upper(): v for k, v in LAND_USE_FIXES.items()})
    # replace() above can't match the embedded \r\n key after whitespace collapse
    cleaned = cleaned.replace({"GREENBELT/RES GRRENBELT/RES": "GREENBELT/RES"})
    changed = _n_changed(df["land_use"], cleaned)
    df["land_use"] = cleaned
    df["land_use_group"] = np.select(
        [df["land_use"].isin(RESIDENTIAL), df["land_use"].isin(VACANT)],
        ["Residential", "Vacant / land"],
        default="Commercial / other",
    )
    log.add("standardise_land_use", before, df, changed,
            f"Merged variants/typos into canonical labels; "
            f"{df['land_use'].nunique()} distinct Land Use values remain. "
            "Added land_use_group.")
    return df


def standardise_categoricals(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """Booleans, placeholder values, and city back-fill."""
    before = df
    df = df.copy()
    changed = 0

    for col in ["sold_as_vacant", "multiple_parcels_in_sale"]:
        df[col] = df[col].map({"Yes": True, "No": False}).astype("boolean")

    # 'UNKNOWN' is a placeholder, not a city
    unk = df["property_city"].eq("UNKNOWN")
    df.loc[unk, "property_city"] = np.nan
    changed += int(unk.sum())

    # Back-fill Property City from the assessor city where we can
    fill = df["property_city"].isna() & df["assessor_city"].notna()
    df.loc[fill, "property_city"] = df.loc[fill, "assessor_city"]
    changed += int(fill.sum())

    # State is a constant ('TN') and assessor_city is now redundant
    df = df.drop(columns=["state", "assessor_city"])

    # Condo / suite numbers were read as floats in places ('211.0')
    suite = df["suite_condo_no"].astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
    changed += _n_changed(df["suite_condo_no"], suite)
    df["suite_condo_no"] = suite

    log.add("standardise_categoricals", before, df, changed,
            "Yes/No -> boolean; 'UNKNOWN' city -> NaN; city back-filled; "
            "dropped constant 'state' and redundant 'assessor_city'; "
            "fixed float-style suite numbers.")
    return df


def parse_types(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """Dates to datetime; float-encoded integers to nullable integers."""
    before = df
    df = df.copy()
    df["sale_date"] = pd.to_datetime(df["sale_date"], format="%Y-%m-%d")
    for col in ["neighborhood", "year_built", "bedrooms", "full_bath", "half_bath"]:
        df[col] = df[col].round().astype("Int64")
    df["sale_price"] = df["sale_price"].astype("int64")
    df["sale_year"] = df["sale_date"].dt.year.astype("int64")
    df["sale_month"] = df["sale_date"].dt.month.astype("int64")
    log.add("parse_types", before, df, None,
            "sale_date -> datetime64; neighborhood/year_built/bedrooms/baths -> nullable Int64; "
            "added sale_year, sale_month.")
    return df


def validate_legal_reference(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """Flag legal references that don't match YYYYMMDD-NNNNNNN."""
    before = df
    df = df.copy()
    df["legal_ref_valid"] = df["legal_reference"].str.match(LEGAL_REF_PATTERN)
    bad = int((~df["legal_ref_valid"]).sum())
    log.add("validate_legal_reference", before, df, bad,
            f"{bad} legal references are malformed (e.g. '20130682- 006678'); flagged, "
            "not altered, because the true value cannot be recovered.")
    return df


def drop_duplicate_sales(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """Same parcel, same day, same price => the same sale recorded twice.

    The surviving row is the one with a well-formed legal reference.
    """
    before = df
    key = ["parcel_id", "sale_date", "sale_price"]
    ordered = df.sort_values("legal_ref_valid", ascending=False, kind="stable")
    deduped = ordered.drop_duplicates(subset=key, keep="first").sort_index()
    log.add("drop_duplicate_sales", before, deduped, None,
            f"Removed {len(before) - len(deduped)} repeat records of the same "
            "parcel/date/price, keeping the row with a valid legal reference.")
    return deduped


def clean_property_attributes(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """Turn impossible zeros into missing values and normalise Grade."""
    before = df
    df = df.copy()
    changed = 0

    zero_area = df["finished_area"].eq(0)
    df.loc[zero_area, "finished_area"] = np.nan
    changed += int(zero_area.sum())

    # A single-family house with 0 bedrooms is a missing value, not a fact
    zero_bed = df["bedrooms"].eq(0) & df["land_use"].eq("SINGLE FAMILY")
    df.loc[zero_bed, "bedrooms"] = pd.NA
    changed += int(zero_bed.sum())

    grade = df["grade"].astype("string").str.strip().str.upper()
    grade_clean = grade.where(grade.isin(VALID_GRADES) | grade.isna(), "OTHER")
    changed += _n_changed(df["grade"], grade_clean)
    df["grade"] = grade_clean

    log.add("clean_property_attributes", before, df, changed,
            "finished_area == 0 -> NaN; 0 bedrooms on single-family -> NaN; "
            "commercial grade codes (TCC, AAC, ...) grouped as 'OTHER'.")
    return df


def add_quality_flags(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    """Flag rows an analyst should treat with care instead of silently deleting them."""
    before = df
    df = df.copy()
    df["has_assessor_data"] = df[["assessor_address", "total_value"]].notna().all(axis=1)

    # $50 / $100 / $1,000 "sales" are nominal transfers, not market prices
    df["nominal_price"] = df["sale_price"] < 1_000

    # When several parcels sell together the same total shows on each parcel's row
    df["price_is_bundle_total"] = df["multiple_parcels_in_sale"].fillna(False)

    vacant_land = df["land_use"].str.startswith("VACANT")
    df["sold_as_vacant_mismatch"] = df["sold_as_vacant"].fillna(False) != vacant_land

    df["built_after_sale"] = (df["year_built"].notna()
                              & (df["year_built"] > df["sale_year"]))

    df["price_comparable"] = ~(df["nominal_price"] | df["price_is_bundle_total"])

    log.add("add_quality_flags", before, df, None,
            "Added has_assessor_data, nominal_price, price_is_bundle_total, "
            "sold_as_vacant_mismatch, built_after_sale, price_comparable.")
    return df


def add_derived_features(df: pd.DataFrame, log: CleaningLog) -> pd.DataFrame:
    before = df
    df = df.copy()
    ok = df["price_comparable"] & df["finished_area"].gt(0) & df["land_use_group"].eq("Residential")
    df["price_per_sqft"] = np.where(ok, df["sale_price"] / df["finished_area"], np.nan).round(2)
    age = df["sale_year"] - df["year_built"].astype("float")
    df["age_at_sale"] = age.where(age >= 0).astype("Int64")
    log.add("add_derived_features", before, df, None,
            "Added price_per_sqft (comparable residential sales only) and age_at_sale.")
    return df


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
def run_pipeline(raw: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    log = CleaningLog()
    df = load_raw() if raw is None else raw
    for step in (tidy_columns, clean_text_fields, standardise_land_use,
                 standardise_categoricals, parse_types, validate_legal_reference,
                 drop_duplicate_sales, clean_property_attributes,
                 add_quality_flags, add_derived_features):
        df = step(df, log)
    return df.reset_index(drop=True), log.to_frame()


def main() -> None:
    clean, log = run_pipeline()
    CLEAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    clean.to_csv(CLEAN_PATH, index=False)
    log.to_csv(LOG_PATH, index=False)
    print(log.to_string(index=False))
    print(f"\nSaved {len(clean):,} rows x {clean.shape[1]} cols -> {CLEAN_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
