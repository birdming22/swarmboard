#!/usr/bin/env python3
"""
SwarmBoard Human Commander Client — interactive terminal for humans.

Displays all blackboard broadcasts in real-time and allows typing commands.

Usage:
  uv run swarmboard-commander [--name commander] [--router tcp://127.0.0.1:5570] [--pub tcp://127.0.0.1:5571]
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
    print("\n[Commander] Shutting down...", flush=True)
    running = False


def main():
    global running
    parser = argparse.ArgumentParser(description="SwarmBoard Human Commander Client")
    parser.add_argument(
        "--name", default="commander", help="Display name (default: commander)"
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

    instance_id = f"cmd-{args.name}-{uuid.uuid4().hex[:4]}"
    source = make_source(instance_id, "human", "human_commander")

    ctx = zmq.Context()

    # DEALER socket
    dealer = ctx.socket(zmq.DEALER)
    dealer.setsockopt_string(zmq.IDENTITY, instance_id)
    dealer.connect(args.router)

    # SUB socket
    sub = ctx.socket(zmq.SUB)
    sub.connect(args.pub)
    sub.setsockopt_string(zmq.SUBSCRIBE, "blackboard")
    sub.setsockopt(zmq.RCVTIMEO, 500)

    print(f"[Commander] ID: {instance_id}", flush=True)
    print(f"[Commander] ROUTER: {args.router}", flush=True)
    print(f"[Commander] PUB:    {args.pub}", flush=True)

    # Sync
    read_req = make_msg(source, Action.READ_REQUEST)
    dealer.send_string(encode_msg(read_req))
    print("[Commander] Syncing blackboard...", flush=True)

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
            print(f"[Commander] Synced: {len(history)} entries", flush=True)
            if history:
                print("─── Blackboard History ───", flush=True)
                for i, entry in enumerate(history):
                    src = entry.get("source", {})
                    model = src.get("model_name", "?")
                    eid = src.get("instance_id", "?")
                    role = src.get("role", "?")
                    content = entry.get("content", "")
                    print(f"  #{i + 1} [{eid} ({model}/{role})] {content}", flush=True)
                print("─── End History ───", flush=True)
            synced = True

    if not synced:
        print("[Commander] Sync timeout — proceeding", flush=True)

    # Main loop
    poller = zmq.Poller()
    poller.register(dealer, zmq.POLLIN)
    poller.register(sub, zmq.POLLIN)
    poller.register(sys.stdin, zmq.POLLIN)

    print(
        "[Commander] Type a message and press Enter to broadcast a command.", flush=True
    )
    print("[Commander] (Ctrl+C to quit)\n", flush=True)

    while running:
        try:
            socks = dict(poller.poll(timeout=500))
        except zmq.ZMQError:
            if not running:
                break
            continue

        # Broadcast from server
        if sub in socks:
            topic = sub.recv_string()
            data = sub.recv_string()
            msg = decode_msg(data)
            if msg and msg.get("action") == Action.STATE_UPDATE.value:
                entry = json.loads(msg.get("content", "{}"))
                src = entry.get("source", {})
                model = src.get("model_name", "?")
                eid = src.get("instance_id", "?")
                role = src.get("role", "?")
                content = entry.get("content", "")
                if eid != instance_id:
                    print(f"  [{eid} ({model}/{role})] {content}", flush=True)

        # DEALER reply
        if dealer in socks:
            reply = dealer.recv_string()

        # Stdin — human command
        if sys.stdin in socks:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            write_msg = make_msg(source, Action.WRITE, f"[COMMANDER] {line}")
            dealer.send_string(encode_msg(write_msg))
            print(f"  >>> Sent: {line}", flush=True)

    # Cleanup
    dealer.close()
    sub.close()
    ctx.term()
    print("[Commander] Shutdown complete.", flush=True)


if __name__ == "__main__":
    main()
