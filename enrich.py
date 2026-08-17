import os
import json
import time
import logging
import pandas as pd
from dotenv import load_dotenv
from groq import Groq

# ---------- CONFIG ----------
INPUT_FILE = "products.csv"
OUTPUT_FILE = "enriched_output.csv"
FAILED_LOG_FILE = "failed_rows.csv"
LOG_FILE = "run_log.txt"
SUMMARY_FILE = "run_summary.json"
DUPLICATES_FILE = "duplicate_parts_report.csv"
NEEDS_REVIEW_FILE = "needs_review.csv"
CATEGORY_KEYWORDS = "Dishwasher|Drill|Impact Driver|Impact Wrench"
MODEL_NAME = "llama-3.3-70b-versatile"
SECONDS_BETWEEN_CALLS = 2.0
MAX_RETRIES = 2
RATE_LIMIT_WAIT_SECONDS = 15
CONFIDENCE_REVIEW_THRESHOLD = 70  # rows scoring below this go to needs_review.csv

KEY_FIELDS_FOR_CONFIDENCE = [
    "material_or_color", "invoice_desc", "mobile_desc",
    "short_title", "long_description"
]

# ---------- LOGGING SETUP ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ---------- SETUP ----------
load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def load_products():
    df = pd.read_csv(INPUT_FILE)
    selected = df[df["Part_Desc"].str.contains(CATEGORY_KEYWORDS, case=False, na=False, regex=True)]
    return selected


def check_duplicates(df):
    """Find rows sharing the same part number -- a real data-quality issue worth flagging."""
    dupes = df[df.duplicated(subset=["Mfg_Part_Num"], keep=False)]
    if len(dupes) > 0:
        dupes = dupes.sort_values("Mfg_Part_Num")
        dupes.to_csv(DUPLICATES_FILE, index=False)
        logger.warning(f"Found {len(dupes)} rows with duplicate part numbers -- see {DUPLICATES_FILE}")
    else:
        logger.info("No duplicate part numbers found in source data.")
    return len(dupes)


def get_already_processed_ids():
    if os.path.exists(OUTPUT_FILE):
        existing = pd.read_csv(OUTPUT_FILE)
        return set(existing["manufacturer_part_number"].astype(str))
    return set()


def is_row_valid(row):
    part_desc = row.get("Part_Desc")
    if pd.isna(part_desc) or not str(part_desc).strip():
        return False, "missing or empty Part_Desc"
    if pd.isna(row.get("Mfg_Part_Num")) or not str(row.get("Mfg_Part_Num")).strip():
        return False, "missing or empty Mfg_Part_Num"
    return True, None


