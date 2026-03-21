#!/usr/bin/env python3
"""
SwarmBoard Server — ZMQ multi-instance blackboard.

Opens two ZMQ sockets:
  - ROUTER (Port 5570): handles WRITE and READ_REQUEST from clients
  - PUB    (Port 5571): broadcasts STATE_UPDATE on every new blackboard entry

Usage:
  uv run swarmboard-server [--router-bind tcp://0.0.0.0:5570] [--pub-bind tcp://0.0.0.0:5571]
"""

import argparse
import json
import signal
import sys
import time
from pathlib import Path

import zmq
from loguru import logger

LOG_FILE = Path("/home/k200/workspace/swarmboard/logs/server.log")
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
    parser = argparse.ArgumentParser(description="SwarmBoard Server")
    parser.add_argument(
        "--router-bind",
        default="tcp://0.0.0.0:5570",
        help="ROUTER bind address (default: tcp://0.0.0.0:5570)",
    )
    parser.add_argument(
        "--pub-bind",
        default="tcp://0.0.0.0:5571",
        help="PUB bind address (default: tcp://0.0.0.0:5571)",
    )
    parser.add_argument(
        "--data-file",
        default="/home/k200/workspace/swarmboard/data/blackboard.json",
        help="Blackboard persistence file",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    ctx = zmq.Context()

    # ROUTER socket — handles client requests
    router = ctx.socket(zmq.ROUTER)
    router.bind(args.router_bind)

    # PUB socket — broadcasts blackboard updates
    pub = ctx.socket(zmq.PUB)
    pub.bind(args.pub_bind)

    # Blackboard persistence
    data_file = Path(args.data_file)
    data_file.parent.mkdir(parents=True, exist_ok=True)

    # In-memory blackboard: list of message dicts
    blackboard: list[dict] = []

    # Load from file if exists
    if data_file.exists():
        try:
            blackboard = json.loads(data_file.read_text())
            logger.info(f"Loaded {len(blackboard)} entries from {data_file}")
        except Exception as e:
            logger.warning(f"Failed to load blackboard: {e}")
            blackboard = []

    def save_blackboard():
        try:
            data_file.write_text(json.dumps(blackboard, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.error(f"Failed to save blackboard: {e}")

    server_source = make_source("server", "swarmboard", "server")

    logger.info(f"ROUTER bound to {args.router_bind}")
    logger.info(f"PUB    bound to {args.pub_bind}")

    poller = zmq.Poller()
    poller.register(router, zmq.POLLIN)

    while running:
        try:
            socks = dict(poller.poll(timeout=500))
        except zmq.ZMQError:
            if not running:
                break
            continue

        if router not in socks:
            continue

        # ROUTER receives from DEALER: [client_id, payload] (2 frames)
        # or [client_id, empty, payload] (3 frames, depending on ZMQ version)
        frames = router.recv_multipart()
        if len(frames) < 2:
            continue

        client_id = frames[0]
        payload_str = frames[-1].decode("utf-8", errors="replace")

        msg = decode_msg(payload_str)
        if msg is None:
            continue

        action = msg.get("action", "")
        source = msg.get("source", {})
        instance_id = source.get("instance_id", "unknown")

        if action == Action.READ_REQUEST.value:
            # Return full blackboard history
            response = make_msg(
                server_source,
                Action.READ_RESPONSE,
                json.dumps(blackboard, ensure_ascii=False),
            )
            router.send_multipart(
                [
                    client_id,
                    encode_msg(response).encode("utf-8"),
                ]
            )
            logger.info(
                f"READ_REQUEST from {instance_id} → sent {len(blackboard)} entries"
            )

        elif action == Action.WRITE.value:
            # Append to blackboard
            entry = {
                "msg_id": msg.get("msg_id", f"msg-{int(time.time() * 1000)}"),
                "timestamp": msg.get("timestamp", int(time.time())),
                "source": source,
                "action": Action.WRITE.value,
                "content": msg.get("content", ""),
            }
            blackboard.append(entry)

            # Save to file
            save_blackboard()

            # ACK to the writer
            ack = make_msg(server_source, Action.WRITE, "OK")
            router.send_multipart(
                [
                    client_id,
                    encode_msg(ack).encode("utf-8"),
                ]
            )

            # Broadcast via PUB
            pub_update = make_msg(
                server_source,
                Action.STATE_UPDATE,
                json.dumps(entry, ensure_ascii=False),
            )
            pub.send_string("blackboard", zmq.SNDMORE)
            pub.send_string(encode_msg(pub_update))

            model = source.get("model_name", "?")
            logger.info(f"WRITE from {instance_id} ({model}): {entry['content'][:80]}")

        else:
            logger.warning(f"Unknown action '{action}' from {instance_id}")

    # Cleanup
    logger.info(f"Final blackboard size: {len(blackboard)}")
    router.close()
    pub.close()
    ctx.term()
    logger.info("Shutdown complete.")


if __name__ == "__main__":
    main()
