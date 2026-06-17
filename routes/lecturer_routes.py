import os
import re
from flask import Blueprint, request, jsonify, render_template, current_app
from flask_jwt_extended import jwt_required
from database.models import (
    db, Course, Lecture, Material, Exam, Question, Submission,
    Answer, Enrollment, Violation, User, LiveClass, LearningProgress
)
from utils.security import role_required, get_identity
from utils.helpers import paginate_query, save_uploaded_file, allowed_file
from datetime import datetime, timedelta

lecturer_bp = Blueprint('lecturer', __name__)

ASSESSMENT_TOTAL_MARKS = {
    'cat1': 30,
    'cat2': 30,
    'assignment': 30,
    'main_exam': 70,
}

ASSESSMENT_LABELS = {
    'cat1': 'CAT 1',
    'cat2': 'CAT 2',
    'assignment': 'Assignment',
    'main_exam': 'Main Exam',
}


def map_assessment_type_to_exam_type(assessment_type):
    mapping = {
        'cat1': 'quiz',
        'cat2': 'midterm',
        'assignment': 'assignment',
        'main_exam': 'final',
    }
    return mapping.get((assessment_type or '').lower(), 'quiz')


def infer_assessment_type(exam):
    description = (exam.description or '').strip()
    marker = '[assessment:'
    if description.lower().startswith(marker):
        end = description.find(']')
        if end > len(marker):
            parsed = description[len(marker):end].strip().lower()
            if parsed in ASSESSMENT_TOTAL_MARKS:
                return parsed

    if exam.exam_type == 'final':
        return 'main_exam'
    if exam.exam_type == 'midterm':
        return 'cat2'
    if exam.exam_type == 'assignment':
        return 'assignment'
    return 'cat1'


def build_description_with_assessment_marker(description, assessment_type):
    base = (description or '').strip()
    marker = f'[assessment:{assessment_type}]'
    if not base:
        return marker
    if base.lower().startswith('[assessment:'):
        end = base.find(']')
        if end != -1:
            base = base[end + 1:].strip()
    return f'{marker} {base}'.strip()


def parse_manual_questions(raw_text, default_type='short_answer', default_difficulty='understand'):
    blocks = [b.strip() for b in re.split(r'\n\s*\n', raw_text or '') if b.strip()]
    questions = []

    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue

        question_lines = []
        options = []
        correct_answer = None
        marks = None
        qtype = None

        for line in lines:
            lower = line.lower()
            if lower.startswith('type:'):
                qtype = line.split(':', 1)[1].strip().lower()
                continue
            if lower.startswith('marks:'):
                raw_marks = line.split(':', 1)[1].strip()
                try:
                    marks = float(raw_marks)
                except ValueError:
                    marks = None
                continue
            if lower.startswith('answer:'):
                correct_answer = line.split(':', 1)[1].strip()
                continue

            if re.match(r'^[A-Ha-h][\).\-\s]+', line):
                opt_text = re.sub(r'^[A-Ha-h][\).\-\s]+', '', line).strip()
                if opt_text:
                    options.append(opt_text)
                continue

            if not question_lines and re.match(r'^(q\d+|\d+[\).])\s+', line, flags=re.I):
                line = re.sub(r'^(q\d+|\d+[\).])\s+', '', line, flags=re.I)
            question_lines.append(line)

        question_text = ' '.join(question_lines).strip()
        if not question_text:
            continue

        if not qtype:
            qtype = 'mcq' if options else default_type
        if qtype not in {'mcq', 'short_answer', 'essay'}:
            qtype = default_type

        if qtype == 'mcq' and options:
            if correct_answer is not None:
                raw_answer = str(correct_answer).strip()
                if re.match(r'^[A-Ha-h]$', raw_answer):
                    correct_answer = ord(raw_answer.upper()) - ord('A')
                else:
                    match_index = next((i for i, opt in enumerate(options) if opt.lower() == raw_answer.lower()), None)
                    if match_index is not None:
                        correct_answer = match_index
        elif qtype != 'mcq':
            if isinstance(correct_answer, str) and not correct_answer.strip():
                correct_answer = None

        questions.append({
            'question_text': question_text,
            'question_type': qtype,
            'options': options or None,
            'correct_answer': correct_answer,
            'marks': marks,
            'difficulty': default_difficulty,
        })

    return questions


def get_existing_assessment_types(course_id):
    exams = Exam.query.filter_by(course_id=course_id).all()
    return {infer_assessment_type(exam) for exam in exams}


def validate_assessment_type_availability(course_id, assessment_type):
    if assessment_type not in {'cat1', 'cat2'}:
        return None

    existing_assessment_types = get_existing_assessment_types(course_id)
    if assessment_type in existing_assessment_types:
        return f"{ASSESSMENT_LABELS[assessment_type]} is already done for this course."

    return None


# ──────────────── PAGE ROUTES ────────────────

@lecturer_bp.route('/lecturer/dashboard')
@jwt_required()
@role_required('lecturer', 'admin')
def dashboard():
    return render_template('lecturer_panel.html')


@lecturer_bp.route('/lecturer/exams/manual')
@jwt_required()
@role_required('lecturer')
def manual_exam_builder():
    identity = get_identity()
    courses = Course.query.filter_by(lecturer_id=identity['id']).order_by(Course.title.asc()).all()
    selected_course_id = request.args.get('course_id', type=int)
    return render_template(
        'manual_exam.html',
        courses=[c.to_dict() for c in courses],
        selected_course_id=selected_course_id,
    )


