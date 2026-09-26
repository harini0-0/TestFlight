"""Transactional outbox relay. Unpublished rows go to EventBridge and SQS."""

from __future__ import annotations

import json
import os
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from glasswing_adapters.db import OutboxRow

Publisher = Callable[[str, dict, str], None]


def relay_unpublished(session: Session, publisher: Publisher) -> int:
    rows = session.scalars(select(OutboxRow).where(OutboxRow.published == 0).order_by(OutboxRow.event_id)).all()
    count = 0
    for row in rows:
        publisher(row.event_type, json.loads(row.payload_json), row.event_id)
        row.published = 1
        count += 1
    return count


class EventBridgeSqsPublisher:
    """Publishes one domain event to EventBridge and, when configured, a consumer queue."""

    def __init__(self, bus_name: str, queue_url: str | None = None, endpoint_url: str | None = None) -> None:
        import boto3

        self.bus_name = bus_name
        self.queue_url = queue_url
        self.events = boto3.client("events", endpoint_url=endpoint_url)
        self.sqs = boto3.client("sqs", endpoint_url=endpoint_url) if queue_url else None

    def __call__(self, event_type: str, payload: dict, event_id: str) -> None:
        detail = json.dumps({"event_id": event_id, "payload": payload})
        self.events.put_events(
            Entries=[
                {
                    "Source": "glasswing",
                    "DetailType": event_type,
                    "Detail": detail,
                    "EventBusName": self.bus_name,
                }
            ]
        )
        if self.sqs is not None and self.queue_url:
            self.sqs.send_message(
                QueueUrl=self.queue_url,
                MessageBody=detail,
                MessageAttributes={"event_type": {"DataType": "String", "StringValue": event_type}},
            )


def default_publisher() -> Publisher:
    bus = os.environ.get("GLASSWING_EVENT_BUS", "").strip()
    if not bus:
        return lambda _event_type, _payload, _event_id: None
    return EventBridgeSqsPublisher(
        bus_name=bus,
        queue_url=os.environ.get("GLASSWING_SQS_QUEUE_URL") or None,
        endpoint_url=os.environ.get("AWS_ENDPOINT_URL") or None,
    )
