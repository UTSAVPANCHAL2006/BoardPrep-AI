from pathlib import Path

import pdfplumber
from langchain_core.messages import HumanMessage, SystemMessage

from app.common.custom_exception import CustomException
from app.common.logger import get_logger
from app.common.utils import parse_json_response
from app.config.config import OPENAI_API_KEY
from app.prompts.daf_prompt import DAF_SYSTEM_PROMPT, DAF_USER_TEMPLATE
from app.schema.interview import DAFProfile

logger = get_logger(__name__)


class DafTool:
    def __init__(self, llm):
        self.llm = llm

    def extract_text_from_pdf(self, file_path):
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

    def extract_daf_fields(self, file_path, raw_text=None, session_id: str = ""):
        try:
            logger.info("DafTool started")
            if not OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY is required for DAF extraction")

            from app.common.utils import llm_message_text
            text = raw_text or self.extract_text_from_pdf(file_path)
            llm = self.llm.get_llm(temperature=0).bind(response_format={"type": "json_object"})
            from app.observability.langfuse_client import langchain_invoke_config

            config = langchain_invoke_config(
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
            raw_content = llm_message_text(response)
            try:
                data = parse_json_response(raw_content)
            except Exception as parse_err:
                logger.warning(f"DafTool JSON parse retry without bind: {parse_err}")
                raw_llm = self.llm.get_llm(temperature=0)
                resp = raw_llm.invoke([
                    SystemMessage(content=DAF_SYSTEM_PROMPT + "\nOutput MUST start with '{' and end with '}'."),
                    HumanMessage(content=DAF_USER_TEMPLATE.format(raw_text=text[:4000])),
                ])
                data = parse_json_response(llm_message_text(resp))

            profile = DAFProfile.model_validate(data)
            logger.info("DafTool completed")
            return profile

        except Exception as e:
            logger.error(f"Error in DafTool: {str(e)}")
            raise CustomException("DafTool Failed", e)
