import csv
import io
import threading
from datetime import datetime, timedelta

import serial
from flask import Flask, Response, jsonify, render_template_string, request

PORT = "COM3"
BAUD = 115200

ser = serial.Serial(PORT, BAUD)
app = Flask(__name__)

lock = threading.Lock()
state = {"t_ms": 0, "raw": 0, "bpm": 0.0, "live": 0.0}
recording = False
rec_rows = []
rec_start_wall = None

# Breath detection settings, changed from the page. Detection runs here in
# Python on the raw signal; the Arduino's own peak flags are ignored.
config = {"threshold": 60, "refractory": 400}


def samples(ser):
    t_ms = 0
    rate = 0.0
    interval = 0
    last_peak_t = None
    is_peak = False
    buf = []
    while True:
        for b in ser.read(ser.in_waiting or 1):
            if b & 0x80:            # start of packet
                buf = [b]
                continue
            if not buf:             # still syncing
                continue
            buf.append(b)
            peak = buf[0] & 0x40
            if len(buf) == (6 if peak else 3):
                raw = ((buf[0] & 0x1F) << 5) | buf[1]
                t_ms += buf[2]
                buf = []
                # Same logic the Arduino used, with adjustable numbers
                th, refr = config["threshold"], config["refractory"]
                if raw > th and not is_peak:
                    if last_peak_t is None:
                        last_peak_t = t_ms
                    elif t_ms - last_peak_t > refr:
                        interval = t_ms - last_peak_t
                        rate = 60000.0 / interval
                        last_peak_t = t_ms
                    is_peak = True   # wait for the signal to drop before the next breath
                if raw < th * 0.7:
                    is_peak = False
                # Live rate: drops between breaths once the gap is longer
                # than the last breath interval
                since = t_ms - last_peak_t if last_peak_t is not None else 0
                live = 60000.0 / since if interval and since > interval else rate
                yield t_ms, raw, rate, live


def reader():
    for t_ms, raw, rate, live in samples(ser):
        with lock:
            state.update(t_ms=t_ms, raw=raw, bpm=rate, live=live)
            if recording:
                rec_rows.append((t_ms, raw, rate, live))


threading.Thread(target=reader, daemon=True).start()

@app.route("/")
def index():
    return render_template_string(PAGE)


@app.route("/status")
def status():
    with lock:
        return jsonify(bpm=state["live"], raw=state["raw"], recording=recording,
                       samples=len(rec_rows))


@app.route("/config", methods=["GET", "POST"])
def set_config():
    if request.method == "POST":
        d = request.get_json(force=True)
        try:
            t = int(d["threshold"])
            r = int(d["refractory"])
        except (KeyError, TypeError, ValueError):
            return "threshold and refractory must be whole numbers", 400
        if not 1 <= t <= 1023:
            return "threshold must be 1-1023", 400
        if not 50 <= r <= 10000:
            return "refractory must be 50-10000 ms", 400
        config.update(threshold=t, refractory=r)
    return jsonify(config)


@app.route("/start", methods=["POST"])
def start():
    global recording, rec_start_wall
    with lock:
        rec_rows.clear()
        rec_start_wall = datetime.now()
        recording = True
    return "", 204


@app.route("/stop", methods=["POST"])
def stop():
    global recording
    with lock:
        recording = False
        rows = list(rec_rows)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["timestamp", "time_s", "value", "bpm", "bpm_live"])
    t0 = rows[0][0] if rows else 0
    for t_ms, raw, rate, live in rows:
        wall = rec_start_wall + timedelta(milliseconds=t_ms - t0)
        w.writerow([wall.isoformat(timespec="milliseconds"),
                    f"{(t_ms - t0) / 1000:.3f}", raw, f"{rate:.2f}", f"{live:.2f}"])
    return Response(out.getvalue(), mimetype="text/csv")


