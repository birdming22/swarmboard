#!/usr/bin/env python3
"""
Intelligent message router for SwarmBoard.
Analyzes message content and suggests which agent should handle it.

Usage:
  python scripts/router.py route --message "幫忙更新 SKILL.md"
  python scripts/router.py register --agent sisyphus --skills "documentation,coordination"
  python scripts/router.py register --agent mimo --skills "coding,testing"
"""

import argparse
import json
import os
import sys


AGENTS_FILE = "data/agents.json"


def load_agents():
    if os.path.exists(AGENTS_FILE):
        with open(AGENTS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_agents(agents):
    os.makedirs(os.path.dirname(AGENTS_FILE), exist_ok=True)
    with open(AGENTS_FILE, "w") as f:
        json.dump(agents, f, indent=2, ensure_ascii=False)


def register_agent(name, skills):
    agents = load_agents()
    agents[name] = {
        "name": name,
        "skills": skills.split(","),
    }
    save_agents(agents)
    print(f"[router] Registered: {name} with skills: {skills}")


def route_message(message):
    agents = load_agents()

    if not agents:
        print("[router] No agents registered. Use 'register' command first.")
        return

    message_lower = message.lower()

    skill_keywords = {
        "documentation": [
            "文件",
            "文檔",
            "documentation",
            "readme",
            "skill",
            "faq",
            "更新",
        ],
        "coding": ["程式", "代碼", "code", "script", "python", "bug", "修正", "實作"],
        "testing": ["測試", "test", "驗證", "確認"],
        "coordination": ["協調", "coordinate", "分配", "issue", "任務"],
        "monitoring": ["監控", "monitor", "daemon", "listen", "監聽"],
    }

    scores = {}
    for agent_name, agent_info in agents.items():
        score = 0
        for skill in agent_info["skills"]:
            keywords = skill_keywords.get(skill, [])
            for keyword in keywords:
                if keyword in message_lower:
                    score += 1
        scores[agent_name] = score

    sorted_agents = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    print(f"[router] Message: {message}")
    print(f"[router] Suggested routing:")

    for i, (agent_name, score) in enumerate(sorted_agents[:3]):
        if score > 0:
            print(f"  {i + 1}. @{agent_name} (score: {score})")
        else:
            print(f"  {i + 1}. @{agent_name} (default)")

    if sorted_agents and sorted_agents[0][1] > 0:
        print(f"\n[router] Recommended: @{sorted_agents[0][0]}")
    else:
        print(f"\n[router] No strong match. Use @all for general discussion.")


def main():
    parser = argparse.ArgumentParser(description="Intelligent message router")
    subparsers = parser.add_subparsers(dest="command")

    route_parser = subparsers.add_parser(
        "route", help="Route a message to appropriate agent"
    )
    route_parser.add_argument("--message", required=True, help="Message to route")

    register_parser = subparsers.add_parser(
        "register", help="Register an agent with skills"
    )
    register_parser.add_argument("--agent", required=True, help="Agent name")
    register_parser.add_argument(
        "--skills", required=True, help="Comma-separated list of skills"
    )

    args = parser.parse_args()

    if args.command == "route":
        route_message(args.message)
    elif args.command == "register":
        register_agent(args.agent, args.skills)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
