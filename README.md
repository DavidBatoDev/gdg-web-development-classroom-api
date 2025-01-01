# Email Sender Flask API

This is a Flask-based API that allows you to send emails via an SMTP server. It uses Python and the `waitress` WSGI server to handle incoming requests. The application is deployed using Docker and hosted on Render. Once deployed you can use this to send emails via API and use that api across your projects!

## Features

- API endpoint to send emails (`/send-email`).
- Supports sending emails with a `subject`, `body`, and list of `to_emails`.
- Built with Flask, and uses `EmailSender` class to send emails via SMTP.

## Getting Started

### Prerequisites

- Python 3.x
- Docker (for containerization)
- An SMTP email service (e.g., Gmail)

### Local Development

Follow the steps below to run the email sender application locally.

#### 1. Clone the Repository

```bash
git clone https://github.com/your-username/email_sender_flask.git
cd email_sender_flask
```
#### 2. Create a Virtual Environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
```
#### 3. Install Dependencies
```bash
pip install -r requirements.txt
```
#### 4. Set Environment Variables
Create a .env file in the root directory with the following content, replacing the placeholders with your email settings:

```bash
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=465
EMAIL_USER=your-email@gmail.com
EMAIL_PASSWORD=your-email-password
```
Make sure to include .env in your .gitignore file to avoid sharing sensitive information.

#### 5. Run the Application
To run the Flask app locally, use:

```bash
python email_api/email_api.py
```

Or use waitress to run the app:
```bash
Copy code
waitress-serve --port=5000 email_api.email_api:app
```
Now, you can send a POST request to http://localhost:5000/send-email to test the email sending functionality.

### Using Postman or cURL to Send Email
#### 1. Send a POST Request to /send-email:
- URL: http://localhost:5000/send-email
- Method: POST
- Headers: Content-Type: application/json
- Body (raw, JSON format):
```json
{
    "subject": "Test Email",
    "body": "This is a test email.",
    "to_emails": ["recipient@example.com"]
}
```
### 2. Python Example using requests Library
If you want to send a test email via Python, use the following script:

```python
import requests

# URL of the Flask application
url = "http://localhost:5000/send-email"

# Email data to be sent
data = {
    "subject": "Test Email",
    "body": "This is a test email.",
    "to_emails": ["recipient@example.com"]
}

# Sending the POST request to the API
response = requests.post(url, json=data)

# Checking the response
if response.status_code == 200:
    print("Email sent successfully!")
else:
    print(f"Failed to send email. Status code: {response.status_code}")
    print(response.json())
```

### Docker Deployment
#### 1. Build the Docker Image
```bash
docker build -t flask-email-sender .
```

#### 2. Run the Docker Container
```bash
docker run -d -p 5000:5000 --name flask-email-sender-container flask-email-sender
```
This will run your Flask app inside a Docker container. The application will be accessible at http://localhost:5000.

### Deploy on Render
Follow these steps to deploy the app on Render:

#### 1. Create an Account: Sign up at Render.
#### 2. Create a New Web Service:
- Choose Docker as the deployment option.
- Link your GitHub repository with the Render app.
- Select the correct branch. (default is "main")
#### 3. Deploy the Service: Click on Deploy and wait for Render to build and start the application.
Once your service is live, you can send requests to the provided Render URL (e.g., https://your-app-name.onrender.com/send-email).

### Notes
- Ensure you have a valid SMTP server configured in your .env file.
- The email sending functionality is built using the smtplib Python module and can be extended to support other features (e.g., attachments, HTML emails).
- You can scale and manage your application easily with Render's free tier.
### Troubleshooting
- If you face any issues with Docker, make sure you have correctly configured your .env file and Dockerfile.
- Ensure your email credentials are correct and not blocked by your email provider (e.g., Gmail might block sign-ins from new locations).

```vbnet
### Key sections explained:

- **Prerequisites**: Make sure you have the necessary tools and services.
- **Local Development**: Instructions for running the app locally, including dependencies and environment setup.
- **Using Postman or cURL**: Instructions to test the `/send-email` API endpoint with Postman or cURL.
- **Docker Deployment**: Steps to build and run the app using Docker.
- **Render Deployment**: How to deploy the app on Render using Docker.

Feel free to update the repository URL and any personal or project-specific details before committing it to GitHub.
```
