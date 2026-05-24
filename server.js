#!/usr/bin/env node
/**
 * Radio Streams Web Server
 *
 * Displays current playing content from all radio streams.
 * Probes ICY metadata in the background, serves via Express + SSE.
 */

const express = require('express');
const fs = require('fs');
const path = require('path');
const http = require('http');
const https = require('https');
const { SocksProxyAgent } = require('socks-proxy-agent');

const SOCKS_PROXY = 'socks5://192.168.8.99:1081';
const socksAgent = new SocksProxyAgent(SOCKS_PROXY);

const PORT = process.env.PORT || 3000;
const DATA_FILE = path.join(__dirname, 'station_analysis.md');
const STATE_FILE = path.join(__dirname, '.radio_state.json');
const CACHE_TTL = 180_000; // 3min between full re-probes

// ---------------------------------------------------------------
// 1. Parse station_analysis.md into structured station list
// ---------------------------------------------------------------
function parseStations() {
  const lines = fs.readFileSync(DATA_FILE, 'utf-8').split('\n');

  // Find start of Full Station List section
  let startIdx = -1;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim() === '## Full Station List') {
      startIdx = i + 1;
      break;
    }
  }
  if (startIdx === -1) {
    console.error('Could not find Full Station List section');
    return [];
  }

  // Collect raw rows (handle multi-line continuations)
  const rawRows = [];
  let current = null;

  for (let i = startIdx; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    // Skip table header and separator rows
    if (trimmed === '' || trimmed.startsWith('|---') || trimmed.startsWith('||--')) continue;

    // Detect new row: starts with |  digits  |
    const isNewRow = /^\|\s*\d+\s*\|/.test(line);

    if (isNewRow) {
      if (current) rawRows.push(current);
      current = line;
    } else if (current) {
      // Continuation line — append to current row
      current += line;
    }
  }
  if (current) rawRows.push(current);

  // Parse each raw row by splitting on ` | `
  const stations = [];
  for (const row of rawRows) {
    // Strip leading and trailing pipes, then split
    const cleaned = row.replace(/^\|/, '').replace(/\|$/, '').trim();
    const parts = cleaned.split(/\s*\|\s*/);

    if (parts.length < 11) continue;

    const name = parts[2]?.trim() || '';
    const country = parts[3]?.trim() || '';
    const language = parts[4]?.trim() || '';
    let genre = parts[5]?.trim() || '';
    let format = parts[6]?.trim() || '';
    const status = parts[7]?.trim() || '';
    const icyName = parts[8]?.trim() || '';
    let bitrate = parts[9]?.trim() || '';
    const song = parts[10]?.trim() || '';
    const url = parts[11]?.trim() || '';

    // Normalise genre
    if (genre.includes('/')) genre = genre.split('/')[0].trim();

    // Normalise format
    if (format === 'dead(html)' || format === 'dead/timeout' || format === 'redirect') {
      continue; // skip dead stations
    }
    if (format.startsWith('dead(')) continue;

    // Clean up format: 'MP3', 'AAC', 'OGG', 'FLAC', 'M3U', 'PLS'
    let rawFmt = format.toUpperCase();
    let fmt = rawFmt;
    if (rawFmt.includes('MP3') || rawFmt === 'M3U' || rawFmt.includes('MPEG')) fmt = 'MP3';
    else if (rawFmt.includes('AAC')) fmt = 'AAC';
    else if (rawFmt.includes('OGG') || rawFmt.includes('VORBIS')) fmt = 'OGG';
    else if (rawFmt.includes('FLAC')) fmt = 'FLAC';
    else if (rawFmt === 'PLS') fmt = 'PLS';
    else if (rawFmt.startsWith('OTHER(')) {
      let inner = rawFmt.replace('OTHER(', '').replace(')', '');
      if (inner.includes('MPEG') || inner.includes('M3U')) fmt = 'MP3';
      else if (inner.includes('AAC')) fmt = 'AAC';
      else fmt = inner;
    }

    const br = parseInt(bitrate) || 0;

    stations.push({
      name,
      country,
      language,
      genre,
      format: fmt, // normalized format
      status,
      icyName,
      bitrate: br,
      song,
      url,
      // Will be filled by live probe
      currentSong: '',
      lastSeen: null,
      // Black jazz rating
      jazzRating: classifyBlackJazz(name, genre, song, url)
    });
  }

  return stations;
}

