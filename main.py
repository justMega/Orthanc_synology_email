import os
import smtplib
import threading
import urllib.request
from email.message import EmailMessage

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from markupsafe import escape

load_dotenv()  # read .env file

app = Flask(__name__)
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")

SYNOLOGY_URL = os.getenv("SYNOLOGY_URL")
SYNO_USER = os.getenv("SYNO_USER")
SYNO_PASS = os.getenv("SYNO_PASS")

ORTHANC_URL = os.getenv("ORTHANC_URL")
OR_USER = os.getenv("OR_USER")
OR_PASS = os.getenv("OR_PASS")

STUDY_PATH = os.getenv("STUDY_PATH")
SYNOLOGY_PATH = os.getenv("SYNOLOGY_PATH")

download_progress = {}

# One lock per study, so two requests for the same study don't download
# into the same file at the same time.
_study_locks = {}
_study_locks_guard = threading.Lock()


def _lock_for(study_id):
    with _study_locks_guard:
        return _study_locks.setdefault(study_id, threading.Lock())


def zip_study(study_id):
    output_path = f"{STUDY_PATH}/{study_id}.zip"
    tmp_path = output_path + ".part"

    with _lock_for(study_id):
        if os.path.exists(output_path):
            download_progress[study_id] = {"percent": "100%", "status": "downloading"}
            return

        url = f"{ORTHANC_URL}/studies/{study_id}/archive"

        def download_progress_treck(block_num, block_size, total_size):
            downloaded = block_num * block_size
            if total_size > 0:
                percent = min(100, downloaded * 100 / total_size)
                download_progress[study_id] = {
                    "percent": f"{percent:.0f}%",
                    "status": "downloading",
                }
            else:
                download_progress[study_id] = {
                    "percent": f"{downloaded} bytes",
                    "status": "downloading",
                }

        # Setup basic authentication
        password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        password_mgr.add_password(None, ORTHANC_URL, OR_USER, OR_PASS)
        opener = urllib.request.build_opener(
            urllib.request.HTTPBasicAuthHandler(password_mgr)
        )
        urllib.request.install_opener(opener)

        # Download to a temporary file; only a complete download gets the final name,
        # so an interrupted download is never mistaken for a finished one.
        try:
            urllib.request.urlretrieve(
                url, tmp_path, reporthook=download_progress_treck
            )
            os.replace(tmp_path, output_path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


def create_synology_share(filepath):
    session = requests.Session()

    # Login
    login_params = {
        "api": "SYNO.API.Auth",
        "version": "6",
        "method": "login",
        "account": SYNO_USER,
        "passwd": SYNO_PASS,
        "session": "FileStation",
        "format": "sid",
    }

    login = session.get(
        f"{SYNOLOGY_URL}/webapi/auth.cgi", params=login_params, verify=False
    )
    login_data = login.json()
    if not login_data.get("success"):
        raise Exception(f"Synology login failed: {login_data.get('error')}")
    sid = login_data["data"]["sid"]

    try:
        # Create share link
        share_params = {
            "api": "SYNO.FileStation.Sharing",
            "version": "3",
            "method": "create",
            "path": filepath,
            "create_short_url": "true",
            "_sid": sid,
        }

        share = session.get(
            f"{SYNOLOGY_URL}/webapi/entry.cgi", params=share_params, verify=False
        )

        share_data = share.json()
        if not share_data.get("success"):
            raise Exception(f"Failed to create share link: {share_data.get('error')}")

        return share_data["data"]["links"][0]["url"]
    finally:
        # Logout so sessions don't pile up on the NAS
        try:
            session.get(
                f"{SYNOLOGY_URL}/webapi/auth.cgi",
                params={
                    "api": "SYNO.API.Auth",
                    "version": "6",
                    "method": "logout",
                    "session": "FileStation",
                    "_sid": sid,
                },
                verify=False,
            )
        except Exception:
            pass


def download_and_email(uuid, patient, patientid, date, email):
    download_progress[uuid] = {"percent": "0", "status": "downloading"}

    try:
        zip_study(uuid)
    except Exception as e:
        download_progress[uuid]["status"] = f"Error downloading study: {e}"
        return

    try:
        url = create_synology_share(f"{SYNOLOGY_PATH}/{uuid}.zip")
    except Exception as e:
        download_progress[uuid]["status"] = f"Error generation share link: {e}"
        return

    # Create email
    msg = EmailMessage()
    msg["Subject"] = "Link do CT preiskave"
    msg["From"] = SENDER_EMAIL
    msg["To"] = email

    try:
        with open("massage.txt", "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        download_progress[uuid]["status"] = f"Error reading email template: {e}"
        return

    # Escape the patient name: it comes from the URL and goes into HTML
    html_content = content.replace("#PATIENT#", str(escape(patient or ""))).replace(
        "#LINK#", url
    )
    msg.set_content(f"Link do CT preiskave: {url}")  # plain-text fallback
    msg.add_alternative(html_content, subtype="html")

    # Send email
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.starttls()
            smtp.login(SENDER_EMAIL, SENDER_PASSWORD)
            refused = smtp.send_message(msg)
        if refused:
            download_progress[uuid]["status"] = (
                f"Error sending email: refused {list(refused)}"
            )
        else:
            download_progress[uuid]["status"] = "done"
    except Exception as e:
        download_progress[uuid]["status"] = f"Error sending email: {e}"


@app.route("/error/<error>/<uuid>")
def error(error, uuid):
    return jsonify({"error": error, "uuid": uuid})


@app.route("/done/<uuid>")
def done(uuid):
    return f"EMAIL SENT {escape(uuid)}"


@app.route("/progress/<study_id>")
def progress(study_id):
    info = download_progress.get(study_id, {"percent": "0", "status": "downloading"})
    return jsonify({"progress": info["percent"], "status": info["status"]})


@app.route("/export-url", methods=["GET", "POST"])
def export_url():
    # GET request
    uuid = request.args.get("uuid")
    patient = request.args.get("patient")
    patientid = request.args.get("patientid")
    date = request.args.get("date")

    if request.method == "POST":
        email = request.form.get("email")
        # Start background thread
        thread = threading.Thread(
            target=download_and_email,
            args=(uuid, patient, patientid, date, email),
            daemon=True,
        )
        thread.start()
        return render_template("progress.html", uuid=uuid)

    return render_template(
        "email_form.html", uuid=uuid, patient=patient, patientid=patientid, date=date
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
