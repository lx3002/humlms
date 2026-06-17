import pytest
from lms.database.models import(
    User,
    Course,
    Enrollment,
    Lecture,
    Material,
    Exam,
    Question,
    Submission,
    Answer,
    Violation,
    UserAnalytics,
    LearningProgress,
    LiveClass
)

class Create_User(pytest):