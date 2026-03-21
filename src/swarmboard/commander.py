#!/usr/bin/env python3
"""
SwarmBoard Human Commander Client — interactive terminal for humans.

Displays all blackboard broadcasts in real-time and allows typing commands.

Usage:
  uv run swarmboard-commander [--name commander] [--router tcp://127.0.0.1:5570] [--pub tcp://127.0.0.1:5571]
"""

import argparse
import json
import select
import signal
import sys
import time
import uuid
from pathlib import Path

import zmq
from loguru import logger

LOG_FILE = Path("/home/k200/workspace/swarmboard/logs/commander.log")
LOG_FILE.parent.mkdir(exist_ok=True)

logger.add(
    LOG_FILE,
    rotation="10 MB",
    retention="1 day",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
)

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
    logger.info("Shutting down...")
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

    logger.info(f"ID: {instance_id}")
    logger.info(f"ROUTER: {args.router}")
    logger.info(f"PUB:    {args.pub}")

    # Sync
    read_req = make_msg(source, Action.READ_REQUEST)
    dealer.send_string(encode_msg(read_req))
    logger.info("Syncing blackboard...")

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
            logger.info(f"Synced: {len(history)} entries")
            if history:
                logger.info("─── Blackboard History ───")
                for i, entry in enumerate(history):
                    src = entry.get("source", {})
                    model = src.get("model_name", "?")
                    eid = src.get("instance_id", "?")
                    role = src.get("role", "?")
                    content = entry.get("content", "")
                    logger.info(f"  #{i + 1} [{eid} ({model}/{role})] {content}")
                logger.info("─── End History ───")
            synced = True

    if not synced:
        logger.warning("Sync timeout — proceeding")

    # Main loop
    poller = zmq.Poller()
    poller.register(dealer, zmq.POLLIN)
    poller.register(sub, zmq.POLLIN)

    logger.info("Type a message and press Enter to broadcast a command.")
    logger.info("(Ctrl+C to quit)")

    while running:
        # Check stdin separately using select
        readable, _, _ = select.select([sys.stdin], [], [], 0.1)
        if readable:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if line:
                write_msg = make_msg(source, Action.WRITE, f"[COMMANDER] {line}")
                dealer.send_string(encode_msg(write_msg))
                logger.info(f">>> Sent: {line}")
            continue

        # Poll ZMQ sockets
        try:
            socks = dict(poller.poll(timeout=100))
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
                    logger.info(f"[BROADCAST] [{eid} ({model}/{role})] {content}")

        # DEALER reply
        if dealer in socks:
            reply = dealer.recv_string()

    # Cleanup
    dealer.close()
    sub.close()
    ctx.term()
    logger.info("Shutdown complete.")


if __name__ == "__main__":
    main()
