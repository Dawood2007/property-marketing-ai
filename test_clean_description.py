from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

PROPERTY_URL = "https://www.bmestates.com/property/ocean-road-leicester-le5/bmest-004116/1"

START_TEXT = "BM Estates are delighted to present"
END_TEXT = "Early viewing is highly recommended"


with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    page.goto(PROPERTY_URL, wait_until="networkidle")

    soup = BeautifulSoup(page.content(), "html.parser")
    description_section = soup.select_one("#description")

    if not description_section:
        print("Could not find the description section.")
        browser.close()
        raise SystemExit

    full_text = description_section.get_text("\n", strip=True)

    start_index = full_text.find(START_TEXT)
    end_index = full_text.find(END_TEXT)

    if start_index == -1:
        print("Could not find the start of the property description.")
        browser.close()
        raise SystemExit

    if end_index == -1:
        clean_description = full_text[start_index:]
    else:
        end_index += len(END_TEXT)
        clean_description = full_text[start_index:end_index]

    print("\nCLEAN PROPERTY DESCRIPTION:\n")
    print(clean_description)

    browser.close()