PAGE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Breathing rate</title>
<style>
  :root {
    --bg: #1c2230; --panel: #262e3f; --ink: #e8ebf2; --muted: #9aa3b5;
    --ok: #3ccf7a; --over: #ff5a5a; --accent: #8fb3ff;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    background: var(--bg); color: var(--ink);
    font-family: "Segoe UI", system-ui, -apple-system, Roboto, sans-serif;
    display: flex; flex-direction: column;
  }
  header { padding: 2rem 1rem 0; text-align: center; }
  #bpm {
    font-size: clamp(5rem, 22vw, 14rem); font-weight: 700; line-height: 1;
    font-variant-numeric: tabular-nums; transition: color .2s;
  }
  #bpm.ok { color: var(--ok); }
  #bpm.over { color: var(--over); }
  .unit { color: var(--muted); font-size: 1.25rem; margin-top: .5rem; }
  #limit, #info { color: var(--muted); margin-top: .25rem; }
  main { flex: 1; }
  footer {
    background: var(--panel); padding: 1rem;
    display: flex; flex-wrap: wrap; gap: .75rem; align-items: center;
    justify-content: center;
  }
  label { color: var(--muted); }
  select, input, button {
    font: inherit; padding: .6rem .8rem; border-radius: 6px;
    border: 1px solid #3a4459; background: var(--bg); color: var(--ink);
  }
  input { width: 4.5rem; }
  input[type=checkbox] { width: auto; accent-color: var(--accent); }
  fieldset {
    border: 1px solid #3a4459; border-radius: 8px; padding: .5rem .75rem;
    display: flex; flex-wrap: wrap; gap: .5rem; align-items: center;
  }
  legend { color: var(--muted); padding: 0 .3rem; }
  #warn { color: var(--over); font-weight: 600; min-height: 1.5em; margin-top: .25rem; }
  #maxBpm { color: var(--muted); }
  #maxBpm.bad { color: var(--over); }
  button { background: var(--accent); color: #10141d; border: 0; font-weight: 600; cursor: pointer; }
  button.rec { background: var(--over); color: #fff; }
  :focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
</style>
</head>
<body>
<header>
  <div id="bpm" class="ok">0.0</div>
  <div class="unit">breaths per minute</div>
  <div id="limit"></div>
  <div id="warn" role="status"></div>
  <div id="info"></div>
</header>
<main></main>
<footer>
  <fieldset>
    <legend>Alarms</legend>
    <label for="species">Species</label>
    <select id="species">
      <option value="200">Rousettus aegyptiacus [egyptian fruit bat]</option>
      <option value="100">Eptesicus fuscus [little brown bat]</option>
      <option value="180">Carollia [short tailed bat]</option>
      <option value="other">Other</option>
    </select>
    <label><input type="checkbox" id="hiOn" checked> Above</label>
    <input id="hi" type="number" min="1" step="1" aria-label="High limit, bpm"> bpm
    <label><input type="checkbox" id="loOn" checked> Below</label>
    <input id="lo" type="number" min="0" step="1" value="20" aria-label="Low limit, bpm"> bpm
    <label><input type="checkbox" id="jumpOn" checked> Change over</label>
    <input id="jumpPct" type="number" min="1" step="1" value="30" aria-label="Sudden change, percent"> %
    within <input id="jumpSec" type="number" min="1" step="1" value="5" aria-label="Sudden change window, seconds"> s
  </fieldset>
  <fieldset>
    <legend>Breath detection</legend>
    <label for="thr">Peak threshold</label>
    <input id="thr" type="number" min="1" max="1023" step="1">
    <label for="refr">Min gap between breaths</label>
    <input id="refr" type="number" min="50" max="10000" step="10"> ms
    <span id="maxBpm"></span>
    <button id="applyBtn">Apply</button>
  </fieldset>
  <button id="recBtn">Start recording</button>
</footer>

<script>
const $ = id => document.getElementById(id);
const sel = $('species'), hi = $('hi'), lo = $('lo');
const jumpPct = $('jumpPct'), jumpSec = $('jumpSec');
const thr = $('thr'), refr = $('refr'), maxBpmEl = $('maxBpm');
const bpmEl = $('bpm'), limitEl = $('limit'), warnEl = $('warn');
const btn = $('recBtn'), infoEl = $('info');
let rec = false;

// ---- Alarm settings ----
// Picking a species fills in its high limit; typing a limit switches to "Other"
sel.onchange = () => {
  if (sel.value !== 'other') hi.value = sel.value;
  else hi.focus();
  updateMaxBpm();
};
hi.oninput = () => { sel.value = 'other'; updateMaxBpm(); };
hi.value = sel.value;

// ---- Sensor settings (sent to the Arduino) ----
function updateMaxBpm() {
  const r = parseFloat(refr.value);
  if (!(r > 0)) { maxBpmEl.textContent = ''; return; }
  const max = 60000 / r;
  const h = parseFloat(hi.value);
  const unreachable = $('hiOn').checked && h >= max;
  maxBpmEl.textContent = 'Max detectable ' + max.toFixed(0) + ' bpm' +
    (unreachable ? ' (below your high limit, so that alarm can never fire)' : '');
  maxBpmEl.className = unreachable ? 'bad' : '';
}
refr.oninput = updateMaxBpm;
$('hiOn').onchange = updateMaxBpm;

async function loadConfig() {
  try {
    const c = await (await fetch('/config')).json();
    thr.value = c.threshold;
    refr.value = c.refractory;
    updateMaxBpm();
  } catch (e) {}
}
loadConfig();

$('applyBtn').onclick = async () => {
  const r = await fetch('/config', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ threshold: thr.value, refractory: refr.value })
  });
  if (r.ok) {
    $('applyBtn').textContent = 'Sent';
    setTimeout(() => $('applyBtn').textContent = 'Apply', 1500);
  } else {
    alert('Not applied: ' + await r.text());
    loadConfig();
  }
};

