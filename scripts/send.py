#!/usr/bin/env python3
"""
Simple script to send a message to SwarmBoard blackboard.
Usage: python scripts/send.py "your message" [--model model-name]
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
    parser = argparse.ArgumentParser(description="Send a message to SwarmBoard")
    parser.add_argument("message", help="Message content to send")
    parser.add_argument(
        "--model", default="kilocode", help="Model name (default: kilocode)"
    )
    parser.add_argument(
        "--router",
        default="tcp://127.0.0.1:5570",
        help="Server ROUTER endpoint (default: tcp://127.0.0.1:5570)",
    )
    parser.add_argument(
        "--pub",
        default="tcp://127.0.0.1:5571",
        help="Server PUB endpoint (default: tcp://127.0.0.1:5571)",
    )
    args = parser.parse_args()

    # Generate a unique instance ID for this sender
    instance_id = f"sender-{args.model}-{uuid.uuid4().hex[:4]}"
    source = make_source(instance_id, args.model, "ai_agent")

    ctx = zmq.Context()

    # DEALER socket — for request/reply with server
    dealer = ctx.socket(zmq.DEALER)
    dealer.setsockopt_string(zmq.IDENTITY, instance_id)
    dealer.connect(args.router)

    print(f"[Sender:{instance_id}] Model: {args.model}")
    print(f"[Sender:{instance_id}] Connecting to {args.router}")

    try:
        # Send WRITE message
        write_msg = make_msg(source, Action.WRITE, args.message)
        dealer.send_string(encode_msg(write_msg))
        print(f"[Sender:{instance_id}] Message sent: {args.message[:50]}...")

        # Wait briefly for ACK (optional)
        poller = zmq.Poller()
        poller.register(dealer, zmq.POLLIN)
        if dict(poller.poll(timeout=1000)):  # 1 second timeout
            reply = dealer.recv_string()
            msg = decode_msg(reply)
            if msg and msg.get("action") == Action.WRITE.value:
                print(f"[Sender:{instance_id}] Message acknowledged")
            else:
                print(f"[Sender:{instance_id}] Unexpected reply: {msg}")
        else:
            print(f"[Sender:{instance_id}] No ACK received (message may still be sent)")

    except Exception as e:
        print(f"[Sender:{instance_id}] Error: {e}")
        sys.exit(1)
    finally:
        dealer.close()
        ctx.term()


if __name__ == "__main__":
    main()