// ---------------------------------------------------------------
// 2. Black Jazz classifier
// ---------------------------------------------------------------
function classifyBlackJazz(name, genre, song, url) {
  const n = name.toLowerCase();
  const s = song.toLowerCase();
  const u = url.toLowerCase();
  const g = genre.toLowerCase();

  // --- Black jazz artist detection ---
  const blackJazzArtists = [
    'mingus', 'monk', 'coltrane', 'davis', 'miles davis', 'gillespie', 'dizzy',
    'parker', 'charlie parker', 'rollins', 'sonny rollins', 'blakey', 'art blakey',
    'silver', 'horace silver', 'morgan', 'lee morgan', 'mobley', 'hank mobley',
    'henderson', 'joe henderson', 'shorter', 'wayne shorter', 'turrentine',
    'smith', 'jimmy smith', 'hancock', 'herbie hancock', 'jarrett',
    'evans', 'bill evans', 'peterson', 'oscar peterson', 'fitzgerald', 'ella',
    'vaughan', 'sarah vaughan', 'holiday', 'billie holiday', 'armstrong',
    'louis armstrong', 'washington', 'grover washington', 'benson', 'george benson',
    'wynton', 'branford', 'marsalis', 'reeves', 'dianne reeves',
    'corea', 'chick corea', 'clarke', 'stanley clarke', 'pastorius',
    'metheny', 'pat metheny', 'di meola', 'al di meola',
    'temptations', 'gaye', 'marvin gaye', 'wonder', 'stevie wonder',
    'franklin', 'aretha franklin', 'king', 'b.b. king', 'bb king',
    'hooker', 'john lee hooker', 'dibango', 'manu dibango',
    'muddy waters', 'howlin wolf', 'ray charles', 'otis redding',
    'james brown', 'brown', 'parliament', 'funkadelic', 'clinton',
    'earth wind', 'kool & the gang', 'brothers johnson',
    'vernon reid', 'living colour', 'hendrix', 'jimi hendrix',
    'santana', 'latin jazz', 'puente', 'tito puente',
    'gillespie', 'dizzy gillespie',
    'hargrove', 'roy hargrove',
    'new edition', 'boyz ii men', 'en vogue', 'toni braxton',
    'bobby womack', 'gladys knight', 'dells', 'drifters',
    'coasters', 'platters', 'four tops', 'supremes',
    'jacksons', 'jackson 5', 'michael jackson',
    'eter', 'everette harp', 'crutchfield', 'adrian crutchfield',
    'rountree', 'lin rountree', 'banton', 'keith banton',
    'cooling', 'joyce cooling', 'kim scott', 'paul hardcastle',
    'braxton', 'braxton brothers', 'jill butler',
    'najee', 'boney james', 'dave koz', 'warren hill',
    'norman brown', 'chris botti', 'rick braun',
  ];

  const isBlackJazzArtist = blackJazzArtists.some(a => s.includes(a) || n.includes(a));

  // --- Station name / genre hints ---
  const funkKeywords = ['funk', 'funk', 'soul', 'blues', 'motown', 'rnb', 'r&b', 'groove'];
  const hasFunkVibe = funkKeywords.some(k => n.includes(k) || g.includes(k));

  const jazzKeywords = ['jazz', 'classical jazz', 'bebop', 'vocal jazz'];
  const isJazzStation = jazzKeywords.some(k => n.includes(k) || g.includes(k));

  // --- Rating ---
  let score = 0;

  if (isJazzStation && isBlackJazzArtist) score = 5;       // ★★★★★
  else if (isJazzStation && hasFunkVibe) score = 4;         // ★★★★
  else if (isJazzStation) score = 3;                        // ★★★
  else if (hasFunkVibe && isBlackJazzArtist) score = 4;     // ★★★★
  else if (hasFunkVibe) score = 3;                          // ★★★
  else if (isBlackJazzArtist) score = 4;                    // ★★★★

  // Override based on known stations
  if (u.includes('classicaljazz')) score = Math.max(score, 5);
  if (u.includes('vocals') && n.includes('jazz')) score = Math.max(score, 4);
  if (u.includes('bebop')) score = Math.max(score, 4);
  if (u.includes('funkyradio')) score = Math.max(score, 5);
  if (n.includes('funk') || n.includes('funky')) score = Math.max(score, 4);
  if (n.includes('smooth jaz')) score = Math.min(score, 3); // Smooth jazz rarely black jazz
  if (n === 'Linn Jazz') score = Math.min(score, 3);       // European
  if (n === 'Hi On Line Jazz Radio') score = Math.min(score, 3);

  // 181FM jazz streams that are actually prog rock (shared playlist)
  if (n === '181.FM Jazz Mix' || n === '181.FM Fusion Jazz' ||
      n === '181.FM Trance Jazz') score = 1;

  return score;
}

