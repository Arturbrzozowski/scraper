#!/usr/bin/env python3
"""
Add a "First name" column to the iS Clinical professionals export, using the
email-based extraction from extract_first_names.py.

- The name goes into the empty, unlabelled column E (headed "First name").
- Rows are left blank when the email belongs to iS Clinical itself:
  brand_email == "yes" (placeholder addresses like LIFEAL243@myinnovativeskincare.com),
  likely_internal == "yes", or an innovativeskincare.com / myinnovativeskincare.com domain.
- Each guess from extract_first_name() is checked against a 61,000-name dictionary
  (the gender-guesser package):
    * cut-short names are extended ("brianna" gave Brian -> Brianna),
    * "surname.firstname" emails use the second part ("fertig.danielle" -> Danielle),
    * a single word that is not a known name is dropped ("results@", "westport@"),
    * an unknown name in a "firstname.lastname" email is kept but highlighted yellow
      so it can be checked by hand ("concie.castro" -> Concie).

Usage:
    pip install openpyxl gender-guesser
    python3 extract_first_names_isclinical.py isclinical_professionals.xlsx [output.xlsx]
"""

import re
import sys

import gender_guesser.detector
import openpyxl
from openpyxl.styles import PatternFill

from extract_first_names import (BUSINESS_PATTERNS, COMMON_FIRST_NAMES, NON_PERSONAL_PREFIXES,
                                 TITLE_PREFIXES, extract_first_name)

BIG_NAMES = set(gender_guesser.detector.Detector(case_sensitive=False).names)
# Dictionary entries that are far more often ordinary words in an email
NOT_NAMES = {'just', 'woo', 'book', 'desk', 'gem', 'glo', 'forms', 'welcome', 'buyer',
             'connect', 'results', 'sunset', 'majestic', 'lilac', 'crafted', 'awaken',
             'grandma', 'makeup', 'injections', 'purchasing', 'glass', 'salon', 'nyc',
             'lilac', 'theskincollective'}
# Mailbox prefixes that come before a location or person name ("gm.savannah", "info.ro")
ROLE_TOKENS = NON_PERSONAL_PREFIXES | {'gm', 'mgr', 'hello', 'hi', 'team', 'the'}
# A name followed by these is a place or ordinary word: georgetown, louisville, bellareception
WORD_RESTS = ('town', 'ville', 'burg', 'boro', 'field', 'park', 'circle', 'port',
              'less', 'reception', 'info', 'grace', 'manage', 'salon', 'spa', 'skin',
              'beauty', 'face', 'studio')
WORD_STARTS = ('marketing', 'billing', 'timeless', 'renew', 'elite', 'williams')
# Second parts that mark a business email rather than a person ("nube.aesthetics")
BUSINESS_WORDS = ('beauty', 'aesthetic', 'skin', 'studio', 'business', 'brow', 'facial',
                  'pmu', 'dnp', 'cwc', 'llc', 'spa', 'salon', 'lash', 'med')


def is_name(word):
    return word in BIG_NAMES and word not in NOT_NAMES and word not in NON_PERSONAL_PREFIXES


PLACE_ENDINGS = ('town', 'ville', 'burg', 'boro', 'field', 'park', 'circle', 'port')


def is_word_not_name(first, name):
    rest = first[len(name):]
    # "georgetown", "williamsburg", "jonesboro": the place ending follows the name closely
    # (but not "kathyfunderburg" or "reginaepark", where a surname sits in between)
    near_place = any(rest.endswith(e) and len(rest) <= len(e) + 2 for e in PLACE_ENDINGS)
    return first.startswith(WORD_STARTS) or near_place or bool(rest and rest.startswith(WORD_RESTS))


