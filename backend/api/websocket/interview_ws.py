"""
WebSocket handler for live voice interviews.
Bridges browser audio <-> Gemini Live API via ADK run_live().
"""

import json
import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from models.schemas import InterviewPhase
from services.session_manager import session_manager
from agents.interview.conductor_agent import create_conductor_agent

from google.adk.runners import Runner, LiveRequestQueue, RunConfig
from google.adk.sessions import InMemorySessionService
from google.genai import types

from config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


def _build_tools(session_id: str):
    """Build tool functions for the conductor agent, bound to a session."""

    def get_next_question() -> dict:
        """Get the next interview question. Returns the question text and metadata, or signals no more questions."""
        question = session_manager.get_next_question(session_id)
        if question is None:
            return {"has_question": False, "message": "No more questions. Proceed to closing phase."}

        # Record original question for evaluation (with question_id)
        session_manager.add_transcript_entry(
            session_id, role="interviewer", text=question.question, question_id=question.id
        )

        session = session_manager.get_session(session_id)
        total = len(session.questions) if session else 0
        current = session.current_question_index if session else 0

        return {
            "has_question": True,
            "question": question.question,
            "question_number": current,
            "total_questions": total,
            "question_type": question.type.value,
            "follow_ups": question.follow_ups,
        }

    def signal_phase_change(phase: str) -> dict:
        """Signal a phase transition in the interview. Phase must be one of: questions, closing, complete."""
        try:
            new_phase = InterviewPhase(phase)
        except ValueError:
            return {"success": False, "error": f"Invalid phase: {phase}"}

        success = session_manager.update_phase(session_id, new_phase)
        return {"success": success, "phase": phase}

    return [get_next_question, signal_phase_change]


async def _send_json(ws: WebSocket, data: dict):
    """Send a JSON message over WebSocket."""
    await ws.send_text(json.dumps(data))


