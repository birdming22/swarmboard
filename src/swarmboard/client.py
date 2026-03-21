#!/usr/bin/env python3
"""
SwarmBoard AI Agent Client — connects to the blackboard.

Each instance gets a unique instance_id (UUID) and synchronizes on startup.

Usage:
  uv run swarmboard-client --model qwen-2.5-coder [--router tcp://127.0.0.1:5570] [--pub tcp://127.0.0.1:5571]
"""

import argparse
import json
import signal
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

running = True


def signal_handler(sig, frame):
    global running
    print("[Client] Shutting down...", flush=True)
    running = False


def main():
    global running
    parser = argparse.ArgumentParser(description="SwarmBoard AI Agent Client")
    parser.add_argument(
        "--model", default="unknown", help="Model name (e.g. qwen-2.5-coder)"
    )
    parser.add_argument(
        "--instance-id", default=None, help="Instance ID (default: auto-generated)"
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

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    instance_id = args.instance_id or f"cli-{args.model}-{uuid.uuid4().hex[:4]}"
    source = make_source(instance_id, args.model, "ai_agent")

    ctx = zmq.Context()

    # DEALER socket — for request/reply with server
    dealer = ctx.socket(zmq.DEALER)
    dealer.setsockopt_string(zmq.IDENTITY, instance_id)
    dealer.connect(args.router)

    # SUB socket — for broadcast updates
    sub = ctx.socket(zmq.SUB)
    sub.connect(args.pub)
    sub.setsockopt_string(zmq.SUBSCRIBE, "blackboard")
    sub.setsockopt(zmq.RCVTIMEO, 500)

    print(f"[Client:{instance_id}] Model: {args.model}", flush=True)
    print(f"[Client:{instance_id}] ROUTER: {args.router}", flush=True)
    print(f"[Client:{instance_id}] PUB:    {args.pub}", flush=True)

    # Phase 1: Synchronize — request full blackboard history
    read_req = make_msg(source, Action.READ_REQUEST)
    dealer.send_string(encode_msg(read_req))
    print(f"[Client:{instance_id}] Sent READ_REQUEST, waiting for sync...", flush=True)

    synced = False
    sync_deadline = time.time() + 5.0

    while not synced and time.time() < sync_deadline:
        try:
            reply = dealer.recv_string()
        except zmq.Again:
            continue
        msg = decode_msg(reply)
        if msg and msg.get("action") == Action.READ_RESPONSE.value:
            history = json.loads(msg.get("content", "[]"))
            print(
                f"[Client:{instance_id}] Synced: {len(history)} entries from blackboard",
                flush=True,
            )
            for entry in history:
                src = entry.get("source", {})
                model = src.get("model_name", "?")
                eid = src.get("instance_id", "?")
                content = entry.get("content", "")
                print(f"  [{eid} ({model})] {content[:120]}", flush=True)
            synced = True

    if not synced:
        print(
            f"[Client:{instance_id}] Sync timeout — proceeding without history",
            flush=True,
        )

    # Phase 2: Main loop — listen for broadcasts, write on demand
    poller = zmq.Poller()
    poller.register(dealer, zmq.POLLIN)
    poller.register(sub, zmq.POLLIN)
    poller.register(sys.stdin, zmq.POLLIN)

    print(
        f"[Client:{instance_id}] Ready. Type a message and press Enter to write to blackboard.",
        flush=True,
    )
    print(f"[Client:{instance_id}] (Ctrl+C to quit)", flush=True)

    while running:
        try:
            socks = dict(poller.poll(timeout=500))
        except zmq.ZMQError:
            if not running:
                break
            continue

        # Broadcast from server (via SUB)
        if sub in socks:
            topic = sub.recv_string()
            data = sub.recv_string()
            msg = decode_msg(data)
            if msg and msg.get("action") == Action.STATE_UPDATE.value:
                entry = json.loads(msg.get("content", "{}"))
                src = entry.get("source", {})
                model = src.get("model_name", "?")
                eid = src.get("instance_id", "?")
                content = entry.get("content", "")
                # Don't echo our own writes twice
                if eid != instance_id:
                    print(f"  [BROADCAST] [{eid} ({model})] {content}", flush=True)

        # DEALER reply (write ACK, etc.)
        if dealer in socks:
            reply = dealer.recv_string()
            msg = decode_msg(reply)
            if msg:
                action = msg.get("action")
                if action == Action.WRITE.value:
                    pass  # silent ACK
                elif action == Action.READ_RESPONSE.value:
                    pass  # already handled

        # Stdin input — write to blackboard
        if sys.stdin in socks:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            write_msg = make_msg(source, Action.WRITE, line)
            dealer.send_string(encode_msg(write_msg))
            print(f"  [WRITE sent] {line[:120]}", flush=True)

    # Cleanup
    dealer.close()
    sub.close()
    ctx.term()
    print(f"[Client:{instance_id}] Shutdown complete.", flush=True)


if __name__ == "__main__":
    main()
