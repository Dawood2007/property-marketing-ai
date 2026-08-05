from playwright.sync_api import sync_playwright
from supabase import create_client
from datetime import datetime, UTC
from bs4 import BeautifulSoup
import hashlib
import re
import time

SUPABASE_URL = "https://dkbtxrinvcifnamapkip.supabase.co"
SUPABASE_KEY = "sb_publishable_fzfohIWnOVYmGld7Dhwpkg_7nEYlpqn"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def make_fingerprint(property_url):
    return hashlib.sha256(property_url.lower().strip().encode()).hexdigest()


def extract_bedrooms(text):
    match = re.search(r"(\d+)\s+Bedroom", text or "", re.IGNORECASE)
    return int(match.group(1)) if match else None


def extract_price_number(price_text):
    if not price_text:
        return None

    digits_only = re.sub(r"[^\d]", "", price_text)
    return int(digits_only) if digits_only else None


def extract_bm_reference(property_url):
    match = re.search(r"(bmest-\d+)", property_url, re.IGNORECASE)
    return match.group(1).lower() if match else None


def extract_property_details(page, property_url):
    page.goto(property_url, wait_until="networkidle")

    html = page.content()
    soup = BeautifulSoup(html, "html.parser")

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None

    if title and "404" in title.lower():
        return {"is_404": True}

    meta_description = soup.find("meta", attrs={"name": "description"})
    description = meta_description["content"] if meta_description else None

    h2 = soup.select_one("#description h2")
    h2_text = h2.get_text(" ", strip=True) if h2 else ""

    price_span = soup.select_one(".priceask")
    price_text = price_span.get_text(" ", strip=True) if price_span else None
    price_number = extract_price_number(price_text)

    status_span = soup.select_one(".detail-propstat_sold_stc")
    status = status_span.get_text(strip=True) if status_span else None

    image_tags = soup.find_all("meta", attrs={"property": "og:image"})
    image_urls = [tag["content"] for tag in image_tags if tag.get("content")]

    bedrooms = extract_bedrooms(title)

    property_type = h2_text
    if price_text:
        property_type = property_type.replace(price_text, "")
    if status:
        property_type = property_type.replace(status, "")
    property_type = property_type.strip()

    return {
        "is_404": False,
        "title": title,
        "price": price_number,
        "bedrooms": bedrooms,
        "property_type": property_type,
        "description": description,
        "main_image_url": image_urls[0] if image_urls else None,
        "image_urls": image_urls,
        "bm_reference": extract_bm_reference(property_url),
    }


properties = (
    supabase.table("property_listings")
    .select("id, property_url")
    .eq("detail_extracted", False)
    .execute()
)

print(f"Properties to process: {len(properties.data)}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    processed = 0
    failed = 0

    for prop in properties.data:
        property_id = prop["id"]
        property_url = prop["property_url"]

        print(f"\nProcessing ID {property_id}: {property_url}")

        try:
            details = extract_property_details(page, property_url)
            now = datetime.now(UTC).isoformat()

            if details.get("is_404"):
                supabase.table("property_listings").update({
                    "currently_live": False,
                    "listing_status": "Off Market",
                    "detail_extracted": False,
                    "title": None,
                    "price": None,
                    "bedrooms": None,
                    "property_type": None,
                    "description": None,
                    "main_image_url": None,
                    "last_seen_at": now,
                }).eq("id", property_id).execute()

                supabase.table("property_images").delete().eq("property_listing_id", property_id).execute()

                processed += 1
                print(f"Marked off market: {property_url}")
                time.sleep(0.5)
                continue

            update_data = {
                "title": details["title"],
                "price": details["price"],
                "bedrooms": details["bedrooms"],
                "property_type": details["property_type"],
                "description": details["description"],
                "main_image_url": details["main_image_url"],
                "bm_reference": details["bm_reference"],
                "detail_extracted": True,
                "last_seen_at": now,
            }

            supabase.table("property_listings").update(update_data).eq("id", property_id).execute()

            supabase.table("property_images").delete().eq("property_listing_id", property_id).execute()

            for index, image_url in enumerate(details["image_urls"]):
                supabase.table("property_images").insert({
                    "property_listing_id": property_id,
                    "image_url": image_url,
                    "image_order": index + 1
                }).execute()

            processed += 1
            print(f"Saved: {details['title']}")
            print(f"Images: {len(details['image_urls'])}")

            time.sleep(0.5)

        except Exception as e:
            failed += 1
            print(f"FAILED: {property_url}")
            print(e)

    browser.close()

print("\nFinished extracting details.")
print(f"Processed: {processed}")
print(f"Failed: {failed}")