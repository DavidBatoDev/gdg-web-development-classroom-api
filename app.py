from flask import Flask, jsonify, request, Response
from flask_cors import CORS
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import os
import pickle
from werkzeug.serving import WSGIRequestHandler
import socket
import re

WSGIRequestHandler.protocol_version = "HTTP/1.1"

# Initialize Flask app
app = Flask(__name__)
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = False
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
    """Authenticate and return the Google API service."""
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
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
    - state (optional): Filter submissions by their state (e.g., TURNED_IN, CREATED).

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


@app.route('/grades', methods=['POST'])
def update_student_grades():
    """
    Update grades of all students for a specific assignment in a course.
    Add a new column for assignment state and update points accordingly.

    Query Parameters:
    - course_id: The ID of the course.
    - assignment_id: The ID of the assignment.

    Example: /grades?course_id=<course_id>&assignment_id=<assignment_id>&spreadsheet_id=<spreadsheet_id>
    """
    course_id = request.args.get('course_id')
    assignment_id = request.args.get('assignment_id')

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
        spreadsheet_id = request.args.get('spreadsheet_id')
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
                if state != 'Done':
                    grade = submission.get('studentSubmissions', [{}])[0].get('assignedGrade', 0)
                    if grade > 0:  # Only add grade and set "Done" if grade is greater than 0
                        row[points_column_index] = int(row[points_column_index]) + grade
                        row[state_column_index] = 'Done'

            updated_data.append(row)

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





if __name__ == '__main__':
    app.run(debug=True)



