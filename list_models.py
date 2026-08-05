from dotenv import load_dotenv
from openai import OpenAI
import os

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

models = client.models.list()

print("\nAvailable models:\n")

for model in models.data:
    print(model.id)