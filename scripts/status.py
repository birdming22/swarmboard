#!/usr/bin/env python3
"""
Report agent status to SwarmBoard blackboard.
Usage: python scripts/status.py --status <listening|busy|offline> --model <model-name>
"""

import argparse
import sys
import uuid
import zmq

from swarmboard.protocol import (
    Action,
    decode_msg,
    encode_msg,
    make_msg,
    make_source,
)

STATUS_EMOJI = {
    "listening": "🟢",
    "busy": "🟡",
    "offline": "⚫",
}

STATUS_LABEL = {
    "listening": "正在監聽",
    "busy": "忙碌中",
    "offline": "已離線",
}


def main():
    parser = argparse.ArgumentParser(description="Report agent status to SwarmBoard")
    parser.add_argument(
        "--status",
        required=True,
        choices=["listening", "busy", "offline"],
        help="Agent status: listening, busy, or offline",
    )
    parser.add_argument("--model", required=True, help="Model name")
    parser.add_argument(
        "--router",
        default="tcp://127.0.0.1:5570",
        help="Server ROUTER endpoint",
    )
    args = parser.parse_args()

    instance_id = f"status-{args.model}-{uuid.uuid4().hex[:4]}"
    source = make_source(instance_id, args.model, "ai_agent")

    ctx = zmq.Context()
    dealer = ctx.socket(zmq.DEALER)
    dealer.setsockopt_string(zmq.IDENTITY, instance_id)
    dealer.connect(args.router)

    emoji = STATUS_EMOJI[args.status]
    label = STATUS_LABEL[args.status]
    content = f"[STATUS] {args.model}: {emoji} {label}"

    state_msg = make_msg(source, Action.STATE_UPDATE, content)
    dealer.send_string(encode_msg(state_msg))

    try:
        poller = zmq.Poller()
        poller.register(dealer, zmq.POLLIN)
        if dict(poller.poll(timeout=2000)):
            reply = dealer.recv_string()
            msg = decode_msg(reply)
            if msg:
                print(f"[STATUS] {args.model} -> {args.status} ({emoji}) - 已更新")
            else:
                print(f"[STATUS] {args.model} -> {args.status} ({emoji}) - 回覆異常")
        else:
            print(f"[STATUS] {args.model} -> {args.status} ({emoji}) - 無回覆")
    except Exception as e:
        print(f"[STATUS] Error: {e}")
        sys.exit(1)
    finally:
        dealer.close()
        ctx.term()


if __name__ == "__main__":
    main()
