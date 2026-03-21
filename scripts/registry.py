#!/usr/bin/env python3
"""
Agent registry for SwarmBoard.
Allows agents to register their capabilities and find suitable agents for tasks.

Usage:
  python scripts/registry.py register --name sisyphus --model nemotron-3-super-free --capabilities "documentation,coordination"
  python scripts/registry.py list
  python scripts/registry.py find --capability documentation
"""

import argparse
import json
import os
import sys
from datetime import datetime


REGISTRY_FILE = "data/agents.json"


def load_registry():
    if os.path.exists(REGISTRY_FILE):
        with open(REGISTRY_FILE, "r") as f:
            return json.load(f)
    return {}


def save_registry(registry):
    os.makedirs(os.path.dirname(REGISTRY_FILE), exist_ok=True)
    with open(REGISTRY_FILE, "w") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)


def register_agent(name, model, capabilities):
    registry = load_registry()

    registry[name] = {
        "name": name,
        "model": model,
        "capabilities": capabilities.split(","),
        "registered_at": datetime.now().isoformat(),
        "status": "active",
    }

    save_registry(registry)
    print(f"[registry] Registered: {name} ({model}) with capabilities: {capabilities}")


def list_agents():
    registry = load_registry()

    if not registry:
        print("[registry] No agents registered")
        return

    print("[registry] Registered Agents:")
    print("=" * 60)

    for name, info in registry.items():
        status_icon = "🟢" if info.get("status") == "active" else "⚫"
        print(f"{status_icon} {name}")
        print(f"   Model: {info['model']}")
        print(f"   Capabilities: {', '.join(info['capabilities'])}")
        print(f"   Registered: {info['registered_at']}")
        print()


def find_agents(capability):
    registry = load_registry()

    matches = []
    for name, info in registry.items():
        if capability in info.get("capabilities", []):
            matches.append((name, info))

    if not matches:
        print(f"[registry] No agents found with capability: {capability}")
        return

    print(f"[registry] Agents with capability '{capability}':")
    for name, info in matches:
        print(f"  - {name} ({info['model']})")


def main():
    parser = argparse.ArgumentParser(description="Agent registry for SwarmBoard")
    subparsers = parser.add_subparsers(dest="command")

    register_parser = subparsers.add_parser("register", help="Register an agent")
    register_parser.add_argument("--name", required=True, help="Agent name")
    register_parser.add_argument("--model", required=True, help="Model name")
    register_parser.add_argument(
        "--capabilities", required=True, help="Comma-separated capabilities"
    )

    subparsers.add_parser("list", help="List all registered agents")

    find_parser = subparsers.add_parser("find", help="Find agents by capability")
    find_parser.add_argument(
        "--capability", required=True, help="Capability to search for"
    )

    args = parser.parse_args()

    if args.command == "register":
        register_agent(args.name, args.model, args.capabilities)
    elif args.command == "list":
        list_agents()
    elif args.command == "find":
        find_agents(args.capability)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
