from flask import Blueprint, request, jsonify, render_template
from flask_jwt_extended import jwt_required
from database.models import (
    db, User, Course, Enrollment, Exam, Submission,
    Violation, UserAnalytics, Answer, Question, LearningProgress, Material
)
from utils.security import role_required, get_identity
from sqlalchemy import func
from datetime import datetime, timedelta

analytics_bp = Blueprint('analytics', __name__)


def _score_trend(scores):
    if len(scores) < 2:
        return 'stable'
    midpoint = len(scores) // 2
    first_avg = sum(scores[:midpoint]) / max(1, len(scores[:midpoint]))
    second_avg = sum(scores[midpoint:]) / max(1, len(scores[midpoint:]))
    delta = second_avg - first_avg
    if delta > 3:
        return 'improving'
    if delta < -3:
        return 'declining'
    return 'stable'



@analytics_bp.route('/analytics')
@jwt_required()
@role_required('student', 'lecturer', 'admin')
def analytics_page():
    return render_template('analytics.html')


# ──────────────── STUDENT ANALYTICS ────────────────

@analytics_bp.route('/api/analytics/student/overview', methods=['GET'])
@jwt_required()
@role_required('student')
def student_overview():
    identity = get_identity()
    student_id = identity['id']

    enrollments = Enrollment.query.filter_by(student_id=student_id, status='active').count()
    submissions = Submission.query.filter_by(student_id=student_id).all()

    total_exams = len(submissions)
    avg_score = 0
    if submissions:
        scored = [s.total_score for s in submissions if s.total_score is not None]
        avg_score = sum(scored) / len(scored) if scored else 0

    flagged_count = sum(1 for s in submissions if s.is_flagged)

    return jsonify({
        'enrolled_courses': enrollments,
        'total_exams_taken': total_exams,
        'average_score': round(avg_score, 2),
        'flagged_exams': flagged_count,
    })


# ──────────────── COURSE ANALYTICS (Lecturer) ────────────────

@analytics_bp.route('/api/analytics/course/<int:course_id>', methods=['GET'])
@jwt_required()
@role_required('lecturer', 'admin')
def course_analytics(course_id, student_id):
    identity = get_identity()

    if identity['role'] == 'lecturer':
        course = Course.query.filter_by(id=course_id, lecturer_id=identity['id']).first()
        if not course:
            return jsonify({'error': 'Course not found'}), 404

    total_students = Enrollment.query.filter_by(course_id=course_id,student_id= student_id, status='active').count()

    # Exam performance
    exams = Exam.query.filter_by(course_id=course_id).all()
    exam_stats = []
    for exam in exams:
        subs = Submission.query.filter_by(exam_id=exam.id, status='graded').all()
        scores = [s.total_score for s in subs if s.total_score is not None]
        exam_stats.append({
            'exam_id': exam.id,
            'exam_title': exam.title,
            'total_submissions': len(subs),
            'average_score': round(sum(scores) / len(scores), 2) if scores else 0,
            'highest_score': max(scores) if scores else 0,
            'lowest_score': min(scores) if scores else 0,
            'pass_rate': round(
                sum(1 for s in scores if s >= (exam.passing_marks or 50)) / len(scores) * 100, 1
            ) if scores else 0,
        })

    return jsonify({
        'course_id': course_id,
        'total_students': total_students,
        'exam_stats': exam_stats,
    })


