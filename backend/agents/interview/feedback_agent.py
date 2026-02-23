"""
Feedback Generator Agent - Creates human-readable feedback reports.
Uses Gemini 2.5 Pro for quality report generation.
Runs async (not live streaming).
"""

import json
import asyncio
import logging
from typing import Dict, Any

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from models.schemas import FeedbackReport

logger = logging.getLogger(__name__)

FEEDBACK_INSTRUCTION = """You are a career coach creating detailed interview feedback reports for Malaysian fresh graduates.

## Your Task
Take the evaluation data from a completed interview and generate a comprehensive, encouraging feedback report.

## Report Requirements

### Overall Assessment
- Calculate an overall score (1-10) from the per-question scores
- Assign a letter grade (A+: 9.5+, A: 9+, B+: 8+, B: 7+, C+: 6+, C: 5+, D: 4+, F: below 4)
- Write a 2-3 sentence summary that is honest but encouraging

### Strengths & Improvements
- Identify the top 3 strengths demonstrated across all answers
- Identify the top 3 areas for improvement
- Be specific - reference actual answers when possible

### Per-Question Feedback
- Include the detailed evaluation for each question
- Make feedback actionable and specific

### Action Items
- Provide 3-5 specific, actionable steps the candidate can take to improve
- Each action item should include:
  - The area to work on
  - A concrete suggestion
  - An example of how to implement it (when possible)

### Encouragement
- End with a genuine, encouraging message
- Remind them that interview skills improve with practice
- Be culturally appropriate for Malaysian context

## Important
- Be constructive, never harsh or discouraging
- Use "you" to address the candidate directly
- Make the report feel personal, not generic
- Focus on growth mindset - every interview is a learning opportunity
"""


class FeedbackAgent:
    """Generates comprehensive feedback reports from evaluation data."""

    def __init__(self):
        self.session_service = InMemorySessionService()
        self.app_name = "jobless_feedback"

        self.agent = LlmAgent(
            name="feedback_generator",
            model="gemini-2.5-flash",
            description="Career coach that generates detailed interview feedback reports",
            instruction=FEEDBACK_INSTRUCTION,
            output_schema=FeedbackReport,
            disallow_transfer_to_parent=True,
            disallow_transfer_to_peers=True,
        )

        self.runner = Runner(
            agent=self.agent,
            app_name=self.app_name,
            session_service=self.session_service,
        )

    async def generate_feedback(
        self,
        session_id: str,
        candidate_name: str,
        company: str,
        position: str,
        evaluation_data: dict,
        max_retries: int = 2,
    ) -> Dict[str, Any]:
        """
        Generate a feedback report from evaluation data.

        Args:
            session_id: The interview session ID
            candidate_name: Candidate's name
            company: Company name
            position: Position applied for
            evaluation_data: Output from the evaluator agent
            max_retries: Number of retries on failure

        Returns:
            Dict with feedback report
        """
        prompt = f"""Generate a detailed feedback report for this interview:

Candidate: {candidate_name}
Company: {company}
Position: {position}
Session ID: {session_id}

## Evaluation Data:
{json.dumps(evaluation_data, indent=2)}

Create a comprehensive, encouraging feedback report that will help this candidate improve."""

        content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)],
        )

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                session = await self.session_service.create_session(
                    app_name=self.app_name,
                    user_id="feedback",
                    state={"session_id": session_id},
                )

                async for event in self.runner.run_async(
                    user_id="feedback",
                    session_id=session.id,
                    new_message=content,
                ):
                    if event.is_final_response():
                        if event.content and event.content.parts:
                            raw_text = event.content.parts[0].text
                            try:
                                clean = raw_text.strip()
                                if clean.startswith("```"):
                                    clean = clean[clean.index("\n") + 1:]
                                    if clean.endswith("```"):
                                        clean = clean[:-3].strip()
                                parsed = json.loads(clean)
                                parsed["status"] = "success"
                                logger.info(f"[feedback] Success on attempt {attempt + 1}")
                                return parsed
                            except (json.JSONDecodeError, ValueError):
                                return {"status": "success", "raw_text": raw_text}

                        elif event.actions and event.actions.escalate:
                            last_error = f"Agent escalated: {event.error_message or 'Unknown'}"
                            break

                if last_error is None:
                    last_error = "No final response received"

            except Exception as e:
                last_error = str(e)
                logger.warning(f"[feedback] Attempt {attempt + 1} failed: {last_error}")

            if attempt < max_retries:
                await asyncio.sleep(2.0)

        return {"status": "error", "message": f"Feedback generation failed: {last_error}"}