def refine(email, guess):
    """Return (name, needs_review) after checking the guess against BIG_NAMES."""
    local = email.split('@')[0].lower().split('+')[0]
    tokens = [t for t in re.split(r'[._-]', local) if t]
    if not tokens:
        return '', False
    first = re.match(r'[a-z]*', tokens[0]).group()
    second = re.match(r'[a-z]*', tokens[1]).group() if len(tokens) > 1 else ''
    multi = len(tokens) > 1

    if first in NOT_NAMES or (multi and first in ROLE_TOKENS):
        return '', False
    # "fertig.danielle", "shumway.tara": first part unknown, second part a common name.
    # Only common US names count here, so "anshul.lal" or "emmaclaire.connor" stay as they are.
    if multi and not is_name(first) and first not in TITLE_PREFIXES \
            and second in COMMON_FIRST_NAMES and len(second) >= 3 \
            and not (guess and guess.lower() != first and len(guess) >= 4 and is_name(guess.lower())):
        return second.capitalize(), False
    if not guess:
        return '', False
    g = guess.lower()
    if first.startswith(g) and is_word_not_name(first, g):
        return '', False

    # "brianna" -> Brianna, "kendalldoherty" -> Kendall (guess was Brian / Ken)
    if first.startswith(g):
        for length in range(len(first), len(g), -1):
            longer, rest = first[:length], first[length:]
            if is_name(longer) and (not rest or len(rest) >= 2):
                return longer.capitalize(), False

    if is_name(g):
        return guess, False
    # "ashleym.benavente" -> Ashley (name + initial)
    if len(g) > 3 and g[-1] not in 'aeiouy' and g[:-1] in COMMON_FIRST_NAMES:
        return g[:-1].capitalize(), False
    # Unknown word: keep (highlighted) only as the first part of "firstname.lastname"
    # "bejan_lilia", "langer.rock": unknown first part, name second -> second, checked by hand
    if multi and g == first and len(second) >= 4 and is_name(second) and first not in NOT_NAMES:
        return second.capitalize(), True
    if multi and g == first and len(second) >= 3 and not first.startswith(('dr', 'doc')) \
            and first not in NOT_NAMES and not is_name(second) \
            and not any(w in second for w in BUSINESS_WORDS) \
            and not any(re.match(p, second) for p in BUSINESS_PATTERNS):
        return guess, True
    return '', False

EMAIL_COLUMN = 'email'
NAME_COLUMN_INDEX = 5  # column E, empty in the export
INTERNAL_DOMAINS = ('innovativeskincare.com', 'myinnovativeskincare.com')
REVIEW_FILL = PatternFill(start_color='FFFF00', end_color='FFFF00', fill_type='solid')


def is_internal(row, header):
    def val(col):
        return str(row[header.index(col)].value or '').strip().lower() if col in header else ''
    domain = val(EMAIL_COLUMN).rsplit('@', 1)[-1]
    return val('brand_email') == 'yes' or val('likely_internal') == 'yes' or domain in INTERNAL_DOMAINS


def process_xlsx(input_file, output_file=None):
    if output_file is None:
        output_file = input_file[:-5] + '_with_first_names.xlsx'

    wb = openpyxl.load_workbook(input_file)
    ws = wb.active
    header = [c.value for c in ws[1]]
    if header[NAME_COLUMN_INDEX - 1] not in (None, '', 'First name'):
        sys.exit(f'Column {NAME_COLUMN_INDEX} is not empty ({header[NAME_COLUMN_INDEX - 1]!r}); aborting.')
    ws.cell(row=1, column=NAME_COLUMN_INDEX).value = 'First name'
    email_idx = header.index(EMAIL_COLUMN)

    total = skipped = no_email = found = review = 0
    for row in ws.iter_rows(min_row=2):
        if all(c.value in (None, '') for c in row):
            continue
        total += 1
        email = str(row[email_idx].value or '').strip()
        if not email:
            no_email += 1
            continue
        if is_internal(row, header):
            skipped += 1
            continue
        name, needs_review = refine(email, extract_first_name(email))
        if name:
            cell = ws.cell(row=row[0].row, column=NAME_COLUMN_INDEX)
            cell.value = name
            found += 1
            if needs_review:
                cell.fill = REVIEW_FILL
                review += 1

    wb.save(output_file)
    print(f'Rows: {total}')
    print(f'No email: {no_email} | iS Clinical internal/placeholder emails skipped: {skipped}')
    print(f'First names found: {found} ({review} highlighted for review)')
    print(f'Output written to: {output_file}')
    return output_file


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    process_xlsx(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
