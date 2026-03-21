#!/usr/bin/env python3
"""
Check for new messages on SwarmBoard blackboard.
Usage: python scripts/check.py --last-id <id> --exclude-self <model-name>
"""

import argparse
import json
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
    parser = argparse.ArgumentParser(description="Check for new messages on SwarmBoard")
    parser.add_argument(
        "--last-id", required=True, help="Last message ID to check from"
    )
    parser.add_argument(
        "--exclude-self", required=True, help="Model name to exclude (self)"
    )
    parser.add_argument(
        "--router",
        default="tcp://127.0.0.1:5570",
        help="Server ROUTER endpoint",
    )
    args = parser.parse_args()

    instance_id = f"checker-{uuid.uuid4().hex[:4]}"
    source = make_source(instance_id, args.exclude_self, "ai_agent")

    ctx = zmq.Context()
    dealer = ctx.socket(zmq.DEALER)
    dealer.setsockopt_string(zmq.IDENTITY, instance_id)
    dealer.RCVTIMEO = 2000
    dealer.connect(args.router)

    # Send READ_REQUEST
    read_req = make_msg(source, Action.READ_REQUEST)
    dealer.send_string(encode_msg(read_req))

    try:
        reply = dealer.recv_string()
        msg = decode_msg(reply)

        if msg and msg.get("action") == Action.READ_RESPONSE.value:
            history = json.loads(msg.get("content", "[]"))

            # Filter: exclude self, get messages after last-id
            # Use timestamp comparison instead of lexicographic msg_id comparison
            last_timestamp = 0
            for entry in history:
                if entry.get("msg_id") == args.last_id:
                    last_timestamp = entry.get("timestamp", 0)
                    break

            new_msgs = []
            for entry in history:
                if entry.get("timestamp", 0) > last_timestamp:
                    src = entry.get("source", {})
                    if src.get("model_name") != args.exclude_self:
                        new_msgs.append(entry)

            if new_msgs:
                print("NEW_MESSAGES")
                for entry in new_msgs:
                    print(json.dumps(entry))
            else:
                print("NO_NEW_MESSAGES")
        else:
            print("NO_NEW_MESSAGES")

    except zmq.Again:
        print("NO_NEW_MESSAGES")
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    finally:
        dealer.close()
        ctx.term()


if __name__ == "__main__":
    main()
