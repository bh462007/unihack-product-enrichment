from flask import Flask, render_template
import pandas as pd

app = Flask(__name__)

@app.route("/")
def home():
    df = pd.read_csv("enriched_output.csv")
    products = df.to_dict(orient="records")
    columns = df.columns.tolist()
    return render_template("index.html", products=products, columns=columns)

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)