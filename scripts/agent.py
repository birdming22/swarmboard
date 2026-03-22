#!/usr/bin/env python3
"""
Simplified SwarmBoard Agent.
Uses pull-based architecture: register, request tasks, process, repeat.

Usage:
  python scripts/agent.py --name kilo --model xiaomi/mimo-v2-pro
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
    parser = argparse.ArgumentParser(description="SwarmBoard Agent")
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

    print(f"[agent] Connecting to {args.router}")

    # Step 1: Register
    register_msg = make_msg(source, Action.REGISTER, args.name)
    dealer.send_string(encode_msg(register_msg))

    # Wait for ACK
    poller = zmq.Poller()
    poller.register(dealer, zmq.POLLIN)
    if dict(poller.poll(timeout=5000)):
        reply_str = dealer.recv_string()
        reply = decode_msg(reply_str)
        if reply and reply.get("action") == Action.REGISTER_ACK.value:
            print(f"[agent] Registered as {args.name}")
        else:
            print(f"[agent] Registration failed")
            return
    else:
        print(f"[agent] Registration timeout")
        return

    # Step 2: Request tasks loop
    # Try up to 3 times, wait 10 seconds between attempts if no task
    print(f"[agent] Ready to receive tasks")
    task_count = 0
    max_retries = 3
    retry_wait = 10
    no_task_count = 0

    while no_task_count < max_retries:
        # Request task
        request_msg = make_msg(source, Action.REQUEST_TASK, "")
        dealer.send_string(encode_msg(request_msg))

        # Wait for response
        if dict(poller.poll(timeout=5000)):
            response_str = dealer.recv_string()
            response = decode_msg(response_str)

            if response:
                action = response.get("action", "")

                if action == Action.ASSIGN_TASK.value:
                    # Process task
                    task_data = json.loads(response.get("content", "{}"))
                    task_content = task_data.get("content", "")
                    task_msg_id = task_data.get("msg_id", "")
                    task_count += 1
                    no_task_count = 0  # Reset counter when task found
                    print(f"[agent] Task #{task_count}: {task_content[:100]}")

                    # Process task - send result to blackboard
                    result_msg = make_msg(
                        source,
                        Action.WRITE,
                        f"[RESULT] {args.name} 已處理任務 #{task_count}",
                    )
                    dealer.send_string(encode_msg(result_msg))
                    dealer.recv_string()  # ACK

                elif action == Action.NO_TASK.value:
                    no_task_count += 1
                    if no_task_count < max_retries:
                        print(
                            f"[agent] No task, waiting {retry_wait}s (attempt {no_task_count}/{max_retries})"
                        )
                        time.sleep(retry_wait)
                    else:
                        print(
                            f"[agent] No tasks after {max_retries} attempts, stopping"
                        )

        else:
            print(f"[agent] Timeout waiting for response")
            time.sleep(1)

    print(f"[agent] Processed {task_count} tasks, exiting")
    dealer.close()
    ctx.term()


if __name__ == "__main__":
    main()
