"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { createClient } from "@/utils/supabase/client";

interface Room {
  id: string;
  name: string;
  owner: string | null;
  is_private: boolean;
  created_at: string;
  metadata: Record<string, unknown>;
}

interface Message {
  id?: string;
  msg_id?: string;
  room?: string;
  source?: { instance_id?: string; model_name?: string; role?: string; type?: string; id?: string };
  action?: string;
  content: string;
  timestamp?: number;
  created_at?: string;
}

export default function Lobby() {
  const supabase = createClient();

  const [rooms, setRooms] = useState<Room[]>([]);
  const [currentRoom, setCurrentRoom] = useState("lobby");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [username, setUsername] = useState("");
  const [usernameSet, setUsernameSet] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Load saved username on mount
  useEffect(() => {
    const saved = localStorage.getItem("swarmboard-username");
    if (saved) {
      setUsername(saved);
      setUsernameSet(true);
    }
  }, []);

  // Fetch rooms from Supabase
  useEffect(() => {
    async function fetchRooms() {
      const { data } = await supabase
        .from("rooms")
        .select("*")
        .order("created_at", { ascending: true });
      if (data) setRooms(data);
    }
    fetchRooms();

    const channel = supabase
      .channel("rooms-changes")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "rooms" },
        () => fetchRooms()
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  // Fetch messages for current room
  useEffect(() => {
    async function fetchMessages() {
      const { data } = await supabase
        .from("messages")
        .select("*")
        .eq("room", currentRoom)
        .order("timestamp", { ascending: true })
        .limit(100);
      if (data) setMessages(data);
    }
    fetchMessages();
  }, [currentRoom]);

  // Subscribe to Realtime broadcast + DB changes for current room
  useEffect(() => {
    const channel = supabase.channel(`room:${currentRoom}`);

    channel
      .on("broadcast", { event: "message" }, ({ payload }) => {
        setMessages((prev) => [...prev, payload as Message]);
      })
      .subscribe();

    const dbChannel = supabase
      .channel(`db-messages-${currentRoom}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "messages",
          filter: `room=eq.${currentRoom}`,
        },
        (payload) => {
          const newMsg = payload.new as Message;
          setMessages((prev) => {
            if (newMsg.msg_id && prev.some((m) => m.msg_id === newMsg.msg_id)) {
              return prev;
            }
            return [...prev, newMsg];
          });
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
      supabase.removeChannel(dbChannel);
    };
  }, [currentRoom]);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = useCallback(async () => {
    if (!input.trim() || !usernameSet) return;

    const msg: Message = {
      msg_id: `web-${Date.now()}`,
      room: currentRoom,
      source: {
        type: "web_user",
        id: username,
        model_name: username,
        role: "human_commander",
      },
      action: "WRITE",
      content: input,
      timestamp: Math.floor(Date.now() / 1000),
    };

    // Persist to Supabase
    await supabase.from("messages").insert({
      room_id: rooms.find((r) => r.name === currentRoom)?.id,
      msg_id: msg.msg_id,
      source: msg.source,
      action: msg.action,
      content: msg.content,
      room: currentRoom,
    });

    // Broadcast via Realtime channel
    await supabase.channel(`room:${currentRoom}`).send({
      type: "broadcast",
      event: "message",
      payload: msg,
    });

    setInput("");
  }, [input, username, usernameSet, currentRoom, rooms, supabase]);

  const handleSetUsername = () => {
    if (username.trim()) {
      localStorage.setItem("swarmboard-username", username);
      setUsernameSet(true);
    }
  };

  const formatTime = (msg: Message) => {
    const ts = msg.timestamp || 0;
    if (ts) return new Date(ts * 1000).toLocaleTimeString("en-US", { hour12: false });
    if (msg.created_at) return new Date(msg.created_at).toLocaleTimeString("en-US", { hour12: false });
    return "??:??:??";
  };

  const getSender = (msg: Message) => {
    const src = msg.source;
    if (!src) return "system";
    return src.model_name || src.id || src.instance_id || "unknown";
  };

  const getMsgClass = (msg: Message) => {
    if (msg.action === "ROOM_JOIN") return "text-emerald-400";
    if (msg.action === "ROOM_LEAVE") return "text-orange-400";
    if (msg.action === "TASK_COMPLETE") return "text-cyan-400";
    if (msg.source?.role === "human_commander" || msg.source?.type === "web_user")
      return "text-red-400 font-semibold";
    if (msg.content?.includes("[RESULT]")) return "text-emerald-300";
    return "text-gray-200";
  };

  // Username entry screen
  if (!usernameSet) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-950">
        <div className="bg-gray-900 border border-gray-700 rounded-lg p-8 w-80">
          <h2 className="text-cyan-400 text-xl font-mono mb-4 text-center">
            SwarmBoard Lobby
          </h2>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSetUsername()}
            placeholder="Enter your name..."
            className="w-full bg-gray-800 border border-gray-600 text-gray-100 rounded px-3 py-2 font-mono mb-4 focus:outline-none focus:border-cyan-500"
            autoFocus
          />
          <button
            onClick={handleSetUsername}
            className="w-full bg-cyan-600 hover:bg-cyan-500 text-white font-mono py-2 rounded transition-colors"
          >
            Join Lobby
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100 font-mono">
      {/* Left sidebar: Rooms */}
      <div className="w-56 border-r border-gray-800 flex flex-col">
        <div className="p-3 border-b border-gray-800">
          <h2 className="text-cyan-400 text-sm font-bold">Rooms</h2>
        </div>
        <div className="flex-1 overflow-y-auto">
          {rooms.map((room) => (
            <button
              key={room.id}
              onClick={() => setCurrentRoom(room.name)}
              className={`w-full text-left px-3 py-2 text-sm hover:bg-gray-800 transition-colors ${
                currentRoom === room.name
                  ? "bg-gray-800 text-cyan-400 border-l-2 border-cyan-400"
                  : "text-gray-400 border-l-2 border-transparent"
              }`}
            >
              # {room.name}
              {room.is_private && " \uD83D\uDD12"}
            </button>
          ))}
        </div>
        <div className="p-3 border-t border-gray-800 text-xs text-gray-600">
          {rooms.length} rooms
        </div>
      </div>

      {/* Center: Chat */}
      <div className="flex-1 flex flex-col">
        <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
          <span className="text-cyan-400 font-bold"># {currentRoom}</span>
          <span className="text-xs text-gray-500">{username} | v0.8.0</span>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-1">
          {messages.map((msg, i) => (
            <div key={msg.msg_id || msg.id || i} className="flex gap-2 text-sm">
              <span className="text-gray-600 shrink-0 w-16 text-right">
                {formatTime(msg)}
              </span>
              <span className={`${getMsgClass(msg)} shrink-0 max-w-32 truncate`}>
                {getSender(msg)}
              </span>
              <span className={`${getMsgClass(msg)} flex-1`}>
                {msg.content}
              </span>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        <div className="p-3 border-t border-gray-800 flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && sendMessage()}
            placeholder={`Message #${currentRoom}...`}
            className="flex-1 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-cyan-500"
          />
          <button
            onClick={sendMessage}
            className="bg-cyan-600 hover:bg-cyan-500 px-4 py-2 rounded text-sm font-bold transition-colors"
          >
            Send
          </button>
        </div>
      </div>

      {/* Right sidebar: Info */}
      <div className="w-56 border-l border-gray-800 flex flex-col">
        <div className="p-3 border-b border-gray-800">
          <h2 className="text-cyan-400 text-sm font-bold">Info</h2>
        </div>
        <div className="p-3 text-xs text-gray-500 space-y-2">
          <div><span className="text-gray-400">Room:</span> {currentRoom}</div>
          <div><span className="text-gray-400">Messages:</span> {messages.length}</div>
          <div><span className="text-gray-400">You:</span> {username}</div>
          <div className="pt-2 border-t border-gray-800 text-gray-600">
            Supabase Realtime enabled
          </div>
        </div>
      </div>
    </div>
  );
}
