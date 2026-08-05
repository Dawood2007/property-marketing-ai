from playwright.sync_api import sync_playwright
from supabase import create_client
from datetime import datetime, UTC
from bs4 import BeautifulSoup
import hashlib
import re

SUPABASE_URL = "https://dkbtxrinvcifnamapkip.supabase.co"
SUPABASE_KEY = "sb_publishable_fzfohIWnOVYmGld7Dhwpkg_7nEYlpqn"

PROPERTY_URL = "https://www.bmestates.com/property/ocean-road-leicester-le5/bmest-004116/1"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def make_fingerprint(property_url):
    return hashlib.sha256(property_url.lower().strip().encode()).hexdigest()


def extract_bedrooms(text):
    match = re.search(r"(\d+)\s+Bedroom", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def extract_price_number(price_text):
    if not price_text:
        return None

    digits_only = re.sub(r"[^\d]", "", price_text)

    if not digits_only:
        return None

    return int(digits_only)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto(PROPERTY_URL, wait_until="networkidle")

    html = page.content()
    soup = BeautifulSoup(html, "html.parser")

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None

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

    bedrooms = extract_bedrooms(title or "")

    property_type = h2_text
    if price_text:
        property_type = property_type.replace(price_text, "")
    if status:
        property_type = property_type.replace(status, "")
    property_type = property_type.strip()

    fingerprint = make_fingerprint(PROPERTY_URL)
    now = datetime.now(UTC).isoformat()

    existing = (
        supabase.table("property_listings")
        .select("id")
        .eq("property_fingerprint", fingerprint)
        .execute()
    )

    if not existing.data:
        print("Property not found in property_listings.")
        browser.close()
        raise SystemExit

    property_listing_id = existing.data[0]["id"]

    update_data = {
        "title": title,
        "price": price_number,
        "bedrooms": bedrooms,
        "property_type": property_type,
        "description": description,
        "main_image_url": image_urls[0] if image_urls else None,
        "detail_extracted": True,
        "last_seen_at": now,
    }

    supabase.table("property_listings").update(update_data).eq("id", property_listing_id).execute()

    supabase.table("property_images").delete().eq("property_listing_id", property_listing_id).execute()

    for index, image_url in enumerate(image_urls):
        supabase.table("property_images").insert({
            "property_listing_id": property_listing_id,
            "image_url": image_url,
            "image_order": index + 1
        }).execute()

    print("Saved details to Supabase.")
    print("Property listing ID:", property_listing_id)
    print("Title:", title)
    print("Price text:", price_text)
    print("Price number:", price_number)
    print("Bedrooms:", bedrooms)
    print("Property type:", property_type)
    print("Images saved:", len(image_urls))

    browser.close()