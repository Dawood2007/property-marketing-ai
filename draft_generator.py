import os

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel
from supabase import create_client


# ---------------------------------------------------------
# Environment
# ---------------------------------------------------------

load_dotenv()

OPENAI_API_KEY = os.getenv(
    "OPENAI_API_KEY"
)

SUPABASE_URL = os.getenv(
    "SUPABASE_URL"
)

SUPABASE_KEY = os.getenv(
    "SUPABASE_KEY"
)


if not OPENAI_API_KEY:
    raise RuntimeError(
        "OPENAI_API_KEY is missing from the environment."
    )

if not SUPABASE_URL:
    raise RuntimeError(
        "SUPABASE_URL is missing from the environment."
    )

if not SUPABASE_KEY:
    raise RuntimeError(
        "SUPABASE_KEY is missing from the environment."
    )


client = OpenAI(
    api_key=OPENAI_API_KEY
)

default_supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY,
)


# ---------------------------------------------------------
# Structured AI output
# ---------------------------------------------------------

class PlatformDrafts(BaseModel):
    instagram: str
    facebook: str
    tiktok: str


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def format_price(price):
    if price is None:
        return "Price on application"

    return f"£{float(price):,.0f}"


def load_marketing_brain():
    base_dir = os.path.dirname(
        os.path.abspath(__file__)
    )

    file_path = os.path.join(
        base_dir,
        "ai",
        "marketing_brain.txt",
    )

    with open(
        file_path,
        "r",
        encoding="utf-8",
    ) as file:
        return file.read()


# ---------------------------------------------------------
# AI generation
# ---------------------------------------------------------

def generate_ai_drafts(
    event_type,
    property_data,
):
    marketing_brain = (
        load_marketing_brain()
    )

    instructions = f"""
{marketing_brain}

Create three genuinely different property marketing drafts:

1. Instagram
2. Facebook
3. TikTok

GENERAL RULES

- Use only the supplied property information.
- Do not invent features, claims, urgency or local information.
- Do not merely rewrite the same caption three times.
- Silently consider several possible hooks before selecting the strongest angle.
- Focus on the most useful and distinctive facts in the full description.
- Match the wording to the event type.
- Use natural UK English.
- Mention BM Estates.
- Include the property URL.
- Return complete publishable drafts.

EVENT RULES

NEW_LISTING:
- Present the property as newly available.
- Focus on its strongest benefits and why it deserves attention.
- Do not claim it was listed today unless that information is supplied.

PRICE_REDUCED:
- Clearly state that the price has been reduced.
- Mention the current price.
- Do not invent urgency.
- Do not call it a new listing.

RELISTED:
- Clearly state that the property is back on the market.
- Do not imply why the previous sale or tenancy failed.
- Focus on the renewed opportunity.

SOLD:
- Clearly celebrate that the property has been sold.
- Thank the seller for trusting BM Estates.
- Keep the tone positive and professional.
- Do not describe the property as still available.
- Do not invite people to arrange a viewing of the sold property.
- End with a call to action aimed at homeowners thinking of selling.
- Do not invent the sale price or details of the transaction.

INSTAGRAM

- Engaging and visually scannable.
- Strong first line.
- Approximately 120–190 words.
- Selective emojis.
- Include 4–7 relevant hashtags.
- End with an appropriate call to action.

FACEBOOK

- More informative and conversational than Instagram.
- Approximately 150–240 words.
- Explain practical and lifestyle benefits where appropriate.
- Use fewer emojis.
- Use no more than 3 hashtags.
- End with an appropriate call to action.

TIKTOK

- Write a caption for a property video, not a full script.
- Hook-first and conversational.
- Approximately 50–100 words.
- Keep it punchier than the other versions.
- Include 3–5 relevant hashtags.
- End with a short appropriate call to action.
"""

    property_input = f"""
EVENT TYPE
{event_type}

PROPERTY TITLE
{property_data.get("title")}

LISTING STATUS
{property_data.get("listing_status")}

PRICE
{format_price(property_data.get("price"))}

BEDROOMS
{property_data.get("bedrooms")}

PROPERTY TYPE
{property_data.get("property_type")}

FULL DESCRIPTION
{property_data.get("description")}

PROPERTY URL
{property_data.get("property_url")}

AGENCY
BM Estates
"""

    response = client.responses.parse(
        model="gpt-5.5",
        instructions=instructions,
        input=property_input,
        text_format=PlatformDrafts,
    )

    return response.output_parsed


