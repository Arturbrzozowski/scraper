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
    'practice', 'office', 'scheduling', 'appt', 'rx', 'pharmacy',
    'manager', 'director', 'owner', 'ceo', 'cfo', 'coo', 'president',
    'assistant', 'secretary', 'coordinator', 'supervisor', 'lead',
    'principal', 'founder', 'partner', 'associate', 'consultant',
    'provider', 'doctor', 'nurse', 'therapist', 'specialist',
    'medjuv', 'medispa', 'rejuve', 'aesthetix', 'dermcare'
}

# Common business/company-like patterns in email local parts
BUSINESS_PATTERNS = [
    r'.*international.*', r'.*llc.*', r'.*inc.*', r'.*corp.*',
    r'.*company.*', r'.*studio.*', r'.*center.*', r'.*centre.*',
    r'.*clinic.*', r'.*medspa.*', r'.*medical.*', r'.*health.*',
    r'.*aesthetic.*', r'.*beauty.*', r'.*skin.*', r'.*derm.*',
    r'.*wellness.*', r'.*spa\d*$', r'.*rx$', r'.*nprx$',
    r'^medjuv.*', r'^medispa.*', r'^rejuve.*',
]

# Title prefixes that may appear before names in emails (e.g., "drandrea" = dr + andrea)
TITLE_PREFIXES = ['dr', 'mr', 'mrs', 'ms', 'miss', 'prof', 'doc']

