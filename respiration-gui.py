import csv
import io
import threading
from datetime import datetime, timedelta

import serial
from flask import Flask, Response, jsonify, render_template_string

PORT = "COM3"
BAUD = 115200

ser = serial.Serial(PORT, BAUD)
app = Flask(__name__)

lock = threading.Lock()
state = {"t_ms": 0, "raw": 0, "bpm": 0.0, "live": 0.0}
recording = False
rec_rows = []
rec_start_wall = None


def samples(ser):
    t_ms = 0
    rate = 0.0
    interval = 0
    last_peak_t = 0
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
                if peak:
                    interval = (buf[3] << 14) | (buf[4] << 7) | buf[5]
                    rate = 60000.0 / interval
                    last_peak_t = t_ms
                buf = []
                # Live rate: drops between breaths once the gap is longer
                # than the last breath interval
                since = t_ms - last_peak_t
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
  input { width: 6rem; }
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
  <div id="info"></div>
</header>
<main></main>
<footer>
  <label for="species">Threshold</label>
  <select id="species">
    <option value="160">Rousettus aegyptiacus [egyptian fruit bat], 160 bpm</option>
    <option value="100">Eptesicus fuscus [little brown bat], 100 bpm</option>
    <option value="180">Carollia [short tailed bat], 180 bpm</option>
    <option value="other">Other</option>
  </select>
  <input id="custom" type="number" min="1" step="1" placeholder="bpm" hidden>
  <button id="recBtn">Start recording</button>
</footer>

<script>
const sel = document.getElementById('species');
const custom = document.getElementById('custom');
const bpmEl = document.getElementById('bpm');
const limitEl = document.getElementById('limit');
const btn = document.getElementById('recBtn');
const infoEl = document.getElementById('info');
let rec = false;

function threshold() {
  return parseFloat(sel.value === 'other' ? custom.value : sel.value);
}

sel.onchange = () => {
  custom.hidden = sel.value !== 'other';
  if (!custom.hidden) custom.focus();
};

async function poll() {
  try {
    const s = await (await fetch('/status')).json();
    const th = threshold();
    bpmEl.textContent = s.bpm.toFixed(1);
    bpmEl.className = (!isNaN(th) && s.bpm > th) ? 'over' : 'ok';
    limitEl.textContent = isNaN(th) ? 'Enter a threshold' : 'Limit ' + th + ' bpm';
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