@router.websocket("/ws/interview/{session_id}")
async def interview_websocket(ws: WebSocket, session_id: str):
    """
    WebSocket endpoint for live voice interviews.

    Protocol:
    - Client sends: binary PCM audio (16kHz, 16-bit, mono) OR JSON text messages
    - Server sends: binary PCM audio (24kHz) + JSON control messages
    - JSON messages: transcript, phase, metadata, interview_complete, error
    """
    session = session_manager.get_session(session_id)
    if not session:
        await ws.close(code=4004, reason="Session not found")
        return

    await ws.accept()
    logger.info(f"WebSocket connected for session {session_id}")

    # Build tools and agent
    tools = _build_tools(session_id)
    agent = create_conductor_agent(
        candidate_name=session.config.candidate_name,
        company=session.config.company,
        position=session.config.position,
        total_questions=len(session.questions),
        tools=tools,
        model=settings.GEMINI_LIVE_MODEL,
    )

    # Create ADK runner
    adk_session_service = InMemorySessionService()
    runner = Runner(
        agent=agent,
        app_name="jobless_conductor",
        session_service=adk_session_service,
    )

    adk_session = await adk_session_service.create_session(
        app_name="jobless_conductor",
        user_id=session_id,
        state={
            "candidate_name": session.config.candidate_name,
            "company": session.config.company,
            "position": session.config.position,
        },
    )

    # Send initial phase
    await _send_json(ws, {"type": "phase", "phase": "greeting"})
    await _send_json(ws, {
        "type": "metadata",
        "question_number": 0,
        "total_questions": len(session.questions),
    })

    try:
        live_queue = LiveRequestQueue()

        # Send initial prompt to trigger the agent's greeting
        initial_content = types.Content(
            role="user",
            parts=[types.Part.from_text(
                text="Please begin the interview. Greet the candidate and introduce yourself."
            )],
        )
        live_queue.send_content(initial_content)

        # Task: receive audio/text from browser and forward to Gemini
        audio_chunk_count = 0

        async def forward_client_input():
            nonlocal audio_chunk_count
            try:
                while True:
                    data = await ws.receive()
                    if "bytes" in data:
                        audio_chunk_count += 1
                        if audio_chunk_count <= 3 or audio_chunk_count % 100 == 0:
                            logger.info(f"[audio-in] Chunk #{audio_chunk_count}, size={len(data['bytes'])} bytes")
                        blob = types.Blob(mime_type="audio/pcm", data=data["bytes"])
                        live_queue.send_realtime(blob)
                    elif "text" in data:
                        msg = json.loads(data["text"])
                        if msg.get("type") == "text_input":
                            session_manager.add_transcript_entry(
                                session_id, role="candidate", text=msg["text"]
                            )
                            content = types.Content(
                                role="user",
                                parts=[types.Part.from_text(text=msg["text"])],
                            )
                            live_queue.send_content(content)
            except WebSocketDisconnect:
                logger.info(f"Client disconnected from {session_id}")
            except Exception as e:
                err_str = str(e).lower()
                if "disconnect" in err_str or "receive" in err_str:
                    logger.debug("Client receive loop ended: %s", e)
                else:
                    logger.error(f"Error receiving from client: {e}")
            finally:
                live_queue.close()

        # Configure live audio streaming with transcription
        run_config = RunConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription=types.AudioTranscriptionConfig(),
            input_audio_transcription=types.AudioTranscriptionConfig(),
        )

        # Task: receive events from Gemini and forward to browser
        async def forward_agent_responses():
            # Track last finalized text per role to skip duplicates
            last_final_output = ""
            last_final_input = ""

            try:
                async for event in runner.run_live(
                    session_id=adk_session.id,
                    user_id=session_id,
                    live_request_queue=live_queue,
                    run_config=run_config,
                ):
                    # --- Audio chunks (agent speaking) ---
                    if event.content and event.content.parts:
                        for part in event.content.parts:
                            if part.inline_data and part.inline_data.data:
                                await ws.send_bytes(part.inline_data.data)

                    # --- Agent speech transcription ---
                    if event.output_transcription and event.output_transcription.text:
                        text = event.output_transcription.text
                        is_final = bool(event.output_transcription.finished)
                        # Skip if this final text was already sent
                        if is_final and text == last_final_output:
                            continue
                        if is_final:
                            last_final_output = text
                        await _send_json(ws, {
                            "type": "transcript",
                            "role": "agent",
                            "text": text,
                            "is_final": is_final,
                        })

                    # --- User speech transcription ---
                    if event.input_transcription and event.input_transcription.text:
                        text = event.input_transcription.text
                        is_final = bool(event.input_transcription.finished)
                        # Skip if this final text was already sent
                        if is_final and text == last_final_input:
                            continue
                        if is_final:
                            last_final_input = text
                            session_manager.add_transcript_entry(
                                session_id, role="candidate", text=text,
                            )
                        await _send_json(ws, {
                            "type": "transcript",
                            "role": "user",
                            "text": text,
                            "is_final": is_final,
                        })

                    # Check if phase changed
                    current_session = session_manager.get_session(session_id)
                    if current_session:
                        await _send_json(ws, {
                            "type": "phase",
                            "phase": current_session.phase.value,
                        })
                        if current_session.phase == InterviewPhase.COMPLETE:
                            await _send_json(ws, {
                                "type": "interview_complete",
                                "session_id": session_id,
                            })
                            return

            except Exception as e:
                err_msg = str(e)
                if "1000" in err_msg:
                    logger.debug("Live connection closed normally")
                elif "1011" in err_msg:
                    logger.warning("Gemini Live connection closed (1011 internal error)")
                else:
                    logger.error(f"Error streaming agent responses: {e}")
                try:
                    if "1000" not in err_msg:
                        await _send_json(ws, {
                            "type": "error",
                            "message": "Voice connection was interrupted. Please start a new interview.",
                        })
                except Exception:
                    pass

        # Run both tasks concurrently
        await asyncio.gather(
            forward_client_input(),
            forward_agent_responses(),
            return_exceptions=True,
        )

    except Exception as e:
        logger.error(f"Live mode failed for {session_id}: {e}", exc_info=True)
        try:
            await _send_json(ws, {
                "type": "error",
                "message": f"Voice connection failed: {str(e)}. Please try again.",
            })
        except Exception:
            pass

    finally:
        logger.info(f"WebSocket closed for session {session_id}")
