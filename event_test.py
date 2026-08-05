from playwright.sync_api import sync_playwright
from supabase import create_client
from bs4 import BeautifulSoup
import re

SUPABASE_URL = "https://dkbtxrinvcifnamapkip.supabase.co"
SUPABASE_KEY = "sb_publishable_fzfohIWnOVYmGld7Dhwpkg_7nEYlpqn"

PROPERTY_ID = 20

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def extract_price_number(price_text):
    if not price_text:
        return None

    digits_only = re.sub(r"[^\d]", "", price_text)
    return int(digits_only) if digits_only else None


def create_event(property_id, event_type, old_value=None, new_value=None, metadata=None):
    supabase.table("listing_events").insert({
        "property_listing_id": property_id,
        "event_type": event_type,
        "old_value": str(old_value) if old_value is not None else None,
        "new_value": str(new_value) if new_value is not None else None,
        "metadata": metadata or {},
        "processed": False,
    }).execute()


property_record = (
    supabase.table("property_listings")
    .select("id, property_url, price")
    .eq("id", PROPERTY_ID)
    .single()
    .execute()
)

property_url = property_record.data["property_url"]
old_price = property_record.data["price"]

print("Property URL:", property_url)
print("Old stored price:", old_price)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto(property_url, wait_until="networkidle")

    html = page.content()
    soup = BeautifulSoup(html, "html.parser")

    price_span = soup.select_one(".priceask")
    price_text = price_span.get_text(" ", strip=True) if price_span else None
    new_price = extract_price_number(price_text)

    print("Website price text:", price_text)
    print("Website price number:", new_price)

    browser.close()

if old_price != new_price:
    if new_price < old_price:
        event_type = "PRICE_REDUCED"
    else:
        event_type = "PRICE_INCREASED"

    create_event(
        PROPERTY_ID,
        event_type,
        old_price,
        new_price,
        {
            "old_price": old_price,
            "new_price": new_price,
            "price_text": price_text,
        }
    )

    print("Event created:", event_type)
else:
    print("No price change detected.")