@analytics_bp.route('/api/analytics/course/<int:course_id>/student-insights', methods=['GET'])
@jwt_required()
@role_required('lecturer', 'admin')
def course_student_insights(course_id):
    identity = get_identity()

    if identity['role'] == 'lecturer' or 'admin':
        course = Course.query.filter_by(id=course_id, lecturer_id=identity['id'], admin_id = identity['id']).first()
        if not course:
            return jsonify({'error': 'Course not found'}), 404
    else:
        course = Course.query.get(course_id)
        if not course:
            return jsonify({'error': 'Course not found'}), 404

    exams = Exam.query.filter_by(course_id=course_id).all()
    exam_ids = [e.id for e in exams]

    students = db.session.query(User).join(
        Enrollment, Enrollment.student_id == User.id
    ).filter(
        Enrollment.course_id == course_id,
        Enrollment.status == 'active',
        User.role == 'student'
    ).all()

    material_ids = [m.id for m in Material.query.filter_by(course_id=course_id).all()]

    student_rows = []
    class_scores = []
    class_study_hours = []
    at_risk_count = 0

    for student in students:
        submissions = Submission.query.filter(
            Submission.student_id == student.id,
            Submission.exam_id.in_(exam_ids) if exam_ids else False
        ).order_by(Submission.submitted_at.asc(), Submission.started_at.asc()).all() if exam_ids else []

        graded_scores = [s.total_score for s in submissions if s.total_score is not None]
        avg_score = round(sum(graded_scores) / len(graded_scores), 1) if graded_scores else 0
        trend = _score_trend(graded_scores)

        progress_rows = LearningProgress.query.filter(
            LearningProgress.student_id == student.id,
            LearningProgress.material_id.in_(material_ids) if material_ids else False
        ).all() if material_ids else []

        materials_read = sum(1 for p in progress_rows if p.has_opened or (p.progress_percent or 0) > 0)
        total_materials = len(material_ids)
        read_rate = round((materials_read / total_materials) * 100, 1) if total_materials else 0
        study_hours = round(sum((p.time_spent_seconds or 0) for p in progress_rows) / 3600, 2)
        avg_material_progress = round(
            sum((p.progress_percent or 0) for p in progress_rows) / len(progress_rows), 1
        ) if progress_rows else 0

        score_history = [
            {
                'exam_title': (s.exam.title if s.exam else 'Exam'),
                'score': s.total_score,
                'submitted_at': s.submitted_at.isoformat() if s.submitted_at else None,
            }
            for s in submissions if s.total_score is not None
        ]

        if avg_score < 50 and len(graded_scores) > 0:
            at_risk_count += 1

        if len(graded_scores) > 0:
            class_scores.append(avg_score)
        class_study_hours.append(study_hours)

        student_rows.append({
            'student_id': student.id,
            'student_name': f'{student.first_name} {student.last_name}',
            'email': student.email,
            'exam_attempts': len(submissions),
            'graded_exams': len(graded_scores),
            'average_score': avg_score,
            'trend': trend,
            'study_hours': study_hours,
            'materials_read': materials_read,
            'materials_total': total_materials,
            'read_rate': read_rate,
            'avg_material_progress': avg_material_progress,
            'score_history': score_history,
        })

    pass_rate = 0
    if class_scores:
        pass_rate = round(sum(1 for s in class_scores if s >= 50) / len(class_scores) * 100, 1)

    summary = {
        'total_students': len(students),
        'class_average_score': round(sum(class_scores) / len(class_scores), 1) if class_scores else 0,
        'class_pass_rate': pass_rate,
        'average_study_hours': round(sum(class_study_hours) / len(class_study_hours), 2) if class_study_hours else 0,
        'at_risk_students': at_risk_count,
    }

    return jsonify({
        'course_id': course_id,
        'course_title': course.title,
        'summary': summary,
        'students': sorted(student_rows, key=lambda x: (x['average_score'] if x['graded_exams'] else -1), reverse=True),
    })


@analytics_bp.route('/api/analytics/course/<int:course_id>/materials-reading', methods=['GET'])
@jwt_required()
@role_required('lecturer', 'admin')
def course_material_reading_analytics(course_id):
    identity = get_identity()

    if identity['role'] == 'lecturer':
        course = Course.query.filter_by(id=course_id, lecturer_id=identity['id']).first()
        if not course:
            return jsonify({'error': 'Course not found'}), 404
    else:
        course = Course.query.get(course_id)
        if not course:
            return jsonify({'error': 'Course not found'}), 404

    students = db.session.query(User).join(
        Enrollment, Enrollment.student_id == User.id
    ).filter(
        Enrollment.course_id == course_id,
        Enrollment.status == 'active',
        User.role == 'student'
    ).all()

    materials = Material.query.filter_by(course_id=course_id).order_by(Material.uploaded_at.desc()).all()
    if not materials or not students:
        return jsonify({'course_id': course_id, 'records': [], 'summary': []})

    student_ids = [s.id for s in students]
    material_ids = [m.id for m in materials]

    progress_rows = LearningProgress.query.filter(
        LearningProgress.student_id.in_(student_ids),
        LearningProgress.material_id.in_(material_ids)
    ).all()
    progress_map = {(p.student_id, p.material_id): p for p in progress_rows}

    records = []
    for material in materials:
        for student in students:
            p = progress_map.get((student.id, material.id))
            has_read = bool(p and (p.has_opened or (p.progress_percent or 0) > 0 or (p.time_spent_seconds or 0) > 0))
            records.append({
                'material_id': material.id,
                'material_title': material.title,
                'student_id': student.id,
                'student_name': f"{student.first_name} {student.last_name}",
                'has_read': has_read,
                'last_page': p.last_page if p else 0,
                'total_pages': p.total_pages if p else 0,
                'progress_percent': round(float(p.progress_percent or 0), 1) if p else 0,
                'time_spent_minutes': round((p.time_spent_seconds or 0) / 60, 1) if p else 0,
                'last_accessed': p.last_accessed.isoformat() if (p and p.last_accessed) else None,
            })

    summary = []
    for material in materials:
        material_records = [r for r in records if r['material_id'] == material.id]
        read_count = sum(1 for r in material_records if r['has_read'])
        summary.append({
            'material_id': material.id,
            'material_title': material.title,
            'students_read': read_count,
            'students_total': len(material_records),
            'read_rate': round((read_count / len(material_records)) * 100, 1) if material_records else 0,
        })

    return jsonify({'course_id': course_id, 'records': records, 'summary': summary})


# ──────────────── MALPRACTICE REPORT ────────────────

