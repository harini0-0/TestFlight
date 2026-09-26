"""Bedrock client. Used when GLASSWING_LLM=bedrock. Tests use RecordingModel."""

from __future__ import annotations

import json
import os


class BedrockClaude:
    def __init__(self, region: str | None = None) -> None:
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")

    def complete(self, *, model_id: str, system: str, user: str, schema_name: str) -> str:
        import boto3

        client = boto3.client("bedrock-runtime", region_name=self.region)
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2000,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        response = client.invoke_model(modelId=model_id, body=json.dumps(body))
        payload = json.loads(response["body"].read())
        return payload["content"][0]["text"]
