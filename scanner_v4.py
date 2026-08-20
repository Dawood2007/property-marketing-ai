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


# ---------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------

def launch_browser(playwright, headless: bool):
    """
    Launch Chromium with settings that are safer inside
    container environments such as Railway.
    """

    return playwright.chromium.launch(
        headless=headless,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )


def create_page(browser):
    """
    Create a fresh browser page.

    A default timeout is set as an additional safeguard.
    Navigation also has its own timeout inside extractor.py.
    """

    page = browser.new_page()

    page.set_default_timeout(
        30000
    )

    page.set_default_navigation_timeout(
        30000
    )

    return page


def browser_or_page_crashed(exc: Exception) -> bool:
    """
    Detect Playwright errors that normally indicate the
    current page, browser context or browser process is no
    longer usable.
    """

    message = str(exc).lower()

    crash_markers = [
        "page crashed",
        "target page, context or browser has been closed",
        "browser has been closed",
        "browser closed",
        "context closed",
        "target closed",
    ]

    return any(
        marker in message
        for marker in crash_markers
    )


# ---------------------------------------------------------
# Main scanner
# ---------------------------------------------------------

def run_scanner_v4(
    supabase: Client,
    headless: bool = False,
) -> dict:

    properties = load_live_properties(
        supabase
    )

    total_properties = len(
        properties
    )

    processed = 0
    failed = 0
    events_created = 0

    new_listings = 0
    price_reductions = 0
    relisted_properties = 0
    off_market_properties = 0

    print("")
    print("Scanner V4 starting.")
    print(
        f"Properties to process: "
        f"{total_properties}"
    )

    with sync_playwright() as playwright:

        browser = launch_browser(
            playwright,
            headless,
        )

        page = create_page(
            browser
        )

        try:

            for index, old_property in enumerate(
                properties,
                start=1,
            ):

                property_id = (
                    old_property["id"]
                )

                property_url = (
                    old_property[
                        "property_url"
                    ]
                )

                print("")
                print(
                    f"Processing property "
                    f"{index} of "
                    f"{total_properties}"
                )

                print(
                    f"Property ID: "
                    f"{property_id}"
                )

                print(
                    f"Property URL: "
                    f"{property_url}"
                )

                # -----------------------------------------
                # Extract property
                #
                # One retry is allowed if Chromium or the
                # current page crashes.
                # -----------------------------------------

                new_property = None
                extraction_error = None

                for attempt in range(
                    1,
                    3,
                ):

                    try:

                        new_property = (
                            extract_property(
                                page,
                                property_url,
                            )
                        )

                        extraction_error = None

                        break

                    except Exception as exc:

                        extraction_error = exc

                        print("")
                        print(
                            f"Extraction attempt "
                            f"{attempt} failed."
                        )

                        print(
                            f"Error: {exc}"
                        )

                        # ---------------------------------
                        # If Chromium/page crashed, rebuild
                        # the browser before retrying.
                        # ---------------------------------

                        if browser_or_page_crashed(
                            exc
                        ):

                            print(
                                "Browser/page crash "
                                "detected."
                            )

                            print(
                                "Restarting Chromium..."
                            )

                            try:
                                page.close()
                            except Exception:
                                pass

                            try:
                                browser.close()
                            except Exception:
                                pass

                            try:

                                browser = (
                                    launch_browser(
                                        playwright,
                                        headless,
                                    )
                                )

                                page = (
                                    create_page(
                                        browser
                                    )
                                )

                                print(
                                    "Chromium restarted "
                                    "successfully."
                                )

                            except Exception as restart_error:

                                extraction_error = (
                                    restart_error
                                )

                                print(
                                    "Unable to restart "
                                    "Chromium."
                                )

                                print(
                                    f"Restart error: "
                                    f"{restart_error}"
                                )

                                break

                        # ---------------------------------
                        # Retry ordinary extraction errors
                        # once using the existing browser.
                        # ---------------------------------

                        elif attempt == 1:

                            print(
                                "Retrying property once..."
                            )

                # -----------------------------------------
                # Property extraction failed after retries
                # -----------------------------------------

                if new_property is None:

                    failed += 1

                    print("")
                    print(
                        f"FAILED: "
                        f"{property_url}"
                    )

                    print(
                        f"Final error: "
                        f"{extraction_error}"
                    )

                    continue

                # -----------------------------------------
                # Compare / event / database operations
                # -----------------------------------------

                try:

                    changes = compare_property(
                        old_property,
                        new_property,
                    )

                    if changes:

                        print(
                            "Changes detected:"
                        )

                        for change in changes:

                            print(
                                change
                            )

                            event_created = (
                                create_event(
                                    supabase,
                                    property_id,
                                    change,
                                    property_url,
                                )
                            )

                            if event_created:

                                events_created += 1

                                event_type = (
                                    change.get(
                                        "event_type"
                                    )
                                )

                                if (
                                    event_type ==
                                    "NEW_LISTING"
                                ):
                                    new_listings += 1

                                elif (
                                    event_type ==
                                    "PRICE_REDUCED"
                                ):
                                    price_reductions += 1

                                elif (
                                    event_type ==
                                    "RELISTED"
                                ):
                                    relisted_properties += 1

                                elif (
                                    event_type ==
                                    "OFF_MARKET"
                                ):
                                    off_market_properties += 1

                    else:

                        print(
                            "No changes detected."
                        )

                    update_property(
                        supabase,
                        property_id,
                        new_property,
                    )

                    if (
                        new_property.get(
                            "currently_live"
                        )
                        is True
                    ):

                        refresh_property_images(
                            supabase,
                            property_id,
                            new_property.get(
                                "image_urls"
                            ),
                        )

                    processed += 1

                except Exception as exc:

                    failed += 1

                    print("")
                    print(
                        f"FAILED: "
                        f"{property_url}"
                    )

                    print(
                        "Property extraction succeeded, "
                        "but processing failed."
                    )

                    print(
                        f"Error: "
                        f"{exc}"
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

    # -----------------------------------------------------
    # Final result
    # -----------------------------------------------------

    result = {
        "total_properties":
            total_properties,

        "processed":
            processed,

        "failed":
            failed,

        "events_created":
            events_created,

        "new_listings":
            new_listings,

        "price_reductions":
            price_reductions,

        "relisted_properties":
            relisted_properties,

        "off_market_properties":
            off_market_properties,
    }

    print("")
    print(
        "Scanner V4 finished."
    )

    print(
        f"Total properties: "
        f"{total_properties}"
    )

    print(
        f"Processed successfully: "
        f"{processed}"
    )

    print(
        f"Failed: "
        f"{failed}"
    )

    print(
        f"Events created: "
        f"{events_created}"
    )

    print(
        f"New listings: "
        f"{new_listings}"
    )

    print(
        f"Price reductions: "
        f"{price_reductions}"
    )

    print(
        f"Relisted properties: "
        f"{relisted_properties}"
    )

    print(
        f"Off market properties: "
        f"{off_market_properties}"
    )

    return result


if __name__ == "__main__":
    raise RuntimeError(
        "scanner_v4.py must be started through "
        "scanner_orchestrator.py."
    )