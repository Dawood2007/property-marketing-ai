from playwright.sync_api import sync_playwright
from supabase import create_client
from bs4 import BeautifulSoup
from datetime import datetime, UTC
import re
import time

SUPABASE_URL = "https://dkbtxrinvcifnamapkip.supabase.co"
SUPABASE_KEY = "sb_publishable_fzfohIWnOVYmGld7Dhwpkg_7nEYlpqn"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def extract_price_number(price_text):
    if not price_text:
        return None
    digits_only = re.sub(r"[^\d]", "", price_text)
    return int(digits_only) if digits_only else None


def extract_bedrooms(text):
    match = re.search(r"(\d+)\s+Bedroom", text or "", re.IGNORECASE)
    return int(match.group(1)) if match else None


def create_event(property_id, change, property_url):
    event_type = change["event_type"]
    old_value = str(change["old_value"]) if change["old_value"] is not None else None
    new_value = str(change["new_value"]) if change["new_value"] is not None else None

    existing = (
        supabase.table("listing_events")
        .select("id")
        .eq("property_listing_id", property_id)
        .eq("event_type", event_type)
        .eq("new_value", new_value)
        .eq("processed", False)
        .execute()
    )

    if existing.data:
        print(f"Skipped duplicate event: {event_type}")
        return False

    supabase.table("listing_events").insert({
        "property_listing_id": property_id,
        "event_type": event_type,
        "old_value": old_value,
        "new_value": new_value,
        "metadata": {
            "field": change["field"],
            "property_url": property_url,
            "scan_time": datetime.now(UTC).isoformat(),
            "trigger": "scanner_v3"
        },
        "processed": False
    }).execute()

    print(f"Created event: {event_type}")
    return True


def extract_website_details(page, property_url):
    page.goto(property_url, wait_until="networkidle")

    html = page.content()
    soup = BeautifulSoup(html, "html.parser")

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None

    if title and "404" in title.lower():
        return {
            "is_404": True,
            "listing_status": "Off Market",
        }

    price_span = soup.select_one(".priceask")
    price_text = price_span.get_text(" ", strip=True) if price_span else None

    image_tags = soup.find_all("meta", attrs={"property": "og:image"})
    image_urls = [tag["content"] for tag in image_tags if tag.get("content")]

    return {
        "is_404": False,
        "title": title,
        "price": extract_price_number(price_text),
        "price_text": price_text,
        "bedrooms": extract_bedrooms(title),
        "main_image_url": image_urls[0] if image_urls else None,
        "image_count": len(image_urls),
    }


def compare_price(old, new):
    old_price = old.get("price")
    new_price = new.get("price")

    if old_price is None or new_price is None:
        return None

    if old_price == new_price:
        return None

    event_type = "PRICE_REDUCED" if new_price < old_price else "PRICE_INCREASED"

    return {
        "event_type": event_type,
        "field": "price",
        "old_value": old_price,
        "new_value": new_price,
    }


def compare_main_image(old, new):
    old_image = old.get("main_image_url")
    new_image = new.get("main_image_url")

    if old_image == new_image:
        return None

    return {
        "event_type": "MAIN_IMAGE_CHANGED",
        "field": "main_image_url",
        "old_value": old_image,
        "new_value": new_image,
    }


def compare_bedrooms(old, new):
    old_bedrooms = old.get("bedrooms")
    new_bedrooms = new.get("bedrooms")

    if old_bedrooms == new_bedrooms:
        return None

    return {
        "event_type": "BEDROOMS_CHANGED",
        "field": "bedrooms",
        "old_value": old_bedrooms,
        "new_value": new_bedrooms,
    }


def compare_status(old, new):
    if new.get("is_404"):
        if old.get("currently_live") is False:
            return None

        return {
            "event_type": "OFF_MARKET",
            "field": "listing_status",
            "old_value": old.get("listing_status"),
            "new_value": "Off Market",
        }

    if old.get("currently_live") is False:
        return {
            "event_type": "RELISTED",
            "field": "currently_live",
            "old_value": "false",
            "new_value": "true",
        }

    return None


def compare_property(old, new):
    comparison_rules = [
        compare_status,
        compare_price,
        compare_main_image,
        compare_bedrooms,
    ]

    changes = []

    for rule in comparison_rules:
        change = rule(old, new)
        if change:
            changes.append(change)

    return changes


def update_property(property_id, new):
    if new.get("is_404"):
        update_data = {
            "currently_live": False,
            "listing_status": "Off Market",
            "detail_extracted": False,
            "title": None,
            "price": None,
            "bedrooms": None,
            "main_image_url": None,
            "last_seen_at": datetime.now(UTC).isoformat(),
        }
    else:
        update_data = {
            "title": new.get("title"),
            "price": new.get("price"),
            "bedrooms": new.get("bedrooms"),
            "main_image_url": new.get("main_image_url"),
            "currently_live": True,
            "listing_status": "Live",
            "detail_extracted": True,
            "last_seen_at": datetime.now(UTC).isoformat(),
        }

    supabase.table("property_listings").update(update_data).eq("id", property_id).execute()


properties = (
    supabase.table("property_listings")
    .select("*")
    .eq("currently_live", True)
    .execute()
)

print(f"Properties to process: {len(properties.data)}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    processed = 0
    failed = 0
    events_created = 0

    for old in properties.data:
        property_id = old["id"]
        property_url = old["property_url"]

        print(f"\nProcessing ID {property_id}: {property_url}")

        try:
            new = extract_website_details(page, property_url)
            changes = compare_property(old, new)

            if changes:
                print("Changes detected:")
                for change in changes:
                    print(change)
                    if create_event(property_id, change, property_url):
                        events_created += 1
            else:
                print("No changes detected.")

            update_property(property_id, new)

            processed += 1
            time.sleep(0.5)

        except Exception as e:
            failed += 1
            print(f"FAILED: {property_url}")
            print(e)

    browser.close()

print("\nScanner V3 finished.")
print(f"Processed: {processed}")
print(f"Failed: {failed}")
print(f"Events created: {events_created}")