@lecturer_bp.route('/lecturer/materials/<int:material_id>/read')
@jwt_required()
@role_required('lecturer')
def read_material_lecturer(material_id):
    identity = get_identity()
    material = Material.query.get(material_id)
    if not material:
        return render_template('lecturer_panel.html')

    course = Course.query.filter_by(id=material.course_id, lecturer_id=identity['id']).first()
    if not course:
        return render_template('lecturer_panel.html')

    if material.file_type != 'pdf':
        return render_template('lecturer_panel.html')

    material_data = material.to_dict()
    material_data['file_url'] = f"/uploads/{material.file_path}"
    material_data['course_title'] = material.course.title if material.course else None

    return render_template(
        'material_reader.html',
        material_data=material_data,
        progress_data=None,
        back_url='/lecturer/dashboard?view=materials',
    )


@lecturer_bp.route('/lecturer/classes')
@jwt_required()
@role_required('lecturer', 'admin')
def classes_page():
    return render_template('classes.html')


@lecturer_bp.route('/lecturer/profile')
@jwt_required()
@role_required('lecturer', 'admin')
def profile_page():
    return render_template('lecturer_profile.html')




@lecturer_bp.route('/api/lecturer/courses', methods=['GET'])
@jwt_required()
@role_required('lecturer')
def get_my_courses():
    identity = get_identity()
    page = request.args.get('page', 1, type=int)
    courses = Course.query.filter_by(lecturer_id=identity['id'])
    return jsonify(paginate_query(courses, page))


@lecturer_bp.route('/api/lecturer/courses', methods=['POST'])
@jwt_required()
@role_required('lecturer', 'admin')
def create_course():
    identity = get_identity()
    data = request.get_json()

    if not data.get('title') or not data.get('code'):
        return jsonify({'error': 'Title and code are required'}), 400

    if Course.query.filter_by(code=data['code']).first():
        return jsonify({'error': 'Course code already exists'}), 400

    course = Course(
        code=data['code'],
        title=data['title'],
        description=data.get('description', ''),
        lecturer_id=identity['id'],
        category=data.get('category', ''),
        is_published=data.get('is_published', False),
    )
    db.session.add(course)
    db.session.commit()
    return jsonify({'message': 'Course created', 'course': course.to_dict()}), 201


