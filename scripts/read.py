#!/usr/bin/env python3
"""
Read all messages from SwarmBoard blackboard.
Usage: python scripts/read.py
"""

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
    instance_id = f"reader-{uuid.uuid4().hex[:4]}"
    source = make_source(instance_id, "reader", "ai_agent")

    ctx = zmq.Context()
    dealer = ctx.socket(zmq.DEALER)
    dealer.setsockopt_string(zmq.IDENTITY, instance_id)
    dealer.RCVTIMEO = 3000
    dealer.connect("tcp://127.0.0.1:5570")

    # Send READ_REQUEST
    read_req = make_msg(source, Action.READ_REQUEST)
    dealer.send_string(encode_msg(read_req))

    try:
        reply = dealer.recv_string()
        msg = decode_msg(reply)
        
        if msg and msg.get("action") == Action.READ_RESPONSE.value:
            history = json.loads(msg.get("content", "[]"))
            print(json.dumps(history, indent=2, ensure_ascii=False))
        else:
            print("[]")
            
    except zmq.Again:
        print("[]")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        dealer.close()
        ctx.term()


if __name__ == "__main__":
    main()
