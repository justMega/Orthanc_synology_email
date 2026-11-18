import logging
import os
import re
import smtplib
import threading
import time
from datetime import date as date_cls
from datetime import datetime, timedelta
from email.message import EmailMessage

import requests
import urllib3
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from markupsafe import escape

load_dotenv()  # read .env file

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger(__name__)

app = Flask(__name__)

SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

SYNOLOGY_URL = os.getenv("SYNOLOGY_URL")
SYNO_USER = os.getenv("SYNO_USER")
SYNO_PASS = os.getenv("SYNO_PASS")
# Synology usually runs with a self-signed certificate
SYNO_VERIFY_SSL = os.getenv("SYNO_VERIFY_SSL", "false").lower() in ("1", "true", "yes")
if not SYNO_VERIFY_SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ORTHANC_URL = os.getenv("ORTHANC_URL")
OR_USER = os.getenv("OR_USER")
OR_PASS = os.getenv("OR_PASS")

STUDY_PATH = os.getenv("STUDY_PATH", "etc/data")
SYNOLOGY_PATH = os.getenv("SYNOLOGY_PATH")
MESSAGE_FILE = os.getenv("MESSAGE_FILE", "message.txt")

# Exported studies older than this are deleted, and share links expire then too
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "14"))
CLEANUP_INTERVAL_HOURS = float(os.getenv("CLEANUP_INTERVAL_HOURS", "6"))

