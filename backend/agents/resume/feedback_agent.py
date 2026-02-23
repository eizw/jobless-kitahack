"""
Resume Feedback Agent - Provides detailed feedback on resume content and structure.
Uses Google ADK with Gemini to analyze annotated resume data and generate actionable feedback.
"""

import json
import asyncio
import logging
from typing import Dict, Any

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

logger = logging.getLogger(__name__)

RESUME_FEEDBACK_INSTRUCTION = """You are an expert career coach and resume reviewer specializing in Malaysian tech job applications.

## Your Task
Analyze the provided resume data and generate comprehensive, actionable feedback to help the candidate improve their resume for Malaysian tech companies.

## Analysis Framework

### 1. Content Quality (30%)
- Clarity and impact of descriptions
- Use of action verbs and quantifiable achievements
- Relevance to target positions (Software Engineering, Data Science, etc.)
- Technical depth and specificity

### 2. Structure & Organization (25%)
- Logical flow and readability
- Section ordering and hierarchy
- Consistent formatting and spacing
- Professional presentation

### 3. Technical Skills Assessment (25%)
- Skill relevance to Malaysian tech market
- Skill level representation
- Technology stack alignment
- Certifications and learning evidence

### 4. Malaysian Market Fit (20%)
- Alignment with local company expectations (Grab, Shopee, Google Malaysia, etc.)
- Cultural and professional communication style
- Local education and experience presentation
- Language proficiency demonstration

## Required Output Structure

### Overall Assessment
- Overall score (1-10) with letter grade (A+ to F)
- 2-3 sentence executive summary
- Resume strengths summary
- Critical improvement areas

### Detailed Section Analysis
For each resume section (Personal Info, Education, Experience, Skills, Projects):
- Score (1-10) with specific feedback
- What works well
- Specific improvement suggestions
- Examples of better phrasing

### Actionable Recommendations
- 5-7 specific, prioritized action items
- Examples of improved content
- Suggestions for Malaysian tech market positioning
- Next steps for resume enhancement

### Market Positioning Advice
- Target company recommendations based on profile
- Salary range expectations (if applicable)
- Skill development priorities
- Interview preparation suggestions

## Important Guidelines
- Be constructive and encouraging while being honest
- Provide specific examples and suggestions
- Consider Malaysian cultural context and expectations
- Focus on actionable advice that can be implemented immediately
- Reference specific Malaysian companies and market trends when relevant
- Ensure feedback is tailored to the candidate's experience level
"""