def build_prompt(part_desc, manufacturer):
    return f"""
You are given a short, abbreviated product description from a distributor catalog.
Expand it into structured, commerce-ready product data following these rules:
- invoice_desc: ALL CAPS, maximum 40 characters, abbreviated style like a receipt line
- mobile_desc: MUST be between 60 and 80 characters exactly (count carefully). Combine manufacturer, product type, model number, and key features into one sentence to reach this length.
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


def is_rate_limit_error(e):
    msg = str(e).lower()
    return "429" in msg or "rate limit" in msg or "rate_limit" in msg


def call_ai_with_retry(prompt):
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
            logger.warning(last_error)
        except Exception as e:
            if is_rate_limit_error(e):
                logger.warning(f"Rate limited, waiting {RATE_LIMIT_WAIT_SECONDS}s before retry...")
                time.sleep(RATE_LIMIT_WAIT_SECONDS)
                last_error = f"Rate limit hit on attempt {attempt}"
                continue
            last_error = f"API error on attempt {attempt}: {e}"
            logger.warning(last_error)
        time.sleep(1)
    return None, last_error


def repair_mobile_desc(mobile_desc, part_desc, manufacturer, max_attempts=2):
    current = mobile_desc
    for attempt in range(max_attempts):
        length = len(current)
        if 60 <= length <= 80:
            return current

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
        except Exception as e:
            logger.warning(f"Repair attempt failed: {e}")
            break

    return current


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


def compute_confidence_score(data):
    """Score 0-100 based on how many key fields the AI could actually derive vs. guessed/missing."""
    missing_count = 0
    for field in KEY_FIELDS_FOR_CONFIDENCE:
        value = str(data.get(field, "")).lower()
        if "not available in input" in value or not value.strip():
            missing_count += 1

    score = 100 - (missing_count * 15)

    if data.get("validation_flags") != "passed all checks":
        score -= 10

    return max(0, min(100, score))

def detect_manufacturer_ambiguity(data, manufacturer_field):
    """
    Real entity-resolution check: does the AI's derived manufacturer match
    the raw distributor manufacturer field, or is there a conflict/ambiguity?
    """
    manufacturer_field_clean = str(manufacturer_field).lower()
    short_title = str(data.get("short_title", "")).lower()
    long_desc = str(data.get("long_description", "")).lower()

    # Strip out known non-manufacturer distributor terms so we're comparing fairly
    distributor_terms = ["appliance dealers cooperative", "-- unbranded --", "-- no dib brand --", "unbranded"]
    is_distributor_only = any(term in manufacturer_field_clean for term in distributor_terms)

    combined_output_text = short_title + " " + long_desc

    if is_distributor_only:
        # We can't verify against a real manufacturer name at all
        return "AMBIGUOUS: manufacturer field is a distributor/placeholder, not a real manufacturer name"

    # crude check: does any word from the manufacturer field appear in our derived output?
    manufacturer_words = [w for w in manufacturer_field_clean.replace("(", " ").replace(")", " ").split() if len(w) > 3]
    found_match = any(word in combined_output_text for word in manufacturer_words)

    if not found_match:
        return f"AMBIGUOUS: derived brand does not match manufacturer field '{manufacturer_field}'"

    return "RESOLVED: manufacturer consistent with source data"

def process_all():
    df_all = load_products()
    check_duplicates(df_all)

    already_done = get_already_processed_ids()
    logger.info(f"Total matching rows: {len(df_all)}")
    logger.info(f"Already processed (will skip): {len(already_done)}")

    new_results = []
    failed_rows = []
    skipped_bad_input = 0
    passed_validation_count = 0
    failed_validation_count = 0

    for index, row in df_all.iterrows():
        part_num = str(row["Mfg_Part_Num"])
        if part_num in already_done:
            continue

        valid, reason = is_row_valid(row)
        if not valid:
            logger.warning(f"Skipping row {index}: {reason}")
            failed_rows.append({"Mfg_Part_Num": part_num, "Part_Desc": row.get("Part_Desc"), "error": reason})
            skipped_bad_input += 1
            continue

        part_desc = row["Part_Desc"]
        manufacturer = row["Part_Manuf"]
        prompt = build_prompt(part_desc, manufacturer)

        data, error = call_ai_with_retry(prompt)

        if error:
            logger.error(f"FAILED: {part_desc} -- {error}")
            failed_rows.append({"Mfg_Part_Num": part_num, "Part_Desc": part_desc, "error": error})
            continue

        data["mobile_desc"] = repair_mobile_desc(data.get("mobile_desc", ""), part_desc, manufacturer)
        data["validation_flags"] = validate_row(data)
        data["manufacturer_part_number"] = part_num
        data["confidence_score"] = compute_confidence_score(data)
        data["entity_resolution_status"] = detect_manufacturer_ambiguity(data, manufacturer)

        if data["validation_flags"] == "passed all checks":
            passed_validation_count += 1
        else:
            failed_validation_count += 1

        new_results.append(data)
        logger.info(f"Processed: {part_desc} (confidence: {data['confidence_score']})")

        time.sleep(SECONDS_BETWEEN_CALLS)

    if new_results:
        new_df = pd.DataFrame(new_results)
        if os.path.exists(OUTPUT_FILE):
            new_df.to_csv(OUTPUT_FILE, mode="a", header=False, index=False)
        else:
            new_df.to_csv(OUTPUT_FILE, index=False)

    if failed_rows:
        pd.DataFrame(failed_rows).to_csv(FAILED_LOG_FILE, index=False)

    # Build the needs-review split from the FULL output file, not just this run's new rows
    if os.path.exists(OUTPUT_FILE):
        full_output = pd.read_csv(OUTPUT_FILE)
        needs_review = full_output[
            (full_output["confidence_score"] < CONFIDENCE_REVIEW_THRESHOLD) |
            (full_output["validation_flags"] != "passed all checks")
        ]
        needs_review.to_csv(NEEDS_REVIEW_FILE, index=False)
        logger.info(f"{len(needs_review)} of {len(full_output)} total rows flagged for human review")

    summary = {
        "total_matching_rows": len(df_all),
        "already_processed_skipped": len(already_done),
        "newly_processed": len(new_results),
        "skipped_bad_input": skipped_bad_input,
        "api_failures": len(failed_rows) - skipped_bad_input,
        "passed_validation": passed_validation_count,
        "failed_validation": failed_validation_count,
        "pass_rate_percent": round((passed_validation_count / len(new_results) * 100), 1) if new_results else 0
    }

    with open(SUMMARY_FILE, "w") as f:
        json.dump(summary, f, indent=2)

    logger.info("=" * 40)
    logger.info("RUN SUMMARY")
    for key, value in summary.items():
        logger.info(f"  {key}: {value}")
    logger.info("=" * 40)


if __name__ == "__main__":
    process_all()