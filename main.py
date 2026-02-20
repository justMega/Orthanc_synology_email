from markupsafe import escape
from flask import Flask, request, jsonify, render_template
import smtplib
from email.message import EmailMessage
import requests
import os


app = Flask(__name__)
SENDER_EMAIL = os.getenv("SENDER_EMAIL") 
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
#"luip xbwh mcml dzty" 

SYNOLOGY_URL = os.getenv("SYNOLOGY_URL")
SYNO_USER = os.getenv("SYNO_USER")
SYNO_PASS = os.getenv("SYNO_PASS")


def create_synology_share(filepath):
    session = requests.Session()

    # Login
    login_params = {
        "api": "SYNO.API.Auth",
        "version": "3",
        "method": "login",
        "account": SYNO_USER,
        "passwd": SYNO_PASS,
        "session": "FileStation",
        "format": "sid"
    }

    login = session.get(f"{SYNOLOGY_URL}/webapi/auth.cgi", params=login_params, verify=False)
    sid = login.json()["data"]["sid"]

    # Create share link
    share_params = {
        "api": "SYNO.FileStation.Sharing",
        "version": "3",
        "method": "create",
        "path": filepath,
        "create_short_url": "true"
    }

    share = session.get(
        f"{SYNOLOGY_URL}/webapi/entry.cgi",
        params=share_params,
        cookies={"id": sid},
        verify=False
    )

    share_data = share.json()

    if not share_data["success"]:
        raise Exception("Failed to create share link")

    return share_data["data"]["links"][0]["url"]


@app.route("/export-url", methods=["GET", "POST"])
def export_url():
    # GET request
    uuid = request.args.get("uuid")
    patient = request.args.get("patient")
    patientid = request.args.get("patientid")
    date = request.args.get("date")

    if request.method == "POST":
        email = request.form.get("email")

        # Create email
        msg = EmailMessage()
        msg["Subject"] = "Link do CT preiskave"
        msg["From"] = SENDER_EMAIL
        msg["To"] = email

        msg.set_content(f"""
            Export Details:
            UUID: {uuid}
            Patient: {patient}
            Patient ID: {patientid}
            Date: {date}
        """)

        # Send email
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                smtp.login(SENDER_EMAIL, SENDER_PASSWORD)
                smtp.send_message(msg)
            return "<h2>Email sent successfully!</h2>"
        except Exception as e:
            return f"Error sending email: {e}"

    return render_template(
        "email_form.html",
        uuid=uuid,
        patient=patient,
        patientid=patientid,
        date=date
    )

if __name__ == "__main__":
    app.run(debug=True)