// ---------------------------------------------------------------
// 3. ICY metadata prober
// ---------------------------------------------------------------
function parseStreamTitle(data) {
  // Look for StreamTitle='...' in the binary data
  const str = data.toString('latin1');
  const m = str.match(/StreamTitle='([^']+)'/);
  return m ? m[1] : '';
}

function probeStation(url, timeoutMs = 6000) {
  return new Promise((resolve) => {
    const startTime = Date.now();
    const isHttps = url.startsWith('https');
    const mod = isHttps ? https : http;

    let parsedUrl;
    try {
      parsedUrl = new URL(url);
    } catch {
      resolve({ song: '', icyName: '', icyBr: '', icyGenre: '', ok: false, latency: 0 });
      return;
    }

    const options = {
      hostname: parsedUrl.hostname,
      port: parsedUrl.port || (isHttps ? 443 : 80),
      path: parsedUrl.pathname + parsedUrl.search,
      method: 'GET',
      agent: socksAgent,
      headers: {
        'Icy-MetaData': '1',
        'User-Agent': 'WinampMPEG/5.66'
      }
    };

    let responded = false;
    let done = false;

    // Hard kill switch — fires regardless of DNS/connect/read state
    const killer = setTimeout(() => {
      if (!done) {
        done = true;
        req.destroy();
        resolve({ song: '', icyName: '', icyBr: '', icyGenre: '', ok: false, latency: timeoutMs });
      }
    }, timeoutMs);

    const req = mod.get(options, (res) => {
      if (done) return;
      responded = true;
      const latency = Date.now() - startTime;
      const icyName = (res.headers['icy-name'] || '').toString().trim();
      const icyBr = (res.headers['icy-br'] || '').toString().trim();
      const icyGenre = (res.headers['icy-genre'] || '').toString().trim();

      const chunks = [];
      let collected = 0;
      let songFound = false;

      res.on('data', (chunk) => {
        if (done || songFound) { req.destroy(); return; }
        chunks.push(chunk);
        collected += chunk.length;

        const combined = Buffer.concat(chunks);
        const song = parseStreamTitle(combined);

        if (song) {
          songFound = true;
          done = true;
          clearTimeout(killer);
          req.destroy();
          resolve({ song, icyName, icyBr, icyGenre, ok: true, latency });
        } else if (collected > 65536) {
          done = true;
          clearTimeout(killer);
          req.destroy();
          resolve({ song: '', icyName, icyBr, icyGenre, ok: true, latency });
        }
      });

      res.on('end', () => {
        if (!done && !songFound) {
          done = true;
          clearTimeout(killer);
          const combined = Buffer.concat(chunks);
          const song = parseStreamTitle(combined);
          resolve({ song, icyName, icyBr, icyGenre, ok: true, latency });
        }
      });
    });

    req.on('error', () => {
      if (!done) {
        done = true;
        clearTimeout(killer);
        resolve({ song: '', icyName: '', icyBr: '', icyGenre: '', ok: false, latency: responded ? Date.now() - startTime : timeoutMs });
      }
    });
  });
}

