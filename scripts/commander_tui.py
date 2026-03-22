#!/usr/bin/env python3
"""
SwarmBoard Commander TUI - Terminal UI for Commander using curses.

Usage:
    uv run python scripts/commander_tui.py [--router tcp://127.0.0.1:5570]
"""

import argparse
import curses
import json
import time
import threading
import zmq


class SwarmBoardTUI:
    def __init__(
        self, router_addr="tcp://127.0.0.1:5570", pub_addr="tcp://127.0.0.1:5571"
    ):
        self.router_addr = router_addr
        self.pub_addr = pub_addr
        self.messages = []
        self.agents = {}
        self.running = True
        self.lock = threading.Lock()
        self.input_buffer = ""
        self.scroll_offset = 0

        # ZMQ context
        self.ctx = zmq.Context()

        # DEALER for sending messages and reading
        self.dealer = self.ctx.socket(zmq.DEALER)
        self.dealer.setsockopt_string(
            zmq.IDENTITY, f"commander-tui-{int(time.time()) % 10000}"
        )
        self.dealer.connect(self.router_addr)
        self.dealer.setsockopt(zmq.RCVTIMEO, 1000)

        # SUB for subscribing to real-time updates
        self.sub = self.ctx.socket(zmq.SUB)
        self.sub.connect(self.pub_addr)
        self.sub.setsockopt_string(zmq.SUBSCRIBE, "")  # Subscribe to all messages

    def read_blackboard(self):
        """Read blackboard from server."""
        read_req = {
            "msg_id": f"msg-{int(time.time())}",
            "timestamp": int(time.time()),
            "source": {
                "instance_id": "commander-tui",
                "model_name": "commander",
                "role": "human_commander",
            },
            "action": "READ_REQUEST",
            "content": "",
        }

        try:
            self.dealer.send_string(json.dumps(read_req, ensure_ascii=False))
            reply = self.dealer.recv_string()
            msg = json.loads(reply)
            if msg.get("action") == "READ_RESPONSE":
                with self.lock:
                    self.messages = json.loads(msg.get("content", "[]"))
                    self._update_agents()
        except zmq.Again:
            pass
        except Exception:
            pass

    def _update_agents(self):
        """Update agent list from messages."""
        agents = {}
        for msg in self.messages:
            source = msg.get("source", {})
            instance_id = source.get("instance_id", "")
            model_name = source.get("model_name", "")
            role = source.get("role", "")

            if role == "ai_agent" and instance_id:
                agents[instance_id] = {
                    "model_name": model_name,
                    "last_seen": msg.get("timestamp", 0),
                }
        self.agents = agents

    def send_message(self, content):
        """Send message to blackboard."""
        msg = {
            "msg_id": f"msg-{int(time.time())}",
            "timestamp": int(time.time()),
            "source": {
                "instance_id": "commander-tui",
                "model_name": "commander",
                "role": "human_commander",
            },
            "action": "WRITE",
            "content": f"[COMMANDER] {content}",
        }

        try:
            self.dealer.send_string(json.dumps(msg, ensure_ascii=False))
            self.dealer.recv_string()  # ACK
        except Exception:
            pass

    def draw(self, stdscr):
        """Draw the TUI."""
        curses.curs_set(1)  # Show cursor
        stdscr.timeout(100)  # Non-blocking input with 100ms timeout

        # Initialize colors
        curses.start_color()
        curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)  # Time
        curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)  # Agent
        curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK)  # Commander
        curses.init_pair(4, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # Status
        curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_BLACK)  # Normal
        curses.init_pair(6, curses.COLOR_MAGENTA, curses.COLOR_BLACK)  # Header

        while self.running:
            try:
                height, width = stdscr.getmaxyx()

                # Clear screen
                stdscr.clear()

                # Draw header
                header = " ╔══════ SwarmBoard Commander TUI ══════╗ "
                stdscr.addstr(
                    0, 0, header[:width], curses.color_pair(6) | curses.A_BOLD
                )

                # Draw messages area (rows 1 to height-5)
                msg_height = height - 5
                with self.lock:
                    msg_list = (
                        self.messages[-(msg_height - 2) :] if self.messages else []
                    )

                row = 1
                stdscr.addstr(
                    row,
                    0,
                    " Time     Source              Message",
                    curses.color_pair(6),
                )
                row += 1
                stdscr.addstr(row, 0, " " + "─" * (width - 2), curses.color_pair(5))
                row += 1

                for msg in msg_list:
                    if row >= height - 5:
                        break
                    timestamp = msg.get("timestamp", 0)
                    time_str = time.strftime("%H:%M:%S", time.localtime(timestamp))
                    source = msg.get("source", {})
                    model = source.get("model_name", "?")
                    role = source.get("role", "?")
                    content = msg.get("content", "")

                    # Determine color
                    if role == "human_commander":
                        color = curses.color_pair(3)
                    elif "[RESULT]" in content:
                        color = curses.color_pair(2)
                    elif "[STATUS]" in content:
                        color = curses.color_pair(4)
                    else:
                        color = curses.color_pair(5)

                    # Truncate content to fit width
                    max_msg_len = width - 30
                    display_content = content[:max_msg_len]

                    line = f" {time_str}  {model:<18} {display_content}"
                    try:
                        stdscr.addstr(row, 0, line[:width], color)
                    except curses.error:
                        pass
                    row += 1

                # Draw separator
                sep_row = height - 4
                try:
                    stdscr.addstr(
                        sep_row, 0, " " + "─" * (width - 2), curses.color_pair(5)
                    )
                except curses.error:
                    pass

                # Draw status bar
                status_row = height - 3
                msg_count = len(self.messages)
                agent_count = len(self.agents)
                status = f" Messages: {msg_count} | Agents: {agent_count}"
                try:
                    stdscr.addstr(
                        status_row,
                        0,
                        status[:width],
                        curses.color_pair(4) | curses.A_BOLD,
                    )
                except curses.error:
                    pass

                # Draw input area
                input_row = height - 2
                try:
                    stdscr.addstr(
                        input_row,
                        0,
                        " Commander > ",
                        curses.color_pair(3) | curses.A_BOLD,
                    )
                    stdscr.addstr(
                        input_row, 13, self.input_buffer, curses.color_pair(5)
                    )
                    # Clear rest of line
                    stdscr.clrtoeol()
                except curses.error:
                    pass

                # Draw help line
                help_row = height - 1
                help_text = " Enter: send | q: quit | /help: commands"
                try:
                    stdscr.addstr(
                        help_row,
                        0,
                        help_text[:width],
                        curses.color_pair(5) | curses.A_DIM,
                    )
                except curses.error:
                    pass

                # Move cursor to input position
                cursor_x = 13 + len(self.input_buffer)
                try:
                    stdscr.move(input_row, cursor_x)
                except curses.error:
                    pass

                # Refresh screen
                stdscr.refresh()

                # Handle input
                try:
                    ch = stdscr.getch()
                    if ch == -1:
                        continue  # No input
                    elif ch == ord("q"):
                        self.running = False
                        break
                    elif ch == 10 or ch == 13:  # Enter
                        if self.input_buffer.strip():
                            self.send_message(self.input_buffer.strip())
                            self.input_buffer = ""
                    elif ch == curses.KEY_BACKSPACE or ch == 127:  # Backspace
                        self.input_buffer = self.input_buffer[:-1]
                    elif ch == 3:  # Ctrl+C
                        self.running = False
                        break
                    elif 32 <= ch <= 126:  # Printable ASCII
                        self.input_buffer += chr(ch)
                except Exception:
                    pass

            except curses.error:
                pass

    def _reader_loop(self):
        """Background thread to read blackboard via SUB socket for real-time updates."""
        poller = zmq.Poller()
        poller.register(self.sub, zmq.POLLIN)
        poller.register(self.dealer, zmq.POLLIN)

        while self.running:
            try:
                events = dict(poller.poll(1000))  # 1 second timeout

                # Check SUB socket for real-time updates
                if self.sub in events and events[self.sub]:
                    try:
                        msg_data = self.sub.recv_string(zmq.NOBLOCK)
                        if msg_data:
                            # Parse the message and add to our list
                            msg = json.loads(msg_data)
                            if msg.get("action") == "WRITE":
                                with self.lock:
                                    # Check if message already exists
                                    msg_id = msg.get("msg_id", "")
                                    if not any(
                                        m.get("msg_id") == msg_id for m in self.messages
                                    ):
                                        self.messages.append(msg)
                                        self._update_agents()
                    except zmq.Again:
                        pass
                    except Exception:
                        pass

                # Check DEALER for initial/full reads
                if self.dealer in events and events[self.dealer]:
                    try:
                        reply = self.dealer.recv_string(zmq.NOBLOCK)
                        msg = json.loads(reply)
                        if msg.get("action") == "READ_RESPONSE":
                            with self.lock:
                                self.messages = json.loads(msg.get("content", "[]"))
                                self._update_agents()
                    except zmq.Again:
                        pass
                    except Exception:
                        pass

            except Exception:
                pass

    def run(self, stdscr):
        """Main entry point for curses."""
        # Start reader thread
        reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        reader_thread.start()

        # Run curses UI
        self.draw(stdscr)


def main():
    parser = argparse.ArgumentParser(description="SwarmBoard Commander TUI")
    parser.add_argument(
        "--router", default="tcp://127.0.0.1:5570", help="ROUTER endpoint"
    )
    parser.add_argument(
        "--pub",
        default="tcp://127.0.0.1:5571",
        help="PUB endpoint for real-time updates",
    )
    args = parser.parse_args()

    tui = SwarmBoardTUI(args.router, args.pub)
    curses.wrapper(tui.run)


if __name__ == "__main__":
    main()
