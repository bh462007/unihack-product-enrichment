import os
import json
import pandas as pd
from dotenv import load_dotenv
from groq import Groq

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

df = pd.read_csv("products.csv")
dishwashers = df[df["Part_Desc"].str.contains("Dishwasher", case=False, na=False)]

results = []

for index, row in dishwashers.iterrows():
    part_desc = row["Part_Desc"]
    manufacturer = row["Part_Manuf"]

    prompt = f"""
You are given a short, abbreviated product description from a distributor catalog.
Expand it into structured product data. Only use information present in the input.
If something is not derivable from the input, say "not available in input" rather than guessing.

Input description: "{part_desc}"
Manufacturer field: "{manufacturer}"

Reply with ONLY valid JSON, no other text, in this exact format:
{{
  "manufacturer_part_number": "...",
  "category_guess": "...",
  "material_or_color": "...",
  "invoice_desc": "...",
  "short_title": "...",
  "long_description": "...",
  "confidence_notes": "explain what you're confident about vs guessing"
}}
"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}]
    )

    reply_text = response.choices[0].message.content
    data = json.loads(reply_text)
    results.append(data)
    print(f"Processed: {part_desc}")

output_df = pd.DataFrame(results)
output_df.to_csv("enriched_output.csv", index=False)
print("Done! Saved to enriched_output.csv")