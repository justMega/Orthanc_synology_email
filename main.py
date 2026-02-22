from markupsafe import escape
from flask import Flask, request, jsonify, render_template
import smtplib
from email.message import EmailMessage
import requests
import urllib.request
import os
from dotenv import load_dotenv
import threading

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

def zip_study(study_id):
	global download_progress
	output_path = f"{STUDY_PATH}/{study_id}.zip"
	if os.path.exists(output_path):
		download_progress[study_id] = {"percent": "100%", "status": "downloading"}
		return
		
	url = f"{ORTHANC_URL}/studies/{study_id}/archive"

	def download_progress_treck(block_num, block_size, total_size):
		downloaded = block_num * block_size
		if total_size > 0:
			percent = min(100, downloaded * 100 / total_size)
			download_progress[study_id] = {"percent": f"{percent}%", "status": "downloading"}
			#print(f"\rDownloading... {percent:.1f}% ({downloaded} / {total_size} bytes)", end="")
		else:
			download_progress[study_id] = {"percent": f"{downloaded} bytes", "status":"downloading"}
			#print(f"\rDownloading... {downloaded} bytes", end="")  # fallback if total unknown

	# Setup basic authentication
	password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
	password_mgr.add_password(None, ORTHANC_URL, OR_USER, OR_PASS)

	handler = urllib.request.HTTPBasicAuthHandler(password_mgr)
	opener = urllib.request.build_opener(handler)
	urllib.request.install_opener(opener)

	# Download file
	urllib.request.urlretrieve(url, output_path, reporthook=download_progress_treck)


def create_synology_share(filepath):
	#print("file", filepath)
	session = requests.Session()

	# Login
	login_params = {
		"api": "SYNO.API.Auth",
		"version": "6",
		"method": "login",
		"account": SYNO_USER,
		"passwd": SYNO_PASS,
		"session": "FileStation",
		"format": "sid"
	}

	login = session.get(
		f"{SYNOLOGY_URL}/webapi/auth.cgi",
		params=login_params,
		verify=False
	)
	#print("SID", login)
	sid = login.json()["data"]["sid"]
	# Create share link
	share_params = {
		"api": "SYNO.FileStation.Sharing",
		"version": "3",
		"method": "create",
		"path": filepath,
		"create_short_url": "true",
		"_sid":sid
	}

	share = session.get(
		f"{SYNOLOGY_URL}/webapi/entry.cgi",
		params=share_params,
		verify=False
	)

	share_data = share.json()
	#print("RES", share_data)
	if not share_data["success"]:
		raise Exception("Failed to create share link")

	return share_data["data"]["links"][0]["url"]


def download_and_email(uuid, patient, patientid, date, email):
	global download_progress
	zip_study(uuid)
	
	try:
		url = create_synology_share(f"{SYNOLOGY_PATH}/{uuid}.zip")
	except Exception as e:
		download_progress[uuid]["status"] = f"Error generation share link: {e}"
		
	# Create email
	msg = EmailMessage()
	msg["Subject"] = "Link do CT preiskave"
	msg["From"] = SENDER_EMAIL
	msg["To"] = email
	
	file_path = "message.txt"
	with open(file_path, "r", encoding="utf-8") as f:
		content = f.read()
	
	msg.set_content(content.replace("#PATIENT#", patient).replace("#LINK#", url))

	# Send email
	try:
		with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
			smtp.login(SENDER_EMAIL, SENDER_PASSWORD)
			smtp.send_message(msg)
	except Exception as e:
		download_progress[uuid]["status"] = f"Error sending email: {e}"
		
	download_progress[uuid]["status"] = "done"

@app.route("/error/<error>/<uuid>")
def error(error, uuid):
	return jsonify({"error": error, "uuid": uuid})

@app.route("/done/<uuid>")
def done(uuid):
	return f"EMAIL SENT {escape(uuid)}"

@app.route("/progress/<study_id>")
def progress(study_id):
	#print({"progress": download_progress[study_id]["percent"], "status": download_progress[study_id]["status"]})
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
		thread = threading.Thread(target=download_and_email, args=(uuid, patient, patientid, date, email))
		thread.start()
		return render_template("progress.html", uuid=uuid)

	return render_template(
		"email_form.html",
		uuid=uuid,
		patient=patient,
		patientid=patientid,
		date=date
	)

if __name__ == "__main__":
	app.run(host='0.0.0.0', port=5000)
