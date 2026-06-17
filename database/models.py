from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


#USERS 

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    role = db.Column(db.Enum('admin', 'lecturer', 'student', name='user_roles'), nullable=False, default='student')
    profile_image = db.Column(db.String(255), nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)
    bio = db.Column(db.Text, nullable=True)
    face_encoding = db.Column(db.LargeBinary, nullable=True)  # For face auth
    share_contact = db.Column(db.Boolean, default=False)
    reset_token = db.Column(db.String(100), nullable=True, index=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    enrollments = db.relationship('Enrollment', backref='student', lazy='dynamic',
                                  foreign_keys='Enrollment.student_id')
    taught_courses = db.relationship('Course', backref='lecturer', lazy='dynamic',
                                     foreign_keys='Course.lecturer_id')
    submissions = db.relationship('Submission', backref='student', lazy='dynamic')
    analytics = db.relationship('UserAnalytics', backref='user', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'role': self.role,
            'profile_image': self.profile_image,
            'phone_number': self.phone_number,
            'bio': self.bio,
            'is_active': self.is_active,
            'share_contact': self.share_contact,
            'profile_complete': self._profile_completion(),
            'face_registered': bool(self.face_encoding),
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def _profile_completion(self):
        """Calculate profile completion percentage."""
        steps = [
            bool(self.profile_image),
            bool(self.phone_number),
            bool(self.bio),
            bool(self.face_encoding),
        ]
        return int(sum(steps) / len(steps) * 100)


# ──────────────────────────── COURSES ────────────────────────────

class Course(db.Model):
    __tablename__ = 'courses'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    lecturer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    ##admin_id = db.Column(db.Integer, db.Foreignkey('user_id'), nullable= True),
    category = db.Column(db.String(100), nullable=True)
    is_published = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    lectures = db.relationship('Lecture', backref='course', lazy='dynamic', cascade='all, delete-orphan')
    materials = db.relationship('Material', backref='course', lazy='dynamic', cascade='all, delete-orphan')
    exams = db.relationship('Exam', backref='course', lazy='dynamic', cascade='all, delete-orphan')
    enrollments = db.relationship('Enrollment', backref='course', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'title': self.title,
            'description': self.description,
            'lecturer_id': self.lecturer_id,
            'category': self.category,
            'is_published': self.is_published,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ──────────────────────────── ENROLLMENTS ────────────────────────────

class Enrollment(db.Model):
    __tablename__ = 'enrollments'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    enrolled_at = db.Column(db.DateTime, default=datetime.utcnow)
    progress = db.Column(db.Float, default=0.0)  # 0-100 percentage
    status = db.Column(db.Enum('active', 'completed', 'dropped', name='enrollment_status'), default='active')

    __table_args__ = (db.UniqueConstraint('student_id', 'course_id', name='unique_enrollment'),)

    def to_dict(self):
        return {
            'id': self.id,
            'student_id': self.student_id,
            'course_id': self.course_id,
            'enrolled_at': self.enrolled_at.isoformat() if self.enrolled_at else None,
            'progress': self.progress,
            'status': self.status,
        }


# ──────────────────────────── LECTURES ────────────────────────────

class Lecture(db.Model):
    __tablename__ = 'lectures'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=True)
    order_index = db.Column(db.Integer, default=0)
    duration_minutes = db.Column(db.Integer, nullable=True)
    is_published = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    materials = db.relationship('Material', backref='lecture', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'course_id': self.course_id,
            'title': self.title,
            'content': self.content,
            'order_index': self.order_index,
            'duration_minutes': self.duration_minutes,
            'is_published': self.is_published,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ──────────────────────────── MATERIALS ────────────────────────────

class Material(db.Model):
    __tablename__ = 'materials'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    lecture_id = db.Column(db.Integer, db.ForeignKey('lectures.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    file_type = db.Column(db.Enum('pdf', 'video', 'slide', 'document', 'other', name='material_types'), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer, nullable=True)  # bytes
    ai_summary = db.Column(db.Text, nullable=True)
    ai_flashcards = db.Column(db.JSON, nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'course_id': self.course_id,
            'lecture_id': self.lecture_id,
            'title': self.title,
            'file_type': self.file_type,
            'file_path': self.file_path,
            'file_size': self.file_size,
            'ai_summary': self.ai_summary,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
        }


# ──────────────────────────── EXAMS ────────────────────────────

class Exam(db.Model):
    __tablename__ = 'exams'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    exam_type = db.Column(db.Enum('quiz', 'midterm', 'final', 'assignment', name='exam_types'), default='quiz')
    duration_minutes = db.Column(db.Integer, nullable=False, default=60)
    total_marks = db.Column(db.Float, nullable=False, default=100)
    passing_marks = db.Column(db.Float, nullable=False, default=50)
    start_time = db.Column(db.DateTime, nullable=True)
    end_time = db.Column(db.DateTime, nullable=True)
    is_proctored = db.Column(db.Boolean, default=True)
    is_published = db.Column(db.Boolean, default=False)
    grades_released = db.Column(db.Boolean, default=False)
    shuffle_questions = db.Column(db.Boolean, default=True)
    allow_review = db.Column(db.Boolean, default=True)
    risk_threshold = db.Column(db.Integer, default=100)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    questions = db.relationship('Question', backref='exam', lazy='dynamic', cascade='all, delete-orphan')
    submissions = db.relationship('Submission', backref='exam', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'course_id': self.course_id,
            'title': self.title,
            'description': self.description,
            'exam_type': self.exam_type,
            'duration_minutes': self.duration_minutes,
            'total_marks': self.total_marks,
            'passing_marks': self.passing_marks,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'is_proctored': self.is_proctored,
            'is_published': self.is_published,
            'grades_released': self.grades_released,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ──────────────────────────── QUESTIONS ────────────────────────────

class Question(db.Model):
    __tablename__ = 'questions'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exams.id'), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.Enum('mcq', 'short_answer', 'essay', name='question_types'), nullable=False)
    options = db.Column(db.JSON, nullable=True)  # For MCQ: list of options
    correct_answer = db.Column(db.Text, nullable=True)
    marks = db.Column(db.Float, nullable=False, default=1)
    difficulty = db.Column(db.Enum('remember', 'understand', 'apply', 'analyze', 'evaluate', 'create',
                                    name='bloom_levels'), default='understand')
    order_index = db.Column(db.Integer, default=0)
    explanation = db.Column(db.Text, nullable=True)

    # Relationships
    answers = db.relationship('Answer', backref='question', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self, include_answer=False):
        data = {
            'id': self.id,
            'exam_id': self.exam_id,
            'question_text': self.question_text,
            'question_type': self.question_type,
            'options': self.options,
            'marks': self.marks,
            'difficulty': self.difficulty,
            'order_index': self.order_index,
        }
        if include_answer:
            data['correct_answer'] = self.correct_answer
            data['explanation'] = self.explanation
        return data


# ──────────────────────────── SUBMISSIONS ────────────────────────────

class Submission(db.Model):
    __tablename__ = 'submissions'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exams.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    submitted_at = db.Column(db.DateTime, nullable=True)
    total_score = db.Column(db.Float, nullable=True)
    is_graded = db.Column(db.Boolean, default=False)
    is_flagged = db.Column(db.Boolean, default=False)
    risk_score = db.Column(db.Integer, default=0)
    status = db.Column(db.Enum('in_progress', 'submitted', 'graded', name='submission_status'), default='in_progress')
    face_verified = db.Column(db.Boolean, default=False)

    # Relationships
    answers = db.relationship('Answer', backref='submission', lazy='dynamic', cascade='all, delete-orphan')
    violations = db.relationship('Violation', backref='submission', lazy='dynamic', cascade='all, delete-orphan')

    __table_args__ = (db.UniqueConstraint('exam_id', 'student_id', name='unique_submission'),)

    def to_dict(self):
        return {
            'id': self.id,
            'exam_id': self.exam_id,
            'student_id': self.student_id,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
            'total_score': self.total_score,
            'is_graded': self.is_graded,
            'is_flagged': self.is_flagged,
            'risk_score': self.risk_score,
            'status': self.status,
            'face_verified': self.face_verified,
        }


# ──────────────────────────── ANSWERS ────────────────────────────

class Answer(db.Model):
    __tablename__ = 'answers'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('submissions.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    answer_text = db.Column(db.Text, nullable=True)
    selected_option = db.Column(db.Integer, nullable=True)  # For MCQ
    is_correct = db.Column(db.Boolean, nullable=True)
    score = db.Column(db.Float, nullable=True)
    ai_feedback = db.Column(db.Text, nullable=True)
    answered_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'submission_id': self.submission_id,
            'question_id': self.question_id,
            'answer_text': self.answer_text,
            'selected_option': self.selected_option,
            'is_correct': self.is_correct,
            'score': self.score,
            'ai_feedback': self.ai_feedback,
        }


# ──────────────────────────── VIOLATIONS ────────────────────────────

class Violation(db.Model):
    __tablename__ = 'violations'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('submissions.id'), nullable=False)
    violation_type = db.Column(db.Enum(
        'multiple_faces', 'no_face', 'eye_gaze', 'head_pose',
        'lip_movement', 'phone_detected', 'tab_switch',
        'background_person', 'other',
        name='violation_types'
    ), nullable=False)
    severity = db.Column(db.Integer, default=5)  # Risk points added
    description = db.Column(db.Text, nullable=True)
    screenshot_path = db.Column(db.String(500), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'submission_id': self.submission_id,
            'violation_type': self.violation_type,
            'severity': self.severity,
            'description': self.description,
            'screenshot_path': self.screenshot_path,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
        }


# ──────────────────────────── USER ANALYTICS ────────────────────────────

class UserAnalytics(db.Model):
    __tablename__ = 'user_analytics'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=True)
    metric_type = db.Column(db.String(50), nullable=False)  # e.g. 'login', 'material_view', 'quiz_attempt'
    metric_value = db.Column(db.Float, nullable=True)
    metadata_json = db.Column(db.JSON, nullable=True)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'course_id': self.course_id,
            'metric_type': self.metric_type,
            'metric_value': self.metric_value,
            'metadata_json': self.metadata_json,
            'recorded_at': self.recorded_at.isoformat() if self.recorded_at else None,
        }


# ──────────────────────────── LEARNING PROGRESS ────────────────────────────

class LearningProgress(db.Model):
    __tablename__ = 'learning_progress'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    material_id = db.Column(db.Integer, db.ForeignKey('materials.id'), nullable=False)
    progress_percent = db.Column(db.Float, default=0.0)
    time_spent_seconds = db.Column(db.Integer, default=0)
    has_opened = db.Column(db.Boolean, default=False)
    first_opened_at = db.Column(db.DateTime, nullable=True)
    last_page = db.Column(db.Integer, default=0)
    total_pages = db.Column(db.Integer, default=0)
    last_accessed = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed = db.Column(db.Boolean, default=False)

    __table_args__ = (db.UniqueConstraint('student_id', 'material_id', name='unique_learning_progress'),)

    def to_dict(self):
        return {
            'id': self.id,
            'student_id': self.student_id,
            'material_id': self.material_id,
            'progress_percent': self.progress_percent,
            'time_spent_seconds': self.time_spent_seconds,
            'has_opened': self.has_opened,
            'first_opened_at': self.first_opened_at.isoformat() if self.first_opened_at else None,
            'last_page': self.last_page,
            'total_pages': self.total_pages,
            'last_accessed': self.last_accessed.isoformat() if self.last_accessed else None,
            'completed': self.completed,
        }


# ──────────────────────────── LIVE CLASSES ────────────────────────────

class LiveClass(db.Model):
    __tablename__ = 'live_classes'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    meeting_link = db.Column(db.String(500), nullable=False)
    platform = db.Column(db.String(50), default='zoom')  # zoom, meet, teams, custom
    scheduled_at = db.Column(db.DateTime, nullable=False)
    duration_minutes = db.Column(db.Integer, default=60)
    is_unlocked = db.Column(db.Boolean, default=False)  # lecturer can manually unlock early
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship
    course = db.relationship('Course', backref=db.backref('live_classes', lazy='dynamic', cascade='all, delete-orphan'))

    def to_dict(self):
        return {
            'id': self.id,
            'course_id': self.course_id,
            'title': self.title,
            'description': self.description,
            'meeting_link': self.meeting_link,
            'platform': self.platform,
            'scheduled_at': self.scheduled_at.isoformat() if self.scheduled_at else None,
            'duration_minutes': self.duration_minutes,
            'is_unlocked': self.is_unlocked,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
