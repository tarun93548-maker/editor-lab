"""One-time script to download Google Fonts .ttf files to fonts/ directory."""
import os
import re
import requests

FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")

# Each entry: (family name for CSS API, weight, output filename)
FONTS = [
    ("Playfair Display", 700, "PlayfairDisplay-Bold.ttf"),
    ("Bebas Neue", 400, "BebasNeue-Regular.ttf"),
    ("Poppins", 600, "Poppins-SemiBold.ttf"),
    ("Dancing Script", 700, "DancingScript-Bold.ttf"),
    ("Oswald", 500, "Oswald-Medium.ttf"),
    ("Permanent Marker", 400, "PermanentMarker-Regular.ttf"),
    ("Abril Fatface", 400, "AbrilFatface-Regular.ttf"),
    ("Quicksand", 600, "Quicksand-SemiBold.ttf"),
    ("Lobster", 400, "Lobster-Regular.ttf"),
    ("Lora", 400, "Lora-Regular.ttf"),
    ("Inter", 400, "Inter-Regular.ttf"),
    ("Montserrat", 400, "Montserrat-Regular.ttf"),
    ("DM Sans", 400, "DMSans-Regular.ttf"),
    ("Nunito", 400, "Nunito-Regular.ttf"),
    ("Raleway", 700, "Raleway-Bold.ttf"),
    ("Outfit", 400, "Outfit-Regular.ttf"),
]

# Use a TrueType-capable user agent so Google returns .ttf URLs (not woff2)
HEADERS = {
    "User-Agent": "Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.1)"
}


def get_ttf_url(family: str, weight: int) -> str:
    """Fetch the Google Fonts CSS and extract the .ttf URL."""
    css_url = f"https://fonts.googleapis.com/css2?family={family.replace(' ', '+')}:wght@{weight}&display=swap"
    resp = requests.get(css_url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    # Extract URL from src: url(...) format: truetype
    match = re.search(r"src:\s*url\(([^)]+\.ttf)\)", resp.text)
    if not match:
        # Try any url() in the response
        match = re.search(r"url\(([^)]+)\)", resp.text)
    if match:
        return match.group(1)
    raise ValueError(f"No font URL found in CSS for {family} {weight}:\n{resp.text[:500]}")


def download_all():
    os.makedirs(FONTS_DIR, exist_ok=True)

    for family, weight, filename in FONTS:
        dest = os.path.join(FONTS_DIR, filename)
        if os.path.exists(dest):
            print(f"  SKIP {filename} (already exists)")
            continue

        try:
            print(f"  {family} (wght {weight})...", end=" ", flush=True)
            ttf_url = get_ttf_url(family, weight)
            resp = requests.get(ttf_url, timeout=30)
            resp.raise_for_status()
            with open(dest, "wb") as f:
                f.write(resp.content)
            print(f"OK ({len(resp.content)} bytes) -> {filename}")
        except Exception as e:
            print(f"FAILED: {e}")

    print("\nDone!")


if __name__ == "__main__":
    download_all()
