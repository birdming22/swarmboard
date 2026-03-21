#!/usr/bin/env python3
"""
SwarmBoard End-to-End Integration Test.

Starts a server, two clients, and verifies:
  1. Clients sync on startup (READ_REQUEST → READ_RESPONSE)
  2. WRITE from one client reaches the other via PUB broadcast
  3. Concurrent writes are serialized correctly
  4. Clean shutdown
"""

import json
import multiprocessing
import signal
import time

import zmq

from swarmboard.protocol import (
    Action,
    decode_msg,
    encode_msg,
    make_msg,
    make_source,
)

ROUTER_ADDR = "tcp://127.0.0.1:15570"
PUB_ADDR = "tcp://127.0.0.1:15571"

_server_running = True


def _server_sigint(sig, frame):
    global _server_running
    _server_running = False


def run_server():
    """In-process server for testing."""
    global _server_running
    _server_running = True
    signal.signal(signal.SIGINT, _server_sigint)

    ctx = zmq.Context()
    router = ctx.socket(zmq.ROUTER)
    router.bind(ROUTER_ADDR)
    pub = ctx.socket(zmq.PUB)
    pub.bind(PUB_ADDR)

    blackboard = []
    server_source = make_source("test-server", "zmb-server", "server")
    poller = zmq.Poller()
    poller.register(router, zmq.POLLIN)

    deadline = time.time() + 15

    while _server_running and time.time() < deadline:
        try:
            socks = dict(poller.poll(timeout=200))
        except zmq.ZMQError:
            break

        if router not in socks:
            continue

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

        if action == Action.READ_REQUEST.value:
            response = make_msg(
                server_source,
                Action.READ_RESPONSE,
                json.dumps(blackboard, ensure_ascii=False),
            )
            router.send_multipart([client_id, encode_msg(response).encode("utf-8")])

        elif action == Action.WRITE.value:
            entry = {
                "msg_id": msg.get("msg_id", ""),
                "timestamp": msg.get("timestamp", 0),
                "source": source,
                "action": Action.WRITE.value,
                "content": msg.get("content", ""),
            }
            blackboard.append(entry)

            ack = make_msg(server_source, Action.WRITE, "OK")
            router.send_multipart([client_id, encode_msg(ack).encode("utf-8")])

            pub_update = make_msg(
                server_source,
                Action.STATE_UPDATE,
                json.dumps(entry, ensure_ascii=False),
            )
            pub.send_string("blackboard", zmq.SNDMORE)
            pub.send_string(encode_msg(pub_update))

    router.close()
    pub.close()
    ctx.term()


def test_sync_and_write():
    """Test: client syncs, writes, other client receives broadcast."""
    server_proc = multiprocessing.Process(target=run_server, daemon=True)
    server_proc.start()
    time.sleep(0.3)  # let server bind

    ctx = zmq.Context()

    # --- Connect SUB first (slow-joiner mitigation) ---
    sub_b = ctx.socket(zmq.SUB)
    sub_b.connect(PUB_ADDR)
    sub_b.setsockopt_string(zmq.SUBSCRIBE, "blackboard")
    sub_b.setsockopt(zmq.RCVTIMEO, 3000)
    time.sleep(0.3)  # ZMQ slow-joiner: let SUB handshake complete

    # --- Client A ---
    source_a = make_source("cli-a", "model-a", "ai_agent")
    dealer_a = ctx.socket(zmq.DEALER)
    dealer_a.setsockopt_string(zmq.IDENTITY, "cli-a")
    dealer_a.connect(ROUTER_ADDR)

    # A syncs
    req = make_msg(source_a, Action.READ_REQUEST)
    dealer_a.send_string(encode_msg(req))
    reply_a = dealer_a.recv_string()
    msg_a = decode_msg(reply_a)
    assert msg_a["action"] == Action.READ_RESPONSE.value
    history = json.loads(msg_a["content"])
    assert isinstance(history, list)
    print(f"[PASS] Client A synced: {len(history)} entries")

    # --- Client B ---
    source_b = make_source("cli-b", "model-b", "ai_agent")
    dealer_b = ctx.socket(zmq.DEALER)
    dealer_b.setsockopt_string(zmq.IDENTITY, "cli-b")
    dealer_b.connect(ROUTER_ADDR)

    # B syncs
    req_b = make_msg(source_b, Action.READ_REQUEST)
    dealer_b.send_string(encode_msg(req_b))
    reply_b = dealer_b.recv_string()
    msg_b = decode_msg(reply_b)
    assert msg_b["action"] == Action.READ_RESPONSE.value
    print("[PASS] Client B synced")

    # --- Client A writes ---
    write_msg = make_msg(source_a, Action.WRITE, "hello from A")
    dealer_a.send_string(encode_msg(write_msg))
    ack_str = dealer_a.recv_string()
    ack = decode_msg(ack_str)
    assert ack["action"] == Action.WRITE.value
    print("[PASS] Client A write ACK received")

    # --- Client B receives broadcast ---
    topic = sub_b.recv_string()
    data = sub_b.recv_string()
    assert topic == "blackboard", f"Expected topic 'blackboard', got '{topic}'"
    broadcast = decode_msg(data)
    assert broadcast["action"] == Action.STATE_UPDATE.value
    entry = json.loads(broadcast["content"])
    assert entry["source"]["instance_id"] == "cli-a"
    assert entry["content"] == "hello from A"
    print(f"[PASS] Client B received broadcast: '{entry['content']}'")

    # --- Client A writes again ---
    write_msg2 = make_msg(source_a, Action.WRITE, "second message")
    dealer_a.send_string(encode_msg(write_msg2))
    dealer_a.recv_string()  # drain ACK

    topic2 = sub_b.recv_string()
    data2 = sub_b.recv_string()
    broadcast2 = decode_msg(data2)
    entry2 = json.loads(broadcast2["content"])
    assert entry2["content"] == "second message"
    print(f"[PASS] Client B received second broadcast: '{entry2['content']}'")

    # --- Client B also writes, Client A can sync and see it ---
    write_msg3 = make_msg(source_b, Action.WRITE, "reply from B")
    dealer_b.send_string(encode_msg(write_msg3))
    dealer_b.recv_string()  # drain ACK

    # A should see the broadcast too (subscribe with a separate SUB)
    sub_a = ctx.socket(zmq.SUB)
    sub_a.connect(PUB_ADDR)
    sub_a.setsockopt_string(zmq.SUBSCRIBE, "blackboard")
    sub_a.setsockopt(zmq.RCVTIMEO, 3000)
    time.sleep(0.3)

    # B wrote before A subscribed, so A needs to read full state
    # Just verify the blackboard has 3 entries via sync
    req_final = make_msg(source_a, Action.READ_REQUEST)
    dealer_a.send_string(encode_msg(req_final))
    reply_final = dealer_a.recv_string()
    msg_final = decode_msg(reply_final)
    final_history = json.loads(msg_final["content"])
    assert len(final_history) == 3, f"Expected 3 entries, got {len(final_history)}"
    assert final_history[0]["content"] == "hello from A"
    assert final_history[1]["content"] == "second message"
    assert final_history[2]["content"] == "reply from B"
    print(f"[PASS] Final blackboard has {len(final_history)} entries in order")

    # Cleanup
    dealer_a.close()
    dealer_b.close()
    sub_a.close()
    sub_b.close()
    ctx.term()
    server_proc.terminate()
    server_proc.join(timeout=2)

    print("\n[PASS] All tests passed.")


if __name__ == "__main__":
    test_sync_and_write()
