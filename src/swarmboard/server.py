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
    print("[Server] Shutting down...", flush=True)
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

    # In-memory blackboard: list of message dicts
    blackboard: list[dict] = []

    server_source = make_source("server", "swarmboard", "server")

    print(f"[Server] ROUTER bound to {args.router_bind}", flush=True)
    print(f"[Server] PUB    bound to {args.pub_bind}", flush=True)

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
            print(
                f"[Server] READ_REQUEST from {instance_id} → sent {len(blackboard)} entries",
                flush=True,
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
            print(
                f"[Server] WRITE from {instance_id} ({model}): {entry['content'][:80]}",
                flush=True,
            )

        else:
            print(f"[Server] Unknown action '{action}' from {instance_id}", flush=True)

    # Cleanup
    print(f"[Server] Final blackboard size: {len(blackboard)}", flush=True)
    router.close()
    pub.close()
    ctx.term()
    print("[Server] Shutdown complete.", flush=True)


if __name__ == "__main__":
    main()
