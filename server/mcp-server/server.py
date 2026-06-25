#!/usr/bin/env python3
"""
NetEase Music MCP Server
Provides play_music, list_playlists, add_song_to_playlist tools
for any MCP-compatible client (Claude Desktop, etc.)
"""
import http.server
import json
import os
import sqlite3
import urllib.request
import urllib.parse
from http.server import HTTPServer
from pathlib import Path

def _load_dotenv():
    env_file = Path(__file__).resolve().parent.parent.parent / '.env'
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                if k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip()

_load_dotenv()

DB_PATH = os.environ.get("MUSIC_DB_PATH", os.path.join(os.path.dirname(__file__), "music.db"))
MCP_TOKEN = os.environ.get("MCP_TOKEN", "your-secret-token")
NETEASE_PROXY = os.environ.get("NETEASE_PROXY", "http://127.0.0.1:3460")
PORT = int(os.environ.get("MCP_PORT", "3456"))

# ── Database ──

def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("""CREATE TABLE IF NOT EXISTS playlists (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        cover_color TEXT DEFAULT '#8B7FA8',
        cover_emoji TEXT DEFAULT '♪',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS playlist_songs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
        song_id TEXT NOT NULL,
        song_name TEXT NOT NULL,
        artist TEXT,
        cover_url TEXT,
        note TEXT,
        added_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    db.commit()
    db.close()

# ── Tool implementations ──

def play_music(query, note=None):
    """Search NetEase Cloud Music, return a music card tag for frontend rendering"""
    try:
        url = 'https://music.163.com/api/search/get?s=' + urllib.parse.quote(query) + '&type=1&limit=3'
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://music.163.com/'
        })
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())
        songs = data.get('result', {}).get('songs', [])
        if not songs:
            return f"No results for '{query}', try different keywords"
        s = songs[0]
        song_id = s.get('id')
        # Fetch cover art
        detail_url = f'https://music.163.com/api/song/detail?ids=[{song_id}]'
        detail_req = urllib.request.Request(detail_url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://music.163.com/'
        })
        try:
            with urllib.request.urlopen(detail_req, timeout=5) as dr:
                dd = json.loads(dr.read().decode())
            pic_url = dd['songs'][0]['album'].get('picUrl', '')
        except:
            pic_url = ''
        name = s.get('name', '').replace(':', '：')
        artist = ', '.join([a.get('name', '') for a in s.get('artists', [])]).replace(':', '：')
        note_str = note or ''
        return f"[music:{song_id}:{name}:{artist}:{pic_url}]{note_str}"
    except Exception as e:
        return f"Search failed: {str(e)}"

def list_playlists():
    try:
        db = sqlite3.connect(DB_PATH)
        rows = db.execute("SELECT id, name, description, cover_emoji FROM playlists ORDER BY id ASC").fetchall()
        db.close()
        if not rows:
            return "No playlists yet"
        return "\n".join([f"ID:{r[0]} {r[3] or '♪'} {r[1]} — {r[2] or ''}" for r in rows])
    except Exception as e:
        return f"Failed to list playlists: {e}"

def add_song_to_playlist(playlist_id, song_id, song_name, artist, cover_url='', note=''):
    try:
        db = sqlite3.connect(DB_PATH)
        existing = db.execute("SELECT id FROM playlist_songs WHERE playlist_id=? AND song_id=?",
                              (playlist_id, str(song_id))).fetchone()
        if existing:
            db.close()
            return f"'{song_name}' is already in this playlist"
        db.execute(
            "INSERT INTO playlist_songs (playlist_id, song_id, song_name, artist, cover_url, note) VALUES (?,?,?,?,?,?)",
            (playlist_id, str(song_id), song_name, artist, cover_url or '', note or '')
        )
        db.execute("UPDATE playlists SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (playlist_id,))
        db.commit()
        pl = db.execute("SELECT name FROM playlists WHERE id=?", (playlist_id,)).fetchone()
        db.close()
        return f"Added '{song_name}' to playlist '{pl[0] if pl else playlist_id}'"
    except Exception as e:
        return f"Failed to add: {e}"

# ── MCP Protocol Handler ──

TOOLS = [
    {
        "name": "play_music",
        "description": "Search and play a song from NetEase Cloud Music. Returns a music card tag [music:ID:NAME:ARTIST:COVER_URL] for frontend rendering.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (song name, artist, etc.)"},
                "note": {"type": "string", "description": "Optional note to display with the music card"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "list_playlists",
        "description": "List all playlists with their IDs, names, and descriptions.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "add_song_to_playlist",
        "description": "Add a song to a playlist. Use list_playlists first to get the playlist ID. The song_id comes from the music card tag returned by play_music.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "playlist_id": {"type": "integer", "description": "Playlist ID from list_playlists"},
                "song_id": {"type": "string", "description": "Song ID from music card"},
                "song_name": {"type": "string", "description": "Song name"},
                "artist": {"type": "string", "description": "Artist name"},
                "cover_url": {"type": "string", "description": "Cover image URL"},
                "note": {"type": "string", "description": "Optional note"}
            },
            "required": ["playlist_id", "song_id", "song_name", "artist"]
        }
    }
]

class MCPHandler(http.server.BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == '/sse' or self.path.startswith('/sse?'):
            self._handle_sse()
        elif self.path == '/health':
            self._json_response({"status": "ok"})
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/message' or self.path.startswith('/message?'):
            self._handle_message()
        else:
            self.send_error(404)

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Allow-Methods', '*')

    def _json_response(self, data, status=200):
        self.send_response(status)
        self._cors()
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _handle_sse(self):
        self.send_response(200)
        self._cors()
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        # Send endpoint event
        endpoint = f"/message?token={MCP_TOKEN}"
        self.wfile.write(f"event: endpoint\ndata: {endpoint}\n\n".encode())
        self.wfile.flush()
        # Keep alive
        import time
        try:
            while True:
                time.sleep(30)
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except:
            pass

    def _handle_message(self):
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        method = body.get('method', '')

        if method == 'initialize':
            self._json_response({"jsonrpc": "2.0", "id": body.get("id"),
                "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                    "serverInfo": {"name": "netease-music-mcp", "version": "1.0.0"}}})
        elif method == 'tools/list':
            self._json_response({"jsonrpc": "2.0", "id": body.get("id"),
                "result": {"tools": TOOLS}})
        elif method == 'tools/call':
            name = body.get('params', {}).get('name', '')
            args = body.get('params', {}).get('arguments', {})
            if name == 'play_music':
                text = play_music(args.get('query', ''), args.get('note'))
            elif name == 'list_playlists':
                text = list_playlists()
            elif name == 'add_song_to_playlist':
                text = add_song_to_playlist(
                    args.get('playlist_id'), args.get('song_id'),
                    args.get('song_name', ''), args.get('artist', ''),
                    args.get('cover_url', ''), args.get('note', ''))
            else:
                text = f"Unknown tool: {name}"
            self._json_response({"jsonrpc": "2.0", "id": body.get("id"),
                "result": {"content": [{"type": "text", "text": text}]}})
        elif method == 'notifications/initialized':
            self._json_response({"jsonrpc": "2.0", "id": body.get("id"), "result": {}})
        else:
            self._json_response({"jsonrpc": "2.0", "id": body.get("id"),
                "error": {"code": -32601, "message": f"Unknown method: {method}"}})

    def log_message(self, format, *args):
        pass  # Suppress default logging

if __name__ == '__main__':
    init_db()
    print(f"🎵 NetEase Music MCP Server running on port {PORT}")
    print(f"   SSE endpoint: http://localhost:{PORT}/sse")
    server = HTTPServer(('0.0.0.0', PORT), MCPHandler)
    server.serve_forever()
