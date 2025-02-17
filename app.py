from flask import Flask, jsonify, request, Response, render_template
from flask_cors import CORS
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import os
import pickle
from werkzeug.serving import WSGIRequestHandler
import socket
import re
import tempfile
import json
from flask import session, redirect, url_for
from flask_session import Session

WSGIRequestHandler.protocol_version = "HTTP/1.1"


# Initialize Flask app
app = Flask(__name__)

# Ensure secret key is set
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = False
app.config['SESSION_TYPE'] = 'filesystem'  # For simple deployments
Session(app)
CORS(app)

socket.setdefaulttimeout(300)  # Set timeout to 300 seconds
# Google Classroom API Scopes
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',  # For Sheets API
    'https://www.googleapis.com/auth/classroom.rosters.readonly',  # For student data
    'https://www.googleapis.com/auth/classroom.profile.emails',  # For student emails
    'https://www.googleapis.com/auth/classroom.courses.readonly',  # For course data
    'https://www.googleapis.com/auth/classroom.coursework.me',  # Access coursework
    'https://www.googleapis.com/auth/classroom.coursework.students'  # Access student submissions
]

######################## Utility Functions ########################
def get_google_service(api_name, api_version):
    """Authenticate and return the Google API service using session-stored credentials."""
    creds = None
    
    # Try to get credentials from session
    if 'token_pickle' in session:
        try:
            token_data = bytes.fromhex(session['token_pickle'])
            creds = pickle.loads(token_data)
        except Exception:
            session.pop('token_pickle')
    
    # If credentials need refresh
    if creds and not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                # Update session with refreshed credentials
                session['token_pickle'] = pickle.dumps(creds).hex()
            except Exception:
                session.pop('token_pickle')
                creds = None
    
    # No valid credentials found, redirect to upload/auth
    if not creds:
        # We can't do a redirect here since this might be called from various places
        # Instead, we'll raise an exception that can be caught by the route handlers
        raise Exception("No valid credentials. Please upload credentials.json first in Manage Credentials Page.")
    
    return build(api_name, api_version, credentials=creds)

def extract_attachments(attachments):
    """
    Extract links or file references from attachments.
    """
    extracted = []
    for attachment in attachments:
        if 'driveFile' in attachment:
            extracted.append({
                'type': 'driveFile',
                'title': attachment['driveFile']['title'],
                'link': attachment['driveFile']['alternateLink']
            })
        elif 'link' in attachment:
            extracted.append({
                'type': 'link',
                'title': attachment['link'].get('title', 'Untitled Link'),
                'link': attachment['link']['url']
            })
        elif 'form' in attachment:
            extracted.append({
                'type': 'form',
                'title': attachment['form']['title'],
                'link': attachment['form']['formUrl']
            })
    return extracted

# Add these imports to your existing imports
from werkzeug.utils import secure_filename
import os

