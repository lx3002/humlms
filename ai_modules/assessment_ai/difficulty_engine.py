

from database.models import db, Question, Answer, Submission


class DifficultyEngine:
    

    # Bloom's taxonomy ordered by difficulty
    BLOOM_ORDER = ['remember', 'understand', 'apply', 'analyze', 'evaluate', 'create']

    def get_adaptive_difficulty(self, student_id, course_id):
        
        from database.models import Exam

        exams = Exam.query.filter_by(course_id=course_id).all()
        exam_ids = [e.id for e in exams]

        submissions = Submission.query.filter_by(student_id=student_id).filter(
            Submission.exam_id.in_(exam_ids)
        ).all()

        if not submissions:
            return 'understand'  # Default starting level

        # Calculate accuracy at each Bloom level
        level_stats = {level: {'correct': 0, 'total': 0} for level in self.BLOOM_ORDER}

        for sub in submissions:
            answers = Answer.query.filter_by(submission_id=sub.id).all()
            for ans in answers:
                q = Question.query.get(ans.question_id)
                if not q or not q.difficulty:
                    continue
                level = q.difficulty
                if level in level_stats:
                    level_stats[level]['total'] += 1
                    if ans.is_correct:
                        level_stats[level]['correct'] += 1

        # Find the highest level where student achieves >= 70% accuracy
        recommended = 'understand'
        for level in self.BLOOM_ORDER:
            stats = level_stats[level]
            if stats['total'] >= 3:  # Need at least 3 attempts
                accuracy = stats['correct'] / stats['total']
                if accuracy >= 0.7:
                    # Student masters this level, try the next
                    idx = self.BLOOM_ORDER.index(level)
                    if idx + 1 < len(self.BLOOM_ORDER):
                        recommended = self.BLOOM_ORDER[idx + 1]
                else:
                    recommended = level
                    break

        return recommended

    def calibrate_question_difficulty(self, question_id):
        
        answers = Answer.query.filter_by(question_id=question_id).all()
        if not answers:
            return None

        correct_count = sum(1 for a in answers if a.is_correct)
        total = len(answers)
        accuracy = correct_count / total

        # Map accuracy to difficulty
        if accuracy > 0.85:
            return 'remember'  # Too easy
        elif accuracy > 0.70:
            return 'understand'
        elif accuracy > 0.55:
            return 'apply'
        elif accuracy > 0.40:
            return 'analyze'
        elif accuracy > 0.25:
            return 'evaluate'
        else:
            return 'create'  # Very hard

    def get_question_bank(self, exam_id, student_id, num_questions=10):
        """
        Select questions from the exam bank adapted to student level.
        Mixes difficulty levels with emphasis on the student's target level.
        """
        from database.models import Exam
        exam = Exam.query.get(exam_id)
        if not exam:
            return []

        target_level = self.get_adaptive_difficulty(student_id, exam.course_id)
        target_idx = self.BLOOM_ORDER.index(target_level)

        all_questions = Question.query.filter_by(exam_id=exam_id).all()
        if not all_questions:
            return []

        # Categorize questions by difficulty
        by_difficulty = {}
        for q in all_questions:
            diff = q.difficulty or 'understand'
            by_difficulty.setdefault(diff, []).append(q)

        # Distribution: 40% target level, 30% one below, 20% one above, 10% others
        selected = []
        import random

        # Target level (40%)
        target_count = max(1, int(num_questions * 0.4))
        target_qs = by_difficulty.get(target_level, [])
        selected.extend(random.sample(target_qs, min(target_count, len(target_qs))))

        # One below (30%)
        if target_idx > 0:
            below_level = self.BLOOM_ORDER[target_idx - 1]
            below_qs = by_difficulty.get(below_level, [])
            below_count = max(1, int(num_questions * 0.3))
            selected.extend(random.sample(below_qs, min(below_count, len(below_qs))))

        # One above (20%)
        if target_idx < len(self.BLOOM_ORDER) - 1:
            above_level = self.BLOOM_ORDER[target_idx + 1]
            above_qs = by_difficulty.get(above_level, [])
            above_count = max(1, int(num_questions * 0.2))
            selected.extend(random.sample(above_qs, min(above_count, len(above_qs))))

        # Fill remaining from any level
        remaining = num_questions - len(selected)
        if remaining > 0:
            unused = [q for q in all_questions if q not in selected]
            selected.extend(random.sample(unused, min(remaining, len(unused))))

        random.shuffle(selected)
        return selected[:num_questions]
