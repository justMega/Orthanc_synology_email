# Orthanc Study Email Sharing Service

A lightweight Flask-based web application designed to run in Docker on Synology NAS and integrate with Orthanc to enable simple and secure email sharing of DICOM studies.
Designed for small clinics, veterinary practices, and private imaging centers using Orthanc on Synology NAS.

# Purpose

This service acts as a companion application to Orthanc.
It allows users to:

- Select a study from Orthanc

- Generate a secure share link

- Send study access via email

- Optionally set expiration for shared links (WIP)

# Orthanc Integration

In order for to integrate this application in orthanc we will first need to app a custom button to the study page that points to this app add the folowing to the `orthanc.json`. Replace the <SERVER_IP> with the synology nas ip and the <APP_PORT> with the port that you will later assign to this aplication.

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

Create a .env file and fill in your data leave the STUDY_PATH as is. For gmail the password has to be an app pasword more about here: https://support.google.com/accounts/answer/185833?hl=en

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
SYNOLOGY_PATH=/path to share folder on synology
```

# Email message

The app allows for a custom email message to be specified. Make a `message.txt` and define your message. You have to use `#LINK#` where you wish for your link to be inserted and `#PATIENT#` for the patient name.

```txt
Dear owner.
We are sending you the link #LINK# to your pet's #PATIENT# CT scan

Best regards
clinc 
```

# Docker install

First copy the repository files to a folder on the synology nas. Then ssh in to synology nas and cd to the repository folder. Lastly run the two commands. 

```txt
sudo docker build -t orthanc_synology_email .
```

```txt
sudo docker run -d --env-file .env -v /path_to_share_folder:/app/etc/data -p <PORT>:5000 orthanc_synology_nas
```