// ---------------------------------------------------------------
// 4. Probe orchestrator — probes all stations in parallel batches
// ---------------------------------------------------------------
async function probeAllStations(stations, onProgress) {
  const results = {};
  const BATCH_SIZE = 30;
  let done = 0;
  const total = stations.length;

  for (let i = 0; i < total; i += BATCH_SIZE) {
    const batch = stations.slice(i, i + BATCH_SIZE);
    const promises = batch.map(s => probeStation(s.url).then(result => ({ station: s, result })));
    const batchResults = await Promise.allSettled(promises);

    for (const pr of batchResults) {
      if (pr.status === 'fulfilled') {
        const { station, result } = pr.value;
        results[station.url] = {
          currentSong: result.song,
          icyName: result.icyName || station.icyName,
          icyBr: result.icyBr || String(station.bitrate),
          lastSeen: result.ok ? Date.now() : (station.lastSeen || 0),
          ok: result.ok,
          latency: result.latency || 0
        };
        done++;
        if (onProgress) onProgress(done, total, station, result);
      }
    }
  }

  return results;
}

// ---------------------------------------------------------------
// 5. Stream Cache — buffers selected station for proxy playback
// ---------------------------------------------------------------
class StreamCache {
  constructor(maxAgeMs = 300_000) {
    this.maxAge = maxAgeMs;           // 5 min default
    this.buffer = [];                 // {time, data, song}
    this.totalBytes = 0;
    this.currentSong = '';
    this.streamUrl = null;
    this._req = null;
    this._res = null;
    this._clients = [];               // active pipe targets
    this._bitrateEstimate = 64000;    // bytes/sec estimate
  }

  get bufferedSeconds() {
    return this.buffer.length > 0
      ? Math.round((this.totalBytes / this._bitrateEstimate) * 10) / 10
      : 0;
  }

  get isActive() {
    return this._req !== null && this.streamUrl !== null;
  }

  start(url) {
    this.stop();
    this.streamUrl = url;
    this.buffer = [];
    this.totalBytes = 0;
    this._connect();
  }

  stop() {
    if (this._req) { this._req.destroy(); this._req = null; }
    this.streamUrl = null;
    this._clients = [];
  }

