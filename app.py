from flask import Flask, render_template, send_file
import pandas as pd
import os

app = Flask(__name__)


def get_raw():
    raw = pd.read_csv("products.csv")[["Mfg_Part_Num", "Part_Desc", "Part_Manuf"]]
    return raw.rename(columns={"Mfg_Part_Num": "manufacturer_part_number"})


def merge_with_raw(df):
    return df.merge(get_raw(), on="manufacturer_part_number", how="left")


@app.route("/")
@app.route("/")
def home():
    df = pd.read_csv("enriched_output.csv")
    merged = merge_with_raw(df)
    products = merged.to_dict(orient="records")

    total = len(df)
    pass_count = int((df["validation_flags"] == "passed all checks").sum())
    pass_rate = round((pass_count / total) * 100, 1) if total else 0
    avg_confidence = round(df["confidence_score"].mean(), 1) if total else 0

    departments = df["classpath"].str.split(">").str[0].str.strip()
    categories = sorted(departments.dropna().unique().tolist())

    dept_counts = departments.value_counts()
    category_counts = [
        {"name": name, "count": int(count), "pct": round((count / total) * 100, 1)}
        for name, count in dept_counts.items()
    ]

    needs_review_products = []
    needs_review_count = 0
    if os.path.exists("needs_review.csv"):
        nr = pd.read_csv("needs_review.csv")
        needs_review_count = len(nr)
        needs_review_products = merge_with_raw(nr).to_dict(orient="records")

    stats = {
        "total": total,
        "pass_rate": pass_rate,
        "pass_count": pass_count,
        "avg_confidence": avg_confidence,
        "categories_count": len(categories),
        "category_counts": category_counts,
        "needs_review_count": needs_review_count,
    }

    hero_examples = []
    for p in products[:5]:
        hero_examples.append({
            "raw": p.get("Part_Desc", ""),
            "title": p.get("short_title", ""),
            "category": p.get("classpath", "").split(">")[0].strip() if p.get("classpath") else "",
            "material": p.get("material_or_color", ""),
            "confidence": p.get("confidence_score", "")
        })

    return render_template(
        "index.html",
        products=products,
        needs_review_products=needs_review_products,
        categories=categories,
        stats=stats,
        hero_examples=hero_examples,
    )

@app.route("/export")
def export():
    return send_file("enriched_output.csv", as_attachment=True, download_name="enriched_products.csv")


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)