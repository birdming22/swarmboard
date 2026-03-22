"""
ZMB Protocol — shared message schema, action enum, and helpers.

All ZMQ payloads are JSON-encoded Message objects with the following structure:

    {
        "msg_id": "msg-<uuid4>",
        "timestamp": <unix_epoch_seconds>,
        "source": {
            "instance_id": "<uuid>",
            "model_name": "<model>",
            "role": "ai_agent|human_commander"
        },
        "action": "WRITE|READ_REQUEST|READ_RESPONSE|STATE_UPDATE",
        "content": "<string>"
    }
"""

import json
import time
import uuid
from enum import Enum


class Action(str, Enum):
    WRITE = "WRITE"
    READ_REQUEST = "READ_REQUEST"
    READ_RESPONSE = "READ_RESPONSE"
    STATE_UPDATE = "STATE_UPDATE"
    REGISTER = "REGISTER"
    REGISTER_ACK = "REGISTER_ACK"
    REQUEST_TASK = "REQUEST_TASK"
    ASSIGN_TASK = "ASSIGN_TASK"
    NO_TASK = "NO_TASK"


def make_source(instance_id: str, model_name: str, role: str) -> dict:
    return {
        "instance_id": instance_id,
        "model_name": model_name,
        "role": role,
    }


def make_msg(source: dict, action: Action, content: str = "") -> dict:
    return {
        "msg_id": f"msg-{uuid.uuid4().hex[:8]}",
        "timestamp": int(time.time()),
        "source": source,
        "action": action.value,
        "content": content,
    }


def encode_msg(msg: dict) -> str:
    return json.dumps(msg, ensure_ascii=False)


def decode_msg(raw: str) -> dict | None:
    try:
        msg = json.loads(raw)
        if not isinstance(msg, dict):
            return None
        if "action" not in msg:
            return None
        return msg
    except (json.JSONDecodeError, TypeError):
        return None
