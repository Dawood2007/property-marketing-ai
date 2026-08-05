from playwright.sync_api import sync_playwright
from supabase import create_client
from datetime import datetime, UTC
import hashlib

SUPABASE_URL = "https://dkbtxrinvcifnamapkip.supabase.co"
SUPABASE_KEY = "sb_publishable_fzfohIWnOVYmGld7Dhwpkg_7nEYlpqn"

BASE_URL = "https://www.bmestates.com"

SEARCHES = [
    {
        "label": "For Sale",
        "listing_type": "Sale",
        "listing_status": "Live",
        "url_template": "https://www.bmestates.com/results?querytype=7&market=1&displayperpage=12&offset={offset}",
    },
    {
        "label": "To Let",
        "listing_type": "Letting",
        "listing_status": "Live",
        "url_template": "https://www.bmestates.com/results?querytype=8&market=1&displayperpage=12&offset={offset}",
    },
    {
        "label": "Commercial Rent",
        "listing_type": "Commercial Rent",
        "listing_status": "Live",
        "url_template": "https://www.bmestates.com/results?querytype=8&market=2&displayperpage=12&offset={offset}",
    },
    {
        "label": "Sold Properties",
        "listing_type": "Sold",
        "listing_status": "Sold",
        "url_template": "https://www.bmestates.com/sold-properties?displayperpage=12&offset={offset}",
    },
]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def make_fingerprint(property_url):
    return hashlib.sha256(property_url.lower().strip().encode()).hexdigest()


def get_property_urls(page, url):
    page.goto(url, wait_until="networkidle")

    property_urls = set()

    for link in page.locator("a").all():
        href = link.get_attribute("href")

        if href and href.startswith("/property/"):
            property_urls.add(BASE_URL + href)

    return property_urls


def save_property(property_url, search):
    now = datetime.now(UTC).isoformat()
    fingerprint = make_fingerprint(property_url)

    existing = (
        supabase.table("property_listings")
        .select("*")
        .eq("property_fingerprint", fingerprint)
        .execute()
    )

    data = {
        "category": search["label"],
        "listing_type": search["listing_type"],
        "listing_status": search["listing_status"],
        "currently_live": True,
        "last_seen_at": now,
    }

    if existing.data:
        response = (
            supabase.table("property_listings")
            .update(data)
            .eq("property_fingerprint", fingerprint)
            .execute()
        )

        print(f"Updated existing: {property_url}")
        return "updated"

    insert_data = {
        "property_url": property_url,
        "property_fingerprint": fingerprint,
        "category": search["label"],
        "listing_type": search["listing_type"],
        "listing_status": search["listing_status"],
        "currently_live": True,
        "first_seen_at": now,
        "last_seen_at": now,
        "post_generated": False,
        "social_posted": False,
    }

    response = supabase.table("property_listings").insert(insert_data).execute()

    print(f"Inserted new: {property_url}")
    return "inserted"


with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    total_found = 0
    total_inserted = 0
    total_updated = 0

    for search in SEARCHES:
        print(f"\nScanning {search['label']}")

        offset = 0

        while True:
            url = search["url_template"].format(offset=offset)
            urls = get_property_urls(page, url)

            if not urls:
                break

            print(f"Offset {offset}: {len(urls)} properties")

            for property_url in urls:
                result = save_property(property_url, search)
                total_found += 1

                if result == "inserted":
                    total_inserted += 1
                else:
                    total_updated += 1

            if len(urls) < 12:
                break

            offset += 12

    browser.close()

    print("\nFinished")
    print("Found:", total_found)
    print("Inserted:", total_inserted)
    print("Updated:", total_updated)