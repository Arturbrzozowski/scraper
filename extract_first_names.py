#!/usr/bin/env python3
"""
Script to extract first names from email addresses in a CSV file.
Parses the email column and outputs a new CSV with a "first_name" column.
"""

import csv
import re
import sys

# Common non-personal email prefixes to ignore
NON_PERSONAL_PREFIXES = {
    'info', 'contact', 'hello', 'support', 'sales', 'admin', 'office',
    'invoices', 'billing', 'accounts', 'operations', 'hr', 'jobs',
    'careers', 'marketing', 'press', 'media', 'news', 'help', 'service',
    'customer', 'customerservice', 'enquiries', 'inquiries', 'general',
    'reception', 'front', 'frontdesk', 'mail', 'email', 'team', 'staff',
    'orders', 'order', 'booking', 'bookings', 'reservations', 'appointments',
    'noreply', 'no-reply', 'donotreply', 'do-not-reply', 'notifications',
    'alerts', 'updates', 'newsletter', 'subscribe', 'unsubscribe',
    'feedback', 'survey', 'legal', 'privacy', 'security', 'webmaster',
    'postmaster', 'hostmaster', 'abuse', 'spam', 'root', 'sysadmin',
    'tech', 'technical', 'it', 'itsupport', 'helpdesk', 'surgery',
    'aesthetic', 'aesthetics', 'skincare', 'skin', 'beauty', 'spa',
    'clinic', 'medical', 'med', 'health', 'wellness', 'care', 'derma',
    'derm', 'plastic', 'cosmetic', 'laser', 'medspa', 'rejuvenation',
    'sculpt', 'glow', 'radiance', 'vitality', 'revive', 'renew',
    'practice', 'office', 'scheduling', 'appt', 'rx', 'pharmacy'
}

# Common business/company-like patterns in email local parts
BUSINESS_PATTERNS = [
    r'.*international.*', r'.*llc.*', r'.*inc.*', r'.*corp.*',
    r'.*company.*', r'.*studio.*', r'.*center.*', r'.*centre.*',
    r'.*clinic.*', r'.*medspa.*', r'.*medical.*', r'.*health.*',
    r'.*aesthetic.*', r'.*beauty.*', r'.*skin.*', r'.*derm.*',
    r'.*wellness.*', r'.*spa\d*$', r'.*rx$', r'.*nprx$',
]


def is_likely_first_name(name):
    """
    Check if a string is likely to be a first name.
    First names are typically 2-12 characters and don't contain business words.
    """
    if not name:
        return False

    name_lower = name.lower()

    # Length check - most first names are 2-12 characters
    if len(name_lower) < 2 or len(name_lower) > 12:
        return False

    # Check against non-personal prefixes
    if name_lower in NON_PERSONAL_PREFIXES:
        return False

    # Check against business patterns
    for pattern in BUSINESS_PATTERNS:
        if re.match(pattern, name_lower):
            return False

    # Check for numbers or weird characters
    if not name_lower.isalpha():
        return False

    return True


def extract_first_name(email):
    """
    Extract a first name from an email address.
    Returns the first name if found, otherwise returns empty string.
    """
    if not email or '@' not in email:
        return ''

    # Get the local part (before @)
    local_part = email.split('@')[0].lower().strip()

    if not local_part:
        return ''

    # Check if the entire local part is a non-personal prefix
    if local_part in NON_PERSONAL_PREFIXES:
        return ''

    first_name = ''

    # Pattern 1: firstname.lastname or firstname_lastname or firstname-lastname
    # Extract first name BEFORE checking business patterns on full local part
    if '.' in local_part:
        first_name = local_part.split('.')[0]
    elif '_' in local_part:
        first_name = local_part.split('_')[0]
    elif '-' in local_part:
        parts = local_part.split('-')
        # For hyphenated, first part is likely the first name
        first_name = parts[0]
    else:
        # Pattern 2: Single word - check for business patterns first
        for pattern in BUSINESS_PATTERNS:
            if re.match(pattern, local_part):
                return ''

        # If it's short enough and looks like a name, use it
        if is_likely_first_name(local_part):
            first_name = local_part
        else:
            # Try to extract from beginning - but only if it's clearly a name
            # Skip this for longer concatenated strings to avoid false positives
            pass

    # Validate the extracted first name
    if first_name and is_likely_first_name(first_name):
        return first_name.capitalize()

    return ''


def process_csv(input_file, output_file=None):
    """
    Process the input CSV and add a first_name column.
    """
    if output_file is None:
        # Default output filename
        if input_file.endswith('.csv'):
            output_file = input_file[:-4] + '_with_first_names.csv'
        else:
            output_file = input_file + '_with_first_names.csv'

    rows_processed = 0
    names_found = 0

    with open(input_file, 'r', encoding='utf-8-sig') as infile:
        reader = csv.DictReader(infile)
        fieldnames = reader.fieldnames + ['first_name']

        with open(output_file, 'w', encoding='utf-8', newline='') as outfile:
            writer = csv.DictWriter(outfile, fieldnames=fieldnames)
            writer.writeheader()

            for row in reader:
                email = row.get('email', '')
                first_name = extract_first_name(email)
                row['first_name'] = first_name
                writer.writerow(row)

                rows_processed += 1
                if first_name:
                    names_found += 1

    print(f"Processed {rows_processed} rows")
    print(f"Found {names_found} first names")
    print(f"Output written to: {output_file}")

    return output_file


if __name__ == '__main__':
    # Default input file
    input_file = 'alastin_stores all 04.02.2026.csv'
    output_file = None

    # Allow command line arguments
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    if len(sys.argv) > 2:
        output_file = sys.argv[2]

    process_csv(input_file, output_file)
