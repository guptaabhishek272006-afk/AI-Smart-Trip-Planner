import os, json, sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from dotenv import load_dotenv
from openai import OpenAI
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-secret-key")
DB = os.path.join(os.path.dirname(__file__), "trips.db")

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS trips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origin TEXT NOT NULL, destination TEXT NOT NULL,
            start_date TEXT NOT NULL, end_date TEXT NOT NULL,
            travellers INTEGER NOT NULL, budget REAL NOT NULL,
            currency TEXT NOT NULL, preferences TEXT,
            itinerary TEXT NOT NULL, created_at TEXT NOT NULL
        )""")

def make_itinerary(data):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("AI API key missing. Add OPENAI_API_KEY to your .env file and restart the app.")
    client = OpenAI(api_key=api_key)
    prompt = f"""
Create a practical, personalized travel plan using the details below.
Origin: {data['origin']}
Destination: {data['destination']}
Dates: {data['start_date']} to {data['end_date']}
Travellers: {data['travellers']}
Total budget: {data['budget']} {data['currency']}
Preferences: {data.get('preferences') or 'General sightseeing'}

Return valid JSON only, with this structure:
{{
 "summary":"short overview and important assumptions",
 "best_time":"seasonal advice for these dates",
 "budget_breakdown":[{{"category":"Stay","estimated_cost":"...","notes":"..."}}],
 "days":[{{"date":"...","title":"...","activities":[{{"time":"Morning","name":"...","description":"...","estimated_cost":"...","map_search":"place name, destination"}}]}}],
 "stay_suggestions":[{{"name":"...","area":"...","why":"...","estimated_price":"..."}}],
 "food_suggestions":[{{"name_or_dish":"...","area":"...","why":"..."}}],
 "transport":"practical transport advice",
 "local_tips":["..."],
 "caveat":"Clearly say prices, availability and opening hours must be verified."
}}
Be realistic and avoid claiming live availability or verified prices. If unsure, label estimates clearly.
"""
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        messages=[
            {"role":"system","content":"You are a careful travel planner. Return valid JSON only. Never invent live bookings or claim current availability."},
            {"role":"user","content":prompt}
        ],
        response_format={"type":"json_object"}
    )
    return json.loads(response.choices[0].message.content)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/plan", methods=["POST"])
def plan():
    fields = ["origin","destination","start_date","end_date","travellers","budget","currency"]
    data = {k: request.form.get(k, "").strip() for k in fields}
    data["preferences"] = request.form.get("preferences","").strip()
    try:
        if any(not data[k] for k in fields):
            raise ValueError("Please complete all required fields.")
        start = datetime.strptime(data["start_date"], "%Y-%m-%d").date()
        end = datetime.strptime(data["end_date"], "%Y-%m-%d").date()
        if end < start: raise ValueError("End date must be on or after start date.")
        data["travellers"] = int(data["travellers"])
        data["budget"] = float(data["budget"])
        if data["travellers"] < 1 or data["budget"] <= 0: raise ValueError("Travellers and budget must be positive.")
        itinerary = make_itinerary(data)
        with db() as con:
            cur = con.execute("""INSERT INTO trips
                (origin,destination,start_date,end_date,travellers,budget,currency,preferences,itinerary,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (data["origin"],data["destination"],data["start_date"],data["end_date"],
                 data["travellers"],data["budget"],data["currency"],data["preferences"],
                 json.dumps(itinerary,ensure_ascii=False),datetime.now().isoformat(timespec="seconds")))
            trip_id = cur.lastrowid
        return redirect(url_for("trip", trip_id=trip_id))
    except (ValueError, RuntimeError, json.JSONDecodeError) as e:
        flash(str(e), "error")
        return redirect(url_for("home"))
    except Exception as e:
        app.logger.exception("Trip generation failed")
        flash("Trip generation failed. Check your API key, internet connection, and server terminal.", "error")
        return redirect(url_for("home"))

@app.route("/trip/<int:trip_id>")
def trip(trip_id):
    with db() as con:
        row = con.execute("SELECT * FROM trips WHERE id=?", (trip_id,)).fetchone()
    if not row:
        flash("Trip not found.", "error")
        return redirect(url_for("home"))
    item = dict(row)
    item["itinerary"] = json.loads(item["itinerary"])
    return render_template("trip.html", trip=item)

@app.route("/my-trips")
def my_trips():
    with db() as con:
        trips = con.execute("SELECT id,origin,destination,start_date,end_date,created_at FROM trips ORDER BY id DESC").fetchall()
    return render_template("my_trips.html", trips=trips)

@app.route("/weather")
def weather():
    place = request.args.get("place","").strip()
    if not place: return jsonify({"error":"Enter a destination."}), 400
    import requests
    try:
        geo = requests.get("https://geocoding-api.open-meteo.com/v1/search", params={"name":place,"count":1,"language":"en","format":"json"}, timeout=10).json()
        results = geo.get("results", [])
        if not results: return jsonify({"error":"Location not found."}), 404
        loc=results[0]
        forecast=requests.get("https://api.open-meteo.com/v1/forecast",
            params={"latitude":loc["latitude"],"longitude":loc["longitude"],
                    "current":"temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                    "daily":"temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                    "timezone":"auto"}, timeout=10).json()
        return jsonify({"location":loc["name"],"country":loc.get("country",""),"forecast":forecast})
    except Exception:
        return jsonify({"error":"Weather service is temporarily unavailable."}), 502

@app.route("/download/<int:trip_id>")
def download(trip_id):
    with db() as con:
        row=con.execute("SELECT * FROM trips WHERE id=?", (trip_id,)).fetchone()
    if not row: return "Trip not found",404
    data=json.loads(row["itinerary"])
    buf=BytesIO()
    doc=SimpleDocTemplate(buf,pagesize=A4,rightMargin=42,leftMargin=42,topMargin=42,bottomMargin=42)
    styles=getSampleStyleSheet()
    story=[Paragraph("AI Smart Trip Planner",styles["Title"]),
           Paragraph(f"{row['origin']} → {row['destination']}",styles["Heading1"]),
           Paragraph(f"{row['start_date']} to {row['end_date']} | {row['travellers']} traveller(s) | Budget: {row['budget']} {row['currency']}",styles["Normal"]),
           Spacer(1,12),Paragraph("Trip overview",styles["Heading2"]),Paragraph(data.get("summary",""),styles["BodyText"]),Spacer(1,10)]
    for day in data.get("days",[]):
        story.append(Paragraph(f"{day.get('date','')} — {day.get('title','')}",styles["Heading2"]))
        for act in day.get("activities",[]):
            story.append(Paragraph(f"<b>{act.get('time','')}</b> — {act.get('name','')}: {act.get('description','')} (Estimated: {act.get('estimated_cost','')})",styles["BodyText"]))
            story.append(Spacer(1,5))
    for title,key in [("Budget breakdown","budget_breakdown"),("Stay suggestions","stay_suggestions"),("Food suggestions","food_suggestions"),("Local tips","local_tips")]:
        story.append(Paragraph(title,styles["Heading2"]))
        for obj in data.get(key,[]):
            story.append(Paragraph(json.dumps(obj,ensure_ascii=False) if isinstance(obj,dict) else str(obj),styles["BodyText"]))
            story.append(Spacer(1,4))
    story.append(Spacer(1,10))
    story.append(Paragraph(data.get("caveat","Verify details before travel."),styles["Italic"]))
    doc.build(story); buf.seek(0)
    return send_file(buf,as_attachment=True,download_name=f"trip-{trip_id}.pdf",mimetype="application/pdf")

@app.route("/about")
def about(): return render_template("about.html")

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
