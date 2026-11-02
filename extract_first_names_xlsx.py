#!/usr/bin/env python3
"""
Fill the "First name" column of an .xlsx export using the email-based
extraction from extract_first_names.py.

- Rows already marked in the skip column (default "Exported" == "x") are left untouched.
- Email columns are tried in order; the first one that yields a name wins
  (default: contact_email, then shippingEmail).
- Names that are not in the known-first-name dictionary are highlighted yellow
  so they can be checked by hand.

Usage:
    python3 extract_first_names_xlsx.py "alumier all scrape 27.03.2026.xlsx" [output.xlsx]
"""

import sys

import openpyxl
from openpyxl.styles import PatternFill

from extract_first_names import COMMON_FIRST_NAMES, extract_first_name

EMAIL_COLUMNS = ['contact_email', 'shippingEmail']
NAME_COLUMN = 'First name'
SKIP_COLUMN = 'Exported'
SKIP_VALUE = 'x'
REVIEW_FILL = PatternFill(start_color='FFFF00', end_color='FFFF00', fill_type='solid')


def process_xlsx(input_file, output_file=None):
    if output_file is None:
        output_file = input_file[:-5] + '_with_first_names.xlsx'

    wb = openpyxl.load_workbook(input_file)
    ws = wb.active
    header = [c.value for c in ws[1]]
    email_idx = [header.index(c) for c in EMAIL_COLUMNS if c in header]
    name_col = header.index(NAME_COLUMN) + 1
    skip_idx = header.index(SKIP_COLUMN)

    pending = found = review = 0
    for row in ws.iter_rows(min_row=2):
        if str(row[skip_idx].value or '').strip().lower() == SKIP_VALUE:
            continue
        pending += 1
        # Prefer a dictionary-confirmed name from any email column, otherwise
        # take the first non-empty guess (contact_email before shippingEmail).
        candidates = [extract_first_name(str(row[i].value or '').strip()) for i in email_idx]
        candidates = [c for c in candidates if c]
        known = [c for c in candidates if c.lower() in COMMON_FIRST_NAMES]
        name = (known or candidates or [''])[0]
        cell = ws.cell(row=row[0].row, column=name_col)
        cell.value = name or None
        if name:
            found += 1
            if name.lower() not in COMMON_FIRST_NAMES:
                cell.fill = REVIEW_FILL
                review += 1

    wb.save(output_file)
    print(f"Rows not exported: {pending}")
    print(f"First names found: {found} ({review} highlighted for review)")
    print(f"Left blank: {pending - found}")
    print(f"Output written to: {output_file}")
    return output_file


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    process_xlsx(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
