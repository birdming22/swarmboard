#!/usr/bin/env python3
"""
Read all messages from SwarmBoard blackboard.
Usage: python scripts/read.py
"""

import argparse
import json
import sys
import time
import uuid
import zmq

from swarmboard.protocol import (
    Action,
    decode_msg,
    encode_msg,
    make_msg,
    make_source,
)


def main():
    parser = argparse.ArgumentParser(description="Read messages from SwarmBoard")
    parser.add_argument(
        "--router",
        default="tcp://127.0.0.1:5570",
        help="Server ROUTER endpoint",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Number of retries on failure",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=3000,
        help="Timeout in milliseconds",
    )
    args = parser.parse_args()

    for attempt in range(args.retries):
        instance_id = f"reader-{uuid.uuid4().hex[:4]}"
        source = make_source(instance_id, "reader", "ai_agent")

        ctx = zmq.Context()
        dealer = ctx.socket(zmq.DEALER)
        dealer.setsockopt_string(zmq.IDENTITY, instance_id)
        dealer.RCVTIMEO = args.timeout
        dealer.connect(args.router)

        read_req = make_msg(source, Action.READ_REQUEST)
        dealer.send_string(encode_msg(read_req))

        try:
            reply = dealer.recv_string()
            msg = decode_msg(reply)

            if msg and msg.get("action") == Action.READ_RESPONSE.value:
                history = json.loads(msg.get("content", "[]"))
                print(json.dumps(history, indent=2, ensure_ascii=False))
                dealer.close()
                ctx.term()
                return

        except zmq.Again:
            if attempt < args.retries - 1:
                wait_time = 2**attempt
                time.sleep(wait_time)
        except Exception as e:
            if attempt < args.retries - 1:
                wait_time = 2**attempt
                time.sleep(wait_time)
        finally:
            dealer.close()
            ctx.term()

    print("[]")


if __name__ == "__main__":
    main()