# For File Upload
UPLOAD_FOLDER = '.'  # Current directory where app.py is located
ALLOWED_EXTENSIONS = {'json'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


####################### FRONTEND ROUTES #######################
# Frontend Routes
@app.route('/')
def home():
    """Home page with navigation to different features"""
    return render_template('home.html')

@app.route('/manage-courses')
def manage_courses():
    """Page to view and manage courses"""
    try:
        service = get_google_service('classroom', 'v1')
        courses = service.courses().list().execute().get('courses', [])
        # Filter courses by name if needed
        filtered_courses = [course for course in courses if course['name'] == "GDG `25 Web Development"]
        return render_template('courses.html', courses=filtered_courses)
    except Exception as e:
        if 'credentials' in str(e).lower():
            return redirect(url_for('manage_credentials'))
        return f"Error: {str(e)}"

@app.route('/manage-students/<course_id>')
def manage_students(course_id):
    """Page to view and manage students in a course"""
    service = get_google_service('classroom', 'v1')
    # Get course details
    course = service.courses().get(id=course_id).execute()
    
    # Get students with pagination
    students = []
    page_token = None
    while True:
        students_response = service.courses().students().list(courseId=course_id, pageToken=page_token).execute()
        students.extend(students_response.get('students', []))
        page_token = students_response.get('nextPageToken')
        if not page_token:
            break
    
    return render_template('students.html', course=course, students=students)

@app.route('/manage-assignments/<course_id>')
def manage_assignments(course_id):
    """Page to view and manage assignments"""
    service = get_google_service('classroom', 'v1')
    course = service.courses().get(id=course_id).execute()
    assignments = service.courses().courseWork().list(courseId=course_id).execute().get('courseWork', [])
    return render_template('assignments.html', course=course, assignments=assignments)

@app.route('/view-submissions/<course_id>/<assignment_id>')
def view_submissions(course_id, assignment_id):
    """Page to view submissions for an assignment"""
    service = get_google_service('classroom', 'v1')
    course = service.courses().get(id=course_id).execute()
    assignment = service.courses().courseWork().get(courseId=course_id, id=assignment_id).execute()
    submissions = service.courses().courseWork().studentSubmissions().list(
        courseId=course_id,
        courseWorkId=assignment_id
    ).execute().get('studentSubmissions', [])
    return render_template('submissions.html', 
                         course=course, 
                         assignment=assignment, 
                         submissions=submissions)

@app.route('/manage-spreadsheet')
def manage_spreadsheet():
    """Page to manage Google Spreadsheet operations"""
    return render_template('spreadsheet.html')

@app.route('/credentials', methods=['GET', 'POST'])
def manage_credentials():
    """Handle credentials.json file upload for each user"""
    message = None

    message = None
    
    # Create a dictionary to track file presence
    files = {}
    
    # Check if credentials.json is in session
    if 'credentials_json' in session:
        files['credentials.json'] = True
    
    # Check if token.pickle is in session
    if 'token_pickle' in session:
        files['token.pickle'] = True
    
    if request.method == 'POST':
        # Check if a file was uploaded
        if 'credentials' not in request.files:
            message = {'type': 'error', 'text': 'No file selected'}
            return render_template('credentials.html', message=message, files=files)
        
        file = request.files['credentials']
        
        # Check if user selected a file
        if file.filename == '':
            message = {'type': 'error', 'text': 'No file selected'}
            return render_template('credentials.html', message=message)
        
        # Check if file is allowed and secure
        if file and allowed_file(file.filename):
            try:
                # Instead of saving to disk, we'll store in session
                file_content = file.read().decode('utf-8')
                
                # Validate that it's proper JSON and has expected structure
                try:
                    creds_json = json.loads(file_content)
                    if 'installed' not in creds_json and 'web' not in creds_json:
                        raise ValueError("Invalid credentials format")
                except Exception as e:
                    message = {'type': 'error', 'text': f'Invalid credentials format: {str(e)}'}
                    return render_template('credentials.html', message=message)
                
                # Store in session
                session['credentials_json'] = file_content
                
                # Remove any existing token
                if 'token_pickle' in session:
                    session.pop('token_pickle')
                
                message = {'type': 'success', 'text': 'Credentials uploaded successfully. Please authenticate the application.'}
                return redirect(url_for('authenticate_google'))
                
            except Exception as e:
                message = {'type': 'error', 'text': f'Error processing file: {str(e)}'}
        else:
            message = {'type': 'error', 'text': 'Invalid file type. Please upload a .json file'}
    
    return render_template('credentials.html', message=message)


######################## API Endpoints ########################
@app.route('/courses', methods=['GET'])
def get_courses():
    """
    Fetch all courses or a specific course based on a query parameter.

    Query Parameters:
    - course_name (optional): Filter courses by name.
    """
    service = get_google_service('classroom', 'v1')  # Initialize Classroom API service
    course_name_filter = request.args.get('course_name', '').lower()  # Optional query parameter

    try:
        # Fetch all courses
        results = service.courses().list().execute()
        courses = results.get('courses', [])
        
        # If a filter is provided, filter courses by name
        if course_name_filter:
            courses = [course for course in courses if course_name_filter in course['name'].lower()]
        
        return jsonify(courses)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/students', methods=['GET'])
def get_all_students():
    """
    Fetch all students in a course (fetch all pages in one endpoint).

    Query Parameter:
    - course_id: The ID of the course.

    Example: /students?course_id=<course_id>
    """
    course_id = request.args.get('course_id')
    if not course_id:
        return jsonify({'error': 'course_id query parameter is required'}), 400

    service = get_google_service('classroom', 'v1')  # Initialize Classroom API service
    all_students = []
    page_token = None

    try:
        while True:
            # Fetch students from the current page
            response = service.courses().students().list(
                courseId=course_id,
                pageToken=page_token
            ).execute()

            # print the student response
            print(response)

            # Add students from this page to the total list
            all_students.extend([
                {
                    'id': student['userId'],
                    'name': student['profile']['name']['fullName'],
                    'email': student['profile'].get('emailAddress', 'No email available'),
                }
                for student in response.get('students', [])
            ])

            # Check for the next page
            page_token = response.get('nextPageToken')
            if not page_token:
                break  # Exit the loop if there are no more pages

        # Return all students as a single response
        return jsonify(all_students)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/submissions', methods=['GET'])
def get_submissions_with_attachments():
    """
    Fetch all student submissions for a specific assignment, including attachments,
    student names, and emails.

    Query Parameters:
    - course_id: The ID of the course.
    - assignment_id: The ID of the assignment.
    - state (optional): Filter submissions by their state (e.g., TURNED_IN, CREATED, NEW).

    Example: /submissions?course_id=<course_id>&assignment_id=<assignment_id>&state=TURNED_IN
    """
    course_id = request.args.get('course_id')
    assignment_id = request.args.get('assignment_id')
    state_filter = request.args.get('state')  # Optional query parameter

    if not course_id or not assignment_id:
        return jsonify({'error': 'course_id and assignment_id query parameters are required'}), 400

    service = get_google_service('classroom', 'v1') 
    all_submissions = []
    student_map = {}  # Map of userId to student name and email
    page_token = None

    try:
        # Fetch all students in the course and build a mapping of userId to name and email
        while True:
            students_response = service.courses().students().list(
                courseId=course_id, pageToken=page_token
            ).execute()

            for student in students_response.get('students', []):
                student_map[student['userId']] = {
                    'name': student['profile']['name']['fullName'],
                    'email': student['profile'].get('emailAddress', 'No email available')  # Use safe fallback
                }

            page_token = students_response.get('nextPageToken')
            if not page_token:
                break

        # Fetch all submissions for the assignment
        page_token = None  # Reset page token for submissions
        while True:
            response = service.courses().courseWork().studentSubmissions().list(
                courseId=course_id,
                courseWorkId=assignment_id,
                pageToken=page_token
            ).execute()

            # Extract details and attachments
            for submission in response.get('studentSubmissions', []):
                if not state_filter or submission.get('state') == state_filter:
                    user_id = submission['userId']
                    student_details = student_map.get(user_id, {'name': 'Unknown', 'email': 'Unknown'})
                    all_submissions.append({
                        'id': submission['id'],
                        'userId': user_id,
                        'name': student_details['name'],
                        'email': student_details['email'],
                        'state': submission.get('state', 'UNKNOWN'),  # TURNED_IN, RETURNED, etc.
                        'assignedGrade': submission.get('assignedGrade', None),  # Grade if available
                        'attachments': extract_attachments(submission.get('assignmentSubmission', {}).get('attachments', []))
                    })

            # Check for the next page
            page_token = response.get('nextPageToken')
            if not page_token:
                break  # Exit the loop if there are no more pages

        return jsonify(all_submissions)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/assignments', methods=['GET'])
def get_assignments():
    """
    Fetch all assignments (coursework) for a specific course.

    Query Parameters:
    - course_id: The ID of the course.

    Example: /assignments?course_id=<course_id>
    """
    course_id = request.args.get('course_id')

    if not course_id:
        return jsonify({'error': 'course_id query parameter is required'}), 400

    service = get_google_service('classroom', 'v1') 

    try:
        # Fetch all assignments for the course
        response = service.courses().courseWork().list(courseId=course_id).execute()
        assignments = [
            {
                'id': coursework['id'],
                'title': coursework['title'],
                'description': coursework.get('description', 'No description provided'),
                'dueDate': coursework.get('dueDate', 'No due date'),
                'creationTime': coursework['creationTime'],
                'alternateLink': coursework['alternateLink']
            }
            for coursework in response.get('courseWork', [])
        ]
        return jsonify(assignments)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/push_students_to_sheet', methods=['POST'])
def push_students_to_sheet():
    """
    Fetch all students in a course and push their details to an existing Google Spreadsheet.

    Query Parameter:
    - course_id: The ID of the course.
    - spreadsheet_id: The ID of the Google Spreadsheet.

    Example: /push_students_to_sheet?course_id=<course_id>&spreadsheet_id=<spreadsheet_id>
    """
    course_id = request.args.get('course_id')
    spreadsheet_id = request.args.get('spreadsheet_id') 
    if not course_id or not spreadsheet_id:
        return jsonify({'error': 'course_id and spreadsheet_id query parameters are required'}), 400

    classroom_service = get_google_service('classroom', 'v1')  
    sheets_service = get_google_service('sheets', 'v4')  
    all_students = []
    page_token = None

    try:
        while True:
            # Fetch students from the current page
            response = classroom_service.courses().students().list(
                courseId=course_id,
                pageToken=page_token
            ).execute()

            # Add students from this page to the total list
            all_students.extend([
                [
                    student['userId'],
                    student['profile']['name']['fullName'].replace(',', ' '),
                    student['profile'].get('emailAddress', 'No email available'),
                    0,  # Initial points set to 0
                    'Cadet'  # Default rank
                ]
                for student in response.get('students', [])
            ])

            # Check for the next page
            page_token = response.get('nextPageToken')
            if not page_token:
                break  # Exit the loop if there are no more pages

        # Fetch existing data from the spreadsheet
        existing_data = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range='Sheet1!A2:F'
        ).execute().get('values', [])

        existing_ids = {row[0] for row in existing_data}  # Extract existing student IDs

        # Filter out students who are already in the spreadsheet
        new_students = [student for student in all_students if student[0] not in existing_ids]

        # Assign ranks based on points
        for student in new_students:
            points = student[3]  # Points column (initially 0)
            if points >= 600:
                student[4] = 'Senior'
            elif points >= 400:
                student[4] = 'Junior'

        if new_students:
            # Append new students to the spreadsheet
            sheets_service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range='Sheet1!A2',
                valueInputOption='RAW',
                insertDataOption='INSERT_ROWS',
                body={'values': new_students}
            ).execute()

        # Update column names if not already set
        headers = [['google_classroom_Id', 'name', 'email', 'points', 'rank']]
        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range='Sheet1!A1:E1',
            valueInputOption='RAW',
            body={'values': headers}
        ).execute()

        return jsonify({'message': 'Student data successfully pushed to the spreadsheet with ranks.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/update-grades', methods=['POST'])
def update_student_grades():
    """
    Update grades of all students for a specific assignment in a course.
    Add a new column for assignment state and update points accordingly.

    Query Parameters:
    - course_id: The ID of the course.
    - assignment_id: The ID of the assignment.
    - spreadsheet_id: the ID of the spreadsheet

    Example: /update-grades?course_id=<course_id>&assignment_id=<assignment_id>&spreadsheet_id=<spreadsheet_id>
    """
    course_id = request.args.get('course_id')
    assignment_id = request.args.get('assignment_id')
    spreadsheet_id = request.args.get('spreadsheet_id')

    if not course_id or not assignment_id:
        return jsonify({'error': 'course_id and assignment_id query parameters are required'}), 400

    service = get_google_service('classroom', 'v1')  # Initialize Classroom API service
    sheets_service = get_google_service('sheets', 'v4')  # Initialize Sheets API service

    try:
        # Fetch the assignment details to get the assignment name
        assignment = service.courses().courseWork().get(
            courseId=course_id, id=assignment_id
        ).execute()
        assignment_name = assignment['title']
        cleaned_name = re.sub(r'[^\w\s]', '', assignment_name)  # Remove special characters
        cleaned_name = cleaned_name.replace(' ', '_')  # Replace spaces with underscores
        truncated_name = cleaned_name[:50]  # Limit to 50 characters
        state_column_name = f"{truncated_name}_state"

        # Fetch existing spreadsheet data
        sheet_data = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range='Sheet1!A1:Z'
        ).execute()

        rows = sheet_data.get('values', [])
        headers = rows[0] if rows else []
        data = rows[1:] if len(rows) > 1 else []

        # Ensure the new state column exists
        if state_column_name not in headers:
            headers.append(state_column_name)

        state_column_index = headers.index(state_column_name)
        points_column_index = headers.index('points') if 'points' in headers else len(headers)

        # Update rows with grades and states
        updated_data = []
        for row in data:
            user_id = row[0]
            # Ensure the row has enough columns for the state column
            while len(row) <= state_column_index:
                row.append('')

            # Fetch the student's submission
            submission = service.courses().courseWork().studentSubmissions().list(
                courseId=course_id, courseWorkId=assignment_id, userId=user_id
            ).execute()

            if submission:
                state = row[state_column_index]
                if not state:
                    grade = submission.get('studentSubmissions', [{}])[0].get('assignedGrade', 0)
                    if grade > 0:  # Only add grade and set "Done" if grade is greater than 0
                        row[points_column_index] = int(row[points_column_index]) + grade
                        row[state_column_index] = grade

            updated_data.append(row)
        
        return jsonify({'message': 'debugging'}), 200

        # Update spreadsheet with new data
        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range='Sheet1!A1',
            valueInputOption='RAW',
            body={'values': [headers] + updated_data}
        ).execute()

        return jsonify({'message': f'Grades updated and {state_column_name} column added.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/push_attendance', methods=['POST'])
def push_attendance():
    """
    Push attendance grades from another sheet to Sheet1.
    Creates a new column in Sheet1 named after the source sheet
    and adds points based on email matches.

    If the column already exists, it won't be recreated,
    and any existing cell values in that column won't be overwritten.
    
    Query Parameters:
    - spreadsheet_id: The ID of the Google Spreadsheet
    - sheet_name: Name of the sheet containing attendance data

    Example: /push_attendance?spreadsheet_id=<spreadsheet_id>&sheet_name=<sheet_name>
    """
    spreadsheet_id = request.args.get('spreadsheet_id')
    sheet_name = request.args.get('sheet_name')

    if not spreadsheet_id or not sheet_name:
        return jsonify({'error': 'spreadsheet_id and sheet_name query parameters are required'}), 400

    sheets_service = get_google_service('sheets', 'v4')

    try:
        # 1) Fetch existing data from "Sheet1"
        sheet1_data = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range='Sheet1!A1:Z'
        ).execute()
        sheet1_rows = sheet1_data.get('values', [])
        if not sheet1_rows:
            return jsonify({'error': 'Sheet1 is empty'}), 400

        sheet1_headers = sheet1_rows[0]

        # 2) Ensure we have a 'points' column
        try:
            points_index = sheet1_headers.index('points')
        except ValueError:
            return jsonify({'error': '"points" column not found in Sheet1'}), 400

        # 3) Find or create the attendance column
        if sheet_name in sheet1_headers:
            # Column already exists; reuse its index
            new_column_index = sheet1_headers.index(sheet_name)
        else:
            # Column does not exist; append it
            sheet1_headers.append(sheet_name)
            new_column_index = len(sheet1_headers) - 1

        # 4) Fetch data from the attendance sheet
        attendance_data = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f'{sheet_name}!A1:Z'
        ).execute()
        attendance_rows = attendance_data.get('values', [])
        if not attendance_rows:
            return jsonify({'error': f'Sheet "{sheet_name}" is empty'}), 400

        attendance_headers = attendance_rows[0]

        # 5) Find the email column in the attendance sheet
        attendance_email_index = None
        for possible_header in ['email', 'Email', 'USERNAME', 'Username']:
            try:
                attendance_email_index = attendance_headers.index(possible_header)
                break
            except ValueError:
                continue

        if attendance_email_index is None:
            return jsonify({'error': 'No email/username column found in attendance sheet'}), 400

        # 6) Create a set of emails from the attendance sheet
        attendance_emails = {
            row[attendance_email_index].lower().strip()
            for row in attendance_rows[1:]
            if len(row) > attendance_email_index and row[attendance_email_index].strip()
        }

        # 7) Update "Sheet1" data
        updated_rows = [sheet1_headers]  # Start with updated headers
        for row in sheet1_rows[1:]:
            # Pad the row if needed (in case we just added a new column)
            while len(row) < len(sheet1_headers):
                row.append('')

            # Get the row's email
            email_col_index = None
            try:
                email_col_index = sheet1_headers.index('email')
            except ValueError:
                return jsonify({'error': 'Email column not found in Sheet1'}), 400

            email = row[email_col_index].lower().strip()

            # If this cell is already filled, don't overwrite
            if not row[new_column_index]:
                # Only add points/mark attendance if the user is in the attendance list
                if email in attendance_emails:
                    current_points = int(row[points_index]) if row[points_index].isdigit() else 0
                    row[points_index] = str(current_points + 20)
                    row[new_column_index] = 20

            updated_rows.append(row)

        # 8) Write everything back to "Sheet1"
        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range='Sheet1!A1',
            valueInputOption='RAW',
            body={'values': updated_rows}
        ).execute()

        # Count how many new attendances were marked (rows that have "20" in the new column)
        # We skip the header row with [1:]
        matches_found = sum(1 for row in updated_rows[1:] if len(row) > new_column_index and row[new_column_index] == '20')

        return jsonify({
            'message': f'Successfully updated attendance from {sheet_name}',
            'points_added': '20 points added for each new matching email',
            'matches_found': matches_found
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@app.route('/authenticate_google')
def authenticate_google():
    """Authenticate with Google using stored credentials"""
    if 'credentials_json' not in session:
        return redirect(url_for('manage_credentials'))
    
    # Create a temporary credentials.json file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_file:
        temp_file.write(session['credentials_json'])
        temp_file_path = temp_file.name
    
    try:
        # Set up the OAuth flow
        flow = InstalledAppFlow.from_client_secrets_file(temp_file_path, SCOPES)
        # This will redirect to Google's auth page automatically
        flow.redirect_uri = url_for('oauth2callback', _external=True)
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        
        # Store the state in the session
        session['state'] = state
        
        # Clean up
        os.unlink(temp_file_path)
        
        return redirect(authorization_url)
    except Exception as e:
        # Clean up on error
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        return f"Error during authentication: {str(e)}"

@app.route('/oauth2callback')
def oauth2callback():
    """Handle the OAuth 2.0 callback from Google"""
    if 'credentials_json' not in session:
        return redirect(url_for('manage_credentials'))
    
    # Create temporary credentials file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_file:
        temp_file.write(session['credentials_json'])
        temp_file_path = temp_file.name
    
    try:
        # Set up flow with the saved state
        flow = InstalledAppFlow.from_client_secrets_file(
            temp_file_path, SCOPES, state=session.get('state'))
        flow.redirect_uri = url_for('oauth2callback', _external=True)
        
        # Exchange authorization code for credentials
        flow.fetch_token(authorization_response=request.url)
        
        # Store credentials in session
        credentials = flow.credentials
        session['token_pickle'] = pickle.dumps(credentials).hex()
        
        # Clean up
        os.unlink(temp_file_path)
        
        return redirect(url_for('home'))
    except Exception as e:
        # Clean up on error
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        return f"Error completing authentication: {str(e)}"


if __name__ == '__main__':
    app.run(debug=True)



