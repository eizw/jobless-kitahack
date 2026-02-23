"""
Evaluation Pipeline - Orchestrates Evaluator → Feedback agents.
Runs after an interview completes.
"""

import logging
from typing import Optional, Dict, Any

from agents.interview.evaluator_agent import EvaluatorAgent
from agents.interview.feedback_agent import FeedbackAgent
from services.session_manager import session_manager
from services import firestore_service
from models.schemas import InterviewStatus

logger = logging.getLogger(__name__)

# Singleton agent instances
_evaluator = EvaluatorAgent()
_feedback = FeedbackAgent()


async def run_evaluation(session_id: str) -> Dict[str, Any]:
    """
    Run the full evaluation pipeline for a completed interview.

    Steps:
    1. Get transcript from session manager
    2. Run evaluator agent to score each answer
    3. Run feedback agent to generate report
    4. Store results and update session status

    Returns:
        Dict with feedback report or error
    """
    session = session_manager.get_session(session_id)
    if not session:
        return {"status": "error", "message": "Session not found"}

    if session.status not in (InterviewStatus.COMPLETED, InterviewStatus.EVALUATING):
        return {"status": "error", "message": f"Session is {session.status.value}, not completed"}

    # Mark as evaluating
    session_manager.update_status(session_id, InterviewStatus.EVALUATING)

    try:
        # Step 1: Get transcript data
        transcript_data = session_manager.get_transcript_for_evaluation(session_id)
        if not transcript_data:
            return {"status": "error", "message": "No transcript data found"}

        logger.info(f"[pipeline] Evaluating {len(transcript_data)} Q&A pairs for {session_id}")

        # Step 2: Run evaluator
        eval_result = await _evaluator.evaluate(
            session_id=session_id,
            company=session.config.company,
            position=session.config.position,
            transcript_data=transcript_data,
        )

        if eval_result.get("status") != "success":
            session_manager.update_status(session_id, InterviewStatus.COMPLETED)
            return {"status": "error", "message": f"Evaluation failed: {eval_result.get('message', 'Unknown')}"}

        logger.info(f"[pipeline] Evaluation complete for {session_id}")

        # Step 3: Run feedback generator
        feedback_result = await _feedback.generate_feedback(
            session_id=session_id,
            candidate_name=session.config.candidate_name,
            company=session.config.company,
            position=session.config.position,
            evaluation_data=eval_result,
        )

        if feedback_result.get("status") != "success":
            session_manager.update_status(session_id, InterviewStatus.COMPLETED)
            return {"status": "error", "message": f"Feedback generation failed: {feedback_result.get('message', 'Unknown')}"}

        logger.info(f"[pipeline] Feedback generated for {session_id}")

        # Step 4: Store results
        session_manager.store_feedback(session_id, feedback_result)

        # Persist to Firestore (optional, won't fail if not configured)
        await firestore_service.save_feedback(session_id, feedback_result)
        await firestore_service.update_session_field(
            session_id, "status", InterviewStatus.EVALUATED.value
        )

        return feedback_result

    except Exception as e:
        logger.error(f"[pipeline] Pipeline failed for {session_id}: {e}", exc_info=True)
        session_manager.update_status(session_id, InterviewStatus.COMPLETED)
        return {"status": "error", "message": f"Pipeline error: {str(e)}"}
