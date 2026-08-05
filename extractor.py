from bs4 import BeautifulSoup
import re


def extract_price_number(price_text):
    if not price_text:
        return None

    digits_only = re.sub(r"[^\d]", "", price_text)
    return int(digits_only) if digits_only else None
from bs4 import BeautifulSoup
import re


def extract_price_number(price_text):
    if not price_text:
        return None

    digits_only = re.sub(r"[^\d]", "", price_text)
    return int(digits_only) if digits_only else None


def extract_bedrooms(text):
    match = re.search(r"(\d+)\s+Bedroom", text or "", re.IGNORECASE)
    return int(match.group(1)) if match else None


def extract_bm_reference(property_url):
    match = re.search(r"(bmest-\d+)", property_url, re.IGNORECASE)
    return match.group(1).lower() if match else None


def extract_clean_description(soup):
    description_section = soup.select_one("#description")

    if not description_section:
        return None

    text = description_section.get_text("\n", strip=True)

    start_markers = [
        "BM Estates are delighted to present",
        "BM Estates are pleased to present",
        "BM Estates are proud to present",
        "BM Estates present",
    ]

    end_markers = [
        "Early viewing is highly recommended",
        "Viewing is highly recommended",
        "Contact BM Estates",
    ]

    start_index = -1

    for marker in start_markers:
        index = text.find(marker)
        if index != -1:
            start_index = index
            break

    if start_index == -1:
        return None

    clean_text = text[start_index:]

    direction_index = clean_text.find("\nDirections:")
    if direction_index != -1:
        before_directions = clean_text[:direction_index].strip()
        after_directions = clean_text[direction_index:]

        closing_line = None

        for marker in end_markers:
            marker_index = after_directions.find(marker)
            if marker_index != -1:
                closing_line = marker
                break

        if closing_line:
            clean_text = f"{before_directions}\n{closing_line}"
        else:
            clean_text = before_directions

    else:
        for marker in end_markers:
            marker_index = clean_text.find(marker)
            if marker_index != -1:
                marker_end = marker_index + len(marker)
                clean_text = clean_text[:marker_end]
                break

    return clean_text.strip()


def extract_property(page, property_url):
    page.goto(property_url, wait_until="networkidle")

    html = page.content()
    soup = BeautifulSoup(html, "html.parser")

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None

    if title and "404" in title.lower():
        return {
            "property_url": property_url,
            "bm_reference": extract_bm_reference(property_url),
            "currently_live": False,
            "listing_status": "Off Market",
            "is_404": True,
        }

    description = extract_clean_description(soup)

    if not description:
        meta_description = soup.find("meta", attrs={"name": "description"})
        description = (
            meta_description.get("content")
            if meta_description
            else None
        )

    h2 = soup.select_one("#description h2")
    h2_text = h2.get_text(" ", strip=True) if h2 else ""

    price_span = soup.select_one(".priceask")
    price_text = price_span.get_text(" ", strip=True) if price_span else None
    price = extract_price_number(price_text)

    status_span = soup.select_one(".detail-propstat_sold_stc")
    page_status = status_span.get_text(strip=True) if status_span else None

    image_tags = soup.find_all("meta", attrs={"property": "og:image"})
    image_urls = [
        tag["content"]
        for tag in image_tags
        if tag.get("content")
    ]

    property_type = h2_text

    if price_text:
        property_type = property_type.replace(price_text, "")

    if page_status:
        property_type = property_type.replace(page_status, "")

    property_type = property_type.strip()

    return {
        "property_url": property_url,
        "bm_reference": extract_bm_reference(property_url),
        "currently_live": True,
        "listing_status": page_status or "Live",
        "is_404": False,
        "title": title,
        "price": price,
        "price_text": price_text,
        "bedrooms": extract_bedrooms(title),
        "property_type": property_type,
        "description": description,
        "main_image_url": image_urls[0] if image_urls else None,
        "image_urls": image_urls,
        "image_count": len(image_urls),
    }