# ares/server/app.py
import logging
import os
from flask import Flask, jsonify, render_template_string
from flask_socketio import SocketIO

log = logging.getLogger(__name__)

_DASHBOARD_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Project Ares</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js"></script>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0a0a0f; color: #c8d8e8; font-family: 'Courier New', monospace; font-size: 13px; }
#header { display: flex; justify-content: space-between; align-items: center;
          padding: 8px 16px; background: #0d1117; border-bottom: 1px solid #1e3a5f; }
#title { color: #4a9eff; font-size: 15px; font-weight: bold; letter-spacing: 2px; }
#status { display: flex; gap: 12px; align-items: center; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.dot.connected { background: #00ff88; }
.dot.disconnected { background: #ff4444; }
#main { display: grid; grid-template-columns: 1fr; padding: 12px; gap: 12px; }
#live-panel, #prog-panel { background: #0d1117; border: 1px solid #1e3a5f; padding: 12px; border-radius: 4px; }
.panel-title { color: #4a9eff; font-size: 11px; letter-spacing: 2px; margin-bottom: 10px; }
#boss-hp-bar { height: 14px; background: #1a1a2e; border-radius: 2px; margin-bottom: 12px; overflow: hidden; }
#boss-hp-fill { height: 100%; background: linear-gradient(90deg, #ff4444, #ff8844); transition: width 0.5s; }
.combatant-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.cname { width: 120px; }
.cjob { width: 40px; color: #7a9ab8; }
.cbar { flex: 1; height: 10px; background: #1a1a2e; border-radius: 2px; overflow: hidden; }
.cbar-fill { height: 100%; background: #4a9eff; transition: width 0.5s; }
.cdps { width: 70px; text-align: right; color: #00ff88; }
.cpct { width: 45px; text-align: right; color: #7a9ab8; }
#prog-chart { height: 100px; display: flex; align-items: flex-end; gap: 6px; padding: 8px 0; }
.pull-bar-wrap { display: flex; flex-direction: column; align-items: center; gap: 3px; cursor: pointer; }
.pull-bar { width: 32px; background: #4a9eff; border-radius: 2px 2px 0 0; min-height: 4px;
            transition: background 0.2s; }
.pull-bar.wipe { background: #ff6644; }
.pull-bar.kill { background: #00ff88; }
.pull-bar.active { background: #ffcc44; }
.pull-bar-wrap:hover .pull-bar { filter: brightness(1.3); }
.pull-label { font-size: 10px; color: #5a7a9a; }
#pull-list { margin-top: 12px; }
.pull-row { display: flex; align-items: center; gap: 8px; padding: 5px 8px; margin-bottom: 3px;
            border-radius: 3px; cursor: pointer; border: 1px solid transparent; }
.pull-row:hover { border-color: #1e3a5f; background: #0a0a1a; }
.pull-row.selected { border-color: #4a9eff; background: #0a0a1a; }
.outcome { width: 40px; font-size: 11px; }
.outcome.kill { color: #00ff88; }
.outcome.wipe { color: #ff6644; }
.outcome.active { color: #ffcc44; }
.pduration { width: 50px; color: #7a9ab8; }
.php-bar { flex: 1; height: 8px; background: #1a1a2e; border-radius: 2px; overflow: hidden; }
.php-fill { height: 100%; background: #ff6644; }
.php-pct { width: 40px; text-align: right; color: #ff6644; font-size: 11px; }
.analyze-btn { padding: 2px 8px; font-size: 10px; background: #1e3a5f; color: #4a9eff;
               border: 1px solid #4a9eff; border-radius: 2px; cursor: pointer; font-family: inherit; }
.analyze-btn:hover { background: #4a9eff; color: #000; }
#vs-bar { padding: 8px 12px; background: #0d1117; border-top: 1px solid #1e3a5f;
          font-size: 11px; color: #5a7a9a; display: flex; gap: 24px; }
.vs-good { color: #00ff88; }
.vs-bad { color: #ff6644; }
#log-feed { height: 80px; overflow-y: auto; font-size: 10px; color: #3a5a7a; margin-top: 8px;
            border-top: 1px solid #1a2a3a; padding-top: 6px; }
</style>
</head>
<body>
<div id="header">
  <div id="title">PROJECT ARES</div>
  <div id="status">
    <span class="dot disconnected" id="conn-dot"></span>
    <span id="conn-label">Disconnected</span>
    <span id="zone-label" style="color:#7a9ab8"></span>
    <span id="pull-label" style="color:#ffcc44"></span>
  </div>
</div>
<div id="main">
  <div id="live-panel" style="display:none">
    <div class="panel-title">LIVE</div>
    <div id="boss-hp-bar"><div id="boss-hp-fill" style="width:100%"></div></div>
    <div id="party-dps" style="color:#00ff88;margin-bottom:8px;font-size:15px"></div>
    <div id="combatants"></div>
    <div id="vs-bar">
      <span id="vs-dps"></span>
      <span id="vs-hp"></span>
    </div>
  </div>
  <div id="prog-panel">
    <div class="panel-title">PROGRESSION</div>
    <div id="prog-chart"></div>
    <div id="pull-list"></div>
    <div id="log-feed"></div>
  </div>
</div>
<script>
const socket = io();
let pulls = [];
let currentPull = null;
let selectedPullId = null;

socket.on('connect', () => {
  document.getElementById('conn-dot').className = 'dot connected';
  document.getElementById('conn-label').textContent = 'Connected';
  fetch('/api/session').then(r => r.json()).then(updateSession);
});
socket.on('disconnect', () => {
  document.getElementById('conn-dot').className = 'dot disconnected';
  document.getElementById('conn-label').textContent = 'Disconnected';
});
socket.on('encounter_state', data => {
  currentPull = data;
  document.getElementById('live-panel').style.display = 'block';
  document.getElementById('pull-label').textContent = `PULL ${data.pull_number} - LIVE ${formatDuration(data.duration)}`;
  document.getElementById('zone-label').textContent = data.zone || '';
  if (data.boss_hp_pct != null) {
    document.getElementById('boss-hp-fill').style.width = data.boss_hp_pct + '%';
  }
  document.getElementById('party-dps').textContent = 'PARTY DPS  ' + fmtNum(data.party_dps) + '    TOTAL DMG  ' + fmtNum(data.total_damage);
  renderCombatants(data.combatants || []);
  const vs = data.vs_prev;
  if (vs) {
    document.getElementById('vs-dps').innerHTML = `vs Pull ${vs.pull_id} avg: DPS <span class="${vs.dps_delta >= 0 ? 'vs-good' : 'vs-bad'}">${vs.dps_delta >= 0 ? '+' : ''}${fmtNum(vs.dps_delta)}</span>`;
    document.getElementById('vs-hp').innerHTML = `Boss HP: <span class="${vs.on_pace ? 'vs-good' : 'vs-bad'}">${vs.on_pace ? 'on pace' : 'behind pace'}</span>`;
  }
});
socket.on('encounter_end', data => {
  pulls.push(data);
  renderProgression();
  // Show final stats instead of hiding
  document.getElementById('pull-label').textContent = `PULL ${data.pull_id} - ${data.outcome.toUpperCase()} ${formatDuration(data.duration_secs)}`;
  document.getElementById('party-dps').textContent = 'FINAL DPS  ' + fmtNum(data.party_dps) + '    TOTAL DMG  ' + fmtNum(data.combatants?.reduce((s,c) => s + (c.total_damage||0), 0) || 0);
  if (data.combatants) renderCombatants(data.combatants.map(c => ({...c, dps: c.total_damage / data.duration_secs, pct: 100})));
});
socket.on('combat_event', data => {
  const feed = document.getElementById('log-feed');
  feed.innerHTML = data.raw_line.substring(0, 80) + '<br>' + feed.innerHTML;
  if (feed.children.length > 20) feed.lastChild.remove();
});

function updateSession(data) {
  pulls = data.pulls || [];
  if (data.current) {
    currentPull = data.current;
  }
  renderProgression();
}

function renderProgression() {
  // Chart
  const chart = document.getElementById('prog-chart');
  chart.innerHTML = '';
  pulls.forEach(p => {
    const pct = p.boss_hp_pct_at_end ?? 0;
    const height = Math.max(4, (100 - pct));
    const wrap = document.createElement('div');
    wrap.className = 'pull-bar-wrap';
    const bar = document.createElement('div');
    bar.className = `pull-bar ${p.outcome}`;
    bar.style.height = height + 'px';
    const lbl = document.createElement('div');
    lbl.className = 'pull-label';
    lbl.textContent = 'P' + p.pull_id;
    wrap.appendChild(bar);
    wrap.appendChild(lbl);
    wrap.onclick = () => selectPull(p.pull_id);
    chart.appendChild(wrap);
  });

  // Pull list
  const list = document.getElementById('pull-list');
  list.innerHTML = '';
  [...pulls].reverse().forEach(p => {
    const row = document.createElement('div');
    row.className = 'pull-row' + (selectedPullId === p.pull_id ? ' selected' : '');
    row.id = `pull-row-${p.pull_id}`;
    const pct = p.boss_hp_pct_at_end ?? 0;
    const dur = formatDuration(p.duration_secs);
    row.innerHTML = `
      <span class="outcome ${p.outcome}">Pull ${p.pull_id}</span>
      <span class="outcome ${p.outcome}">${p.outcome.toUpperCase()}</span>
      <span class="pduration">${dur}</span>
      <div class="php-bar"><div class="php-fill" style="width:${pct}%"></div></div>
      <span class="php-pct">${pct.toFixed(1)}%</span>
      <button class="analyze-btn" onclick="analyzePull(${p.pull_id})">Analyze</button>
    `;
    row.onclick = (e) => { if (!e.target.classList.contains('analyze-btn')) selectPull(p.pull_id); };
    list.appendChild(row);
  });
}

function selectPull(pullId) {
  selectedPullId = pullId;
  document.querySelectorAll('.pull-row').forEach(r => r.classList.remove('selected'));
  const row = document.getElementById(`pull-row-${pullId}`);
  if (row) row.classList.add('selected');
}

function analyzePull(pullId) {
  fetch(`/api/pulls/${pullId}/export`, {method: 'POST'})
    .then(r => r.json())
    .then(d => alert(`Exported to: ${d.path}`));
}

function renderCombatants(combatants) {
  const maxDps = Math.max(...combatants.map(c => c.dps), 1);
  const el = document.getElementById('combatants');
  el.innerHTML = combatants.map(c => `
    <div class="combatant-row">
      <span class="cname">${c.name}</span>
      <span class="cjob">${c.job}</span>
      <div class="cbar"><div class="cbar-fill" style="width:${(c.dps/maxDps*100).toFixed(1)}%"></div></div>
      <span class="cdps">${fmtNum(c.dps)}</span>
      <span class="cpct">${c.pct.toFixed(1)}%</span>
      <span style="width:80px;text-align:right;color:#7a9ab8;font-size:11px">${fmtNum(c.total_damage)} dmg</span>
    </div>`).join('');
}

function formatDuration(secs) {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${s.toString().padStart(2,'0')}`;
}
function fmtNum(n) {
  return Math.round(n).toLocaleString();
}
</script>
</body>
</html>'''


def create_app(session=None, deucalion_mgr=None):
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'ares-secret'
    socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

    @app.route('/')
    def dashboard():
        return render_template_string(_DASHBOARD_HTML)

    @app.route('/api/health')
    def health():
        return jsonify({
            'connected': deucalion_mgr.connected if deucalion_mgr else False,
            'status': 'ok'
        })

    @app.route('/api/session')
    def get_session():
        if session is None:
            return jsonify({'pulls': [], 'current': None})
        current = None
        if session.encounter_mgr.current:
            enc = session.encounter_mgr.current
            current = {
                'pull_number': enc.pull_id,
                'duration': enc.duration_secs,
                'active': True,
            }
        return jsonify({
            'pulls': session.encounter_mgr.progression_summary(),
            'current': current
        })

    @app.route('/api/pulls')
    def get_pulls():
        if session is None:
            return jsonify([])
        return jsonify(session.encounter_mgr.progression_summary())

    @app.route('/api/pulls/<int:pull_id>/export', methods=['POST'])
    def export_pull(pull_id):
        return jsonify({'path': f'logs/Pull_{pull_id}_export.log', 'status': 'ok'})

    return app, socketio
