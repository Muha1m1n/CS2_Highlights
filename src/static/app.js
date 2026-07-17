/**
 * ClipperCS2 Desktop Application Logic (`src/static/app.js`)
 * Handles local navigation, demo folder scanning, background parsing with SSE progress,
 * match browsing, player selection, highlight ranking, and live recording control.
 */

const state = {
    currentScreen: 'home',
    demos: [],
    matches: [],
    selectedMatch: null,
    players: [],
    selectedPlayer: null,
    highlights: [],
    rounds: [],
    activeTab: 'highlights',
    parseEventSource: null,
    recordEventSource: null
};

// DOM References
const $screens = {
    home: document.getElementById('homeScreen'),
    generate: document.getElementById('generateScreen'),
    matches: document.getElementById('matchesScreen'),
    detail: document.getElementById('detailScreen')
};

// Navigation
function showScreen(screenId) {
    Object.keys($screens).forEach(k => {
        if ($screens[k]) $screens[k].classList.toggle('active', k === screenId);
    });
    state.currentScreen = screenId;
}

function goHome() {
    showScreen('home');
}

function goToGenerate() {
    showScreen('generate');
    // Auto-fill default steam folder if empty
    const input = document.getElementById('demoFolderInput');
    if (!input.value) {
        input.value = "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Counter-Strike Global Offensive\\game\\csgo\\replays";
    }
    scanDemoFolder();
}

async function goToMatches() {
    showScreen('matches');
    await fetchMatches();
}

// API helper
async function apiFetch(url, options = {}) {
    try {
        const res = await fetch(url, options);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
    } catch (e) {
        console.error(`API Error [${url}]:`, e);
        return null;
    }
}

// ============================================================
// Demo Folder Scanner & Parsing
// ============================================================
async function scanDemoFolder() {
    const folder = document.getElementById('demoFolderInput').value.trim();
    const $list = document.getElementById('demoList');
    $list.innerHTML = '<div class="loading-state"><div class="spinner"></div><span>Scanning folder for .dem files...</span></div>';

    const data = await apiFetch(`/api/demos?folder=${encodeURIComponent(folder)}`);
    if (!data || !data.exists) {
        $list.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">&#9888;</div>
                <div class="empty-state-text">Folder not found or inaccessible</div>
                <div style="font-size:12px; color:var(--text-dim); margin-top:4px;">${escapeHtml(folder)}</div>
            </div>`;
        return;
    }

    state.demos = data.demos || [];
    state.demos.sort((a, b) => new Date(b.modified) - new Date(a.modified));
    if (state.demos.length === 0) {
        $list.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">&#128194;</div>
                <div class="empty-state-text">No .dem replay files found in this folder</div>
            </div>`;
        return;
    }

    $list.innerHTML = '';
    state.demos.forEach(d => {
        const card = document.createElement('div');
        card.className = 'demo-card';
        card.innerHTML = `
            <div>
                <div class="demo-info-title">&#128196; ${escapeHtml(d.filename)}</div>
                <div class="demo-info-sub">Size: ${d.size_mb} MB &bull; Modified: ${new Date(d.modified).toLocaleDateString()}</div>
            </div>
            <button class="btn-parse" onclick="parseDemoFile('${escapeJs(d.path)}', '${escapeJs(d.filename)}')">
                Parse & Generate Match &#8594;
            </button>
        `;
        $list.appendChild(card);
    });
}

async function parseDemoFile(path, filename) {
    showParseToast('parsing', `Starting parse for ${filename}...`);
    try {
        const res = await fetch('/api/parse', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ demo_path: path })
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        
        if (state.parseEventSource) state.parseEventSource.close();
        state.parseEventSource = new EventSource(`/api/parse/${data.task_id}/status`);
        
        state.parseEventSource.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                if (msg.message === 'STREAM_END') {
                    state.parseEventSource.close();
                    state.parseEventSource = null;
                    if (msg.status === 'done') {
                        showParseToast('done', `Success! ${filename} has been parsed.`);
                        setTimeout(() => { hideParseToast(); goToMatches(); }, 3000);
                    } else {
                        showParseToast('error', `Parsing failed for ${filename}`);
                        setTimeout(() => hideParseToast(), 5000);
                    }
                    return;
                }
                showParseToast(msg.status, msg.message);
            } catch (e) {
                console.error('SSE parse error:', e);
            }
        };
    } catch (e) {
        showParseToast('error', `Failed to initiate parsing: ${e.message}`);
        setTimeout(() => hideParseToast(), 5000);
    }
}

