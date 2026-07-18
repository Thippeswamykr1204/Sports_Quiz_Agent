from google import genai
from src.core.exceptions import GenerationError
from src.core.logging import get_logger

logger = get_logger("gemini_client")


class GeminiLLMClient:
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash", temperature: float = 0.7):
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._temperature = temperature

    def generate_json(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=f"{system_prompt}\n\n{user_prompt}",
                config={
                    "temperature": self._temperature,
                    "response_mime_type": "application/json",
                },
            )
            if not response.text:
                raise GenerationError("Gemini returned an empty response.")
            return response.text
        except Exception as exc:
            raise GenerationError(f"Gemini call failed: {exc}") from exc