# Comprehensive list of common first names (US Census + popular names)
# This enables detection of names in concatenated emails like "ambersentamu@gmail.com"
COMMON_FIRST_NAMES = {
    # Female names - very common
    'mary', 'patricia', 'jennifer', 'linda', 'elizabeth', 'barbara', 'susan',
    'jessica', 'sarah', 'karen', 'nancy', 'lisa', 'betty', 'margaret', 'sandra',
    'ashley', 'kimberly', 'emily', 'donna', 'michelle', 'dorothy', 'carol',
    'amanda', 'melissa', 'deborah', 'stephanie', 'rebecca', 'sharon', 'laura',
    'cynthia', 'kathleen', 'amy', 'angela', 'shirley', 'anna', 'brenda',
    'pamela', 'emma', 'nicole', 'helen', 'samantha', 'katherine', 'christine',
    'debra', 'rachel', 'carolyn', 'janet', 'catherine', 'maria', 'heather',
    'diane', 'ruth', 'julie', 'olivia', 'joyce', 'virginia', 'victoria',
    'kelly', 'lauren', 'christina', 'joan', 'evelyn', 'judith', 'megan',
    'andrea', 'cheryl', 'hannah', 'jacqueline', 'martha', 'gloria', 'teresa',
    'ann', 'sara', 'madison', 'frances', 'kathryn', 'janice', 'jean', 'abigail',
    'alice', 'judy', 'sophia', 'grace', 'denise', 'amber', 'doris', 'marilyn',
    'danielle', 'beverly', 'isabella', 'theresa', 'diana', 'natalie', 'brittany',
    'charlotte', 'marie', 'kayla', 'alexis', 'lori', 'tina', 'alissa', 'tatiana',
    'melanie', 'katie', 'nichole', 'natasha', 'layla', 'monique', 'brooke',
    'vanessa', 'jill', 'erin', 'penny', 'kristen', 'kristin', 'erica', 'tiffany',
    'stacy', 'stacey', 'shannon', 'molly', 'gina', 'holly', 'wendy', 'tracy',
    'misty', 'sherry', 'carrie', 'dawn', 'allison', 'alison', 'taylor', 'carmen',
    'jenny', 'jenna', 'leslie', 'lesley', 'yolanda', 'anne', 'lynda', 'bonnie',
    'marcia', 'haley', 'morgan', 'sophie', 'chloe', 'zoey', 'zoe', 'lily',
    'lillian', 'harper', 'addison', 'aubrey', 'eleanor', 'stella', 'violet',
    'claire', 'bella', 'aurora', 'lucy', 'anna', 'caroline', 'aaliyah', 'ariana',
    'audrey', 'leah', 'madeline', 'arianna', 'ellie', 'peyton', 'rylee', 'clara',
    'vivian', 'reagan', 'mackenzie', 'kinley', 'ryleigh', 'jade', 'ivy', 'faith',
    'naomi', 'alexandra', 'ana', 'candice', 'adriana', 'alicia', 'cassandra',
    'felicia', 'gabriella', 'jasmine', 'kimberley', 'latoya', 'monique', 'priscilla',
    'serena', 'tara', 'veronica', 'bianca', 'briana', 'brittney', 'caitlin',
    'candace', 'celeste', 'chantel', 'ciara', 'claudia', 'colleen', 'constance',
    'darlene', 'desiree', 'elena', 'esther', 'eva', 'gail', 'geraldine', 'ginger',
    'gretchen', 'harmony', 'harriet', 'hilda', 'ingrid', 'irene', 'iris', 'jackie',
    'janelle', 'janine', 'jeanette', 'jeanne', 'joann', 'joanna', 'joanne', 'jocelyn',
    'jodie', 'jody', 'johanna', 'josie', 'joy', 'juanita', 'julia', 'juliana',
    'julianne', 'justine', 'kaitlyn', 'kara', 'karla', 'kassandra', 'kate', 'katelyn',
    'kathy', 'kayleigh', 'keisha', 'kelley', 'kellie', 'kelsey', 'kendra', 'kerri',
    'kerry', 'kirsten', 'krista', 'kristi', 'kristie', 'kristina', 'kristy', 'lacey',
    'lana', 'latasha', 'latisha', 'latoya', 'laurel', 'lauren', 'laurie', 'leann',
    'leigh', 'lena', 'leticia', 'libby', 'lila', 'liliana', 'lindsay', 'lindsey',
    'logan', 'lola', 'loretta', 'lorna', 'lorraine', 'lucia', 'lucille', 'lydia',
    'lynette', 'lynn', 'mabel', 'macy', 'madelyn', 'mae', 'maggie', 'mandy', 'marcia',
    'margarita', 'marge', 'marguerite', 'mari', 'mariana', 'marianne', 'maribel',
    'marissa', 'marla', 'marlene', 'marsha', 'marta', 'martina', 'marva', 'maryann',
    'maureen', 'maxine', 'maya', 'meagan', 'meghan', 'melinda', 'mercedes', 'meredith',
    'mia', 'michaela', 'michele', 'mildred', 'mindy', 'miranda', 'moira', 'muriel',
    'myra', 'myrna', 'nadine', 'nadia', 'nan', 'nanci', 'nancyann', 'nanette', 'nannette',
    'naomi', 'natalia', 'nettie', 'nina', 'nita', 'noel', 'noelle', 'nola', 'nora',
    'noreen', 'norma', 'olga', 'opal', 'ora', 'paige', 'patrice', 'paula', 'pauline',
    'pearl', 'peggy', 'penelope', 'petra', 'phoebe', 'phyllis', 'polly', 'portia',
    'precious', 'queen', 'quinn', 'rachael', 'rae', 'ramona', 'randi', 'raven',
    'reba', 'rebekah', 'regan', 'regina', 'rena', 'renae', 'rene', 'renee', 'rhoda',
    'rhonda', 'rita', 'roberta', 'robin', 'robyn', 'rochelle', 'ronda', 'rosa',
    'rosalie', 'rosalind', 'rosalyn', 'rosanna', 'rose', 'roseann', 'roseanne',
    'rosemarie', 'rosemary', 'rosetta', 'rosie', 'roxanne', 'ruby', 'ruth', 'ruthie',
    'sabrina', 'sadie', 'sally', 'sandy', 'savannah', 'scarlett', 'selena', 'selma',
    'shari', 'shayla', 'sheena', 'sheila', 'shelby', 'shelley', 'shelly', 'sheri',
    'sherri', 'sherrie', 'sheryl', 'shirlee', 'sierra', 'silvia', 'simone', 'sondra',
    'sonia', 'sonja', 'sonya', 'stacie', 'starla', 'stormy', 'sue', 'summer', 'sunny',
    'susan', 'susanne', 'susie', 'suzanne', 'suzette', 'sybil', 'sydney', 'sylvia',
    'tabatha', 'tabitha', 'tamara', 'tami', 'tamika', 'tammi', 'tammie', 'tammy',
    'tania', 'tanisha', 'tanya', 'taryn', 'tasha', 'terra', 'terri', 'terrie', 'terry',
    'tess', 'tessa', 'thea', 'thelma', 'tia', 'tiana', 'tiara', 'tierra', 'tonya',
    'tori', 'tracey', 'traci', 'tracie', 'tricia', 'trina', 'trisha', 'trudy', 'tyler',
    'ursula', 'valarie', 'valeria', 'valerie', 'veda', 'velma', 'vera', 'verna',
    'vicki', 'vickie', 'vicky', 'viola', 'viviana', 'wanda', 'whitney', 'wilma',
    'winifred', 'winnie', 'yesenia', 'yolanda', 'yvette', 'yvonne',

    # Male names - very common
    'james', 'john', 'robert', 'michael', 'william', 'david', 'richard', 'joseph',
    'thomas', 'charles', 'christopher', 'daniel', 'matthew', 'anthony', 'mark',
    'donald', 'steven', 'paul', 'andrew', 'joshua', 'kenneth', 'kevin', 'brian',
    'george', 'timothy', 'ronald', 'edward', 'jason', 'jeffrey', 'ryan', 'jacob',
    'gary', 'nicholas', 'eric', 'jonathan', 'stephen', 'larry', 'justin', 'scott',
    'brandon', 'benjamin', 'samuel', 'raymond', 'gregory', 'frank', 'alexander',
    'patrick', 'jack', 'dennis', 'jerry', 'tyler', 'aaron', 'jose', 'adam', 'nathan',
    'henry', 'douglas', 'zachary', 'peter', 'kyle', 'noah', 'ethan', 'jeremy',
    'walter', 'christian', 'keith', 'roger', 'terry', 'austin', 'sean', 'gerald',
    'carl', 'harold', 'dylan', 'arthur', 'lawrence', 'jordan', 'jesse', 'bryan',
    'billy', 'bruce', 'gabriel', 'joe', 'logan', 'albert', 'willie', 'alan', 'eugene',
    'russell', 'vincent', 'philip', 'bobby', 'johnny', 'bradley', 'roy', 'ralph',
    'randy', 'eugene', 'russell', 'louis', 'harry', 'wayne', 'howard', 'fred',
    'barry', 'jimmy', 'arthur', 'jaime', 'victor', 'martin', 'liam', 'mason',
    'elijah', 'oliver', 'aiden', 'lucas', 'carter', 'jayden', 'jackson', 'sebastian',
    'mateo', 'owen', 'wyatt', 'jack', 'luke', 'jayden', 'isaac', 'levi', 'grayson',
    'julian', 'isaiah', 'theodore', 'caleb', 'parker', 'connor', 'lincoln', 'jaxon',
    'cameron', 'maverick', 'miles', 'colton', 'easton', 'cooper', 'blake', 'cole',
    'evan', 'drew', 'grant', 'brett', 'brad', 'chad', 'travis', 'derek', 'dustin',
    'trevor', 'shane', 'todd', 'craig', 'dave', 'doug', 'greg', 'marc', 'mike',
    'nick', 'dan', 'jim', 'tom', 'tony', 'bill', 'bob', 'jeff', 'matt', 'chris',
    'andy', 'ben', 'sam', 'alex', 'jon', 'steve', 'rick', 'ted', 'ray', 'don',
    'lee', 'jay', 'tim', 'ken', 'ron', 'joe', 'max', 'ian', 'rob', 'phil',
    'carl', 'dean', 'troy', 'lance', 'wade', 'dale', 'kirk', 'glen', 'glenn',
    'neil', 'neal', 'lloyd', 'leon', 'ross', 'russ', 'kurt', 'kent', 'earl',
    'gene', 'hugh', 'ivan', 'karl', 'lane', 'luke', 'mark', 'omar', 'otto', 'owen',
    'pete', 'reed', 'reid', 'rene', 'rhys', 'rick', 'ross', 'rudy', 'sean', 'seth',
    'stan', 'todd', 'tony', 'wade', 'walt', 'ward', 'will', 'zach', 'zack',
    'abel', 'adam', 'alan', 'axel', 'bart', 'beau', 'brad', 'bret', 'burt', 'cade',
    'cary', 'clay', 'clint', 'cody', 'coby', 'dane', 'dion', 'dirk', 'dion', 'drew',
    'duke', 'earl', 'eden', 'eli', 'erik', 'ezra', 'finn', 'ford', 'gage', 'gale',
    'hank', 'hans', 'hugo', 'igor', 'ike', 'jace', 'jaden', 'jake', 'jay', 'jean',
    'jed', 'joel', 'joey', 'josh', 'juan', 'jude', 'kade', 'kane', 'luca', 'luis',
    'mack', 'malik', 'marco', 'mario', 'nash', 'nate', 'nico', 'noel', 'omar', 'pablo',
    'quinn', 'rafael', 'ramon', 'rex', 'rico', 'riley', 'rocco', 'roman', 'rowan',
    'saul', 'shawn', 'silas', 'simon', 'tate', 'trent', 'vince', 'weston', 'xavier',
    'yusuf', 'zane',

    # Additional common names
    'alana', 'kirby', 'daryl', 'darryl', 'darren', 'darin', 'daren', 'marvin',
    'melvin', 'calvin', 'alvin', 'devin', 'devon', 'gavin', 'kevin', 'kelvin',
    'irvin', 'ervin', 'marlin', 'merlin', 'berlin', 'carlin', 'harlin', 'arlin',
    'sheryl', 'cheryl', 'beryl', 'daryl', 'meryl', 'gina', 'tina', 'nina', 'dina',
    'lina', 'mina', 'rina', 'bina', 'fina', 'kina', 'pina', 'vina', 'wina', 'zina',
}

