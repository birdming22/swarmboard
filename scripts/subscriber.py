#!/usr/bin/env python3
"""
ZMQ Subscriber for SwarmBoard.
Subscribes to blackboard updates via PUB socket (Port 5571).

Unlike daemon.py (polling), this receives PUSH notifications from Server.

Usage:
  python scripts/subscriber.py --model <model-name> [--pub tcp://127.0.0.1:5571] [--mention-filter]

With --mention-filter, only messages containing @<model-name> or @all are printed.
"""

import argparse
import json
import sys
import time

import zmq


def should_process_message(message, model_name):
    """Check if message mentions the model."""
    content = message.get("content", "")
    return f"@{model_name}" in content or "@all" in content


def main():
    parser = argparse.ArgumentParser(description="SwarmBoard ZMQ Subscriber")
    parser.add_argument("--model", required=True, help="Model name")
    parser.add_argument(
        "--pub",
        default="tcp://127.0.0.1:5571",
        help="Server PUB endpoint (default: tcp://127.0.0.1:5571)",
    )
    parser.add_argument(
        "--mention-filter",
        action="store_true",
        help="Only output messages that mention @<model-name> or @all",
    )
    args = parser.parse_args()

    ctx = zmq.Context()
    sub = ctx.socket(zmq.SUB)
    sub.connect(args.pub)
    sub.setsockopt_string(zmq.SUBSCRIBE, "blackboard")

    print(f"[subscriber] Connected to {args.pub}", file=sys.stderr)
    print(f"[subscriber] Listening for blackboard updates...", file=sys.stderr)

    total_messages = 0

    try:
        while True:
            # Receive topic
            topic = sub.recv_string()
            # Receive data
            data = sub.recv_string()

            # Parse message
            try:
                msg = json.loads(data)
                content_data = json.loads(msg.get("content", "{}"))

                # Skip messages from self
                source = content_data.get("source", {})
                if source.get("model_name") == args.model:
                    continue

                # Apply mention filter
                if args.mention_filter and not should_process_message(
                    content_data, args.model
                ):
                    continue

                total_messages += 1
                print(
                    f"[subscriber] New message (total: {total_messages})",
                    file=sys.stderr,
                )
                # Output to stdout for processing
                print(json.dumps(content_data, ensure_ascii=False))
                sys.stdout.flush()

            except json.JSONDecodeError:
                continue

    except KeyboardInterrupt:
        print(
            f"\n[subscriber] Stopped. Total messages: {total_messages}",
            file=sys.stderr,
        )
    finally:
        sub.close()
        ctx.term()


if __name__ == "__main__":
    main()