class ResumeFeedbackAgent:
    """Resume feedback agent using Google ADK and Gemini for comprehensive resume analysis."""

    def __init__(self):
        self.session_service = InMemorySessionService()
        self.app_name = "jobless_resume_feedback"

        self.agent = LlmAgent(
            name="resume_feedback_agent",
            model="gemini-2.5-flash",
            description="Expert resume reviewer for Malaysian tech job market",
            instruction=RESUME_FEEDBACK_INSTRUCTION,
            disallow_transfer_to_parent=True,
            disallow_transfer_to_peers=True,
        )

        self.runner = Runner(
            agent=self.agent,
            app_name=self.app_name,
            session_service=self.session_service,
        )

    async def analyze_resume(
        self,
        session_id: str,
        annotated_resume: Dict[str, Any],
        target_position: str = "Software Engineer",
        target_companies: list = None,
        max_retries: int = 2,
    ) -> Dict[str, Any]:
        """
        Analyze annotated resume and generate comprehensive feedback.

        Args:
            session_id: Resume analysis session ID
            annotated_resume: Resume data from annotation agent
            target_position: Target job position/role
            target_companies: List of target companies
            max_retries: Number of retries on failure

        Returns:
            Dict with detailed feedback analysis
        """
        if target_companies is None:
            target_companies = ["Grab", "Shopee", "Google", "AirAsia", "TNG Digital"]

        # Build comprehensive analysis prompt
        prompt = f"""Analyze this resume for a {target_position} position in Malaysian tech companies.

## Target Information
- Target Position: {target_position}
- Target Companies: {', '.join(target_companies)}
- Session ID: {session_id}

## Resume Data:
{json.dumps(annotated_resume, indent=2)}

## Analysis Requirements:
1. Evaluate content quality, structure, technical skills, and Malaysian market fit
2. Provide specific, actionable feedback for each section
3. Suggest improvements for Malaysian tech company applications
4. Include market positioning advice and next steps

Generate comprehensive feedback following the specified output structure."""

        content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)],
        )

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                session = await self.session_service.create_session(
                    app_name=self.app_name,
                    user_id="resume_analyzer",
                    state={"session_id": session_id, "target_position": target_position},
                )

                async for event in self.runner.run_async(
                    user_id="resume_analyzer",
                    session_id=session.id,
                    new_message=content,
                ):
                    if event.is_final_response():
                        if event.content and event.content.parts:
                            raw_text = event.content.parts[0].text
                            try:
                                # Clean up the response
                                clean = raw_text.strip()
                                if clean.startswith("```"):
                                    clean = clean[clean.index("\n") + 1:]
                                    if clean.endswith("```"):
                                        clean = clean[:-3].strip()
                                
                                # Try to parse as JSON, fallback to raw text
                                try:
                                    parsed = json.loads(clean)
                                    parsed["status"] = "success"
                                    parsed["session_id"] = session_id
                                    logger.info(f"[resume_feedback] Success on attempt {attempt + 1}")
                                    return parsed
                                except json.JSONDecodeError:
                                    # Return structured response with raw text
                                    return {
                                        "status": "success",
                                        "session_id": session_id,
                                        "raw_feedback": raw_text,
                                        "feedback_format": "raw_text"
                                    }

                            except Exception as parse_error:
                                logger.error(f"Parse error on attempt {attempt + 1}: {parse_error}")
                                return {
                                    "status": "success",
                                    "session_id": session_id,
                                    "raw_feedback": raw_text,
                                    "feedback_format": "raw_text",
                                    "parse_error": str(parse_error)
                                }

                    elif event.actions and event.actions.escalate:
                        last_error = f"Agent escalated: {event.error_message or 'Unknown'}"
                        break

                if last_error is None:
                    last_error = "No final response received"

            except Exception as e:
                last_error = str(e)
                logger.warning(f"[resume_feedback] Attempt {attempt + 1} failed: {last_error}")

            if attempt < max_retries:
                await asyncio.sleep(2.0)

        return {
            "status": "error",
            "session_id": session_id,
            "message": f"Resume analysis failed: {last_error}"
        }

    async def quick_scan(
        self,
        annotated_resume: Dict[str, Any],
        session_id: str,
    ) -> Dict[str, Any]:
        """
        Perform a quick resume scan for initial assessment.

        Args:
            annotated_resume: Resume data from annotation agent
            session_id: Session identifier

        Returns:
            Quick assessment with basic metrics and recommendations
        """
        try:
            data = annotated_resume.get("data", {})
            
            # Extract basic metrics
            personal_info = data.get("personal_info", {})
            education = data.get("education", [])
            experience = data.get("experience", [])
            skills = data.get("skills", {})
            
            # Calculate basic scores
            completeness_score = self._calculate_completeness_score(data)
            experience_score = self._calculate_experience_score(experience)
            skills_score = self._calculate_skills_score(skills)
            
            overall_score = (completeness_score + experience_score + skills_score) / 3
            
            return {
                "status": "success",
                "session_id": session_id,
                "quick_assessment": {
                    "overall_score": round(overall_score, 1),
                    "completeness_score": completeness_score,
                    "experience_score": experience_score,
                    "skills_score": skills_score,
                    "grade": self._get_grade(overall_score),
                    "metrics": {
                        "education_entries": len(education),
                        "experience_entries": len(experience),
                        "technical_skills": len(skills.get("technical", [])),
                        "soft_skills": len(skills.get("soft", [])),
                        "has_contact_info": bool(personal_info.get("email") and personal_info.get("phone")),
                    },
                    "immediate_recommendations": self._get_quick_recommendations(data, overall_score)
                }
            }
            
        except Exception as e:
            logger.error(f"Quick scan failed: {e}")
            return {
                "status": "error",
                "session_id": session_id,
                "message": f"Quick scan failed: {str(e)}"
            }

    def _calculate_completeness_score(self, data: Dict[str, Any]) -> float:
        """Calculate resume completeness score."""
        sections = ["personal_info", "education", "experience", "skills"]
        present_sections = sum(1 for section in sections if data.get(section))
        return (present_sections / len(sections)) * 10

    def _calculate_experience_score(self, experience: list) -> float:
        """Calculate experience section score."""
        if not experience:
            return 2.0
        
        score = 5.0  # Base score for having experience
        for exp in experience:
            if exp.get("description") and len(exp["description"]) > 50:
                score += 1.0
            if exp.get("duration"):
                score += 0.5
        
        return min(score, 10.0)

    def _calculate_skills_score(self, skills: Dict[str, Any]) -> float:
        """Calculate skills section score."""
        if not skills:
            return 2.0
        
        tech_skills = len(skills.get("technical", []))
        soft_skills = len(skills.get("soft", []))
        
        score = 4.0  # Base score
        score += min(tech_skills * 0.3, 4.0)  # Max 4 points for tech skills
        score += min(soft_skills * 0.2, 2.0)  # Max 2 points for soft skills
        
        return min(score, 10.0)

    def _get_grade(self, score: float) -> str:
        """Convert score to letter grade."""
        if score >= 9.5:
            return "A+"
        elif score >= 9.0:
            return "A"
        elif score >= 8.0:
            return "B+"
        elif score >= 7.0:
            return "B"
        elif score >= 6.0:
            return "C+"
        elif score >= 5.0:
            return "C"
        elif score >= 4.0:
            return "D"
        else:
            return "F"

    def _get_quick_recommendations(self, data: Dict[str, Any], score: float) -> list:
        """Get quick improvement recommendations."""
        recommendations = []
        
        if not data.get("personal_info", {}).get("email"):
            recommendations.append("Add professional email address")
        
        if len(data.get("experience", [])) < 2:
            recommendations.append("Add more detailed work experience")
        
        if len(data.get("skills", {}).get("technical", [])) < 5:
            recommendations.append("Expand technical skills section")
        
        if score < 6.0:
            recommendations.append("Consider adding projects or certifications")
        
        return recommendations[:3]  # Return top 3 recommendations