  _connect() {
    if (!this.streamUrl) return;
    const isHttps = this.streamUrl.startsWith('https');
    const mod = isHttps ? https : http;

    let parsedUrl;
    try { parsedUrl = new URL(this.streamUrl); } catch { return; }

    const options = {
      hostname: parsedUrl.hostname,
      port: parsedUrl.port || (isHttps ? 443 : 80),
      path: parsedUrl.pathname + parsedUrl.search,
      agent: socksAgent,
      headers: {
        'Icy-MetaData': '1',
        'User-Agent': 'WinampMPEG/5.66'
      }
    };

    const req = mod.get(options, (res) => {
      this._req = req;
      const contentType = res.headers['content-type'] || 'audio/mpeg';

      let metaint = parseInt(res.headers['icy-metaint']) || 0;
      let metaBuf = null;
      let metaRemain = 0;

      // Update bitrate estimate from ICY header
      const icyBr = parseInt(res.headers['icy-br']);
      if (icyBr > 0) this._bitrateEstimate = Math.round(icyBr * 1000 / 8);

      res.on('data', (chunk) => {
        const now = Date.now();

        // Parse ICY metadata if available
        let data = chunk;
        if (metaint > 0) {
          // In-place ICY parsing
          const chunks = [];
          let offset = 0;
          while (offset < data.length) {
            if (metaRemain > 0) {
              const take = Math.min(metaRemain, data.length - offset);
              if (metaBuf) {
                metaBuf = Buffer.concat([metaBuf, data.slice(offset, offset + take)]);
              }
              metaRemain -= take;
              offset += take;
              if (metaRemain === 0 && metaBuf) {
                const song = parseStreamTitle(metaBuf);
                if (song && song !== this.currentSong) {
                  this.currentSong = song;
                }
                metaBuf = null;
              }
              continue;
            }
            const chunkEnd = Math.min(offset + metaint, data.length);
            chunks.push(data.slice(offset, chunkEnd));
            offset += metaint;
            if (offset < data.length) {
              const metaLen = data[offset] * 16;
              offset++;
              if (metaLen > 0) {
                metaRemain = metaLen;
                metaBuf = Buffer.alloc(0);
              }
            }
          }
          if (chunks.length > 0) data = Buffer.concat(chunks);
          else return;
        } else {
          // Try to find StreamTitle in raw data
          const song = parseStreamTitle(data);
          if (song && song !== this.currentSong) {
            this.currentSong = song;
          }
        }

        // Add to buffer
        this.buffer.push({ time: now, data, song: this.currentSong });
        this.totalBytes += data.length;

        // Evict old data beyond maxAge
        const cutoff = now - this.maxAge;
        while (this.buffer.length > 0 && this.buffer[0].time < cutoff) {
          this.totalBytes -= this.buffer[0].data.length;
          this.buffer.shift();
        }

        // Pipe to all connected clients
        for (const client of this._clients) {
          try { client.res.write(data); } catch { /* client gone */ }
        }
        this._clients = this._clients.filter(c => {
          try { return c.req.socket && !c.req.destroyed; } catch { return false; }
        });
      });

      res.on('end', () => {
        console.log(`[cache] Stream ended, reconnecting in 3s...`);
        this._req = null;
        setTimeout(() => this._connect(), 3000);
      });

      res.on('close', () => {
        if (this._req === req) {
          console.log(`[cache] Stream closed, reconnecting in 3s...`);
          this._req = null;
          setTimeout(() => this._connect(), 3000);
        }
      });

      res.on('error', () => {
        if (this._req === req) {
          this._req = null;
          setTimeout(() => this._connect(), 5000);
        }
      });
    });

    req.on('error', () => {
      this._req = null;
      setTimeout(() => this._connect(), 5000);
    });

    req.on('timeout', () => {
      req.destroy();
      this._req = null;
      setTimeout(() => this._connect(), 5000);
    });
  }

  // Serve cached + live to a client
  serve(res) {
    // Send buffered data immediately (catch-up)
    for (const chunk of this.buffer) {
      res.write(chunk.data);
    }

    // Register for live relay
    const client = { req: res.req, res };
    this._clients.push(client);

    // Remove on client disconnect
    res.on('close', () => {
      this._clients = this._clients.filter(c => c.res !== res);
    });
  }
}

// ---------------------------------------------------------------
// 6. Main server
// ---------------------------------------------------------------
const app = express();

// Views
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));
app.use(express.static(path.join(__dirname, 'public')));

// State
let stations = [];
let probeCache = {};
let lastFullProbe = 0;
let isProbing = false;
let sseClients = [];
let selectedStation = null; // { url, name, song } of currently selected
let currentVolume = 80; // 1-100
const streamCache = new StreamCache();

// Persist state to disk
function saveState() {
  try {
    fs.writeFileSync(STATE_FILE, JSON.stringify({
      selectedUrl: selectedStation ? selectedStation.url : null,
      selectedName: selectedStation ? selectedStation.name : null,
      selectedSong: selectedStation ? selectedStation.song : null,
      volume: currentVolume
    }));
  } catch(e) { console.error('saveState error:', e.message); }
}

// Load state from disk
function loadState() {
  try {
    if (fs.existsSync(STATE_FILE)) {
      const data = JSON.parse(fs.readFileSync(STATE_FILE, 'utf-8'));
      if (data.selectedUrl) {
        selectedStation = { url: data.selectedUrl, name: data.selectedName || '', song: data.selectedSong || '' };
        streamCache.start(data.selectedUrl); // resume caching
      }
      if (data.volume && data.volume >= 1 && data.volume <= 100) {
        currentVolume = data.volume;
      }
    }
  } catch(e) { console.error('loadState error:', e.message); }
}

// Parse stations on startup
try {
  stations = parseStations();
  loadState(); // restore persisted selection + volume
  console.log(`Parsed ${stations.length} stations, state restored (volume=${currentVolume}${selectedStation ? ', selected=' + selectedStation.name : ''})`);
} catch (err) {
  console.error('Error parsing stations:', err.message);
  process.exit(1);
}

