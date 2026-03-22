#!/usr/bin/env python3
"""
SwarmBoard Server — ZMQ multi-instance blackboard.

Opens two ZMQ sockets:
  - ROUTER (Port 5570): handles WRITE and READ_REQUEST from clients
  - PUB    (Port 5571): broadcasts STATE_UPDATE on every new blackboard entry

Usage:
  uv run swarmboard-server [--router-bind tcp://0.0.0.0:5570] [--pub-bind tcp://0.0.0.0:5571]
"""

SERVER_VERSION = "0.5.0"  # Version with heartbeat feature

import argparse
import json
import signal
import sys
import time
import uuid
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

    # Registered agents: dict of instance_id -> agent info
    agents: dict[str, dict] = {}

    # Task queue: list of pending tasks (messages that need processing)
    task_queue: list[dict] = []

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

    def handle_command(content: str, source: dict) -> str | None:
        """Handle commands starting with /."""
        if not content.startswith("/"):
            return None

        parts = content.split()
        cmd = parts[0].lower()

        if cmd == "/help":
            return """可用命令：
/help - 顯示此幫助訊息
/version - 顯示 Server 版本
/status - 顯示 Server 狀態
/sessions - 列出已註冊的 Agent
/reload - 重新載入黑板"""

        elif cmd == "/version":
            return f"SwarmBoard Server v{SERVER_VERSION}"

        elif cmd == "/status":
            return f"""Server 狀態：
- 版本：{SERVER_VERSION}
- 已註冊 Agent：{len(agents)} 個
- 黑板訊息數：{len(blackboard)} 條
- 任務隊列：{len(task_queue)} 個"""

        elif cmd == "/sessions":
            if not agents:
                return "目前沒有已註冊的 Agent"
            lines = ["已註冊的 Agent："]
            for instance_id, info in agents.items():
                name = info.get("name", "unknown")
                model = info.get("model_name", "unknown")
                last_seen = info.get("last_seen", 0)
                age = int(time.time()) - last_seen
                lines.append(f"- {name} ({model}) - {age}秒前活動")
            return "\n".join(lines)

        elif cmd == "/reload":
            # Reload blackboard from file
            try:
                if data_file.exists():
                    new_blackboard = json.loads(data_file.read_text())
                    blackboard.clear()
                    blackboard.extend(new_blackboard)
                    return f"已重新載入 {len(blackboard)} 條黑板訊息"
                else:
                    return "黑板檔案不存在"
            except Exception as e:
                return f"載入失敗: {e}"

        else:
            return f"未知命令：{cmd}。輸入 /help 查看可用命令。"

    logger.info(f"ROUTER bound to {args.router_bind}")
    logger.info(f"PUB    bound to {args.pub_bind}")

    poller = zmq.Poller()
    poller.register(router, zmq.POLLIN)

    # Heartbeat settings
    heartbeat_interval = 10  # seconds (reduced from 30)
    last_heartbeat = time.time()

    while running:
        try:
            socks = dict(poller.poll(timeout=500))
        except zmq.ZMQError:
            if not running:
                break
            continue

        # Send heartbeat to registered agents
        current_time = time.time()
        if current_time - last_heartbeat >= heartbeat_interval:
            for instance_id in list(agents.keys()):
                heartbeat_msg = make_msg(
                    server_source, Action.STATE_UPDATE, "heartbeat"
                )
                try:
                    router.send_multipart(
                        [
                            instance_id.encode("utf-8"),
                            encode_msg(heartbeat_msg).encode("utf-8"),
                        ]
                    )
                except Exception:
                    pass  # Agent may have disconnected
            last_heartbeat = current_time
            if agents:
                logger.debug(f"Heartbeat sent to {len(agents)} agents")

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

        elif action == Action.REGISTER.value:
            # Register agent
            agent_info = {
                "instance_id": instance_id,
                "model_name": source.get("model_name", "unknown"),
                "name": msg.get("content", source.get("model_name", "unknown")),
                "registered_at": int(time.time()),
                "last_seen": int(time.time()),
            }
            agents[instance_id] = agent_info
            logger.info(f"REGISTER from {instance_id} ({agent_info['name']})")

            # Broadcast agent joined
            join_entry = {
                "msg_id": f"msg-{uuid.uuid4().hex[:8]}",
                "timestamp": int(time.time()),
                "source": source,
                "action": Action.WRITE.value,
                "content": f"[JOIN] {agent_info['name']} ({agent_info['model_name']}) 已加入",
            }
            blackboard.append(join_entry)
            save_blackboard()

            # Broadcast via PUB
            pub_update = make_msg(
                server_source,
                Action.STATE_UPDATE,
                json.dumps(join_entry, ensure_ascii=False),
            )
            pub.send_string("blackboard", zmq.SNDMORE)
            pub.send_string(encode_msg(pub_update))

            # Send ACK to agent
            ack = make_msg(
                server_source,
                Action.REGISTER_ACK,
                json.dumps({"status": "ok", "name": agent_info["name"]}),
            )
            router.send_multipart([client_id, encode_msg(ack).encode("utf-8")])

        elif action == Action.REQUEST_TASK.value:
            # Update last seen
            if instance_id in agents:
                agents[instance_id]["last_seen"] = int(time.time())

            # Find task for this agent (message with @mention)
            agent_name = agents.get(instance_id, {}).get("name", "")
            model_name = source.get("model_name", "")

            found_task = None
            for entry in blackboard:
                content = entry.get("content", "")
                entry_source = entry.get("source", {})
                entry_instance = entry_source.get("instance_id", "")
                # Skip if:
                # 1. Already assigned
                # 2. Is a RESULT message
                # 3. From the same agent
                if entry.get("assigned_to"):
                    continue
                if content.startswith("[RESULT]"):
                    continue
                if entry_instance == instance_id:
                    continue
                # Check if this message mentions the agent
                if f"@{agent_name}" in content or f"@{model_name}" in content:
                    found_task = entry
                    entry["assigned_to"] = instance_id
                    break

            if found_task:
                response = make_msg(
                    server_source,
                    Action.ASSIGN_TASK,
                    json.dumps(found_task, ensure_ascii=False),
                )
                logger.info(
                    f"ASSIGN_TASK to {instance_id}: {found_task['content'][:50]}"
                )
            else:
                response = make_msg(
                    server_source,
                    Action.NO_TASK,
                    "No tasks available",
                )
                logger.info(f"NO_TASK for {instance_id}")

            router.send_multipart([client_id, encode_msg(response).encode("utf-8")])

        elif action == Action.WRITE.value:
            content = msg.get("content", "")

            cmd_response = handle_command(content, source)
            if cmd_response:
                response = make_msg(server_source, Action.WRITE, cmd_response)
                router.send_multipart([client_id, encode_msg(response).encode("utf-8")])
                logger.info(f"COMMAND from {instance_id}: {content}")
                continue

            # Append to blackboard
            entry = {
                "msg_id": msg.get("msg_id", f"msg-{int(time.time() * 1000)}"),
                "timestamp": msg.get("timestamp", int(time.time())),
                "source": source,
                "action": Action.WRITE.value,
                "content": content,
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

            # Broadcast via PUB (skip [RESULT] messages)
            if not content.startswith("[RESULT]"):
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