# ---------------------------------------------------------
# Draft database helpers
# ---------------------------------------------------------

def draft_already_exists(
    supabase,
    event_id,
    platform,
):
    response = (
        supabase
        .table("marketing_drafts")
        .select("id")
        .eq(
            "listing_event_id",
            event_id,
        )
        .eq(
            "platform",
            platform,
        )
        .limit(1)
        .execute()
    )

    return bool(
        response.data
    )


def insert_draft(
    supabase,
    event_id,
    property_id,
    platform,
    draft_text,
):
    if draft_already_exists(
        supabase,
        event_id,
        platform,
    ):
        print(
            f"Draft already exists: "
            f"event {event_id} / "
            f"{platform}"
        )

        return False

    (
        supabase
        .table("marketing_drafts")
        .insert(
            {
                "listing_event_id":
                    event_id,

                "property_listing_id":
                    property_id,

                "platform":
                    platform,

                "draft_text":
                    draft_text,

                "approval_status":
                    "Pending Approval",
            }
        )
        .execute()
    )

    return True


# ---------------------------------------------------------
# Main draft generator
# ---------------------------------------------------------

def run_draft_generation(
    supabase=None,
):
    if supabase is None:
        supabase = (
            default_supabase
        )

    eligible_event_types = [
        "NEW_LISTING",
        "PRICE_REDUCED",
        "RELISTED",
        "SOLD",
    ]

    events = (
        supabase
        .table("listing_events")
        .select(
            "id, "
            "event_type, "
            "property_listing_id"
        )
        .eq(
            "processed",
            False,
        )
        .in_(
            "event_type",
            eligible_event_types,
        )
        .order(
            "created_at",
        )
        .execute()
        .data
    )

    print("")
    print(
        "AI draft generation starting."
    )

    print(
        f"Eligible events to process: "
        f"{len(events)}"
    )

    drafts_created = 0
    events_processed = 0
    events_failed = 0

    for event in events:
        event_id = event[
            "id"
        ]

        event_type = event[
            "event_type"
        ]

        property_id = event[
            "property_listing_id"
        ]

        print("")
        print(
            f"Processing event "
            f"{event_id}: "
            f"{event_type}"
        )

        try:
            property_response = (
                supabase
                .table(
                    "property_listings"
                )
                .select("*")
                .eq(
                    "id",
                    property_id,
                )
                .single()
                .execute()
            )

            property_data = (
                property_response.data
            )

            if not property_data:
                raise RuntimeError(
                    f"Property {property_id} "
                    f"could not be loaded."
                )

            drafts = (
                generate_ai_drafts(
                    event_type,
                    property_data,
                )
            )

            platform_drafts = {
                "Instagram":
                    drafts.instagram,

                "Facebook":
                    drafts.facebook,

                "TikTok":
                    drafts.tiktok,
            }

            for (
                platform,
                draft_text,
            ) in platform_drafts.items():

                inserted = (
                    insert_draft(
                        supabase=supabase,
                        event_id=event_id,
                        property_id=property_id,
                        platform=platform,
                        draft_text=draft_text,
                    )
                )

                if inserted:
                    drafts_created += 1

            (
                supabase
                .table(
                    "listing_events"
                )
                .update(
                    {
                        "processed":
                            True,
                    }
                )
                .eq(
                    "id",
                    event_id,
                )
                .execute()
            )

            events_processed += 1

            print(
                f"Draft generation complete "
                f"for event {event_id}."
            )

        except Exception as error:
            events_failed += 1

            print("")
            print(
                f"FAILED event "
                f"{event_id}"
            )

            print(
                f"Error: "
                f"{error}"
            )

    result = {
        "drafts_created":
            drafts_created,

        "events_processed":
            events_processed,

        "events_failed":
            events_failed,
    }

    print("")
    print(
        "AI draft generation finished."
    )

    print(
        f"Drafts created: "
        f"{drafts_created}"
    )

    print(
        f"Events processed: "
        f"{events_processed}"
    )

    print(
        f"Events failed: "
        f"{events_failed}"
    )

    return result


# ---------------------------------------------------------
# Manual entry point
# ---------------------------------------------------------

if __name__ == "__main__":
    run_draft_generation()