from supabase import Client
from playwright.sync_api import sync_playwright

from extractor import extract_property
from comparison import compare_property
from events import create_event
from database import (
    load_live_properties,
    update_property,
    refresh_property_images,
)


def run_scanner_v4(
    supabase: Client,
    headless: bool = False,
) -> dict:
    properties = load_live_properties(supabase)

    total_properties = len(properties)
    processed = 0
    failed = 0
    events_created = 0

    print("")
    print("Scanner V4 starting.")
    print(f"Properties to process: {total_properties}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=headless,
        )

        page = browser.new_page()

        try:
            for index, old_property in enumerate(
                properties,
                start=1,
            ):
                property_id = old_property["id"]
                property_url = old_property["property_url"]

                print("")
                print(
                    f"Processing property "
                    f"{index} of {total_properties}"
                )
                print(f"Property ID: {property_id}")
                print(f"Property URL: {property_url}")

                try:
                    new_property = extract_property(
                        page,
                        property_url,
                    )

                    changes = compare_property(
                        old_property,
                        new_property,
                    )

                    if changes:
                        print("Changes detected:")

                        for change in changes:
                            print(change)

                            event_created = create_event(
                                supabase,
                                property_id,
                                change,
                                property_url,
                            )

                            if event_created:
                                events_created += 1
                    else:
                        print("No changes detected.")

                    update_property(
                        supabase,
                        property_id,
                        new_property,
                    )

                    if new_property.get("currently_live") is True:
                        refresh_property_images(
                            supabase,
                            property_id,
                            new_property.get("image_urls"),
                        )

                    processed += 1

                except Exception as exc:
                    failed += 1

                    print("")
                    print(f"FAILED: {property_url}")
                    print(f"Error: {exc}")

        finally:
            browser.close()

    result = {
        "total_properties": total_properties,
        "processed": processed,
        "failed": failed,
        "events_created": events_created,
    }

    print("")
    print("Scanner V4 finished.")
    print(f"Total properties: {total_properties}")
    print(f"Processed successfully: {processed}")
    print(f"Failed: {failed}")
    print(f"Events created: {events_created}")

    return result


if __name__ == "__main__":
    raise RuntimeError(
        "scanner_v4.py must be started through "
        "scanner_orchestrator.py."
    )