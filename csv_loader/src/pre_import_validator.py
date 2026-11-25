"""Pre-import CSV validation.

Runs entirely on the source file, before the database is touched. Catches
encoding issues, malformed rows, missing columns, header mismatches, and
unexpected null patterns.

This module never raises on a bad input — every problem is recorded as a
failed check on the returned StageResult so the orchestrator can decide what
to do next.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

from .config import JobConfig
from .reporting import StageResult


# UTF-8 byte-order mark, written by Excel and many other tools when saving as
# "CSV UTF-8". We strip it so the first column header doesn't end up as
# "﻿id" instead of "id" (BUG-09).
_BOM = "﻿"


def _strip_bom(value: str) -> str:
    return value.lstrip(_BOM) if isinstance(value, str) else value


def _open_csv(
    path: Path,
    encoding: str,
    delimiter: str = ",",
    has_header: bool = True,
    columns: list | None = None,
) -> pd.DataFrame:
    """Read a CSV strictly — preserve original strings, no type inference.

    BUG-01: explicitly forwards the configured delimiter to pandas, otherwise
    pandas defaults to ',' regardless of the job config and tab/pipe/semicolon
    files always fail header validation.
    """
    kwargs = dict(
        encoding=encoding,
        sep=delimiter,
        dtype=str,
        keep_default_na=False,
        na_values=[],
    )
    if not has_header:
        kwargs["header"] = None
        if columns:
            kwargs["names"] = columns
    df = pd.read_csv(path, **kwargs)
    # BUG-09: BOM may show up on the first column name.
    df.columns = [_strip_bom(c) for c in df.columns]
    return df


def validate_csv(job: JobConfig) -> Tuple[StageResult, Optional[pd.DataFrame]]:
    """Run pre-import checks for a single job.

    Returns ``(stage_result, dataframe)``. The DataFrame is ``None`` when
    parsing fails early; otherwise it is the fully-parsed CSV that downstream
    stages can reuse without re-reading the file.
    """
    stage = StageResult(stage="pre_import")

    path = Path(job.source_csv)

    # 1. File exists and is readable
    if not path.exists():
        stage.record(
            "file_exists", False,
            detail=f"CSV not found at {path}",
        )
        return stage, None
    stage.record("file_exists", True, detail=str(path))

    # 2. Encoding can be decoded
    try:
        with path.open("r", encoding=job.encoding) as f:
            f.read(8192)
        stage.record("encoding_readable", True, detail=job.encoding)
    except UnicodeDecodeError as e:
        stage.record(
            "encoding_readable", False,
            detail=f"Cannot decode as {job.encoding}: {e}",
        )
        return stage, None

    # 3. Delimiter sniff — record for visibility but DO NOT fail the stage
    #    on a mismatch. csv.Sniffer is a heuristic and gets it wrong on valid
    #    files (BUG-10). The actual ground truth is whether pandas can parse
    #    the file with the configured delimiter, which we test next.
    try:
        with path.open("r", encoding=job.encoding) as f:
            sample = f.read(4096)
        dialect = csv.Sniffer().sniff(sample)
        if dialect.delimiter == job.delimiter:
            stage.record("delimiter_match", True, detail=job.delimiter)
        else:
            stage.record(
                "delimiter_match", True,  # informational, not a failure
                detail=(
                    f"Sniffer suggests '{dialect.delimiter}' but config says "
                    f"'{job.delimiter}'. Treated as a warning; pandas parse "
                    f"is the source of truth."
                ),
            )
    except (csv.Error, UnicodeDecodeError):
        stage.record(
            "delimiter_match", True,
            detail="Could not sniff (small file or unusual content); "
                   "deferring to pandas parse",
        )

    # 4. Parse the file. Catches ragged rows, bad delimiters, truncated files
    #    in one place. BUG-11: previously this stage always reported True
    #    because pandas would have raised before reaching the record call.
    try:
        col_names = [c.csv_name for c in job.columns] if not job.has_header else None
        df = _open_csv(path, job.encoding, job.delimiter,
                       has_header=job.has_header, columns=col_names)
    except (pd.errors.ParserError, ValueError) as e:
        stage.record(
            "row_shape_consistent", False,
            detail=f"pandas could not parse the CSV: {e}",
        )
        return stage, None
    except UnicodeDecodeError as e:
        stage.record(
            "row_shape_consistent", False,
            detail=f"Decoding error during parse: {e}",
        )
        return stage, None

    stage.record(
        "row_shape_consistent", True,
        detail=f"{len(df)} rows parsed without ragged-row errors",
        metric={"row_count": len(df)},
    )

    # 5. Header presence and column-name match
    expected = {c.csv_name for c in job.columns}
    actual = set(df.columns)

    missing = expected - actual
    extra = actual - expected
    if missing:
        stage.record(
            "headers_complete", False,
            detail=f"Missing columns in CSV: {sorted(missing)}",
        )
    else:
        stage.record("headers_complete", True)

    if extra:
        stage.record(
            "no_unexpected_headers", False,
            detail=f"Unexpected extra columns in CSV: {sorted(extra)}",
        )
    else:
        stage.record("no_unexpected_headers", True)

    # 6. Required columns must not contain NULL-like values
    null_set = set(job.null_values) | {""}
    for col_spec in job.required_columns:
        if col_spec.csv_name not in df.columns:
            continue  # already flagged by headers_complete
        series = df[col_spec.csv_name]
        null_mask = series.isin(null_set) | series.isna()
        null_count = int(null_mask.sum())
        pct = (null_count / len(df) * 100.0) if len(df) else 0.0
        passed = pct <= job.thresholds.max_pct_null_in_required
        stage.record(
            f"non_null_required.{col_spec.csv_name}",
            passed,
            detail=f"{null_count}/{len(df)} null ({pct:.2f}%)",
            metric={"null_count": null_count, "null_pct": pct},
        )

    # 7. Max-length compliance (text columns)
    for col_spec in job.columns:
        if col_spec.max_length is None or col_spec.csv_name not in df.columns:
            continue
        lengths = df[col_spec.csv_name].fillna("").astype(str).str.len()
        too_long = int((lengths > col_spec.max_length).sum())
        stage.record(
            f"max_length.{col_spec.csv_name}",
            too_long == 0,
            detail=(
                f"{too_long} rows exceed max_length={col_spec.max_length}"
            ),
            metric={"violations": too_long, "max_length": col_spec.max_length},
        )

    # 8. Minimum row count (BUG-20). Only enforced when configured > 0.
    if job.thresholds.min_rows > 0:
        ok = len(df) >= job.thresholds.min_rows
        stage.record(
            "min_rows",
            ok,
            detail=f"{len(df)} rows (min required: {job.thresholds.min_rows})",
            metric={"row_count": len(df), "min_rows": job.thresholds.min_rows},
        )

    return stage, df
