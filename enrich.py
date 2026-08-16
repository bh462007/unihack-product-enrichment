import os
import json
import time
import pandas as pd
from dotenv import load_dotenv
from groq import Groq

# ---------- CONFIG (change things here, not buried in logic below) ----------
INPUT_FILE = "products.csv"
OUTPUT_FILE = "enriched_output.csv"
FAILED_LOG_FILE = "failed_rows.csv"
CATEGORY_KEYWORDS = "Dishwasher|Drill|Impact Driver|Impact Wrench"
MODEL_NAME = "llama-3.3-70b-versatile"
SECONDS_BETWEEN_CALLS = 1.0
MAX_RETRIES = 2

# ---------- SETUP ----------
load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def load_products():
    df = pd.read_csv(INPUT_FILE)
    selected = df[df["Part_Desc"].str.contains(CATEGORY_KEYWORDS, case=False, na=False, regex=True)]
    return selected


def get_already_processed_ids():
    """Return a set of part numbers we've already successfully processed, so we don't redo them."""
    if os.path.exists(OUTPUT_FILE):
        existing = pd.read_csv(OUTPUT_FILE)
        return set(existing["manufacturer_part_number"].astype(str))
    return set()


def build_prompt(part_desc, manufacturer):
    return f"""
You are given a short, abbreviated product description from a distributor catalog.
Expand it into structured, commerce-ready product data following these rules:
- invoice_desc: ALL CAPS, maximum 40 characters, abbreviated style like a receipt line
- mobile_desc: MUST be between 60 and 80 characters exactly (count carefully). Combine manufacturer, product type, model number, and key features into one sentence to reach this length. Example: "Whirlpool Corporation WDTS7024RZ Dishwasher, Eco Series, Stainless Steel, Built-in"
- short_title: a clean product title a shopper would read
- long_description: a full sentence description combining known details
- classpath: a category path like "Department > Category > Subcategory" (your best guess)
Only use information present in the input or manufacturer field. If something is not derivable, say "not available in input".

Input description: "{part_desc}"
Manufacturer field: "{manufacturer}"

Reply with ONLY valid JSON, no other text, in this exact format:
{{
  "manufacturer_part_number": "...",
  "classpath": "...",
  "material_or_color": "...",
  "invoice_desc": "...",
  "mobile_desc": "...",
  "short_title": "...",
  "long_description": "...",
  "confidence_notes": "..."
}}
"""


def call_ai_with_retry(prompt):
    """Try calling the AI up to MAX_RETRIES times if it fails or returns bad JSON."""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": prompt}]
            )
            reply_text = response.choices[0].message.content
            data = json.loads(reply_text)
            return data, None
        except json.JSONDecodeError as e:
            last_error = f"Bad JSON on attempt {attempt}: {e}"
        except Exception as e:
            last_error = f"API error on attempt {attempt}: {e}"
        time.sleep(1)
    return None, last_error


def validate_row(data):
    flags = []
    invoice = data.get("invoice_desc", "")
    mobile = data.get("mobile_desc", "")

    if len(invoice) > 40:
        flags.append("invoice_desc exceeds 40 characters")
    if not invoice.isupper():
        flags.append("invoice_desc not all caps")
    if not (60 <= len(mobile) <= 80):
        flags.append(f"mobile_desc length is {len(mobile)}, expected 60-80")

    return "; ".join(flags) if flags else "passed all checks"

def repair_mobile_desc(mobile_desc, part_desc, manufacturer, max_attempts=2):
    """If mobile_desc fails the length rule, ask the AI to specifically fix it, up to max_attempts times."""
    current = mobile_desc
    for attempt in range(max_attempts):
        length = len(current)
        if 60 <= length <= 80:
            return current  # already good, stop early

        repair_prompt = f"""
The following product description needs to be between 60 and 80 characters. It is currently {length} characters.
Rewrite it to fit that range as a natural sentence — do not just pad with spaces or cut it off mid-word.

Product info: "{part_desc}" (Manufacturer: {manufacturer})
Current description: "{current}"

Reply with ONLY the revised description text. No quotes, no explanation, nothing else.
"""
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": repair_prompt}]
            )
            current = response.choices[0].message.content.strip().strip('"')
        except Exception:
            break  # if the repair call itself fails, just stop and return what we have

    return current

def process_all():
    selected = load_products()
    already_done = get_already_processed_ids()
    print(f"Total matching rows: {len(selected)}")
    print(f"Already processed (will skip): {len(already_done)}")

    new_results = []
    failed_rows = []

    for index, row in selected.iterrows():
        part_num = str(row["Mfg_Part_Num"])
        if part_num in already_done:
            continue

        part_desc = row["Part_Desc"]
        manufacturer = row["Part_Manuf"]
        prompt = build_prompt(part_desc, manufacturer)

        data, error = call_ai_with_retry(prompt)

        if error:
            print(f"FAILED: {part_desc} -- {error}")
            failed_rows.append({"Mfg_Part_Num": part_num, "Part_Desc": part_desc, "error": error})
            continue

        data["mobile_desc"] = repair_mobile_desc(data.get("mobile_desc", ""), part_desc, manufacturer)
        data["validation_flags"] = validate_row(data)
        data["manufacturer_part_number"] = part_num # always use the real value, never trust AI extraction for this
        new_results.append(data)
        print(f"Processed: {part_desc}")

        time.sleep(SECONDS_BETWEEN_CALLS)

    # Append new results to existing file instead of overwriting
    if new_results:
        new_df = pd.DataFrame(new_results)
        if os.path.exists(OUTPUT_FILE):
            new_df.to_csv(OUTPUT_FILE, mode="a", header=False, index=False)
        else:
            new_df.to_csv(OUTPUT_FILE, index=False)

    if failed_rows:
        pd.DataFrame(failed_rows).to_csv(FAILED_LOG_FILE, index=False)
        print(f"{len(failed_rows)} rows failed -- see {FAILED_LOG_FILE}")

    print(f"Done! {len(new_results)} new rows processed this run.")


if __name__ == "__main__":
    process_all()