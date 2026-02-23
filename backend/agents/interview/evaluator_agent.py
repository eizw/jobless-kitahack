"""
Evaluator Agent - Scores each answer after the interview completes.
Uses Gemini 2.5 Pro for better reasoning on nuanced evaluation.
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

from models.schemas import EvaluationResult

logger = logging.getLogger(__name__)

EVALUATOR_INSTRUCTION = """You are an expert interview evaluator for top Malaysian tech companies.

## Your Task
Evaluate each question-answer pair from a completed interview. For each answer, score these dimensions (1-10):

1. **Relevance** (weight: 30%): How well does the answer address the actual question asked?
2. **Depth** (weight: 25%): How thorough and detailed is the answer? Does it include specific examples?
3. **Structure** (weight: 25%): Is the answer well-organized? For behavioral questions, did they use STAR method (Situation, Task, Action, Result)?
4. **Communication** (weight: 20%): Is the answer clear, concise, and professional?

## Scoring Guidelines
- 9-10: Exceptional - would impress any interviewer
- 7-8: Strong - demonstrates clear competence
- 5-6: Adequate - meets basic expectations but lacks depth
- 3-4: Weak - misses key points or is poorly structured
- 1-2: Poor - irrelevant or barely attempted

## For Each Question, Provide:
- A brief summary of what the candidate said
- Scores with justifications for each dimension
- An overall weighted score
- 2-3 specific strengths
- 2-3 specific areas for improvement

## Important
- Be fair but honest - constructive criticism helps candidates improve
- Consider the position and company context when evaluating
- For technical questions, evaluate accuracy of technical content
- For behavioral questions, specifically check for STAR method usage
- Provide actionable feedback, not vague comments
"""


class EvaluatorAgent:
    """Post-interview answer evaluator using Gemini 2.5 Pro."""

    def __init__(self):
        self.session_service = InMemorySessionService()
        self.app_name = "jobless_evaluator"

        self.agent = LlmAgent(
            name="answer_evaluator",
            model="gemini-2.5-flash",
            description="Expert interview answer evaluator",
            instruction=EVALUATOR_INSTRUCTION,
            output_schema=EvaluationResult,
            disallow_transfer_to_parent=True,
            disallow_transfer_to_peers=True,
        )

        self.runner = Runner(
            agent=self.agent,
            app_name=self.app_name,
            session_service=self.session_service,
        )

    async def evaluate(
        self,
        session_id: str,
        company: str,
        position: str,
        transcript_data: list[dict],
        max_retries: int = 2,
    ) -> Dict[str, Any]:
        """
        Evaluate a completed interview transcript.

        Args:
            session_id: The interview session ID
            company: Company name
            position: Position applied for
            transcript_data: List of {question, question_id, answer, evaluation_criteria}
            max_retries: Number of retries on failure

        Returns:
            Dict with evaluation results
        """
        prompt = f"""Evaluate this completed interview for a {position} position at {company}.

Session ID: {session_id}

## Interview Transcript:
{json.dumps(transcript_data, indent=2)}

Provide detailed evaluation for each question-answer pair."""

        content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)],
        )

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                session = await self.session_service.create_session(
                    app_name=self.app_name,
                    user_id="evaluator",
                    state={"session_id": session_id},
                )

                async for event in self.runner.run_async(
                    user_id="evaluator",
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
                                logger.info(f"[evaluator] Success on attempt {attempt + 1}")
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
                logger.warning(f"[evaluator] Attempt {attempt + 1} failed: {last_error}")

            if attempt < max_retries:
                await asyncio.sleep(2.0)

        return {"status": "error", "message": f"Evaluation failed: {last_error}"}