def find_name_in_string(text):
    """
    Try to find a known first name at the beginning of a concatenated string.
    Also handles title prefixes like "dr", "mr", etc. (e.g., "drandrea" -> "andrea")
    Returns the name if found, otherwise empty string.
    """
    text_lower = text.lower()

    # First, check if the string starts with a title prefix (dr, mr, mrs, etc.)
    for prefix in TITLE_PREFIXES:
        if text_lower.startswith(prefix) and len(text_lower) > len(prefix):
            # Try to find a name after the title prefix
            remainder = text_lower[len(prefix):]
            # Check if the remainder starts with a known name
            for length in range(min(12, len(remainder)), 1, -1):
                name_candidate = remainder[:length]
                if name_candidate in COMMON_FIRST_NAMES:
                    remaining_after_name = remainder[length:]
                    if remaining_after_name and len(remaining_after_name) >= 2:
                        return name_candidate

    # Try progressively longer prefixes to find a match
    # Start from longer names to prefer longer matches (e.g., "christina" over "chris")
    for length in range(min(12, len(text_lower)), 1, -1):
        prefix = text_lower[:length]
        if prefix in COMMON_FIRST_NAMES:
            # Make sure the remaining part looks like it could be a last name
            # (i.e., the name isn't the entire string, and what follows isn't just a single char)
            remaining = text_lower[length:]
            if remaining and len(remaining) >= 2:
                return prefix

    return ''


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


