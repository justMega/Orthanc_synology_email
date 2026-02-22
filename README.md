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

Create a .env file:

```txt

```
