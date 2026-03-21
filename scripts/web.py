#!/usr/bin/env python3
"""
Simple web interface for SwarmBoard blackboard.
Displays messages and agent status.

Usage:
  python scripts/web.py [--port 8080]
"""

import argparse
import json
import os
import sys

try:
    from flask import Flask, jsonify, render_template_string
except ImportError:
    print("Flask not installed. Install with: pip install flask")
    sys.exit(1)

app = Flask(__name__)

BLACKBOARD_FILE = "data/blackboard.json"
TASKS_FILE = "data/tasks.json"
AGENTS_FILE = "data/agents.json"


def load_json_file(filepath):
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            return json.load(f)
    return []


HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>SwarmBoard Dashboard</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; }
        .card { background: white; border-radius: 8px; padding: 20px; margin: 10px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .header { background: #4CAF50; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
        .message { border-left: 4px solid #4CAF50; padding-left: 15px; margin: 10px 0; }
        .commander { border-left-color: #FF9800; }
        .timestamp { color: #666; font-size: 12px; }
        .source { font-weight: bold; color: #333; }
        .content { margin-top: 5px; }
        .status { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
        .status-completed { background: #4CAF50; color: white; }
        .status-in-progress { background: #FF9800; color: white; }
        .status-pending { background: #9E9E9E; color: white; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background: #f5f5f5; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 SwarmBoard Dashboard</h1>
            <p>即時協作黑板 - Real-time Collaboration Blackboard</p>
        </div>

        <div class="card">
            <h2>📊 統計資訊</h2>
            <p>總訊息數: <strong>{{ messages|length }}</strong></p>
            <p>任務數: <strong>{{ tasks|length }}</strong></p>
            <p>註冊 Agent: <strong>{{ agents|length }}</strong></p>
        </div>

        <div class="card">
            <h2>💬 最新訊息</h2>
            {% for msg in messages[-10:]|reverse %}
            <div class="message {% if msg.source.role == 'human_commander' %}commander{% endif %}">
                <div class="timestamp">{{ msg.timestamp }}</div>
                <div class="source">
                    {% if msg.source.role == 'human_commander' %}👨‍✈️ Commander{% else %}🤖 {{ msg.source.model_name }}{% endif %}
                </div>
                <div class="content">{{ msg.content }}</div>
            </div>
            {% endfor %}
        </div>

        <div class="card">
            <h2>📋 任務列表</h2>
            <table>
                <tr>
                    <th>ID</th>
                    <th>標題</th>
                    <th>負責人</th>
                    <th>狀態</th>
                    <th>優先級</th>
                </tr>
                {% for task in tasks %}
                <tr>
                    <td>{{ task.id }}</td>
                    <td>{{ task.title }}</td>
                    <td>{{ task.assignee }}</td>
                    <td><span class="status status-{{ task.status }}">{{ task.status }}</span></td>
                    <td>{{ task.priority }}</td>
                </tr>
                {% endfor %}
            </table>
        </div>

        <div class="card">
            <h2>🤖 註冊 Agent</h2>
            <table>
                <tr>
                    <th>名稱</th>
                    <th>模型</th>
                    <th>能力</th>
                    <th>狀態</th>
                </tr>
                {% for name, agent in agents.items() %}
                <tr>
                    <td>{{ name }}</td>
                    <td>{{ agent.model }}</td>
                    <td>{{ agent.capabilities|join(', ') }}</td>
                    <td><span class="status status-completed">{{ agent.status }}</span></td>
                </tr>
                {% endfor %}
            </table>
        </div>
    </div>
</body>
</html>
"""


@app.route("/")
def index():
    messages = load_json_file(BLACKBOARD_FILE)
    tasks = load_json_file(TASKS_FILE)
    agents = load_json_file(AGENTS_FILE)

    return render_template_string(
        HTML_TEMPLATE,
        messages=messages,
        tasks=tasks,
        agents=agents,
    )


@app.route("/api/messages")
def api_messages():
    return jsonify(load_json_file(BLACKBOARD_FILE))


@app.route("/api/tasks")
def api_tasks():
    return jsonify(load_json_file(TASKS_FILE))


@app.route("/api/agents")
def api_agents():
    return jsonify(load_json_file(AGENTS_FILE))


def main():
    parser = argparse.ArgumentParser(description="SwarmBoard Web Interface")
    parser.add_argument("--port", type=int, default=8080, help="Port to run on")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    args = parser.parse_args()

    print(f"[web] Starting SwarmBoard Dashboard on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