@analytics_bp.route('/api/analytics/malpractice/<int:exam_id>', methods=['GET'])
@jwt_required()
@role_required('lecturer', 'admin')
def malpractice_report(exam_id):
    identity = get_identity()

    exam = Exam.query.get(exam_id)
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404

    if identity['role'] == 'lecturer':
        course = Course.query.filter_by(id=exam.course_id, lecturer_id=identity['id']).first()
        if not course:
            return jsonify({'error': 'Unauthorized'}), 403

    flagged_submissions = Submission.query.filter_by(exam_id=exam_id, is_flagged=True).all()

    report = []
    for sub in flagged_submissions:
        student = User.query.get(sub.student_id)
        violations = Violation.query.filter_by(submission_id=sub.id).all()

        # Group violations by type
        violation_summary = {}
        for v in violations:
            vtype = v.violation_type
            if vtype not in violation_summary:
                violation_summary[vtype] = {'count': 0, 'total_severity': 0}
            violation_summary[vtype]['count'] += 1
            violation_summary[vtype]['total_severity'] += v.severity

        report.append({
            'student_id': sub.student_id,
            'student_name': f"{student.first_name} {student.last_name}" if student else 'Unknown',
            'risk_score': sub.risk_score,
            'total_violations': len(violations),
            'violation_summary': violation_summary,
            'screenshots': [v.screenshot_path for v in violations if v.screenshot_path],
        })

    return jsonify({
        'exam_id': exam_id,
        'exam_title': exam.title,
        'total_flagged': len(flagged_submissions),
        'reports': report,
    })


# ──────────────── ENGAGEMENT ANALYTICS ────────────────

@analytics_bp.route('/api/analytics/engagement/<int:course_id>', methods=['GET'])
@jwt_required()
@role_required('lecturer', 'admin')
def engagement_analytics(course_id):
    identity = get_identity()

    if identity['role'] == 'lecturer':
        course = Course.query.filter_by(id=course_id, lecturer_id=identity['id']).first()
        if not course:
            return jsonify({'error': 'Course not found'}), 404

    # Material engagement
    progress_records = db.session.query(
        LearningProgress.material_id,
        func.count(LearningProgress.id).label('views'),
        func.avg(LearningProgress.progress_percent).label('avg_progress'),
        func.sum(LearningProgress.time_spent_seconds).label('total_time'),
    ).join(
        LearningProgress.material_id == LearningProgress.material_id
    ).filter(
        LearningProgress.material_id.in_(
            db.session.query(func.distinct(LearningProgress.material_id))
        )
    ).group_by(LearningProgress.material_id).all()

    engagement = []
    for record in progress_records:
        engagement.append({
            'material_id': record.material_id,
            'total_views': record.views,
            'avg_progress': round(float(record.avg_progress or 0), 1),
            'total_time_hours': round((record.total_time or 0) / 3600, 1),
        })

    return jsonify({'course_id': course_id, 'engagement': engagement})


# ──────────────── PERFORMANCE PREDICTION ────────────────

@analytics_bp.route('/api/analytics/predict/<int:student_id>/<int:course_id>', methods=['GET'])
@jwt_required()
@role_required('lecturer', 'admin')
def predict_performance(student_id, course_id):
    """Simple performance prediction based on historical data."""
    submissions = Submission.query.filter_by(student_id=student_id, status='graded').all()
    course_exams = Exam.query.filter_by(course_id=course_id).all()
    course_exam_ids = [e.id for e in course_exams]

    course_submissions = [s for s in submissions if s.exam_id in course_exam_ids]
    scores = [s.total_score for s in course_submissions if s.total_score is not None]

    if len(scores) < 2:
        return jsonify({'prediction': None, 'message': 'Not enough data for prediction'})

    # Simple trend-based prediction
    avg_score = sum(scores) / len(scores)
    recent_avg = sum(scores[-3:]) / len(scores[-3:])  # Last 3 exams

    trend = 'improving' if recent_avg > avg_score else 'declining' if recent_avg < avg_score else 'stable'
    predicted_score = round(recent_avg * 1.05 if trend == 'improving' else recent_avg * 0.95, 1)

    return jsonify({
        'student_id': student_id,
        'course_id': course_id,
        'average_score': round(avg_score, 2),
        'recent_average': round(recent_avg, 2),
        'trend': trend,
        'predicted_next_score': predicted_score,
        'risk_level': 'high' if predicted_score < 40 else 'medium' if predicted_score < 60 else 'low',
    })


# ──────────────── ADMIN DASHBOARD STATS ────────────────

@analytics_bp.route('/api/analytics/admin/overview', methods=['GET'])
@jwt_required()
@role_required('admin')
def admin_overview():
    total_users = User.query.count()
    total_students = User.query.filter_by(role='student').count()
    total_lecturers = User.query.filter_by(role='lecturer').count()
    total_courses = Course.query.count()
    total_exams = Exam.query.count()
    total_submissions = Submission.query.count()
    flagged_submissions = Submission.query.filter_by(is_flagged=True).count()

    return jsonify({
        'total_users': total_users,
        'total_students': total_students,
        'total_lecturers': total_lecturers,
        'total_courses': total_courses,
        'total_exams': total_exams,
        'total_submissions': total_submissions,
        'flagged_submissions': flagged_submissions,
    })
