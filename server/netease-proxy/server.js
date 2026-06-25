const { song_url_v1, search, song_detail } = require('NeteaseCloudMusicApi');
const http = require('http');
const url = require('url');

const path = require('path');
const dotenvPath = path.resolve(__dirname, '../../.env');
if (require('fs').existsSync(dotenvPath)) {
  require('fs').readFileSync(dotenvPath, 'utf8').split('\n').forEach(line => {
    const m = line.match(/^([^#=]+)=(.*)$/);
    if (m && !process.env[m[1].trim()]) process.env[m[1].trim()] = m[2].trim();
  });
}

let COOKIE = process.env.NETEASE_COOKIE || '';
if (!COOKIE) {
  const cookieFile = process.env.NETEASE_COOKIE_FILE || path.resolve(__dirname, '../mcp-server/netease_cookie.txt');
  if (require('fs').existsSync(cookieFile)) COOKIE = require('fs').readFileSync(cookieFile, 'utf8').trim();
}

const server = http.createServer(async (req, res) => {
  const parsed = url.parse(req.url, true);
  const path = parsed.pathname;
  const q = parsed.query;

  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Access-Control-Allow-Origin', '*');

  try {
    if (path === '/song_url') {
      const id = parseInt(q.id);
      const result = await song_url_v1({ id, level: 'standard', cookie: COOKIE });
      const data = result.body.data?.[0];
      let songUrl = data?.url || null;
    if (songUrl) songUrl = songUrl.replace(/^http:\/\//, 'https://');
    res.end(JSON.stringify({ url: songUrl, code: data?.code }));
    } else if (path === '/search') {
      const result = await search({ keywords: q.q, limit: 5, cookie: COOKIE });
      const songs = result.body.result?.songs || [];
      res.end(JSON.stringify({ songs }));
    } else {
      res.end(JSON.stringify({ ok: true }));
    }
  } catch(e) {
    res.statusCode = 500;
    res.end(JSON.stringify({ error: e.message }));
  }
});

server.listen(3460, '127.0.0.1', () => console.log('netease-api on :3460'));
