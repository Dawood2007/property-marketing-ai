from playwright.sync_api import sync_playwright

from database import (
    find_property_by_url,
    insert_property,
    mark_property_sold,
    refresh_property_images,
)
from events import create_event
from extractor import extract_property


BASE_URL = "https://www.bmestates.com"


LIVE_SEARCHES = [
    {
        "label": "For Sale",
        "listing_type": "Sale",
        "url_template": (
            "https://www.bmestates.com/results"
            "?querytype=7"
            "&market=1"
            "&displayperpage=12"
            "&offset={offset}"
        ),
    },
    {
        "label": "To Let",
        "listing_type": "Letting",
        "url_template": (
            "https://www.bmestates.com/results"
            "?querytype=8"
            "&market=1"
            "&displayperpage=12"
            "&offset={offset}"
        ),
    },
    {
        "label": "Commercial Rent",
        "listing_type": "Commercial Rent",
        "url_template": (
            "https://www.bmestates.com/results"
            "?querytype=8"
            "&market=2"
            "&displayperpage=12"
            "&offset={offset}"
        ),
    },
]


SOLD_SEARCH = {
    "label": "Sold",
    "listing_type": "Sale",
    "url_template": (
        "https://www.bmestates.com/sold-properties"
        "?displayperpage=12"
        "&offset={offset}"
    ),
}


def launch_browser(playwright, headless=True):
    return playwright.chromium.launch(
        headless=headless,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )


def create_page(browser):
    page = browser.new_page()

    page.set_default_timeout(
        30000
    )

    page.set_default_navigation_timeout(
        30000
    )

    return page


def get_property_urls(
    page,
    url,
):
    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=30000,
    )

    property_urls = set()

    links = page.locator(
        "a[href^='/property/']"
    )

    count = links.count()

    for index in range(count):
        href = links.nth(
            index
        ).get_attribute(
            "href"
        )

        if not href:
            continue

        property_urls.add(
            BASE_URL + href
        )

    return property_urls


def discover_search_urls(
    page,
    search,
):
    all_urls = set()

    offset = 0

    while True:
        url = search[
            "url_template"
        ].format(
            offset=offset
        )

        print("")
        print(
            f"Discovery: "
            f"{search['label']} "
            f"offset {offset}"
        )

        urls = get_property_urls(
            page,
            url,
        )

        print(
            f"Found "
            f"{len(urls)} "
            f"property URLs."
        )

        if not urls:
            break

        all_urls.update(
            urls
        )

        if len(urls) < 12:
            break

        offset += 12

    return all_urls


def process_new_live_property(
    supabase,
    page,
    property_url,
    search,
):
    print("")
    print(
        "New property discovered:"
    )

    print(
        property_url
    )

    extracted = extract_property(
        page,
        property_url,
    )

    if extracted.get(
        "currently_live"
    ) is False:
        print(
            "Discovered property is "
            "not currently live. Skipping."
        )

        return {
            "inserted": 0,
            "events_created": 0,
            "errors": 0,
        }

    inserted = insert_property(
        supabase=supabase,
        property_url=property_url,
        category=search["label"],
        listing_type=search[
            "listing_type"
        ],
        extracted_property=extracted,
    )

    property_id = inserted[
        "id"
    ]

    refresh_property_images(
        supabase,
        property_id,
        extracted.get(
            "image_urls"
        ),
    )

    event_created = create_event(
        supabase,
        property_id,
        {
            "event_type":
                "NEW_LISTING",

            "field":
                "listing_status",

            "old_value":
                None,

            "new_value":
                "Live",
        },
        property_url,
    )

    print(
        "New property inserted "
        "successfully."
    )

    return {
        "inserted": 1,
        "events_created":
            1
            if event_created
            else 0,
        "errors": 0,
    }


def process_sold_property(
    supabase,
    property_url,
):
    existing = find_property_by_url(
        supabase,
        property_url,
    )

    if not existing:
        print(
            "Sold property was not "
            "previously known. "
            "Skipping SOLD event."
        )

        return {
            "sold": 0,
            "events_created": 0,
            "errors": 0,
        }

    old_status = (
        existing.get(
            "listing_status"
        )
    )

    if (
        old_status
        and old_status.lower()
        == "sold"
    ):
        return {
            "sold": 0,
            "events_created": 0,
            "errors": 0,
        }

    property_id = existing[
        "id"
    ]

    mark_property_sold(
        supabase,
        property_id,
    )

    event_created = create_event(
        supabase,
        property_id,
        {
            "event_type":
                "SOLD",

            "field":
                "listing_status",

            "old_value":
                old_status,

            "new_value":
                "Sold",
        },
        property_url,
    )

    print("")
    print(
        "Property marked SOLD:"
    )

    print(
        property_url
    )

    return {
        "sold": 1,
        "events_created":
            1
            if event_created
            else 0,
        "errors": 0,
    }


def run_discovery(
    supabase,
    headless=True,
):
    print("")
    print(
        "Nyro discovery starting."
    )

    new_listings = 0
    sold_properties = 0
    events_created = 0
    errors = 0

    with sync_playwright() as playwright:
        browser = launch_browser(
            playwright,
            headless=headless,
        )

        page = create_page(
            browser
        )

        try:
            for search in LIVE_SEARCHES:
                try:
                    urls = discover_search_urls(
                        page,
                        search,
                    )
                except Exception as exc:
                    errors += 1

                    print("")
                    print(
                        f"Discovery failed for "
                        f"{search['label']}"
                    )

                    print(
                        f"Error: {exc}"
                    )

                    continue

                for property_url in urls:
                    existing = (
                        find_property_by_url(
                            supabase,
                            property_url,
                        )
                    )

                    if existing:
                        continue

                    try:
                        result = (
                            process_new_live_property(
                                supabase,
                                page,
                                property_url,
                                search,
                            )
                        )

                        new_listings += (
                            result[
                                "inserted"
                            ]
                        )

                        events_created += (
                            result[
                                "events_created"
                            ]
                        )

                    except Exception as exc:
                        errors += 1

                        print("")
                        print(
                            "Failed to process "
                            "new property:"
                        )

                        print(
                            property_url
                        )

                        print(
                            f"Error: {exc}"
                        )

            try:
                sold_urls = (
                    discover_search_urls(
                        page,
                        SOLD_SEARCH,
                    )
                )

            except Exception as exc:
                errors += 1
                sold_urls = set()

                print("")
                print(
                    "Sold-property "
                    "discovery failed."
                )

                print(
                    f"Error: {exc}"
                )

            for property_url in sold_urls:
                try:
                    result = (
                        process_sold_property(
                            supabase,
                            property_url,
                        )
                    )

                    sold_properties += (
                        result[
                            "sold"
                        ]
                    )

                    events_created += (
                        result[
                            "events_created"
                        ]
                    )

                except Exception as exc:
                    errors += 1

                    print("")
                    print(
                        "Failed to process "
                        "sold property:"
                    )

                    print(
                        property_url
                    )

                    print(
                        f"Error: {exc}"
                    )

        finally:
            try:
                page.close()
            except Exception:
                pass

            try:
                browser.close()
            except Exception:
                pass

    result = {
        "new_listings":
            new_listings,

        "sold_properties":
            sold_properties,

        "events_created":
            events_created,

        "errors":
            errors,
    }

    print("")
    print(
        "Nyro discovery finished."
    )

    print(
        f"New listings: "
        f"{new_listings}"
    )

    print(
        f"Sold properties: "
        f"{sold_properties}"
    )

    print(
        f"Discovery events created: "
        f"{events_created}"
    )

    print(
        f"Discovery errors: "
        f"{errors}"
    )

    return result