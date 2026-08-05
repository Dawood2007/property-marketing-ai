from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

PROPERTY_URL = "https://www.bmestates.com/property/ocean-road-leicester-le5/bmest-004116/1"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    page.goto(PROPERTY_URL, wait_until="networkidle")

    soup = BeautifulSoup(page.content(), "html.parser")

    description_section = soup.select_one("#description")

    if description_section:
        print("\nFULL DESCRIPTION SECTION:\n")
        print(description_section.get_text("\n", strip=True))
    else:
        print("Could not find the description section.")

    browser.close()