# Orthanc Study Email Sharing Service

A lightweight Flask-based web application designed to run in Docker on Synology NAS and integrate with Orthanc to enable simple and secure email sharing of DICOM studies.
Designed for small clinics, veterinary practices, and private imaging centers using Orthanc on Synology NAS.

# Purpose

This service acts as a companion application to Orthanc.
It allows users to:

- ✅ Select a study from Orthanc
- ✅ Generate a secure share link
- ✅ Send study access via email
- ✅ Share links expire and exported studies are auto-deleted after `RETENTION_DAYS` (default 14)
- ✅ Use non gmail email (set `SMTP_HOST` / `SMTP_PORT`)

# Orthanc Integration

To integrate this application into Orthanc, you need to add a custom button to the study page in Orthanc Explorer 2.

Add the following configuration to your `orthanc.json`. Then restart orthanc server for the changes to take effect. 

Replace:

- \<SERVER_IP\> with your Synology NAS IP address
- \<APP_PORT\> with the port you assign to this application

```json
 "OrthancExplorer2": {
   "Enable": true,
   "IsDefaultOrthancUI": false,
   "UiOptions" : {
   "CustomButtons": {
       "study": [
           {
               "HttpMethod": "GET",
               "Id": "email-link-button",
               "Tooltip": "Send study info via email",
               "Target": "_blank",
               "Icon": "bi bi-link-45deg",
               "Url": "http://<SERVER_IP>:<APP_PORT>/export-url?uuid={UUID}&patient={PatientName}&patientid={PatientID}&date={StudyDate}"
          }
       ],
       "series": [],
       "instance": [],
       "bulk-studies": []
     }
   }
},
```

# Environment Variables

Create a .env file in the project root and fill in your data.

⚠️ Leave STUDY_PATH unchanged.

For Gmail, you must use an App Password (not your regular account password).
More information:
https://support.google.com/accounts/answer/185833?hl=en

```txt
SENDER_EMAIL=your email
SENDER_PASSWORD=email password

SYNOLOGY_URL=https://<SERVER_IP>:5001
SYNO_USER=example_admin
SYNO_PASS=example_password

ORTHANC_URL=http://<ORTHANC_IP>:<ORTHANC_PORT>
OR_USER=example_orthanc
OR_PASS=example_orthanc_pass

STUDY_PATH=etc/data 
SYNOLOGY_PATH=/path/to/share/folder/on/synology

# Optional (defaults shown)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SYNO_VERIFY_SSL=false
RETENTION_DAYS=14
CLEANUP_INTERVAL_HOURS=6
MESSAGE_FILE=message.txt
```

# Automatic cleanup

Exported study zips in `STUDY_PATH` are deleted automatically once they are older than
`RETENTION_DAYS` (default 14 days). The check runs at startup and then every
`CLEANUP_INTERVAL_HOURS`. Synology share links are created with the same expiration date,
so recipients never get a link to a file that no longer exists. Re-sending a study resets its age.

# Email message

The app allows for a custom email message to be specified. Make a `message.txt` and define your message. 

Use the placeholders:

- #LINK# -> Will be replaced with the generated share link
- #PATIENT# -> Will be replaced with the patient name
- #DATUM# -> Will be replaced with the study date (DD.MM.YYYY)

Example:
```txt
Dear owner.
We are sending you the link #LINK# to your pet's #PATIENT# CT scan

Best regards
clinc 
```

# Docker install

1. Copy Repository

Copy the repository files to a folder on your Synology NAS.

2. SSH Into Synology
```txt
ssh your_user@<SERVER_IP>
cd /path/to/repository
```

3. Build Docker Image
```txt
sudo docker build -t orthanc_synology_email .
```

4. Run Container

Replace:
- /path_to_share_folder with your Synology shared folder path
- \<PORT\> with the port you want to expose
```txt
sudo docker run -d --env-file .env -v /path_to_share_folder:/app/etc/data -p <PORT>:5000 orthanc_synology_email
```

