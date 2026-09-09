from langchain_openai import ChatOpenAI

from app.config.config import CA_BRIEFING_MODEL, OPENAI_API_KEY, OPENAI_MODEL


class LLM:
    def __init__(self):
        self._llm = None

    def get_llm(self, temperature=0.4, max_tokens: int | None = None, model: str | None = None):
        kwargs = {
            "api_key": OPENAI_API_KEY,
            "model": model or OPENAI_MODEL,
            "temperature": temperature,
            "max_retries": 3,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        return ChatOpenAI(**kwargs)

    def get_briefing_llm(self, temperature=0.2, max_tokens: int | None = None):
        return self.get_llm(temperature=temperature, max_tokens=max_tokens, model=CA_BRIEFING_MODEL)

    @property
    def llm(self):
        if self._llm is None:
            self._llm = ChatOpenAI(
                api_key=OPENAI_API_KEY,
                model=OPENAI_MODEL,
                temperature=0.4,
                max_retries=3,
            )
        return self._llm


