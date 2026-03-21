#!/usr/bin/env python3
"""
Initialize/Register to SwarmBoard blackboard.
Usage: python scripts/init.py --name <name> --model <model>
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


def main():
    parser = argparse.ArgumentParser(description="Register to SwarmBoard")
    parser.add_argument("--name", required=True, help="Agent name")
    parser.add_argument("--model", required=True, help="Model name")
    parser.add_argument(
        "--router",
        default="tcp://127.0.0.1:5570",
        help="Server ROUTER endpoint",
    )
    args = parser.parse_args()

    instance_id = f"{args.name}-{uuid.uuid4().hex[:4]}"
    source = make_source(instance_id, args.model, "ai_agent")

    ctx = zmq.Context()
    dealer = ctx.socket(zmq.DEALER)
    dealer.setsockopt_string(zmq.IDENTITY, instance_id)
    dealer.connect(args.router)

    # Send JOIN message
    join_msg = make_msg(source, Action.WRITE, f"[JOIN] {args.name} ({args.model}) 已加入討論")
    dealer.send_string(encode_msg(join_msg))

    try:
        # Wait for ACK
        poller = zmq.Poller()
        poller.register(dealer, zmq.POLLIN)
        if dict(poller.poll(timeout=2000)):
            reply = dealer.recv_string()
            print(f"[JOIN] {args.name} ({args.model}) 已加入 - 收到回覆")
        else:
            print(f"[JOIN] {args.name} ({args.model}) 已加入 - 無回覆")
    except Exception as e:
        print(f"[JOIN] {args.name} ({args.model}) 已加入 - 錯誤: {e}")
    finally:
        dealer.close()
        ctx.term()


if __name__ == "__main__":
    main()