// Background probe loop
async function runProbeCycle() {
  if (isProbing) return;
  isProbing = true;

  console.log(`\n[${new Date().toLocaleTimeString()}] Probing ${stations.length} stations...`);
  const startTime = Date.now();

  probeCache = await probeAllStations(stations, (done, total, station, result) => {
    // Push SSE update
    const data = JSON.stringify({
      type: 'probe_update',
      url: station.url,
      station: station.name,
      currentSong: result.song,
      bitrate: station.bitrate,
      format: station.format,
      latency: result.latency || 0,
      genre: station.genre,
      jazzRating: station.jazzRating,
      ok: result.ok
    });

    for (const client of sseClients) {
      client.res.write(`data: ${data}\n\n`);
    }
  });

  lastFullProbe = Date.now();
  const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
  const alive = Object.values(probeCache).filter(r => r.ok).length;
  console.log(`Probe complete: ${alive}/${stations.length} alive in ${elapsed}s`);

  // Send completion event
  const doneData = JSON.stringify({ type: 'probe_done', alive, total: stations.length, elapsed });
  for (const client of sseClients) {
    client.res.write(`data: ${doneData}\n\n`);
  }

  isProbing = false;
}

// Start first probe immediately, then every CACHE_TTL
runProbeCycle();
setInterval(runProbeCycle, CACHE_TTL);

// ---------------------------------------------------------------
// Routes
// ---------------------------------------------------------------

// Home page
app.get('/', (req, res) => {
  // Merge probe data into station list
  const enriched = stations.map(s => {
    const probe = probeCache[s.url] || {};
    return {
      ...s,
      currentSong: probe.currentSong || s.song,
      lastSeen: probe.lastSeen || null,
      alive: probe.ok !== undefined ? probe.ok : true,
      icyBr: probe.icyBr || String(s.bitrate),
      latency: probe.latency || 0
    };
  });

  const aliveCount = enriched.filter(s => s.alive).length;
  const deadCount = enriched.filter(s => !s.alive).length;

  // Count by jazz rating
  const jazzCounts = {};
  for (let i = 1; i <= 5; i++) {
    jazzCounts[i] = enriched.filter(s => s.jazzRating === i).length;
  }

  res.render('index', {
    stations: enriched,
    aliveCount,
    deadCount,
    totalCount: stations.length,
    jazzCounts,
    isProbing,
    lastUpdated: lastFullProbe ? new Date(lastFullProbe).toLocaleTimeString() : '—',
    lastUpdatedTimestamp: lastFullProbe
  });
});

// SSE endpoint for live probe updates
app.get('/api/probe', (req, res) => {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Access-Control-Allow-Origin': '*'
  });

  const client = { id: Date.now(), res };
  sseClients.push(client);
  console.log(`SSE client connected (total: ${sseClients.length})`);

  // Send current cache snapshot immediately
  const snapshot = stations.map(s => {
    const probe = probeCache[s.url] || {};
    return {
      url: s.url, station: s.name, currentSong: probe.currentSong || s.song,
      bitrate: s.bitrate, format: s.format, genre: s.genre, jazzRating: s.jazzRating,
      latency: probe.latency || 0,
      ok: probe.ok !== undefined ? probe.ok : true
    };
  });
  res.write(`data: ${JSON.stringify({ type: 'snapshot', stations: snapshot })}\n\n`);

  // Start probe if not running
  if (!isProbing && !lastFullProbe) {
    runProbeCycle();
  }

  req.on('close', () => {
    sseClients = sseClients.filter(c => c.id !== client.id);
  });
});

// Manual refresh trigger
app.post('/api/refresh', (req, res) => {
  if (!isProbing) runProbeCycle();
  res.json({ probing: true });
});