function showParseToast(status, message) {
    const $toast = document.getElementById('parseToast');
    const $dot = document.getElementById('parseDot');
    const $title = document.getElementById('parseTitle');
    const $msgs = document.getElementById('parseMessages');
    
    $toast.classList.add('visible');
    $dot.className = 'recording-dot';
    if (status === 'done') { $dot.classList.add('done'); $title.textContent = '&#9989; Parse Complete'; }
    else if (status === 'error') { $dot.classList.add('error'); $title.textContent = '&#10060; Parse Error'; }
    else { $title.textContent = '&#9881; Parsing Demo...'; }
    
    const div = document.createElement('div');
    div.className = 'toast-msg';
    div.textContent = message;
    $msgs.appendChild(div);
    $msgs.scrollTop = $msgs.scrollHeight;
}

function hideParseToast() {
    document.getElementById('parseToast').classList.remove('visible');
    document.getElementById('parseMessages').innerHTML = '';
}

// ============================================================
// Matches Browser & Details
// ============================================================
async function fetchMatches() {
    const $grid = document.getElementById('matchGrid');
    $grid.innerHTML = '<div class="loading-state"><div class="spinner"></div><span>Loading generated matches...</span></div>';
    
    const data = await apiFetch('/api/matches');
    state.matches = data || [];
    
    if (state.matches.length === 0) {
        $grid.innerHTML = `
            <div class="empty-state" style="grid-column: 1 / -1;">
                <div class="empty-state-icon">&#128193;</div>
                <div class="empty-state-text">No matches generated yet</div>
                <div style="font-size:13px; color:var(--text-dim); margin-top:6px;">Go back and click 'Generate New Match' to parse a .dem file</div>
            </div>`;
        return;
    }

    $grid.innerHTML = '';
    state.matches.forEach(m => {
        const card = document.createElement('div');
        card.className = 'match-card-large';
        card.onclick = () => selectMatch(m.sha256, m.demo_filename || m.map_name);
        
        const dateStr = m.parsed_at ? new Date(m.parsed_at).toLocaleDateString() : 'Unknown date';
        card.innerHTML = `
            <div>
                <div class="match-card-header">
                    <span class="match-map-badge">${escapeHtml(m.map_name || 'CS2 Match')}</span>
                    <span style="font-size:11px; color:var(--text-dim);">&#10140; View Highlights</span>
                </div>
                <div class="match-card-demo">${escapeHtml(m.demo_filename || 'unknown.dem')}</div>
            </div>
            <div class="match-card-date">&#128340; Parsed on ${dateStr}</div>
        `;
        $grid.appendChild(card);
    });
}

