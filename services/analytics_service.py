from database.models import db, UserAnalytics, Submission, Enrollment, LearningProgress
from sqlalchemy import func


class AnalyticsService:
    

    @staticmethod
    def record_event(user_id, metric_type, metric_value=None, course_id=None, metadata=None):
        """Record an analytics event."""
        event = UserAnalytics(
            user_id=user_id,
            course_id=course_id,
            metric_type=metric_type,
            metric_value=metric_value,
            metadata_json=metadata,
        )
        db.session.add(event)
        db.session.commit()
        return event

    @staticmethod
    def get_student_performance(student_id):
        
        enrollments = Enrollment.query.filter_by(student_id=student_id).all()
        submissions = Submission.query.filter_by(student_id=student_id).all()

        # Learning progress
        progress_records = LearningProgress.query.filter_by(student_id=student_id).all()
        total_time = sum(p.time_spent_seconds for p in progress_records)
        completed_materials = sum(1 for p in progress_records if p.completed)

        # Exam performance
        graded = [s for s in submissions if s.total_score is not None]
        scores = [s.total_score for s in graded]

        return {
            'student_id': student_id,
            'courses_enrolled': len(enrollments),
            'active_courses': sum(1 for e in enrollments if e.status == 'active'),
            'total_exams': len(submissions),
            'graded_exams': len(graded),
            'average_score': round(sum(scores) / len(scores), 2) if scores else 0,
            'highest_score': max(scores) if scores else 0,
            'lowest_score': min(scores) if scores else 0,
            'total_study_hours': round(total_time / 3600, 1),
            'materials_completed': completed_materials,
            'flagged_exams': sum(1 for s in submissions if s.is_flagged),
        }

    @staticmethod
    def get_course_difficulty_analysis(course_id):
        """Analyze course difficulty based on exam performance."""
        from database.models import Exam, Question

        exams = Exam.query.filter_by(course_id=course_id).all()
        analysis = []

        for exam in exams:
            submissions = Submission.query.filter_by(exam_id=exam.id, status='graded').all()
            if not submissions:
                continue

            scores = [s.total_score for s in submissions if s.total_score is not None]
            pass_count = sum(1 for s in scores if s >= (exam.passing_marks or 50))

            analysis.append({
                'exam_title': exam.title,
                'avg_score': round(sum(scores) / len(scores), 2) if scores else 0,
                'pass_rate': round(pass_count / len(scores) * 100, 1) if scores else 0,
                'difficulty_rating': (
                    'Easy' if (sum(scores) / len(scores) if scores else 0) > 80
                    else 'Medium' if (sum(scores) / len(scores) if scores else 0) > 50
                    else 'Hard'
                ),
                'total_attempts': len(submissions),
            })

        return {'course_id': course_id, 'difficulty_analysis': analysis}