// Select a station for playback
app.post('/api/select', express.json(), (req, res) => {
  const { url } = req.body || {};
  if (!url) {
    selectedStation = null;
    streamCache.stop();
    saveState();
    return res.json({ ok: true, selected: null });
  }
  const s = stations.find(st => st.url === url);
  if (!s) return res.status(404).json({ ok: false, error: 'station not found' });
  const probe = probeCache[url] || {};
  selectedStation = { url: s.url, name: s.name, song: probe.currentSong || s.song };
  streamCache.start(s.url); // start buffering
  saveState();
  res.json({ ok: true, selected: selectedStation });
});

// Get current playback info (JSON)
app.get('/radio', (req, res) => {
  const proto = req.headers['x-forwarded-proto'] || req.protocol;
  const host = req.headers['x-forwarded-host'] || req.headers.host;
  const base = `${proto}://${host}`;
  res.json({
    url: selectedStation ? `${base}/radio/play` : null,
    name: selectedStation ? selectedStation.name : null,
    song: selectedStation ? selectedStation.song : null,
    volume: currentVolume // 1-100
  });
});

// Get selected station info
app.get('/api/selected', (req, res) => {
  res.json({
    ...(selectedStation || { url: null, name: null, song: null }),
    volume: currentVolume
  });
});

// Set volume
app.post('/api/volume', express.json(), (req, res) => {
  const { volume } = req.body || {};
  const v = parseInt(volume);
  if (isNaN(v) || v < 1 || v > 100) {
    return res.status(400).json({ ok: false, error: 'volume must be 1-100' });
  }
  currentVolume = v;
  saveState();
  res.json({ ok: true, volume: currentVolume });
});

// Proxy stream — raw TCP relay (no chunked encoding)
function handleRadioPlay(req, res) {
  if (!selectedStation || !selectedStation.url) {
    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'no station selected' }));
    return;
  }

  const stationUrl = selectedStation.url;
  const isHttps = stationUrl.startsWith('https');
  const mod = isHttps ? https : http;

  let parsedUrl;
  try { parsedUrl = new URL(stationUrl); } catch {
    res.writeHead(500, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'invalid station URL' }));
    return;
  }

  console.log(`[proxy] Client connecting to ${stationUrl}`);

  const options = {
    hostname: parsedUrl.hostname,
    port: parsedUrl.port || (isHttps ? 443 : 80),
    path: parsedUrl.pathname + parsedUrl.search,
    agent: socksAgent,
    headers: {
      'Icy-MetaData': '1',
      'User-Agent': 'WinampMPEG/5.66'
    }
  };

  mod.get(options, (stationRes) => {
    const icyName = stationRes.headers['icy-name'] || selectedStation.name || '';
    const icyBr = stationRes.headers['icy-br'] || '128';
    const ct = stationRes.headers['content-type'] || 'audio/mpeg';

    console.log(`[proxy] Connected, headers sent: ${icyName} @ ${icyBr}kbps`);

    // Prevent Node.js from adding chunked encoding
    res.useChunkedEncodingByDefault = false;
    delete res.chunkedEncoding;

    res.writeHead(200, {
      'Content-Type': ct,
      'icy-name': icyName,
      'icy-br': icyBr,
      'Transfer-Encoding': 'identity',
      'Access-Control-Allow-Origin': '*'
    });
    stationRes.pipe(res);
  }).on('error', (e) => {
    console.log(`[proxy] connect error: ${e.message}`);
    res.writeHead(502, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'connection failed' }));
  });
}

// Cache status - keep for info
app.get('/radio/cache-status', (req, res) => {
  res.json({
    active: streamCache.isActive,
    url: streamCache.streamUrl,
    currentSong: streamCache.currentSong,
    bufferedSeconds: streamCache.bufferedSeconds,
    totalBytes: streamCache.totalBytes,
    clients: streamCache._clients.length
  });
});

// ---------------------------------------------------------------
// Start — intercept /radio/play at HTTP level (no chunked encoding)
// ---------------------------------------------------------------
const server = http.createServer((req, res) => {
  if (req.url === '/radio/play' && req.method === 'GET') {
    return handleRadioPlay(req, res);
  }
  app(req, res);
});
server.listen(PORT, () => {
  console.log(`\n  🎵 Radio Streams Server running at http://localhost:${PORT}`);
  console.log(`  📡 ${stations.length} stations loaded, probing...\n`);
});