async function selectMatch(hash, title) {
    state.selectedMatch = hash;
    state.selectedPlayer = null;
    showScreen('detail');
    
    document.getElementById('detailTitle').textContent = `Match: ${title}`;
    const $chips = document.getElementById('playerChips');
    const $area = document.getElementById('contentArea');
    const $banner = document.getElementById('matchInfoBanner');
    const $stats = document.getElementById('playerStatsBanner');
    
    $stats.style.display = 'none';
    $chips.innerHTML = '<span>Loading players...</span>';
    $area.innerHTML = '<div class="loading-state"><div class="spinner"></div><span>Loading match players...</span></div>';
    
    const res = await apiFetch(`/api/matches/${hash}/players`);
    state.players = (res && res.players) ? res.players : (Array.isArray(res) ? res : []);
    state.matchInfo = (res && res.match_info) ? res.match_info : null;
    
    if (state.matchInfo && $banner) {
        const winnerBadge = state.matchInfo.winner === 'CT' ? '🛡️ CT Victory' : state.matchInfo.winner === 'T' ? '🗡️ T Victory' : '🤝 Tie Match';
        $banner.innerHTML = `<span style="color:var(--text-dim)">Final Score:</span> <span style="color:var(--primary); font-size:15px;">${state.matchInfo.score_string}</span> <span style="margin-left:8px; padding:2px 8px; background:rgba(255,255,255,0.08); border-radius:12px; font-size:12px;">${winnerBadge}</span>`;
        $banner.style.display = 'block';
    } else if ($banner) {
        $banner.style.display = 'none';
    }
    
    if (state.players.length === 0) {
        $chips.innerHTML = '<span style="color:var(--text-dim)">No players found</span>';
        $area.innerHTML = '<div class="empty-state"><div class="empty-state-text">No players found in this match</div></div>';
        return;
    }

    $chips.innerHTML = '';
    state.players.forEach(p => {
        const btn = document.createElement('button');
        btn.className = `player-chip ${p.name === state.selectedPlayer ? 'active' : ''}`;
        btn.onclick = () => selectPlayer(p.name);
        btn.innerHTML = `${escapeHtml(p.name)} <span class="chip-kills">${p.kills}K</span>`;
        $chips.appendChild(btn);
    });
    
    $area.innerHTML = `
        <div class="empty-state">
            <div class="empty-state-icon">&#128100;</div>
            <div class="empty-state-text">Select a player above to view their highlights and rounds</div>
        </div>`;
}

async function selectPlayer(name) {
    state.selectedPlayer = name;
    state.activeTab = 'highlights';
    
    // Update active chip
    document.querySelectorAll('.player-chip').forEach(el => {
        el.classList.toggle('active', el.textContent.includes(name));
    });
    
    // Populate Side and Match Result Stats Banner
    const $stats = document.getElementById('playerStatsBanner');
    const p = state.players.find(x => x.name === name);
    if (p && $stats) {
        $stats.innerHTML = `
            <div style="display:flex; align-items:center; gap:20px; flex-wrap:wrap; width:100%;">
                <div><span style="color:var(--text-dim); font-size:11px; text-transform:uppercase;">Player</span><br><b style="font-size:16px;">${escapeHtml(p.name)}</b></div>
                <div style="width:1px; height:28px; background:rgba(255,255,255,0.1);"></div>
                <div><span style="color:var(--text-dim); font-size:11px; text-transform:uppercase;">Match Result</span><br><b style="color:#10b981; font-size:15px;">🎖️ ${escapeHtml(p.match_result || 'Completed')}</b></div>
                <div style="width:1px; height:28px; background:rgba(255,255,255,0.1);"></div>
                <div><span style="color:var(--text-dim); font-size:11px; text-transform:uppercase;">Combat Stats</span><br><b style="font-size:15px;">⚔️ ${p.kills} Kills / ${p.deaths} Deaths (${p.kd} K/D)</b></div>
            </div>
        `;
        $stats.style.display = 'flex';
    } else if ($stats) {
        $stats.style.display = 'none';
    }
    
    switchTab('highlights');
}

function switchTab(tab) {
    state.activeTab = tab;
    document.getElementById('tabHighlights').classList.toggle('active', tab === 'highlights');
    document.getElementById('tabRounds').classList.toggle('active', tab === 'rounds');
    
    if (!state.selectedPlayer) return;
    renderContent();
}

async function renderContent() {
    const $area = document.getElementById('contentArea');
    $area.innerHTML = '<div class="loading-state"><div class="spinner"></div><span>Loading data...</span></div>';
    
    const encoded = encodeURIComponent(state.selectedPlayer);
    if (state.activeTab === 'highlights') {
        const highlights = await apiFetch(`/api/matches/${state.selectedMatch}/players/${encoded}/highlights`);
        state.highlights = highlights || [];
        renderHighlights();
    } else {
        const rounds = await apiFetch(`/api/matches/${state.selectedMatch}/players/${encoded}/rounds`);
        state.rounds = rounds || [];
        renderRounds();
    }
}

