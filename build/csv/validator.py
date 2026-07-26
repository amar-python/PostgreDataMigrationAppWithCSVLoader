#!/usr/bin/env python3
# csv/validator.py — handles invalid UTF-8 per-row + delimiter auto-detect
import csv
import os
import sys

GREEN, YELLOW, RED, NC = '\033[0;32m', '\033[1;33m', '\033[0;31m', '\033[0m'


def log(m):
    print(f"{GREEN}  [validator OK]{NC} {m}")


def warn(m):
    print(f"{YELLOW}  [validator WARN]{NC} {m}")


def err(m):
    print(f"{RED}  [validator ERR]{NC} {m}", file=sys.stderr)


def has_bad_bytes(cell):
    try:
        cell.encode("utf-8")
        return False
    except UnicodeEncodeError:
        return True


def clean(cell):
    return cell.encode("utf-8", "replace").decode("utf-8")


CSV_FILE = os.environ.get("CSV_FILE", "")
VALID_CSV = os.environ.get("VALID_CSV", "")
SKIP_FILE = os.environ.get("SKIP_FILE", "")
FORCE_DELIM = os.environ.get("CSV_DELIMITER", "")

missing = [
    v for v in ("CSV_FILE", "VALID_CSV", "SKIP_FILE")
    if not os.environ.get(v)
]
if missing:
    err(f"Missing required environment variables: {', '.join(missing)}")
    sys.exit(1)
if not os.path.isfile(CSV_FILE):
    err(f"CSV file not found: {CSV_FILE}")
    sys.exit(1)
os.makedirs(os.path.dirname(VALID_CSV) or ".", exist_ok=True)
os.makedirs(os.path.dirname(SKIP_FILE) or ".", exist_ok=True)


def detect_delimiter(path):
    if FORCE_DELIM:
        return FORCE_DELIM.encode().decode("unicode_escape")
    try:
        with open(path, "r", encoding="utf-8-sig",
                  errors="surrogateescape", newline="") as fh:
            sample = fh.read(8192)
        if not sample:
            return ","
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except Exception:
        return ","


DELIM = detect_delimiter(CSV_FILE)
label = {
    ",": "comma", ";": "semicolon", "\t": "tab", "|": "pipe",
}.get(DELIM, repr(DELIM))

try:
    with open(CSV_FILE, "r", encoding="utf-8-sig",
              errors="surrogateescape", newline="") as src, \
         open(VALID_CSV, "w", encoding="utf-8", newline="") as vf, \
         open(SKIP_FILE, "w", encoding="utf-8", newline="") as sf:
        reader = csv.reader(src, delimiter=DELIM)
        wv = csv.writer(vf, delimiter=DELIM)
        ws = csv.writer(sf, delimiter=DELIM)
        try:
            headers = next(reader)
        except StopIteration:
            err("CSV file is empty — no header row found.")
            sys.exit(1)
        headers = [h.strip() for h in headers]
        ncols = len(headers)
        if ncols == 0:
            err("Header row is empty.")
            sys.exit(1)
        if any(has_bad_bytes(h) for h in headers):
            err("Header row contains invalid UTF-8 bytes — "
                "cannot process file.")
            sys.exit(1)
        log(f"Delimiter: {label}")
        log(f"Header: {ncols} columns — {' | '.join(headers)}")
        dupes = sorted({h for h in headers if headers.count(h) > 1})
        if dupes:
            warn(f"Duplicate column names: {', '.join(dupes)}")
        wv.writerow(headers)
        ws.writerow(headers + ["_skip_reason"])
        valid = skip = 0
        for n, row in enumerate(reader, start=2):
            if not any(c.strip() for c in row):
                ws.writerow(
                    [clean(c) for c in row]
                    + ["empty row — all values blank"]
                )
                skip += 1
                continue
            if any(has_bad_bytes(c) for c in row):
                ws.writerow(
                    [clean(c) for c in row]
                    + [f"invalid UTF-8 bytes at line {n}"]
                )
                skip += 1
                continue
            if len(row) != ncols:
                ws.writerow(
                    [clean(c) for c in row]
                    + [f"column mismatch — expected {ncols}, "
                       f"got {len(row)}"]
                )
                skip += 1
                continue
            wv.writerow(row)
            valid += 1
        log(f"Validation complete — {valid + skip} rows processed.")
        log(f"  Valid rows   : {valid}")
        if skip:
            warn(f"  Skipped rows : {skip} — written to: {SKIP_FILE}")
        if valid == 0:
            err("No valid rows found. Nothing to load.")
            sys.exit(1)
        sys.exit(0)
except PermissionError as e:
    err(f"Permission denied: {e}")
    sys.exit(1)
except Exception as e:
    err(f"Unexpected error: {e}")
    sys.exit(1)
