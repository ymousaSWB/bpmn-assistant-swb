import json
import os
from typing import Any, Generator

from litellm import completion
from openai import OpenAI
from pydantic import BaseModel

from bpmn_assistant.config import logger
from bpmn_assistant.core.enums import Provider
from bpmn_assistant.core.enums.models import (
    AnthropicModels,
    AzureModels,
    OpenAIModels,
)
from bpmn_assistant.core.enums.output_modes import OutputMode
from bpmn_assistant.core.json_parser import parse_json_loose
from bpmn_assistant.core.llm_provider import LLMProvider


class LiteLLMProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        provider: Provider,
        output_mode: OutputMode = OutputMode.JSON,
    ):
        self.api_key = api_key
        self.provider = provider
        self.output_mode = output_mode

    def _is_openai_model(self, model: str) -> bool:
        return model in [m.value for m in OpenAIModels]

    def _is_azure_model(self, model: str) -> bool:
        return model in [m.value for m in AzureModels]

    def _supports_vision(self, model: str) -> bool:
        return self._is_openai_model(model) or self._is_azure_model(model)

    def _validate_vision_support(
        self,
        model: str,
        messages: list[dict[str, Any]],
    ) -> None:
        has_images = any(
            isinstance(msg.get("content"), list)
            and any(
                item.get("type") == "image_url"
                for item in msg.get("content", [])
            )
            for msg in messages
        )

        if has_images and not self._supports_vision(model):
            raise ValueError(
                "Vision input is only supported for OpenAI/Azure models. "
                f"Model '{model}' does not support image inputs."
            )

    def _get_azure_client(self) -> OpenAI:
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")

        if not endpoint:
            raise ValueError("AZURE_OPENAI_ENDPOINT is not configured")

        return OpenAI(
            base_url=endpoint,
            api_key=self.api_key,
        )

    def _messages_to_responses_input(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Convert our existing chat-style messages into input for the
        OpenAI Responses API.
        """
        result = []

        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")

            # Plain text
            if isinstance(content, str):
                result.append(
                    {
                        "role": role,
                        "content": content,
                    }
                )
                continue

            # Multimodal content
            converted_content = []

            for item in content:
                item_type = item.get("type")

                if item_type == "text":
                    converted_content.append(
                        {
                            "type": "input_text",
                            "text": item.get("text", ""),
                        }
                    )

                elif item_type == "image_url":
                    image_url = item.get("image_url", {}).get("url")

                    if image_url:
                        converted_content.append(
                            {
                                "type": "input_image",
                                "image_url": image_url,
                            }
                        )

            result.append(
                {
                    "role": role,
                    "content": converted_content,
                }
            )

        return result

    def _call_azure(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> str:
        client = self._get_azure_client()

        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", model)

        response = client.responses.create(
            model=deployment,
            input=self._messages_to_responses_input(messages),
            max_output_tokens=max_tokens,
        )

        raw_output = response.output_text

        if not raw_output:
            logger.error(f"Azure model returned empty output: {response}")
            raise Exception("Azure model returned empty content")

        return raw_output

    def call(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        structured_output: type[BaseModel] | None = None,
    ) -> str | dict[str, Any]:
        self._validate_vision_support(model, messages)

        if self.provider == Provider.AZURE:
            raw_output = self._call_azure(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
            )

            return self._process_response(raw_output)

        params: dict[str, Any] = {
            "api_key": self.api_key,
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 1,
        }

        if structured_output is not None or self.output_mode == OutputMode.JSON:
            params["response_format"] = {
                "type": "json_object",
            }

        logger.debug(
            f"Sending prompt "
            f"(provider={self.provider.value}, model={model}): "
            f"{json.dumps(messages, indent=2)}"
        )

        response = completion(**params)

        if not response.choices:
            logger.error(f"Empty response from model: {response.choices}")
            raise Exception("Empty response from model")

        raw_output = response.choices[0].message.content

        if raw_output is None:
            logger.error(f"Model returned None content: {response}")
            raise Exception("Model returned empty content")

        return self._process_response(raw_output)

    def stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> Generator[str, None, None]:
        self._validate_vision_support(model, messages)

        if self.provider == Provider.AZURE:
            client = self._get_azure_client()
            deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", model)

            with client.responses.stream(
                model=deployment,
                input=self._messages_to_responses_input(messages),
                max_output_tokens=max_tokens,
            ) as stream:
                for event in stream:
                    if event.type == "response.output_text.delta":
                        delta = event.delta or ""

                        if delta:
                            yield delta

            return

        response = completion(
            api_key=self.api_key,
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=1,
            stream=True,
        )

        for chunk in response:
            if not chunk.choices:
                continue

            fragment = chunk.choices[0].delta.content or ""

            if fragment:
                yield fragment

    def get_initial_messages(self) -> list[dict[str, str]]:
        return (
            [
                {
                    "role": "system",
                    "content": (
                        "You are a helpful assistant designed "
                        "to output JSON."
                    ),
                }
            ]
            if self.output_mode == OutputMode.JSON
            else []
        )

    def check_model_compatibility(self, model: str) -> bool:
        return (
            model in [m.value for m in OpenAIModels]
            or model in [m.value for m in AnthropicModels]
            or model in [m.value for m in AzureModels]
        )

    def _process_response(
        self,
        raw_output: str,
    ) -> str | dict[str, Any]:
        if self.output_mode == OutputMode.JSON:
            try:
                result = json.loads(raw_output)

            except json.decoder.JSONDecodeError as e:
                logger.debug(
                    "Strict JSON parsing failed for model response. "
                    f"Trying loose parser. Error: {e}"
                )

                try:
                    result = parse_json_loose(raw_output)

                except json.decoder.JSONDecodeError as loose_error:
                    logger.error(f"JSONDecodeError: {loose_error}")
                    logger.error(f"Raw output: {raw_output}")

                    raise Exception(
                        "Invalid JSON response from LLM"
                    ) from loose_error

            if not isinstance(result, dict):
                raise ValueError(
                    f"Invalid JSON response from LLM: {result}"
                )

            return result

        if self.output_mode == OutputMode.TEXT:
            return raw_output

        raise ValueError(
            f"Unsupported output mode: {self.output_mode}"
        )