function renderHighlights() {
    const $area = document.getElementById('contentArea');
    if (state.highlights.length === 0) {
        $area.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-text">No highlights detected for ${escapeHtml(state.selectedPlayer)}</div>
            </div>`;
        return;
    }
    
    const sorted = [...state.highlights].sort((a, b) => b.total_score - a.total_score);
    const maxScore = Math.max(...sorted.map(h => h.total_score), 1);
    
    let html = '<div class="highlight-grid">';
    sorted.forEach(h => {
        const badge = getBadgeClass(h.highlight_type);
        const pct = Math.min(100, (h.total_score / maxScore) * 100);
        
        const sideBadge = h.side && h.side !== 'unknown' 
            ? `<span style="font-size:11px; padding:2px 8px; border-radius:10px; background:${h.side === 'CT' ? 'rgba(77,166,255,0.18)' : 'rgba(255,153,51,0.18)'}; color:${h.side === 'CT' ? '#4da6ff' : '#ff9933'}; font-weight:600; border:1px solid ${h.side === 'CT' ? 'rgba(77,166,255,0.3)' : 'rgba(255,153,51,0.3)'};">🛡️ ${h.side} Side</span>` 
            : '';
            
        const outcomeBadge = h.round_won !== undefined && h.round_won !== null
            ? `<span style="font-size:11px; padding:2px 8px; border-radius:10px; background:${h.round_won ? 'rgba(16,185,129,0.18)' : 'rgba(239,68,68,0.18)'}; color:${h.round_won ? '#10b981' : '#ef4444'}; font-weight:600; border:1px solid ${h.round_won ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'};">${h.round_won ? '🏆 Round Won' : '❌ Round Lost'}</span>` 
            : '';
            
        html += `
            <div class="highlight-card">
                <div class="highlight-header" style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px;">
                    <span class="highlight-badge ${badge}">${escapeHtml(h.highlight_type)}</span>
                    <div style="display:flex; align-items:center; gap:6px;">
                        ${sideBadge}
                        ${outcomeBadge}
                        <span style="font-size:12px; color:var(--text-secondary); margin-left:2px;">Round ${h.round_number}</span>
                    </div>
                </div>
                <div class="score-section">
                    <div class="score-label"><span>Score</span><span class="score-value">${h.total_score.toFixed(1)}</span></div>
                    <div class="score-bar-track"><div class="score-bar-fill" style="width:${pct}%"></div></div>
                </div>
                <div class="highlight-desc">${escapeHtml(h.description)}</div>
                <div class="score-breakdown">
                    <span>Base: ${h.base_score.toFixed(1)}</span>
                    <span>Skill: +${h.skill_bonus.toFixed(1)}</span>
                    <span>ML: +${h.ml_boost.toFixed(1)}</span>
                </div>
                <button class="btn-record" onclick="recordClip(${h.start_tick}, ${h.end_tick}, '${escapeJs(h.description)}', ${h.round_number})">
                    &#127916; Record Clip
                </button>
            </div>`;
    });
    html += '</div>';
    $area.innerHTML = html;
}

function renderRounds() {
    const $area = document.getElementById('contentArea');
    if (state.rounds.length === 0) {
        $area.innerHTML = '<div class="empty-state"><div class="empty-state-text">No kill rounds found</div></div>';
        return;
    }
    
    let html = '';
    state.rounds.forEach(r => {
        const sideBadge = r.side && r.side !== 'unknown' 
            ? `<span style="font-size:11px; padding:2px 8px; border-radius:10px; background:${r.side === 'CT' ? 'rgba(77,166,255,0.18)' : 'rgba(255,153,51,0.18)'}; color:${r.side === 'CT' ? '#4da6ff' : '#ff9933'}; font-weight:600; border:1px solid ${r.side === 'CT' ? 'rgba(77,166,255,0.3)' : 'rgba(255,153,51,0.3)'};">🛡️ ${r.side} Side</span>` 
            : '';
            
        const outcomeBadge = r.round_won !== undefined && r.round_won !== null
            ? `<span style="font-size:11px; padding:2px 8px; border-radius:10px; background:${r.round_won ? 'rgba(16,185,129,0.18)' : 'rgba(239,68,68,0.18)'}; color:${r.round_won ? '#10b981' : '#ef4444'}; font-weight:600; border:1px solid ${r.round_won ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'};">${r.round_won ? '🏆 Round Won' : '❌ Round Lost'}</span>` 
            : '';
            
        html += `
            <div class="round-card">
                <div class="round-header" style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px;">
                    <div style="display:flex; align-items:center; gap:8px;">
                        <span class="round-title">Round ${r.round_number}</span>
                        ${sideBadge}
                        ${outcomeBadge}
                    </div>
                    <span class="round-kills-badge">${r.total_kills} Kills</span>
                </div>
                <ul class="kill-list">`;
        
        r.kills.forEach(k => {
            let icons = '';
            if (k.headshot) icons += ' &#127919;';
            if (k.noscope) icons += ' &#128269;';
            if (k.thrusmoke) icons += ' &#128168;';
            if (k.penetrated) icons += ' &#129811;';
            
            html += `
                <li class="kill-item">
                    <span class="kill-weapon">${escapeHtml(k.weapon || 'unknown')}</span>
                    <span class="kill-victim">${escapeHtml(k.victim || 'Unknown')}</span>
                    <span>${icons}</span>
                </li>`;
        });
        
        html += `
                </ul>
                <button class="btn-record" onclick="recordClip(${r.first_kill_tick}, ${r.last_kill_tick}, '${escapeJs(state.selectedPlayer)} Round ${r.round_number}', ${r.round_number})">
                    &#127916; Clip This Round
                </button>
            </div>`;
    });
    $area.innerHTML = html;
}

// ============================================================
// Record Clip with SSE Toast
// ============================================================
async function recordClip(startTick, endTick, desc, roundNum) {
    showRecordToast('connecting', 'Starting recording engine...');
    try {
        const res = await fetch('/api/record', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                match_hash: state.selectedMatch,
                player_name: state.selectedPlayer,
                start_tick: startTick,
                end_tick: endTick,
                description: desc,
                round_num: roundNum
            })
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        
        if (state.recordEventSource) state.recordEventSource.close();
        state.recordEventSource = new EventSource(`/api/record/${data.task_id}/status`);
        
        state.recordEventSource.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                if (msg.message === 'STREAM_END') {
                    state.recordEventSource.close();
                    state.recordEventSource = null;
                    if (msg.status === 'done') showRecordToast('done', 'Clip recorded and saved!');
                    else showRecordToast('error', 'Recording failed');
                    setTimeout(() => hideRecordToast(), 4000);
                    return;
                }
                showRecordToast(msg.status, msg.message);
            } catch (e) {
                console.error('SSE record error:', e);
            }
        };
    } catch (e) {
        showRecordToast('error', `Failed to start recording: ${e.message}`);
        setTimeout(() => hideRecordToast(), 4000);
    }
}

function showRecordToast(status, message) {
    const $toast = document.getElementById('recordingToast');
    const $dot = document.getElementById('toastDot');
    const $title = document.getElementById('toastTitle');
    const $msgs = document.getElementById('toastMessages');
    
    $toast.classList.add('visible');
    $dot.className = 'recording-dot';
    if (status === 'done') { $dot.classList.add('done'); $title.textContent = '&#9989; Recording Complete'; }
    else if (status === 'error') { $dot.classList.add('error'); $title.textContent = '&#10060; Recording Error'; }
    else { $title.textContent = '&#128308; Recording...'; }
    
    const div = document.createElement('div');
    div.className = 'toast-msg';
    div.textContent = message;
    $msgs.appendChild(div);
    $msgs.scrollTop = $msgs.scrollHeight;
}

function hideRecordToast() {
    document.getElementById('recordingToast').classList.remove('visible');
    document.getElementById('toastMessages').innerHTML = '';
}

// Helpers
function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function escapeJs(str) {
    if (!str) return '';
    return String(str).replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"');
}

function getBadgeClass(type) {
    if (!type) return 'badge-kill';
    const t = type.toLowerCase();
    if (t.includes('ace')) return 'badge-ace';
    if (t.includes('4k')) return 'badge-4k';
    if (t.includes('3k')) return 'badge-3k';
    if (t.includes('2k')) return 'badge-2k';
    return 'badge-kill';
}
