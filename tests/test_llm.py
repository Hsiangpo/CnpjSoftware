import pytest

from cnpj_tool.llm import extract_json_object
from cnpj_tool.llm import LLMClient
from cnpj_tool.models import CompanyData


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


class TimeoutOnChatSession:
    def __init__(self):
        self.post_calls = 0

    def get(self, *_args, **_kwargs):
        return FakeResponse(200, {"data": []})

    def post(self, *_args, **_kwargs):
        self.post_calls += 1
        raise TimeoutError("chat timed out")


class FallbackSession:
    def __init__(self):
        self.post_calls: list[str] = []

    def get(self, *_args, **_kwargs):
        return FakeResponse(200, {"data": []})

    def post(self, *_args, **kwargs):
        model = kwargs["json"]["model"]
        self.post_calls.append(model)
        if model == "primary-model":
            raise TimeoutError("primary timed out")
        return FakeResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"names":["Carlos","Poliana"],'
                                '"role":"Sócio-Administrador",'
                                '"confidence":0.97,'
                                '"reasoning":"The QSA shows both people with the highest role."}'
                            )
                        }
                    }
                ]
            },
        )


class RetryOnceSession:
    def __init__(self):
        self.get_calls = 0
        self.post_calls = 0

    def get(self, *_args, **_kwargs):
        self.get_calls += 1
        return FakeResponse(200, {"data": []})

    def post(self, *_args, **kwargs):
        self.post_calls += 1
        if self.post_calls == 1:
            return FakeResponse(
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": '{"pong": true}'
                            }
                        }
                    ]
                },
            )
        if self.post_calls == 2:
            raise TimeoutError("first analysis attempt timed out")
        return FakeResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"names":["Carlos"],'
                                '"role":"Sócio-Administrador",'
                                '"confidence":0.91,'
                                '"reasoning":"Retry succeeded."}'
                            )
                        }
                    }
                ]
            },
        )


def test_extract_json_object_handles_markdown_wrapper():
    text = """
    ```json
    {"names": ["Maria"], "role": "Presidente", "confidence": 0.91}
    ```
    """

    assert extract_json_object(text) == {
        "names": ["Maria"],
        "role": "Presidente",
        "confidence": 0.91,
    }


def test_extract_json_object_handles_text_around_json():
    assert extract_json_object('Resultado: {"names": ["Ana"], "role": "Diretor"} fim') == {
        "names": ["Ana"],
        "role": "Diretor",
    }


def test_llm_client_disables_itself_after_failed_preflight():
    client = LLMClient(
        api_key="sk-test",
        base_urls=["https://api.example.test/v1"],
        model="demo-model",
        timeout_seconds=30,
    )
    client.session = TimeoutOnChatSession()

    assert client.preflight(chat_timeout_seconds=3) is False

    with pytest.raises(ValueError, match="chat timed out"):
        client.analyze_company(
            CompanyData(
                cnpj="03541629000137",
                formatted_cnpj="03.541.629/0001-37",
                url="https://cnpj.biz/03541629000137",
            )
        )

    assert client.session.post_calls == 1


def test_llm_client_uses_fallback_model_when_primary_fails():
    client = LLMClient(
        api_key="sk-test",
        base_urls=["https://api.example.test/v1"],
        model="primary-model",
        fallback_models=["fallback-model"],
        timeout_seconds=30,
    )
    client.session = FallbackSession()

    assert client.preflight(chat_timeout_seconds=3) is True

    result = client.analyze_company(
        CompanyData(
            cnpj="03541629000137",
            formatted_cnpj="03.541.629/0001-37",
            url="https://cnpj.biz/03541629000137",
        )
    )

    assert result.names == ["Carlos", "Poliana"]
    assert result.role == "Sócio-Administrador"
    assert result.analysis_source == "llm_fallback_model"
    assert result.model_used == "fallback-model"
    assert "fallback model fallback-model was used" in result.reasoning
    assert client.session.post_calls == ["primary-model", "fallback-model", "fallback-model"]


def test_llm_client_retries_analysis_after_transient_failure():
    client = LLMClient(
        api_key="sk-test",
        base_urls=["https://api.example.test/v1"],
        model="primary-model",
        timeout_seconds=30,
    )
    client.session = RetryOnceSession()

    assert client.preflight(chat_timeout_seconds=3) is True

    result = client.analyze_company(
        CompanyData(
            cnpj="03541629000137",
            formatted_cnpj="03.541.629/0001-37",
            url="https://cnpj.biz/03541629000137",
        )
    )

    assert result.names == ["Carlos"]
    assert result.role == "Sócio-Administrador"
    assert result.analysis_source == "llm"
    assert result.model_used == "primary-model"
    assert client.session.post_calls == 3
