from dotenv import load_dotenv
from openai import OpenAI
from supabase import create_client
from pydantic import BaseModel
import os

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)


class PlatformDrafts(BaseModel):
    instagram: str
    facebook: str
    tiktok: str


def format_price(price):
    if price is None:
        return "Price on application"

    return f"£{price:,.0f}"


def load_marketing_brain():
    file_path = os.path.join("ai", "marketing_brain.txt")

    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()


def generate_ai_drafts(event_type, property_data):
    marketing_brain = load_marketing_brain()

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

PRICE_REDUCED:
- Clearly state that the price has been reduced.
- Mention the current price.
- Do not invent urgency.
- Do not call it a new listing.

RELISTED:
- Clearly state that the property is back on the market.
- Do not imply why the previous sale or tenancy failed.
- Focus on the renewed opportunity.

INSTAGRAM

- Engaging and visually scannable.
- Strong first line.
- Approximately 120–190 words.
- Selective emojis.
- Include 4–7 relevant hashtags.
- End with a viewing or enquiry call to action.

FACEBOOK

- More informative and conversational than Instagram.
- Approximately 150–240 words.
- Explain practical and lifestyle benefits.
- Use fewer emojis.
- Use no more than 3 hashtags.
- End with a viewing or enquiry call to action.

TIKTOK

- Write a caption for a property video, not a full script.
- Hook-first and conversational.
- Approximately 50–100 words.
- Keep it punchier than the other versions.
- Include 3–5 relevant hashtags.
- End with a short viewing or enquiry call to action.
"""

    property_input = f"""
EVENT TYPE
{event_type}

PROPERTY TITLE
{property_data.get("title")}

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


events = (
    supabase.table("listing_events")
    .select("id, event_type, property_listing_id")
    .eq("processed", False)
    .in_("event_type", ["NEW_LISTING", "PRICE_REDUCED", "RELISTED"])
    .execute()
    .data
)

print(f"Eligible events to process: {len(events)}")

created = 0
failed = 0

for event in events:
    event_id = event["id"]
    event_type = event["event_type"]
    property_id = event["property_listing_id"]

    print(f"\nProcessing event {event_id}: {event_type}")

    try:
        property_response = (
            supabase.table("property_listings")
            .select("*")
            .eq("id", property_id)
            .single()
            .execute()
        )

        property_data = property_response.data

        drafts = generate_ai_drafts(event_type, property_data)

        platform_drafts = {
            "Instagram": drafts.instagram,
            "Facebook": drafts.facebook,
            "TikTok": drafts.tiktok,
        }

        for platform, draft_text in platform_drafts.items():
            supabase.table("marketing_drafts").insert({
                "listing_event_id": event_id,
                "property_listing_id": property_id,
                "platform": platform,
                "draft_text": draft_text,
                "approval_status": "Pending Approval"
            }).execute()

            created += 1

        supabase.table("listing_events").update({
            "processed": True
        }).eq("id", event_id).execute()

        print(f"Created 3 AI drafts for event {event_id}")

    except Exception as error:
        failed += 1
        print(f"FAILED event {event_id}")
        print(error)

print("\nAI draft generation finished.")
print(f"Drafts created: {created}")
print(f"Events failed: {failed}")