@lecturer_bp.route('/api/lecturer/courses/<int:course_id>', methods=['PUT'])
@jwt_required()
@role_required('lecturer', 'admin')
def update_course(course_id):
    identity = get_identity()
    course = Course.query.filter_by(id=course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Course not found'}), 404

    data = request.get_json()
    for field in ['title', 'description', 'category', 'is_published']:
        if field in data:
            setattr(course, field, data[field])

    db.session.commit()
    return jsonify({'message': 'Course updated', 'course': course.to_dict()})


@lecturer_bp.route('/api/lecturer/courses/<int:course_id>', methods=['DELETE'])
@jwt_required()
@role_required('lecturer', 'admin')
def delete_course(course_id):
    identity = get_identity()
    course = Course.query.filter_by(id=course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Course not found'}), 404

    db.session.delete(course)
    db.session.commit()
    return jsonify({'message': 'Course deleted'})


# ──────────────── LECTURE MANAGEMENT ────────────────

@lecturer_bp.route('/api/lecturer/courses/<int:course_id>/lectures', methods=['GET'])
@jwt_required()
@role_required('lecturer', 'admin')
def get_lectures(course_id):
    identity = get_identity()
    course = Course.query.filter_by(id=course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Course not found'}), 404

    lectures = Lecture.query.filter_by(course_id=course_id).order_by(Lecture.order_index).all()
    return jsonify({'lectures': [l.to_dict() for l in lectures]})


@lecturer_bp.route('/api/lecturer/courses/<int:course_id>/lectures', methods=['POST'])
@jwt_required()
@role_required('lecturer', 'admin')
def create_lecture(course_id):
    identity = get_identity()
    course = Course.query.filter_by(id=course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Course not found'}), 404

    data = request.get_json()
    lecture = Lecture(
        course_id=course_id,
        title=data.get('title', 'Untitled Lecture'),
        content=data.get('content', ''),
        order_index=data.get('order_index', 0),
        duration_minutes=data.get('duration_minutes'),
        is_published=data.get('is_published', False),
    )
    db.session.add(lecture)
    db.session.commit()
    return jsonify({'message': 'Lecture created', 'lecture': lecture.to_dict()}), 200


@lecturer_bp.route('/api/lecturer/lectures/<int:lecture_id>', methods=['PUT'])
@jwt_required()
@role_required('lecturer', 'admin')
def update_lecture(lecture_id):
    identity = get_identity()
    lecture = Lecture.query.get(lecture_id)
    admin = User.query.filter_by (id= identity['id'], role= 'admin').first()
    if not lecture or not admin:
        return jsonify({'error': 'Lecture not found'}), 404

    course = Course.query.filter_by(id=lecture.course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json() or {}
    for field in ['title', 'content', 'duration_minutes', 'is_published', 'order_index']:
        if field in data:
            setattr(lecture, field, data[field])

    db.session.commit()
    return jsonify({'message': 'Lecture updated', 'lecture': lecture.to_dict()})


# ──────────────── MATERIAL UPLOAD ────────────────

@lecturer_bp.route('/api/lecturer/courses/<int:course_id>/materials', methods=['POST'])
@jwt_required()
@role_required('lecturer')
def upload_material(course_id):
    identity = get_identity()
    course = Course.query.filter_by(id=course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Course not found'}), 404

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    if not allowed_file(file.filename, 'all'):
        return jsonify({'error': 'File type not allowed'}), 400

    file_path = save_uploaded_file(
        file,
        current_app.config['UPLOAD_FOLDER'],
        subfolder=f'courses/{course_id}'
    )

    # Determine file type
    ext = file.filename.rsplit('.', 1)[-1].lower()
    file_type = 'other'
    for ftype, exts in {
        'pdf': {'pdf'}, 'video': {'mp4', 'avi', 'mkv', 'mov', 'webm'},
        'slide': {'pptx', 'ppt'}, 'document': {'docx', 'doc', 'txt'}
    }.items():
        if ext in exts:
            file_type = ftype
            break

    material = Material(
        course_id=course_id,
        lecture_id=request.form.get('lecture_id', type=int),
        title=request.form.get('title', file.filename),
        file_type=file_type,
        file_path=file_path,
        file_size=file.content_length,
    )
    db.session.add(material)
    db.session.commit()

    # ── Auto-extract text & generate AI summary in background ──
    try:
        import threading
        abs_path = os.path.join(current_app.config['UPLOAD_FOLDER'], file_path)
        app = current_app._get_current_object()
        mat_id = material.id

        def _process_material():
            with app.app_context():
                from utils.text_extractor import extract_text
                from ai_modules.ollama_service import summarize_text
                text = extract_text(abs_path)
                if text and len(text.strip()) >= 50:
                    summary = summarize_text(text)
                    mat = Material.query.get(mat_id)
                    if mat:
                        mat.ai_summary = summary
                        db.session.commit()

        threading.Thread(target=_process_material, daemon=True).start()
    except Exception:
        pass  # Non-critical — summary will be empty until next attempt

    return jsonify({'message': 'Material uploaded', 'material': material.to_dict()}), 201


@lecturer_bp.route('/api/lecturer/materials/<int:material_id>/summarize', methods=['POST'])
@jwt_required()
@role_required('lecturer')
def summarize_material(material_id):
    """Manually trigger AI summarization for a material (useful for older uploads)."""
    identity = get_identity()
    material = Material.query.get(material_id)
    if not material:
        return jsonify({'error': 'Material not found'}), 404

    course = Course.query.filter_by(id=material.course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Unauthorized'}), 403

    upload_folder = current_app.config['UPLOAD_FOLDER']
    abs_path = os.path.join(upload_folder, material.file_path)

    from utils.text_extractor import extract_text
    raw_text = extract_text(abs_path)
    if not raw_text or len(raw_text.strip()) < 50:
        return jsonify({
            'error': 'Could not extract text from this file. If this is a scanned PDF, OCR is required.'
        }), 400

    from ai_modules.ollama_service import summarize_text, _ollama_available
    if _ollama_available():
        try:
            summary = summarize_text(raw_text)
        except Exception:
            summary = ''
    else:
        summary = ''

    if not summary:
        # Fallback: extractive summary using local TF-IDF summarizer
        from ai_modules.learning_ai.summarizer import TextSummarizer
        summary = TextSummarizer().summarize(raw_text, num_sentences=10)

    material.ai_summary = summary
    db.session.commit()
    return jsonify({'message': 'Summary generated', 'material': material.to_dict()})


@lecturer_bp.route('/api/lecturer/courses/<int:course_id>/materials', methods=['GET'])
@jwt_required()
@role_required('lecturer')
def get_materials(course_id):
    identity = get_identity()
    course = Course.query.filter_by(id=course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Course not found'}), 404

    materials = Material.query.filter_by(course_id=course_id).all()
    return jsonify({'materials': [m.to_dict() for m in materials]})


@lecturer_bp.route('/api/lecturer/materials/<int:material_id>', methods=['DELETE'])
@jwt_required()
@role_required('lecturer')
def delete_material(material_id):
    identity = get_identity()
    material = Material.query.get(material_id)
    if not material:
        return jsonify({'error': 'Material not found'}), 404

    course = Course.query.filter_by(id=material.course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Unauthorized'}), 403

    abs_path = os.path.join(current_app.config['UPLOAD_FOLDER'], material.file_path)
    try:
        LearningProgress.query.filter_by(material_id=material.id).delete()
        db.session.delete(material)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'error': 'Failed to delete material. Please try again.'}), 500

    try:
        if os.path.exists(abs_path):
            os.remove(abs_path)
    except Exception:
        pass

    return jsonify({'message': 'Material deleted'})


# ──────────────── EXAM MANAGEMENT ────────────────

@lecturer_bp.route('/api/lecturer/courses/<int:course_id>/exams', methods=['POST'])
@jwt_required()
@role_required('lecturer')
def create_exam(course_id):
    identity = get_identity()
    course = Course.query.filter_by(id=course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Course not found'}), 404

    data = request.get_json()
    assessment_type = (data.get('assessment_type') or '').lower()
    if assessment_type not in ASSESSMENT_TOTAL_MARKS:
        assessment_type = 'cat1'

    assessment_error = validate_assessment_type_availability(course_id, assessment_type)
    if assessment_error:
        return jsonify({'error': assessment_error}), 400

    mapped_exam_type = map_assessment_type_to_exam_type(assessment_type)
    total_marks = data.get('total_marks', ASSESSMENT_TOTAL_MARKS[assessment_type])
    duration = data.get('duration_minutes', 60)
    start = datetime.fromisoformat(data['start_time']) if data.get('start_time') else None
    end = datetime.fromisoformat(data['end_time']) if data.get('end_time') else None
    # Auto-calculate end_time from start + duration if missing or invalid
    if start and (not end or end <= start):
        end = start + timedelta(minutes=duration)

    exam = Exam(
        course_id=course_id,
        title=data.get('title', 'Untitled Exam'),
        description=build_description_with_assessment_marker(data.get('description', ''), assessment_type),
        exam_type=mapped_exam_type,
        duration_minutes=duration,
        total_marks=total_marks,
        passing_marks=data.get('passing_marks', 50),
        start_time=start,
        end_time=end,
        is_proctored=data.get('is_proctored', True),
        shuffle_questions=data.get('shuffle_questions', True),
        risk_threshold=data.get('risk_threshold', 100),
    )
    db.session.add(exam)
    db.session.commit()
    return jsonify({'message': 'Exam created', 'exam': exam.to_dict()}), 201


@lecturer_bp.route('/api/lecturer/courses/<int:course_id>/exams/manual', methods=['POST'])
@jwt_required()
@role_required('lecturer')
def create_manual_exam(course_id):
    identity = get_identity()
    course = Course.query.filter_by(id=course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Course not found'}), 404

    data = request.get_json() or {}
    assessment_type = (data.get('assessment_type') or '').lower()
    if assessment_type not in ASSESSMENT_TOTAL_MARKS:
        assessment_type = 'cat1'

    assessment_error = validate_assessment_type_availability(course_id, assessment_type)
    if assessment_error:
        return jsonify({'error': assessment_error}), 400

    questions_text = (data.get('questions_text') or '').strip()
    if not questions_text:
        return jsonify({'error': 'Paste at least one question to continue.'}), 400

    default_type = (data.get('default_question_type') or 'short_answer').lower()
    default_difficulty = (data.get('difficulty') or 'understand').lower()
    questions = parse_manual_questions(questions_text, default_type, default_difficulty)
    if not questions:
        return jsonify({'error': 'Could not parse any questions from the pasted text.'}), 400

    mapped_exam_type = map_assessment_type_to_exam_type(assessment_type)
    duration = int(data.get('duration_minutes') or 60)
    start = datetime.fromisoformat(data['start_time']) if data.get('start_time') else None
    end = datetime.fromisoformat(data['end_time']) if data.get('end_time') else None
    if start and (not end or end <= start):
        end = start + timedelta(minutes=duration)

    total_marks = int(data.get('total_marks') or ASSESSMENT_TOTAL_MARKS[assessment_type])
    total_marks = max(1, total_marks)
    any_marks = any(q.get('marks') is not None for q in questions)

    if not any_marks:
        base_marks = total_marks // len(questions)
        remainder = total_marks % len(questions)
        for idx, q in enumerate(questions):
            q['marks'] = base_marks + (1 if idx < remainder else 0)
    else:
        for q in questions:
            if q.get('marks') is None:
                q['marks'] = 1
        if not data.get('total_marks'):
            total_marks = int(sum(q.get('marks') or 0 for q in questions) or total_marks)

    passing_marks = int(data.get('passing_marks') or max(1, int(total_marks * 0.5)))

    exam = Exam(
        course_id=course_id,
        title=data.get('title', 'Untitled Exam'),
        description=build_description_with_assessment_marker('Manual exam entry.', assessment_type),
        exam_type=mapped_exam_type,
        duration_minutes=duration,
        total_marks=total_marks,
        passing_marks=passing_marks,
        start_time=start,
        end_time=end,
        is_proctored=data.get('is_proctored', True),
        shuffle_questions=True,
        is_published=False,
    )
    db.session.add(exam)
    db.session.flush()

    for idx, q in enumerate(questions):
        question = Question(
            exam_id=exam.id,
            question_text=q['question_text'],
            question_type=q['question_type'],
            options=q.get('options'),
            correct_answer=q.get('correct_answer'),
            marks=q.get('marks', 1),
            difficulty=q.get('difficulty', default_difficulty),
            order_index=idx,
        )
        db.session.add(question)

    db.session.commit()
    return jsonify({
        'message': 'Manual exam created. Review and publish when ready.',
        'exam': exam.to_dict(),
        'questions': [q.to_dict(include_answer=True) for q in exam.questions.order_by(Question.order_index).all()],
    }), 201


@lecturer_bp.route('/api/lecturer/exams/<int:exam_id>/questions', methods=['POST'])
@jwt_required()
@role_required('lecturer')
def add_question(exam_id):
    identity = get_identity()
    exam = Exam.query.get(exam_id)
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404

    course = Course.query.filter_by(id=exam.course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json()
    question = Question(
        exam_id=exam_id,
        question_text=data['question_text'],
        question_type=data.get('question_type', 'mcq'),
        options=data.get('options'),
        correct_answer=data.get('correct_answer'),
        marks=data.get('marks', 1),
        difficulty=data.get('difficulty', 'understand'),
        order_index=data.get('order_index', 0),
        explanation=data.get('explanation'),
    )
    db.session.add(question)
    db.session.commit()
    return jsonify({'message': 'Question added', 'question': question.to_dict(include_answer=True)}), 201


@lecturer_bp.route('/api/lecturer/exams/<int:exam_id>/questions', methods=['GET'])
@jwt_required()
@role_required('lecturer')
def get_questions(exam_id):
    identity = get_identity()
    exam = Exam.query.get(exam_id)
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404

    course = Course.query.filter_by(id=exam.course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Unauthorized'}), 403

    questions = Question.query.filter_by(exam_id=exam_id).order_by(Question.order_index).all()
    return jsonify({'questions': [q.to_dict(include_answer=True) for q in questions]})


@lecturer_bp.route('/api/lecturer/exams/<int:exam_id>/publish', methods=['POST'])
@jwt_required()
@role_required('lecturer')
def publish_exam(exam_id):
    identity = get_identity()
    exam = Exam.query.get(exam_id)
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404

    course = Course.query.filter_by(id=exam.course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Unauthorized'}), 403

    now = datetime.now()
    if exam.end_time and now > exam.end_time:
        return jsonify({
            'error': 'Exam schedule has expired. Please reset the schedule before publishing.',
            'schedule_expired': True,
            'exam': exam.to_dict(),
        }), 400

    exam.is_published = True
    db.session.commit()
    return jsonify({'message': 'Exam published', 'exam': exam.to_dict()})


@lecturer_bp.route('/api/lecturer/exams/<int:exam_id>/schedule', methods=['PUT'])
@jwt_required()
@role_required('lecturer')
def update_exam_schedule(exam_id):
    identity = get_identity()
    exam = Exam.query.get(exam_id)
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404

    course = Course.query.filter_by(id=exam.course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json() or {}
    start_raw = data.get('start_time')
    if not start_raw:
        return jsonify({'error': 'Start time is required.'}), 400

    duration = int(data.get('duration_minutes') or exam.duration_minutes or 60)
    start = datetime.fromisoformat(start_raw)
    end = datetime.fromisoformat(data['end_time']) if data.get('end_time') else None

    if not end or end <= start:
        end = start + timedelta(minutes=duration)

    exam.start_time = start
    exam.end_time = end
    exam.duration_minutes = duration
    db.session.commit()

    return jsonify({'message': 'Exam schedule updated', 'exam': exam.to_dict()})


@lecturer_bp.route('/api/lecturer/exams/<int:exam_id>/release-grades', methods=['POST'])
@jwt_required()
@role_required('lecturer')
def release_grades(exam_id):
    identity = get_identity()
    exam = Exam.query.get(exam_id)
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404

    course = Course.query.filter_by(id=exam.course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Unauthorized'}), 403

    exam.grades_released = not exam.grades_released
    db.session.commit()
    return jsonify({
        'message': 'Grades released' if exam.grades_released else 'Grades hidden',
        'grades_released': exam.grades_released,
        'exam': exam.to_dict()
    })


@lecturer_bp.route('/api/lecturer/exams/<int:exam_id>', methods=['DELETE'])
@jwt_required()
@role_required('lecturer')
def delete_exam(exam_id):
    identity = get_identity()
    exam = Exam.query.get(exam_id)
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404

    course = Course.query.filter_by(id=exam.course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Unauthorized'}), 403

    db.session.delete(exam)
    db.session.commit()
    return jsonify({'message': 'Exam deleted'})


@lecturer_bp.route('/api/lecturer/courses/<int:course_id>/exams', methods=['GET'])
@jwt_required()
@role_required('lecturer')
def get_exams(course_id):
    identity = get_identity()
    course = Course.query.filter_by(id=course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Course not found'}), 404

    exams = Exam.query.filter_by(course_id=course_id).order_by(Exam.created_at.desc()).all()
    exam_list = []
    for exam in exams:
        ed = exam.to_dict()
        ed['assessment_type'] = infer_assessment_type(exam)
        ed['question_count'] = Question.query.filter_by(exam_id=exam.id).count()
        ed['submission_count'] = Submission.query.filter_by(exam_id=exam.id).count()
        ed['graded_count'] = Submission.query.filter_by(exam_id=exam.id, is_graded=True).count()
        ed['pending_count'] = Submission.query.filter_by(exam_id=exam.id, is_graded=False).filter(Submission.status != 'in_progress').count()
        exam_list.append(ed)
    return jsonify({'exams': exam_list})


@lecturer_bp.route('/api/lecturer/courses/<int:course_id>/exams/generate', methods=['POST'])
@jwt_required()
@role_required('lecturer')
def generate_exam_from_materials(course_id):
    """Auto-generate exam questions from course materials."""
    identity = get_identity()
    course = Course.query.filter_by(id=course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Course not found'}), 404

    data = request.get_json() or {}
    num_questions = data.get('num_questions', 10)
    difficulty = data.get('difficulty', 'understand')
    exam_title = data.get('title', f'{course.title} — Auto-Generated Exam')
    assessment_type = (data.get('assessment_type') or '').lower()
    if assessment_type not in ASSESSMENT_TOTAL_MARKS:
        assessment_type = 'cat1'

    assessment_error = validate_assessment_type_availability(course_id, assessment_type)
    if assessment_error:
        return jsonify({'error': assessment_error}), 400

    exam_type = map_assessment_type_to_exam_type(assessment_type)
    question_types = data.get('question_types', ['mcq', 'short_answer'])

    # Gather text from selected course materials (or all if none selected)
    selected_ids = data.get('material_ids') or []
    if isinstance(selected_ids, list):
        selected_ids = [int(mid) for mid in selected_ids if str(mid).isdigit()]
    else:
        selected_ids = []
    include_lectures = data.get('include_lectures', True)

    materials_query = Material.query.filter_by(course_id=course_id)
    if selected_ids:
        materials_query = materials_query.filter(Material.id.in_(selected_ids))
    materials = materials_query.all()
    if selected_ids and not materials:
        return jsonify({'error': 'Selected materials not found for this course.'}), 400
    if not materials:
        # Also check if at least lectures have content
        lectures = Lecture.query.filter_by(course_id=course_id).all() if include_lectures else []
        has_lecture_content = any(lec.content and len(lec.content.strip()) > 50 for lec in lectures)
        if not has_lecture_content:
            msg = 'No materials found for this course. Upload materials first.'
            if not include_lectures:
                msg = 'No materials selected and lecture notes excluded.'
            return jsonify({'error': msg}), 400
    else:
        lectures = Lecture.query.filter_by(course_id=course_id).all() if include_lectures else []

    combined_text = ''

    # 1) Use existing AI summaries
    for mat in (materials or []):
        if mat.ai_summary:
            combined_text += mat.ai_summary + '\n\n'

    # 2) If summaries are sparse, extract raw text from uploaded files
    if len(combined_text.strip()) < 50:
        from utils.text_extractor import extract_text
        upload_folder = current_app.config['UPLOAD_FOLDER']
        for mat in (materials or []):
            abs_path = os.path.join(upload_folder, mat.file_path)
            raw_text = extract_text(abs_path)
            if raw_text and len(raw_text.strip()) >= 30:
                combined_text += raw_text + '\n\n'
                # Backfill a lightweight summary without blocking exam generation
                if not mat.ai_summary:
                    mat.ai_summary = raw_text[:2000]
                    db.session.commit()

    # 3) Also pull lecture content
    for lec in (lectures or []):
        if lec.content:
            combined_text += lec.content + '\n\n'

    if len(combined_text.strip()) < 50:
        return jsonify({
            'error': 'Not enough text content in materials/lectures to generate questions. '
                     'Upload PDFs or documents with readable text, or add lecture content.'
        }), 400

    # Cap context size to keep generation responsive
    combined_text = combined_text[:12000]

    # Generate questions — try Ollama LLM first, fallback to rule-based
    generated = []
    try:
        from ai_modules.ollama_service import generate_questions_llm
        generated = generate_questions_llm(
            combined_text, num_questions, difficulty, question_types
        )
    except Exception:
        generated = []

    if not generated:
        # Fallback: rule-based generator
        try:
            from ai_modules.assessment_ai.quiz_generator import QuizGenerator
            generator = QuizGenerator()
            generated = generator.generate_from_text(
                combined_text, num_questions, difficulty, question_types
            )
        except Exception:
            generated = []

    if not generated:
        return jsonify({'error': 'Could not generate questions from the available content.'}), 400

    target_total_marks = int(data.get('total_marks', ASSESSMENT_TOTAL_MARKS[assessment_type]))
    target_total_marks = max(1, target_total_marks)
    question_count = len(generated)
    base_marks = target_total_marks // question_count
    remainder_marks = target_total_marks % question_count

    for index, item in enumerate(generated):
        item['marks'] = base_marks + (1 if index < remainder_marks else 0)

    # Create exam in draft (unpublished) state
    gen_duration = data.get('duration_minutes', 60)
    gen_start = datetime.fromisoformat(data['start_time']) if data.get('start_time') else None
    gen_end = datetime.fromisoformat(data['end_time']) if data.get('end_time') else None
    if gen_start and (not gen_end or gen_end <= gen_start):
        gen_end = gen_start + timedelta(minutes=gen_duration)

    exam = Exam(
        course_id=course_id,
        title=exam_title,
        description=build_description_with_assessment_marker(
            f'Auto-generated from course materials. {len(generated)} questions pending review.',
            assessment_type,
        ),
        exam_type=exam_type,
        duration_minutes=gen_duration,
        total_marks=target_total_marks,
        passing_marks=data.get('passing_marks', 50),
        start_time=gen_start,
        end_time=gen_end,
        is_proctored=data.get('is_proctored', True),
        is_published=False,
        shuffle_questions=True,
    )
    db.session.add(exam)
    db.session.flush()

    # Insert generated questions
    for idx, q in enumerate(generated):
        question = Question(
            exam_id=exam.id,
            question_text=q['question_text'],
            question_type=q['question_type'],
            options=q.get('options'),
            correct_answer=q.get('correct_answer'),
            marks=q.get('marks', 1),
            difficulty=q.get('difficulty', difficulty),
            order_index=idx,
            explanation=q.get('explanation'),
        )
        db.session.add(question)

    db.session.commit()

    questions = Question.query.filter_by(exam_id=exam.id).order_by(Question.order_index).all()
    return jsonify({
        'message': f'Exam generated with {len(generated)} questions. Review and publish when ready.',
        'exam': exam.to_dict(),
        'questions': [q.to_dict(include_answer=True) for q in questions],
    }), 201


@lecturer_bp.route('/api/lecturer/questions/<int:question_id>', methods=['PUT'])
@jwt_required()
@role_required('lecturer')
def update_question(question_id):
    """Edit a generated question before publishing."""
    identity = get_identity()
    question = Question.query.get(question_id)
    if not question:
        return jsonify({'error': 'Question not found'}), 404

    exam = Exam.query.get(question.exam_id)
    course = Course.query.filter_by(id=exam.course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json()
    for field in ['question_text', 'question_type', 'options', 'correct_answer',
                   'marks', 'difficulty', 'order_index', 'explanation']:
        if field in data:
            setattr(question, field, data[field])

    db.session.commit()
    return jsonify({'message': 'Question updated', 'question': question.to_dict(include_answer=True)})


@lecturer_bp.route('/api/lecturer/questions/<int:question_id>', methods=['DELETE'])
@jwt_required()
@role_required('lecturer')
def delete_question(question_id):
    """Remove a question from an exam."""
    identity = get_identity()
    question = Question.query.get(question_id)
    if not question:
        return jsonify({'error': 'Question not found'}), 404

    exam = Exam.query.get(question.exam_id)
    course = Course.query.filter_by(id=exam.course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Unauthorized'}), 403

    db.session.delete(question)

    # Recalculate total marks
    remaining = Question.query.filter_by(exam_id=exam.id).all()
    exam.total_marks = sum(q.marks for q in remaining)
    db.session.commit()
    return jsonify({'message': 'Question deleted'})


# ──────────────── SUBMISSIONS & GRADING ────────────────

@lecturer_bp.route('/api/lecturer/exams/<int:exam_id>/submissions', methods=['GET'])
@jwt_required()
@role_required('lecturer')
def get_exam_submissions(exam_id):
    identity = get_identity()
    exam = Exam.query.get(exam_id)
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404

    course = Course.query.filter_by(id=exam.course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Unauthorized'}), 403

    submissions = Submission.query.filter_by(exam_id=exam_id).all()
    result = []
    for sub in submissions:
        student = User.query.get(sub.student_id)
        violations = Violation.query.filter_by(submission_id=sub.id).all()
        result.append({
            **sub.to_dict(),
            'student_name': f"{student.first_name} {student.last_name}" if student else 'Unknown',
            'violations_count': len(violations),
        })
    return jsonify({'submissions': result})


@lecturer_bp.route('/api/lecturer/submissions/<int:submission_id>/grade', methods=['POST'])
@jwt_required()
@role_required('lecturer')
def grade_submission(submission_id):
    identity = get_identity()
    submission = Submission.query.get(submission_id)
    if not submission:
        return jsonify({'error': 'Submission not found'}), 404

    exam = Exam.query.get(submission.exam_id)
    course = Course.query.filter_by(id=exam.course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json()
    # Grade individual answers
    if 'answers' in data:
        for ans_data in data['answers']:
            answer = Answer.query.get(ans_data['id'])
            if answer and answer.submission_id == submission_id:
                answer.score = ans_data.get('score', 0)
                answer.ai_feedback = ans_data.get('feedback', '')
                answer.is_correct = ans_data.get('score', 0) > 0

    # Recalculate total
    answers = Answer.query.filter_by(submission_id=submission_id).all()
    submission.total_score = sum(a.score or 0 for a in answers)
    submission.is_graded = True
    submission.status = 'graded'
    db.session.commit()

    return jsonify({'message': 'Submission graded', 'submission': submission.to_dict()})


@lecturer_bp.route('/api/lecturer/submissions/<int:submission_id>/override-score', methods=['PUT'])
@jwt_required()
@role_required('lecturer')
def override_submission_score(submission_id):
    identity = get_identity()
    submission = Submission.query.get(submission_id)
    if not submission:
        return jsonify({'error': 'Submission not found'}), 404

    exam = Exam.query.get(submission.exam_id)
    course = Course.query.filter_by(id=exam.course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json() or {}
    score = data.get('score', None)
    try:
        score = float(score)
    except (TypeError, ValueError):
        return jsonify({'error': 'Score must be a number.'}), 400

    if score < 0:
        return jsonify({'error': 'Score must be zero or higher.'}), 400

    if exam and exam.total_marks is not None and score > exam.total_marks:
        return jsonify({'error': f'Score cannot exceed {exam.total_marks}.'}), 400

    submission.total_score = score
    submission.is_graded = True
    submission.status = 'graded'
    db.session.commit()

    return jsonify({'message': 'Score updated', 'submission': submission.to_dict()})


# ──────────────── ENROLLED STUDENTS ────────────────

@lecturer_bp.route('/api/lecturer/courses/<int:course_id>/students', methods=['GET'])
@jwt_required()
@role_required('lecturer')
def get_enrolled_students(course_id):
    identity = get_identity()
    course = Course.query.filter_by(id=course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Course not found'}), 404

    enrollments = Enrollment.query.filter_by(course_id=course_id).all()
    students = []
    for enr in enrollments:
        student = User.query.get(enr.student_id)
        if student:
            students.append({
                **student.to_dict(),
                'enrollment_status': enr.status,
                'progress': enr.progress,
            })
    return jsonify({'students': students})


# ──────────────── LIVE CLASSES ────────────────

def purge_expired_live_classes():
    """Delete live classes that have already ended."""
    now = datetime.now()
    classes = LiveClass.query.all()
    deleted = False

    for live_class in classes:
        duration = int(live_class.duration_minutes or 60)
        class_end = live_class.scheduled_at + timedelta(minutes=duration)
        if class_end <= now:
            db.session.delete(live_class)
            deleted = True

    if deleted:
        db.session.commit()

@lecturer_bp.route('/api/lecturer/courses/<int:course_id>/classes', methods=['GET'])
@jwt_required()
@role_required('lecturer')
def get_live_classes(course_id):
    purge_expired_live_classes()
    identity = get_identity()
    course = Course.query.filter_by(id=course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Course not found'}), 404
    classes = LiveClass.query.filter_by(course_id=course_id).order_by(LiveClass.scheduled_at.asc()).all()
    return jsonify({'classes': [c.to_dict() for c in classes]})


@lecturer_bp.route('/api/lecturer/courses/<int:course_id>/classes', methods=['POST'])
@jwt_required()
@role_required('lecturer')
def create_live_class(course_id):
    purge_expired_live_classes()
    identity = get_identity()
    course = Course.query.filter_by(id=course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Course not found'}), 404

    data = request.get_json()
    if not data.get('title') or not data.get('meeting_link') or not data.get('scheduled_at'):
        return jsonify({'error': 'Title, meeting link, and scheduled time are required'}), 400

    scheduled_at = datetime.fromisoformat(data['scheduled_at'])
    duration_minutes = int(data.get('duration_minutes', 60) or 60)
    if duration_minutes <= 0:
        return jsonify({'error': 'Duration must be greater than 0 minutes'}), 400

    new_start = scheduled_at
    new_end = scheduled_at + timedelta(minutes=duration_minutes)

    potential_conflicts = (
        db.session.query(LiveClass, Course)
        .join(Course, LiveClass.course_id == Course.id)
        .filter(LiveClass.scheduled_at < new_end)
        .all()
    )

    for existing_class, existing_course in potential_conflicts:
        existing_duration = int(existing_class.duration_minutes or 60)
        existing_start = existing_class.scheduled_at
        existing_end = existing_start + timedelta(minutes=existing_duration)

        if existing_end > new_start:
            return jsonify({
                'error': (
                    f"Schedule conflict with existing class "
                    f"('{existing_class.title}' in {existing_course.code}) at "
                    f"{existing_start.strftime('%Y-%m-%d %H:%M')}."
                )
            }), 409

    live_class = LiveClass(
        course_id=course_id,
        title=data['title'],
        description=data.get('description', ''),
        meeting_link=data['meeting_link'],
        platform=data.get('platform', 'zoom'),
        scheduled_at=scheduled_at,
        duration_minutes=duration_minutes,
        is_unlocked=data.get('is_unlocked', False),
    )
    db.session.add(live_class)
    db.session.commit()
    return jsonify({'message': 'Live class created', 'class': live_class.to_dict()}), 201


@lecturer_bp.route('/api/lecturer/classes/<int:class_id>/toggle-lock', methods=['POST'])
@jwt_required()
@role_required('lecturer')
def toggle_class_lock(class_id):
    purge_expired_live_classes()
    identity = get_identity()
    live_class = LiveClass.query.get(class_id)
    if not live_class:
        return jsonify({'error': 'Class not found'}), 404
    course = Course.query.filter_by(id=live_class.course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Unauthorized'}), 403
    live_class.is_unlocked = not live_class.is_unlocked
    db.session.commit()
    return jsonify({'message': 'Lock toggled', 'is_unlocked': live_class.is_unlocked})


@lecturer_bp.route('/api/lecturer/classes/<int:class_id>', methods=['PUT'])
@jwt_required()
@role_required('lecturer')
def update_live_class(class_id):
    purge_expired_live_classes()
    identity = get_identity()
    live_class = LiveClass.query.get(class_id)
    if not live_class:
        return jsonify({'error': 'Class not found'}), 404

    owned_course = Course.query.filter_by(id=live_class.course_id, lecturer_id=identity['id']).first()
    if not owned_course:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json() or {}
    if not data.get('title') or not data.get('meeting_link') or not data.get('scheduled_at'):
        return jsonify({'error': 'Title, meeting link, and scheduled time are required'}), 400

    scheduled_at = datetime.fromisoformat(data['scheduled_at'])
    duration_minutes = int(data.get('duration_minutes', 60) or 60)
    if duration_minutes <= 0:
        return jsonify({'error': 'Duration must be greater than 0 minutes'}), 400

    new_start = scheduled_at
    new_end = scheduled_at + timedelta(minutes=duration_minutes)

    potential_conflicts = (
        db.session.query(LiveClass, Course)
        .join(Course, LiveClass.course_id == Course.id)
        .filter(LiveClass.id != class_id)
        .filter(LiveClass.scheduled_at < new_end)
        .all()
    )

    for existing_class, existing_course in potential_conflicts:
        existing_duration = int(existing_class.duration_minutes or 60)
        existing_start = existing_class.scheduled_at
        existing_end = existing_start + timedelta(minutes=existing_duration)

        if existing_end > new_start:
            return jsonify({
                'error': (
                    f"Schedule conflict with existing class "
                    f"('{existing_class.title}' in {existing_course.code}) at "
                    f"{existing_start.strftime('%Y-%m-%d %H:%M')}."
                )
            }), 409

    live_class.title = data['title']
    live_class.description = data.get('description', '')
    live_class.meeting_link = data['meeting_link']
    live_class.platform = data.get('platform', 'zoom')
    live_class.scheduled_at = scheduled_at
    live_class.duration_minutes = duration_minutes
    live_class.is_unlocked = data.get('is_unlocked', False)

    db.session.commit()
    return jsonify({'message': 'Class updated', 'class': live_class.to_dict()})


@lecturer_bp.route('/api/lecturer/classes/<int:class_id>', methods=['DELETE'])
@jwt_required()
@role_required('lecturer')
def delete_live_class(class_id):
    purge_expired_live_classes()
    identity = get_identity()
    live_class = LiveClass.query.get(class_id)
    if not live_class:
        return jsonify({'error': 'Class not found'}), 404
    course = Course.query.filter_by(id=live_class.course_id, lecturer_id=identity['id']).first()
    if not course:
        return jsonify({'error': 'Unauthorized'}), 403
    db.session.delete(live_class)
    db.session.commit()
    return jsonify({'message': 'Class deleted'})
