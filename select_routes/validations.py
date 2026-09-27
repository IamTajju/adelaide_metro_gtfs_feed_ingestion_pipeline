# Student Name: [Your Name]
# Student FAN:  [YourFAN]
# File:         select_routes/validations.py
# Date:         27-09-2026
# Description:  Adelaide Metro Metrocard validations data download and parsing.
# Usage:        from select_routes.validations import download_latest_validations
"""Adelaide Metro Metrocard validations data download and parsing.

Downloads quarterly tap-on counts from data.sa.gov.au.
"""

import json
import re
import urllib.request

import config


def download_latest_validations():
    """Downloads the newest quarterly validations CSV, unless already on disk.

    Uses the CKAN API to find the most recent quarterly resource by last_modified timestamp,
    downloads it if not already cached locally.

    Returns:
        Path to the local CSV.
    """
    with urllib.request.urlopen(config.VALIDATIONS_API, timeout=60) as resp:
        resources = json.load(resp)["result"]["resources"]
    quarterly = [r for r in resources if re.search(r"\d{4} Q[1-4]$", r["name"])]
    newest = max(quarterly, key=lambda r: r["last_modified"])

    path = config.VALIDATIONS_DIR / (newest["name"][-7:].replace(" ", "-").lower() + ".csv")
    if not path.exists():
        config.VALIDATIONS_DIR.mkdir(parents=True, exist_ok=True)
        print("downloading %s" % newest["name"])
        urllib.request.urlretrieve(newest["url"], path)
    return path
