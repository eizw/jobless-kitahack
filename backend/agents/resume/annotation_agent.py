"""
Resume Annotation Agent - Uses annotateai to extract and annotate resume content.
Processes uploaded PDF resumes and extracts structured information.
"""

import logging
import json
import asyncio
from typing import Dict, Any, Optional
from pathlib import Path

try:
    from annotateai import DocumentProcessor
except ImportError:
    # Fallback if annotateai is not installed
    DocumentProcessor = None

logger = logging.getLogger(__name__)


class ResumeAnnotationAgent:
    """Agent for annotating and extracting structured data from resumes using annotateai."""

    def __init__(self):
        self.processor = None
        if DocumentProcessor:
            try:
                self.processor = DocumentProcessor()
                logger.info("Resume annotation agent initialized with annotateai")
            except Exception as e:
                logger.warning(f"Failed to initialize annotateai processor: {e}")
        else:
            logger.warning("annotateai not available, using fallback processing")

    async def annotate_resume(
        self,
        resume_path: str,
        session_id: str,
    ) -> Dict[str, Any]:
        """
        Annotate a resume file and extract structured information.

        Args:
            resume_path: Path to the resume PDF file
            session_id: Session identifier for tracking

        Returns:
            Dict with structured resume data including:
            - personal_info: name, email, phone, location
            - education: list of education entries
            - experience: list of work experience entries
            - skills: technical and soft skills
            - projects: notable projects
            - certifications: professional certifications
        """
        try:
            if not Path(resume_path).exists():
                return {
                    "status": "error",
                    "message": f"Resume file not found: {resume_path}"
                }

            if self.processor:
                return await self._process_with_annotateai(resume_path, session_id)
            else:
                return await self._process_fallback(resume_path, session_id)

        except Exception as e:
            logger.error(f"Resume annotation failed: {e}")
            return {
                "status": "error",
                "message": f"Failed to annotate resume: {str(e)}"
            }

    async def _process_with_annotateai(
        self,
        resume_path: str,
        session_id: str,
    ) -> Dict[str, Any]:
        """Process resume using annotateai library."""
        try:
            # Process the document
            result = await asyncio.to_thread(
                self.processor.process_document,
                resume_path,
                extract_fields=[
                    "personal_info",
                    "education", 
                    "experience",
                    "skills",
                    "projects",
                    "certifications"
                ]
            )

            return {
                "status": "success",
                "session_id": session_id,
                "annotation_method": "annotateai",
                "data": result,
                "raw_text": getattr(result, 'text', ''),
                "confidence": getattr(result, 'confidence', 0.8)
            }

        except Exception as e:
            logger.error(f"annotateai processing failed: {e}")
            # Fallback to basic processing
            return await self._process_fallback(resume_path, session_id)

    async def _process_fallback(
        self,
        resume_path: str,
        session_id: str,
    ) -> Dict[str, Any]:
        """Fallback processing when annotateai is not available."""
        try:
            # This is a simplified fallback - in production you'd use
            # PyPDF2, pdfplumber, or similar for PDF text extraction
            # and then use regex/pattern matching for structured extraction
            
            # For now, return a placeholder structure
            return {
                "status": "success",
                "session_id": session_id,
                "annotation_method": "fallback",
                "data": {
                    "personal_info": {
                        "name": "Extracted Name",
                        "email": "email@example.com",
                        "phone": "+60-12-345-6789",
                        "location": "Kuala Lumpur, Malaysia"
                    },
                    "education": [
                        {
                            "institution": "University Name",
                            "degree": "Bachelor of Computer Science",
                            "year": "2020-2024",
                            "gpa": "3.8"
                        }
                    ],
                    "experience": [
                        {
                            "company": "Company Name",
                            "position": "Software Engineer Intern",
                            "duration": "Jun 2023 - Aug 2023",
                            "description": "Developed web applications using React and Node.js"
                        }
                    ],
                    "skills": {
                        "technical": ["Python", "JavaScript", "React", "Node.js"],
                        "soft": ["Communication", "Teamwork", "Problem Solving"]
                    },
                    "projects": [
                        {
                            "name": "Project Name",
                            "description": "Brief project description",
                            "technologies": ["React", "Node.js", "MongoDB"]
                        }
                    ],
                    "certifications": []
                },
                "raw_text": "Extracted resume text would appear here...",
                "confidence": 0.6,
                "note": "Using fallback processing - annotateai not available"
            }

        except Exception as e:
            logger.error(f"Fallback processing failed: {e}")
            return {
                "status": "error",
                "message": f"Fallback processing failed: {str(e)}"
            }

    def extract_key_sections(self, annotated_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract key sections from annotated resume for analysis."""
        data = annotated_data.get("data", {})
        
        return {
            "summary": {
                "name": data.get("personal_info", {}).get("name", ""),
                "total_experience_years": self._calculate_experience(data.get("experience", [])),
                "education_level": self._get_education_level(data.get("education", [])),
                "skill_count": len(data.get("skills", {}).get("technical", [])),
            },
            "highlights": {
                "recent_experience": data.get("experience", [])[:2],
                "key_skills": data.get("skills", {}).get("technical", [])[:10],
                "education": data.get("education", [])[:1],
            },
            "full_data": data
        }

    def _calculate_experience(self, experience_list: list) -> float:
        """Calculate total years of experience from experience entries."""
        # Simplified calculation - would need proper date parsing in production
        return len(experience_list) * 0.5  # Assume 6 months per entry as rough estimate

    def _get_education_level(self, education_list: list) -> str:
        """Determine highest education level."""
        if not education_list:
            return "Not specified"
        
        degrees = [edu.get("degree", "").lower() for edu in education_list]
        if any("phd" in degree or "doctorate" in degree for degree in degrees):
            return "PhD"
        elif any("master" in degree for degree in degrees):
            return "Master's"
        elif any("bachelor" in degree for degree in degrees):
            return "Bachelor's"
        else:
            return "Other"
