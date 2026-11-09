# Nashville-housing-data-cleaning
A data cleaning project

# Nashville Housing Data Cleaning

A reproducible data-cleaning project on **56,636 Nashville (Davidson County) property sales from 2013 to 2016**. The raw export had duplicate sales, inconsistent categories, wrong data types, impossible values, and, most importantly, **54% of rows with no property-assessor data at all**.

The goal was not just to "make it tidy" but to make every decision explicit: what was fixed, what was flagged instead of deleted, and what cannot be recovered.

**Tools:** Python · pandas · NumPy · matplotlib

---

## Key results

| Raw | Clean |
Rows | 56,636 | 56,468 |
Columns | 31 | 38 (junk removed, flags and features added) |
Duplicate sales (same parcel, date, price) | 168 | 0 |
Distinct `Land Use` labels | 39 | 37 |
Float-encoded integers / text dates | yes | proper `Int64` / `datetime64` |

**Things the cleaning surfaced**

* **Missing data is structural, not random.** 30,619 rows (54.1%) have no assessor fields. Every residential condo sale is affected, as are most sales in Brentwood and Antioch. None of the gaps could be filled from another sale of the same parcel (0 of 30,619 recoverable), so the rows were kept and flagged with `has_assessor_data` rather than imputed.
* **Duplicates hide behind typos.** The same sale was entered twice with different, often malformed, legal references (`20150819-0083759` vs `25015081- 008375`), so de-duplicating on the legal reference alone would miss them.
* **Outliers are mostly meaning, not error.** The $54,278,060 maximum is one multi-parcel sale whose total was repeated on 7 parcel rows. 4,678 rows (8.3%) carry a bundle total, which would double-count in any sum or average.

![Assessor data coverage](images/01_assessor_data_coverage.png)

![Price distribution and data-quality flags](images/02_price_distribution_and_flags.png)

---

## Cleaning steps

| # | Step | What it does |

| 1 | `tidy_columns` | Drops 2 duplicate index columns and a file-path column; converts names to `snake_case` |
| 2 | `clean_text_fields` | Collapses repeated whitespace (`'1208  3RD AVE S'`), trims, upper-cases |
| 3 | `standardise_land_use` | Merges `VACANT RES LAND` / `VACANT RESIENTIAL LAND` into `VACANT RESIDENTIAL LAND`, fixes typos, adds `land_use_group` |
| 4 | `standardise_categoricals` | Yes/No to boolean, `UNKNOWN` city to null, back-fills city, drops constant `state`, fixes `'211.0'` suite numbers |
| 5 | `parse_types` | Text dates to `datetime64`; float-encoded integers to nullable `Int64` |
| 6 | `validate_legal_reference` | Flags references not matching `YYYYMMDD-NNNNNNN` |
| 7 | `drop_duplicate_sales` | Removes repeat records of the same parcel, date and price, keeping the valid legal reference |
| 8 | `clean_property_attributes` | `finished_area = 0` to null; 0-bedroom single-family to null; commercial grade codes to `OTHER` |
| 9 | `add_quality_flags` | Adds six boolean flags (see below) instead of deleting suspect rows |
| 10 | `add_derived_features` | `price_per_sqft`, `age_at_sale`, `sale_year`, `sale_month` |

### Judgment calls

* **Flag, don't delete.** Suspicious rows get a boolean column so the analyst chooses how to treat them.
* **`CONDO` was not merged into `RESIDENTIAL CONDO`.** The two have clearly different price profiles (median about $385k vs $220k), so the bare label looks like a different population, not a typo.
* **Malformed legal references were flagged, not repaired**, because the missing digits cannot be reconstructed. 27 remain after de-duplication.
* **No imputation of assessor fields.** With 54% missing and no recoverable source, imputing would fabricate data. A join to external assessor records on `parcel_id` is the right fix.

---

## Repository structure

```
nashville-housing-data-cleaning/
├── data/
│   ├── raw/Nashville_housing_data_2013_2016.csv   # untouched input
│   └── processed/nashville_housing_clean.csv      # output
├── notebooks/01_data_cleaning.ipynb               # narrated walkthrough with outputs
├── src/clean_nashville.py                         # reusable pipeline
├── reports/cleaning_log.csv                       # one row per step
├── images/                                        # charts used in this README
├── requirements.txt
└── README.md
```

## How to run

```bash
git clone https://github.com/imisibanjo/Nashville-housing-data-cleaning.git
cd nashville-housing-data-cleaning
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python src/clean_nashville.py        # regenerates data/processed + reports/cleaning_log.csv
jupyter notebook notebooks/01_data_cleaning.ipynb
```

---

## Data dictionary (cleaned file)

| Column | Type | Description |

| `parcel_id` | text | County parcel identifier |
| `land_use` | text | Standardised land-use category |
| `land_use_group` | text | Residential / Vacant / land / Commercial / other |
| `property_address` | text | Street address of the sold property |
| `suite_condo_no` | text | Suite or condo unit |
| `property_city` | text | City of the property |
| `sale_date`, `sale_year`, `sale_month` | date / int | Date of sale and its parts |
| `sale_price` | int | Recorded sale price (USD) |
| `legal_reference` | text | Deed instrument reference |
| `sold_as_vacant` | bool | Sale recorded as vacant land |
| `multiple_parcels_in_sale` | bool | Several parcels sold in one transaction |
| `owner_name`, `assessor_address` | text | From assessor records (missing for 54% of rows) |
| `acreage`, `tax_district`, `neighborhood` | num / text / int | Assessor attributes |
| `land_value`, `building_value`, `total_value` | float | Assessed values (USD) |
| `finished_area` | float | Finished living area (sq ft) |
| `foundation_type`, `exterior_wall`, `grade` | text | Building attributes (`grade`: A-E, X, or OTHER) |
| `year_built`, `bedrooms`, `full_bath`, `half_bath` | Int64 | Building attributes |
| `legal_ref_valid` | bool | Legal reference matches `YYYYMMDD-NNNNNNN` |
| `has_assessor_data` | bool | Row has assessor fields |
| `nominal_price` | bool | Sale price under $1,000 |
| `price_is_bundle_total` | bool | Price covers multiple parcels and repeats on each row |
| `price_comparable` | bool | Not nominal and not a bundle total |
| `sold_as_vacant_mismatch` | bool | `sold_as_vacant` disagrees with a `VACANT...` land use |
| `built_after_sale` | bool | `year_built` is later than `sale_year` |
| `price_per_sqft` | float | Sale price / finished area, comparable residential sales only |
| `age_at_sale` | Int64 | Years between build year and sale |

