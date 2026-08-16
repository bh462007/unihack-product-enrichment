# import os
# from dotenv import load_dotenv
# from groq import Groq
# import json

# load_dotenv()
# client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# product_desc = "PDSH4816AF Dishwasher SS - Display Only"

# prompt = f"""
# You are given a short, abbreviated product description from a distributor catalog.
# Expand it into structured product data.

# Input: "{product_desc}"

# Reply with ONLY valid JSON, no other text, in this exact format:
# {{
#   "model_number": "...",
#   "category": "...",
#   "color_or_material": "...",
#   "short_title": "...",
#   "notes": "..."
# }}
# """

# response = client.chat.completions.create(
#     model="llama-3.3-70b-versatile",
#     messages=[{"role": "user", "content": prompt}]
# )

# reply_text = response.choices[0].message.content
# print(reply_text)

# data = json.loads(reply_text)
# print("Model number is:", data["model_number"])


import pandas as pd

df = pd.read_csv("products.csv")

print("Total rows:", len(df))
print(df.head())

dishwashers = df[df["Part_Desc"].str.contains("Dishwasher", case=False, na=False)]
print("Dishwasher rows found:", len(dishwashers))
print(dishwashers)