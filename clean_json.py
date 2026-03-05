#!/usr/bin/env python3
"""
Clean all en-dash / em-dash hyphenation markers from scraped Tamil JSON files.

Usage:
    python clean_json.py                        # cleans scraped_data (1).json → scraped_data_clean.json
    python clean_json.py myfile.json            # cleans a specific file
    python clean_json.py myfile.json --inplace  # overwrites the original file
"""
import json, re, sys, os

BASE = r'C:\Users\Dell\Downloads\E-scrapper'

# Characters to strip
REPLACEMENTS = [
    ('\u2013', ''),   # en-dash  –
    ('\u2014', ''),   # em-dash  —
    ('\u00ad', ''),   # soft hyphen
]

def clean_str(text: str) -> str:
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    # Collapse multiple spaces/tabs created by removal
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text.strip()

def clean_obj(obj):
    """Recursively clean all string values in a JSON object."""
    if isinstance(obj, str):
        return clean_str(obj)
    if isinstance(obj, list):
        return [clean_obj(item) for item in obj]
    if isinstance(obj, dict):
        return {k: clean_obj(v) for k, v in obj.items()}
    return obj  # int, float, bool, None — unchanged

def process(in_path: str, out_path: str) -> None:
    print(f"Reading:  {in_path}")
    with open(in_path, encoding='utf-8') as f:
        data = json.load(f)

    # Count before
    raw = json.dumps(data, ensure_ascii=False)
    before = sum(raw.count(ch) for ch, _ in REPLACEMENTS)

    cleaned = clean_obj(data)

    # Count after
    after_raw = json.dumps(cleaned, ensure_ascii=False)
    after = sum(after_raw.count(ch) for ch, _ in REPLACEMENTS)

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)

    print(f"Writing:  {out_path}")
    print(f"Removed:  {before - after} hyphen markers  ({before} -> {after})")
    print("Done.")

if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = [a for a in sys.argv[1:] if a.startswith('--')]

    in_file = args[0] if args else os.path.join(BASE, 'scraped_data (1).json')
    inplace  = '--inplace' in flags

    if inplace:
        out_file = in_file
    else:
        base_name = os.path.splitext(os.path.basename(in_file))[0]
        out_file = os.path.join(os.path.dirname(in_file) or BASE, base_name + '_clean.json')

    process(in_file, out_file)