# Orthanc IDs look like 2cfe58b3-2d10f214-ff77c451-645bd5bc-201fa027
STUDY_ID_RE = re.compile(r"^[0-9a-f]{8}(-[0-9a-f]{8}){4}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

download_progress = {}

# One lock per study, so two requests for the same study don't download
# into the same file at the same time, and cleanup never deletes a file in use.
_study_locks = {}
_study_locks_guard = threading.Lock()


def _lock_for(study_id):
    with _study_locks_guard:
        return _study_locks.setdefault(study_id, threading.Lock())


def _set_progress(study_id, percent=None, status=None):
    info = download_progress.setdefault(
        study_id, {"percent": "0%", "status": "downloading"}
    )
    if percent is not None:
        info["percent"] = percent
    if status is not None:
        info["status"] = status


def zip_study(study_id):
    output_path = os.path.join(STUDY_PATH, f"{study_id}.zip")
    tmp_path = output_path + ".part"

    with _lock_for(study_id):
        if os.path.exists(output_path):
            # Reusing an existing export: reset its age so cleanup keeps it
            # as long as the new share link is valid.
            os.utime(output_path)
            _set_progress(study_id, percent="100%")
            return

        os.makedirs(STUDY_PATH, exist_ok=True)
        url = f"{ORTHANC_URL}/studies/{study_id}/archive"

        # Download to a temporary file; only a complete download gets the final name,
        # so an interrupted download is never mistaken for a finished one.
        try:
            with requests.get(
                url, auth=(OR_USER, OR_PASS), stream=True, timeout=(10, 300)
            ) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length") or 0)
                downloaded = 0
                with open(tmp_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            percent = f"{min(100, downloaded * 100 / total):.0f}%"
                        else:
                            percent = f"{downloaded / 1024 / 1024:.1f} MB"
                        _set_progress(study_id, percent=percent)
            os.replace(tmp_path, output_path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


def create_synology_share(filepath):
    session = requests.Session()
    session.verify = SYNO_VERIFY_SSL

    login = session.get(
        f"{SYNOLOGY_URL}/webapi/auth.cgi",
        params={
            "api": "SYNO.API.Auth",
            "version": "6",
            "method": "login",
            "account": SYNO_USER,
            "passwd": SYNO_PASS,
            "session": "FileStation",
            "format": "sid",
        },
        timeout=30,
    )
    login_data = login.json()
    if not login_data.get("success"):
        raise RuntimeError(f"Synology login failed: {login_data.get('error')}")
    sid = login_data["data"]["sid"]

    try:
        # The link expires on the same day the file gets cleaned up
        expires = (date_cls.today() + timedelta(days=RETENTION_DAYS)).isoformat()
        share = session.get(
            f"{SYNOLOGY_URL}/webapi/entry.cgi",
            params={
                "api": "SYNO.FileStation.Sharing",
                "version": "3",
                "method": "create",
                "path": filepath,
                "date_expired": expires,
                "create_short_url": "true",
                "_sid": sid,
            },
            timeout=30,
        )
        share_data = share.json()
        if not share_data.get("success"):
            raise RuntimeError(f"Failed to create share link: {share_data.get('error')}")

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
                timeout=10,
            )
        except Exception:
            pass


def format_patient(patient):
    # DICOM names look like "Owner^Pet"; show only the last part
    if not patient:
        return ""
    return patient.split("^")[-1].strip()


def format_date(raw):
    # DICOM dates are YYYYMMDD; fall back to the raw value if it doesn't parse
    try:
        return datetime.strptime(raw or "", "%Y%m%d").strftime("%d.%m.%Y")
    except ValueError:
        return raw or ""


def build_email(to, url, patient, study_date):
    with open(MESSAGE_FILE, "r", encoding="utf-8") as f:
        template = f.read()

    # Escape the patient name: it comes from the URL and goes into HTML
    html_content = (
        template.replace("#PATIENT#", str(escape(format_patient(patient))))
        .replace("#LINK#", url)
        .replace("#DATUM#", format_date(study_date))
    )

    msg = EmailMessage()
    msg["Subject"] = "Link do CT/RTG preiskave"
    msg["From"] = SENDER_EMAIL
    msg["To"] = to
    msg.set_content(f"Link do CT/RTG preiskave: {url}")  # plain-text fallback
    msg.add_alternative(html_content, subtype="html")
    return msg


def send_email(msg):
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=60) as smtp:
        smtp.starttls()
        smtp.login(SENDER_EMAIL, SENDER_PASSWORD)
        refused = smtp.send_message(msg)
    if refused:
        raise RuntimeError(f"refused {list(refused)}")


def download_and_email(uuid, patient, study_date, email):
    _set_progress(uuid, percent="0%", status="downloading")

    # Stop on the first failure and report which step failed
    step = "downloading study"
    try:
        zip_study(uuid)
        step = "generating share link"
        _set_progress(uuid, status="sharing")
        url = create_synology_share(f"{SYNOLOGY_PATH}/{uuid}.zip")
        step = "sending email"
        _set_progress(uuid, status="sending")
        send_email(build_email(email, url, patient, study_date))
    except Exception as e:
        log.exception("Study %s: error %s", uuid, step)
        _set_progress(uuid, status=f"Error {step}: {e}")
        return

    log.info("Study %s: link sent to %s", uuid, email)
    _set_progress(uuid, status="done")


def cleanup_old_studies():
    """Delete exported zips (and leftover partial downloads) older than RETENTION_DAYS."""
    if not os.path.isdir(STUDY_PATH):
        return
    cutoff = time.time() - RETENTION_DAYS * 24 * 3600

    for name in os.listdir(STUDY_PATH):
        if not (name.endswith(".zip") or name.endswith(".zip.part")):
            continue
        path = os.path.join(STUDY_PATH, name)
        study_id = name.split(".", 1)[0]

        lock = _lock_for(study_id)
        # Skip studies that are currently being downloaded or reused
        if not lock.acquire(blocking=False):
            continue
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
                download_progress.pop(study_id, None)
                log.info("Cleanup: deleted %s", name)
        except OSError as e:
            log.warning("Cleanup: could not delete %s: %s", name, e)
        finally:
            lock.release()


def _cleanup_loop():
    while True:
        try:
            cleanup_old_studies()
        except Exception:
            log.exception("Cleanup failed")
        time.sleep(CLEANUP_INTERVAL_HOURS * 3600)


def start_cleanup_thread():
    threading.Thread(target=_cleanup_loop, daemon=True, name="cleanup").start()
    log.info(
        "Cleanup enabled: deleting studies older than %s days every %s h",
        RETENTION_DAYS,
        CLEANUP_INTERVAL_HOURS,
    )


@app.route("/error/<error>/<uuid>")
def error(error, uuid):
    return jsonify({"error": error, "uuid": uuid})


@app.route("/done/<uuid>")
def done(uuid):
    return f"EMAIL SENT {escape(uuid)}"


@app.route("/progress/<study_id>")
def progress(study_id):
    info = download_progress.get(study_id, {"percent": "0%", "status": "downloading"})
    return jsonify({"progress": info["percent"], "status": info["status"]})


@app.route("/export-url", methods=["GET", "POST"])
def export_url():
    uuid = (request.args.get("uuid") or "").strip().lower()
    patient = request.args.get("patient")
    patientid = request.args.get("patientid")
    study_date = request.args.get("date")

    # The ID ends up in a file path, so only accept real Orthanc IDs
    if not STUDY_ID_RE.match(uuid):
        return "Invalid study ID", 400

    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        if not EMAIL_RE.match(email):
            return "Invalid email address", 400

        threading.Thread(
            target=download_and_email,
            args=(uuid, patient, study_date, email),
            daemon=True,
        ).start()
        return render_template("progress.html", uuid=uuid)

    return render_template(
        "email_form.html",
        uuid=uuid,
        patient=" ".join((patient or "").split("^")).strip(),
        patientid=patientid,
        date=format_date(study_date),
    )


if __name__ == "__main__":
    start_cleanup_thread()
    app.run(host="0.0.0.0", port=5000)
