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

PROPERTY_ID = 20
EVENT_TYPE = "NEW_LISTING"


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


property_response = (
    supabase.table("property_listings")
    .select("*")
    .eq("id", PROPERTY_ID)
    .single()
    .execute()
)

property_data = property_response.data
marketing_brain = load_marketing_brain()

instructions = f"""
{marketing_brain}

Create three genuinely different property marketing drafts:

1. Instagram
2. Facebook
3. TikTok

GENERAL RULES

- Use only the supplied property information.
- Do not invent claims, features, urgency or local information.
- Do not merely rewrite the same caption three times.
- Silently consider several possible hooks before selecting the strongest angle.
- Focus on the most useful and distinctive facts in the full description.
- Avoid generic openings such as:
  - New listing
  - Just listed
  - We are delighted to present
  - Discover this stunning property
  - Looking for your dream home?
- Use natural UK English.
- Mention BM Estates.
- Include the property URL.
- Return complete publishable drafts.

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
- Explain the practical and lifestyle benefits clearly.
- Use fewer emojis.
- End with a viewing or enquiry call to action.
- Do not include excessive hashtags; use no more than 3.

TIKTOK

- Write a caption suitable for a property video, not a full video script.
- Hook-first and conversational.
- Approximately 50–100 words.
- Keep it punchier than the other versions.
- Include 3–5 relevant hashtags.
- End with a short viewing or enquiry call to action.
"""

property_input = f"""
EVENT TYPE
{EVENT_TYPE}

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

drafts = response.output_parsed

print("\n================ INSTAGRAM ================\n")
print(drafts.instagram)

print("\n================ FACEBOOK =================\n")
print(drafts.facebook)

print("\n================ TIKTOK ===================\n")
print(drafts.tiktok)