def is_single_initial_pattern(text):
    """
    Check if the text looks like a single initial + lastname (e.g., 'kschoales', 'jsmith')
    Returns True if it matches the pattern of single letter + common lastname suffix
    """
    if len(text) < 4:  # Too short to be initial + lastname
        return False

    # Check if first char is a single letter followed by what looks like a lastname
    first_char = text[0]
    rest = text[1:]

    # If the rest doesn't contain a known first name and starts with a consonant cluster
    # or common lastname pattern, it's probably initial + lastname
    if first_char.isalpha() and len(rest) >= 3:
        # Check if the rest could be a lastname (no known first name in it)
        if not find_name_in_string(rest):
            # Common lastname starts/patterns
            if rest[0] in 'bcdfghjklmnpqrstvwxyz':  # Starts with consonant
                return True

    return False


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

        # Check if the entire local part is a known first name (e.g., "alissa@...")
        if local_part in COMMON_FIRST_NAMES:
            first_name = local_part
        # Try to find a known first name in a concatenated string (e.g., "ambersentamu" -> "amber")
        # This must come BEFORE the single initial check
        elif find_name_in_string(local_part):
            first_name = find_name_in_string(local_part)
        # Check for single initial + lastname pattern (e.g., kschoales)
        elif is_single_initial_pattern(local_part):
            return ''
        # If it's short enough and looks like a name, use it
        elif is_likely_first_name(local_part) and len(local_part) <= 8:
            first_name = local_part

    # Validate the extracted first name
    if first_name:
        # Final validation
        if first_name in COMMON_FIRST_NAMES:
            return first_name.capitalize()
        elif is_likely_first_name(first_name) and len(first_name) <= 10:
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
