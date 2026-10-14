"""Reads the uploaded DAF PDF: the model extracts the profile; if it fails, the standard form is read by rules."""

import re
from pathlib import Path

import pdfplumber
from langchain_core.messages import HumanMessage, SystemMessage

from app.common.custom_exception import CustomException
from app.common.logger import getLogger
from app.common.utils import parseJsonResponse
from app.config.config import OPENAI_API_KEY
from app.prompts.daf_prompt import DAF_SYSTEM_PROMPT, DAF_USER_TEMPLATE
from app.schema.interview import DAFProfile

logger = getLogger(__name__)


class DafTool:
    def __init__(self, llm):
        self.llm = llm

    def extractTextFromPdf(self, file_path):
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"DAF file not found: {path}")
        pages = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text.strip())
        combined = "\n\n".join(pages).strip()
        if not combined:
            raise ValueError(f"No text could be extracted from DAF PDF: {path}")
        return combined

    def extractDafFields(self, file_path, raw_text=None, session_id: str = ""):
        text = raw_text or self.extractTextFromPdf(file_path)
        try:
            return self.extractWithLlm(text, session_id)
        except Exception as e:
            # The model is down or returned junk: read the standard UPSC DAF labels by rules instead of failing.
            logger.warning(f"DafTool LLM extraction failed ({e}); reading the DAF by rules")
            profile = parseDafText(text)
            if profile.hometown or profile.hobbies or profile.education:
                return profile
            logger.error(f"Error in DafTool: {str(e)}")
            raise CustomException("DafTool Failed", e)

    def extractWithLlm(self, text: str, session_id: str = ""):
        try:
            logger.info("DafTool started")
            if not OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY is required for DAF extraction")

            from app.common.utils import llmMessageText
            llm = self.llm.getLlm(temperature=0).bind(response_format={"type": "json_object"})
            from app.observability.langfuse_client import langchainInvokeConfig

            config = langchainInvokeConfig(
                session_id,
                run_name="daf_extraction",
                tags=["upsc-interview", "daf"],
            )
            response = llm.invoke(
                [
                    SystemMessage(content=DAF_SYSTEM_PROMPT),
                    HumanMessage(content=DAF_USER_TEMPLATE.format(raw_text=text[:6000])),
                ],
                config=config,
            )
            raw_content = llmMessageText(response)
            try:
                data = parseJsonResponse(raw_content)
            except Exception as parse_err:
                logger.warning(f"DafTool JSON parse retry without bind: {parse_err}")
                raw_llm = self.llm.getLlm(temperature=0)
                resp = raw_llm.invoke([
                    SystemMessage(content=DAF_SYSTEM_PROMPT + "\nOutput MUST start with '{' and end with '}'."),
                    HumanMessage(content=DAF_USER_TEMPLATE.format(raw_text=text[:4000])),
                ])
                data = parseJsonResponse(llmMessageText(resp))

            profile = DAFProfile.model_validate(data)
            logger.info("DafTool completed")
            return profile

        except Exception as e:
            logger.error(f"Error in DafTool: {str(e)}")
            raise CustomException("DafTool Failed", e)


# ---------- rules-based reading of the standard UPSC DAF (fallback when the model is unavailable) ----------

DATE = r"\d{2}-\d{2}-\d{4}"


def section(text: str, start: str, end: str) -> str:
    found = re.search(start + r"(.*?)" + end, text, re.DOTALL | re.IGNORECASE)
    return found.group(1) if found else ""


def parseDafText(text: str) -> DAFProfile:
    """Reads the fixed labels of a UPSC DAF-II: optional subject, city, education rows, employment rows, service
    preferences and hobbies. Less polished than the model's reading, but it never fails a candidate's upload."""
    lines = [line.strip() for line in text.splitlines()]
    optional = re.search(r"Optional Subject\s*:\s*([A-Z][A-Z &().-]+)", text)
    city = re.search(r"City:\s*([A-Za-z][A-Za-z .-]+)", text)

    education = []
    for index, line in enumerate(lines):
        row = re.match(r"^(10th or Equivalent|12th or Equivalent|Graduation|MASTER OF [A-Z ]+?|BACHELOR OF [A-Z ]+?)"
                       r"\s+(?:FIRST|SECOND|THIRD|DISTINCTION)?\s*(\d{4})\s*(.*)$", line, re.IGNORECASE)  # fmt: skip
        if row:
            places = [near for near in lines[max(0, index - 2): index + 3] if re.search(r"SCHOOL|COLLEGE|UNIVERSITY|INSTITUTE", near)]
            detail = " ".join([row.group(3)] + [place for place in places if place != line])
            detail = re.sub(r"\s+", " ", detail).strip(" ,")  # outside the f-string: Python 3.11 allows no backslash there
            education.append(f"{row.group(1)} ({row.group(2)}): {detail}")

    work = []
    employment = section(text, r"Details of your employment", r"\(b\) Your present Employment").splitlines()
    for index, line in enumerate(employment):
        if re.search(DATE, line):
            joined = " ".join(employment[max(0, index - 1): index + 2])
            joined = re.sub(rf"{DATE}|TILL DATE|TEMPORARY|PERMANENT", " ", joined)
            work.append(re.sub(r"\s+", " ", joined).strip(" ,"))

    preferences = [
        re.sub(r"\s+\d+$", "", line)
        for line in section(text, r"order of preference", r"Cadre").splitlines()
        if re.search(r"SERVICE|SERVICES", line) and re.search(r"\d+$", line)
    ]

    hobbies_text = section(text, r"Other extra-curricular activities and", r"\n\s*21\.")
    hobbies_text = re.sub(r"interests \(hobbies etc\.\)", " ", hobbies_text, flags=re.IGNORECASE)
    hobbies = [re.sub(r"\s+", " ", item).strip().lower() for item in hobbies_text.split(",") if item.strip()]

    return DAFProfile(
        hometown=city.group(1).strip() if city else "",
        optional_subject=optional.group(1).strip() if optional else "",
        education=education,
        work_experience=work,
        service_preferences=preferences,
        hobbies=hobbies,
    )