// ---- Sudden-change detection ----
// Compares the median rate over the last 2 s with the median rate
// jumpSec seconds earlier, so one missed or extra breath doesn't trigger it.
const hist = [];  // [seconds, bpm]
const SMOOTH_S = 2;
function median(a) {
  const s = [...a].sort((x, y) => x - y), m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}
function suddenChange(now, bpm) {
  const win = parseFloat(jumpSec.value), pct = parseFloat(jumpPct.value);
  hist.push([now, bpm]);
  while (hist.length && hist[0][0] < now - (win || 0) - SMOOTH_S - 1) hist.shift();
  if (!(win > 0) || !(pct > 0) || hist[0][0] > now - win - SMOOTH_S + 0.5) return null;
  const recent = hist.filter(h => h[0] >= now - SMOOTH_S).map(h => h[1]);
  const past = hist.filter(h => h[0] >= now - win - SMOOTH_S && h[0] < now - win).map(h => h[1]);
  if (!recent.length || !past.length) return null;
  const a = median(past), b = median(recent);
  if (a <= 0) return null;
  const change = (b - a) / a * 100;
  return Math.abs(change) > pct ? change : null;
}

async function poll() {
  try {
    const s = await (await fetch('/status')).json();
    const now = performance.now() / 1000;
    const h = parseFloat(hi.value), l = parseFloat(lo.value);
    const warnings = [];
    if ($('hiOn').checked && !isNaN(h) && s.bpm > h) warnings.push('Above ' + h + ' bpm');
    if ($('loOn').checked && !isNaN(l) && s.bpm < l) warnings.push('Below ' + l + ' bpm');
    const ch = suddenChange(now, s.bpm);
    if ($('jumpOn').checked && ch !== null)
      warnings.push('Sudden ' + (ch > 0 ? 'rise' : 'drop') + ' ' +
                    Math.abs(ch).toFixed(0) + '% in ' + jumpSec.value + ' s');

    bpmEl.textContent = s.bpm.toFixed(1);
    bpmEl.className = warnings.length ? 'over' : 'ok';
    warnEl.textContent = warnings.join(' · ');
    const parts = [];
    if ($('hiOn').checked && !isNaN(h)) parts.push('High ' + h);
    if ($('loOn').checked && !isNaN(l)) parts.push('Low ' + l);
    limitEl.textContent = parts.length ? parts.join(', ') + ' bpm' : 'No rate limits on';
    infoEl.textContent = 'Signal ' + s.raw +
      (s.recording ? ', recording ' + s.samples + ' samples' : '');
  } catch (e) {
    limitEl.textContent = 'Lost connection to the app';
  }
}
setInterval(poll, 250);
poll();

function defaultName() {
  const d = new Date(), p = n => String(n).padStart(2, '0');
  return `breathing_${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}_` +
         `${p(d.getHours())}-${p(d.getMinutes())}-${p(d.getSeconds())}.csv`;
}

btn.onclick = async () => {
  if (!rec) {
    await fetch('/start', { method: 'POST' });
    rec = true;
    btn.textContent = 'Stop recording';
    btn.classList.add('rec');
    return;
  }

  let handle = null, name = null;
  if (window.showSaveFilePicker) {
    try {
      handle = await showSaveFilePicker({
        suggestedName: defaultName(),
        types: [{ description: 'CSV', accept: { 'text/csv': ['.csv'] } }]
      });
    } catch (e) {
      return;  // cancelled: keep recording
    }
  } else {
    name = prompt('Save recording as:', defaultName());
    if (name === null) return;  // cancelled: keep recording
  }

  const csv = await (await fetch('/stop', { method: 'POST' })).text();
  rec = false;
  btn.textContent = 'Start recording';
  btn.classList.remove('rec');

  if (handle) {
    try {
      const w = await handle.createWritable();
      await w.write(new Blob([csv], { type: 'text/csv' }));
      await w.close();
    } catch (e) {
      alert('Could not write the file (' + e.message + '). Saving to Downloads instead.');
      handle = null;
      name = defaultName();
    }
  }
  if (!handle) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    a.download = name.endsWith('.csv') ? name : name + '.csv';
    a.click();
    URL.revokeObjectURL(a.href);
  }
};
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, threaded=True)