from flask import Flask, jsonify, request, Response
from flask_cors import CORS
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import os
import pickle

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Google Classroom API Scopes
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/classroom.rosters.readonly',
    'https://www.googleapis.com/auth/classroom.courses.readonly',
    'https://www.googleapis.com/auth/classroom.profile.emails'
]

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

@app.route('/leaderboard', methods=['GET'])
def get_leaderboard():
    """
    Fetch leaderboard for a specific course, accumulating grades for all assignments.

    Query Parameter:
    - course_id: The ID of the course to fetch the leaderboard from.

    Example: /leaderboard?course_id=<course_id>
    """
    course_id = request.args.get('course_id')
    if not course_id:
        return jsonify({'error': 'course_id query parameter is required'}), 400

    service = get_google_service()
    leaderboard = {}

    try:
        coursework = service.courses().courseWork().list(courseId=course_id).execute()
        for work in coursework.get('courseWork', []):
            assignment_id = work['id']
            submissions = service.courses().courseWork().studentSubmissions().list(
                courseId=course_id, courseWorkId=assignment_id).execute()

            for submission in submissions.get('studentSubmissions', []):
                student_id = submission['userId']
                if 'assignedGrade' in submission:
                    grade = submission['assignedGrade']
                    if student_id not in leaderboard:
                        leaderboard[student_id] = 0
                    leaderboard[student_id] += grade

        # Convert leaderboard dictionary to a sorted list
        sorted_leaderboard = sorted(
            leaderboard.items(), key=lambda x: x[1], reverse=True
        )
        return jsonify(sorted_leaderboard)
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

    service = get_google_service()
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

    service = get_google_service()

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


# Push Spreadsheet Data to Google Classroom
# Update download_students to push to Google Sheets
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
    spreadsheet_id = request.args.get('spreadsheet_id')  # Spreadsheet ID is required

    if not course_id or not spreadsheet_id:
        return jsonify({'error': 'course_id and spreadsheet_id query parameters are required'}), 400

    classroom_service = get_google_service('classroom', 'v1')  # Initialize Classroom API service
    sheets_service = get_google_service('sheets', 'v4')  # Initialize Sheets API service
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




if __name__ == '__main__':
    app.run(debug=True)



