// DOM Elements — Metronome
const bpmValue = document.getElementById('bpm-value');
const bpmSlider = document.getElementById('bpm-slider');
const toggleBtn = document.getElementById('toggle-btn');
const timeSignatureSelect = document.getElementById('time-signature');
const timeSigValue = document.getElementById('time-sig-value');
const beatIndicator = document.getElementById('beat-indicator');
const presetButtons = document.querySelectorAll('.preset-btn');
const sessionTimeEl = document.getElementById('session-time');
const totalTimeEl = document.getElementById('total-time');
const sessionCountEl = document.getElementById('session-count');
const resetBtn = document.getElementById('reset-btn');
const timerPaused = document.getElementById('timer-paused');

// DOM Elements — Tracking
const trackingToggleBtn = document.getElementById('tracking-toggle-btn');
const trackingStatus = document.getElementById('tracking-status');
const trackingHands = document.getElementById('tracking-hands');
const trackingWrists = document.getElementById('tracking-wrists');
const smoothingSlider = document.getElementById('smoothing-slider');
const smoothingValue = document.getElementById('smoothing-value');

// DOM Elements — Recording
const recToggleBtn = document.getElementById('rec-toggle-btn');
const recStatus = document.getElementById('rec-status');
const recElapsed = document.getElementById('rec-elapsed');
const recList = document.getElementById('rec-list');

// DOM Elements — MIDI
const midiPortSelect = document.getElementById('midi-port-select');
const midiRefreshBtn = document.getElementById('midi-refresh-btn');
const midiToggleBtn = document.getElementById('midi-toggle-btn');
const midiStatusEl = document.getElementById('midi-status');
const midiNote = document.getElementById('midi-note');
const midiVelocity = document.getElementById('midi-velocity');
const midiBody = document.getElementById('midi-body');
const midiNotesCount = document.getElementById('midi-notes-count');
const midiAmpSlider = document.getElementById('midi-amp-slider');
const midiAmpValue = document.getElementById('midi-amp-value');

// State
let isRunning = false;
let isTracking = false;
let isRecording = false;
let isMidiConnected = false;
let recState = 'idle';
let statusPollInterval = null;

// ── Helpers ──

function formatTime(totalSeconds) {
    const seconds = Math.floor(totalSeconds);
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    const mm = String(m).padStart(2, '0');
    const ss = String(s).padStart(2, '0');
    if (h > 0) return `${h}:${mm}:${ss}`;
    return `${mm}:${ss}`;
}

function getTimeSigText(beats) {
    const map = { 2: '2/4', 3: '3/4', 4: '4/4', 5: '5/4', 6: '6/8' };
    return map[beats] || `${beats}/4`;
}

// ── Metronome API ──

async function setBpm(bpm) {
    try {
        const r = await fetch('/bpm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bpm: parseInt(bpm) })
        });
        const d = await r.json();
        bpmValue.textContent = d.bpm;
        bpmSlider.value = d.bpm;
    } catch (e) { console.error('setBpm:', e); }
}

async function setTimeSignature(beats) {
    try {
        const r = await fetch('/time_signature', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ beats: parseInt(beats) })
        });
        const d = await r.json();
        updateBeatDots(d.time_signature);
        timeSigValue.textContent = getTimeSigText(d.time_signature);
    } catch (e) { console.error('setTimeSig:', e); }
}

async function startMetronome() {
    try {
        await fetch('/start', { method: 'POST' });
        isRunning = true;
        updateToggleButton();
        startStatusPolling();
    } catch (e) { console.error('start:', e); }
}

async function stopMetronome() {
    try {
        await fetch('/stop', { method: 'POST' });
        isRunning = false;
        updateToggleButton();
        stopStatusPolling();
        clearActiveBeat();
        await getStatus();
    } catch (e) { console.error('stop:', e); }
}

async function resetPractice() {
    try {
        await fetch('/practice/reset', { method: 'POST' });
        sessionTimeEl.textContent = '00:00';
        totalTimeEl.textContent = '00:00';
        sessionCountEl.textContent = isRunning ? '1' : '0';
    } catch (e) { console.error('resetPractice:', e); }
}

// ── Tracking API ──

async function startTracking() {
    try {
        await fetch('/tracking/start', { method: 'POST' });
        isTracking = true;
        updateTrackingUI();
        startStatusPolling();
    } catch (e) { console.error('startTracking:', e); }
}

async function stopTracking() {
    try {
        await fetch('/tracking/stop', { method: 'POST' });
        isTracking = false;
        updateTrackingUI();
        if (!isRunning) stopStatusPolling();
    } catch (e) { console.error('stopTracking:', e); }
}

async function setSmoothing(val) {
    try {
        await fetch('/tracking/smoothing', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value: val })
        });
    } catch (e) { console.error('setSmoothing:', e); }
}

// ── Recording API ──

async function startRecording() {
    try {
        const r = await fetch('/recording/start', { method: 'POST' });
        const d = await r.json();
        isRecording = d.recording;
        recState = d.state;
        updateRecUI();
        startStatusPolling();
    } catch (e) { console.error('startRecording:', e); }
}

async function stopRecording() {
    recState = 'saving';
    isRecording = false;
    updateRecUI();
    try {
        await fetch('/recording/stop', { method: 'POST' });
        // State transitions are handled by status polling.
        // Once backend finishes saving, polling will set recState='idle'.
    } catch (e) { console.error('stopRecording:', e); }
}

async function loadRecordings() {
    try {
        const r = await fetch('/recording/list');
        const d = await r.json();
        renderRecList(d.files || []);
    } catch (e) { console.error('loadRecordings:', e); }
}

async function deleteRecording(filename) {
    try {
        await fetch(`/recording/${encodeURIComponent(filename)}`, { method: 'DELETE' });
        loadRecordings();
    } catch (e) { console.error('deleteRecording:', e); }
}

// ── MIDI API ──

async function loadMidiPorts() {
    try {
        const r = await fetch('/midi/ports');
        const d = await r.json();
        const ports = d.ports || [];
        midiPortSelect.innerHTML = '<option value="">Select MIDI Device...</option>';
        ports.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p;
            opt.textContent = p;
            midiPortSelect.appendChild(opt);
        });
    } catch (e) { console.error('loadMidiPorts:', e); }
}

async function connectMidi() {
    const port = midiPortSelect.value;
    if (!port) return;
    try {
        const r = await fetch('/midi/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ port_name: port })
        });
        const d = await r.json();
        isMidiConnected = d.enabled;
        updateMidiUI();
        if (isMidiConnected) startStatusPolling();
    } catch (e) { console.error('connectMidi:', e); }
}

async function disconnectMidi() {
    try {
        await fetch('/midi/stop', { method: 'POST' });
        isMidiConnected = false;
        updateMidiUI();
        if (!isRunning && !isTracking && !isRecording) stopStatusPolling();
    } catch (e) { console.error('disconnectMidi:', e); }
}

async function setMidiAmplitude(val) {
    try {
        await fetch('/midi/amplitude', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value: val })
        });
    } catch (e) { console.error('setMidiAmplitude:', e); }
}

function updateMidiUI() {
    if (isMidiConnected) {
        midiToggleBtn.classList.add('active');
        midiToggleBtn.querySelector('.midi-btn-text').textContent = 'Disconnect';
        midiStatusEl.textContent = 'ON';
        midiStatusEl.className = 'midi-status on';
    } else {
        midiToggleBtn.classList.remove('active');
        midiToggleBtn.querySelector('.midi-btn-text').textContent = 'Connect';
        midiStatusEl.textContent = 'OFF';
        midiStatusEl.className = 'midi-status';
        midiNote.textContent = '--';
        midiVelocity.textContent = '--';
        midiBody.textContent = '0.0\u00b0';
        midiNotesCount.textContent = '0';
    }
}

function renderRecList(files) {
    if (!files.length) {
        recList.innerHTML = '<div class="rec-empty">No recordings yet</div>';
        return;
    }
    recList.innerHTML = files.map(f => `
        <div class="rec-item">
            <div class="rec-item-info">
                <span class="rec-item-name">${f.filename}</span>
                <span class="rec-item-size">${f.size_mb} MB</span>
            </div>
            <div class="rec-item-actions">
                <a class="rec-dl-btn" href="/recording/download/${encodeURIComponent(f.filename)}" download>DL</a>
                <button class="rec-del-btn" onclick="deleteRecording('${f.filename}')">Del</button>
            </div>
        </div>
    `).join('');
}

function updateRecUI() {
    if (recState === 'recording') {
        recToggleBtn.classList.add('active');
        recToggleBtn.querySelector('.rec-btn-text').textContent = 'STOP';
        recStatus.textContent = 'REC';
        recStatus.className = 'rec-status on';
    } else if (recState === 'saving') {
        recToggleBtn.classList.add('active');
        recToggleBtn.querySelector('.rec-btn-text').textContent = 'SAVING...';
        recStatus.textContent = 'SAVING';
        recStatus.className = 'rec-status saving';
    } else {
        recToggleBtn.classList.remove('active');
        recToggleBtn.querySelector('.rec-btn-text').textContent = 'REC';
        recElapsed.textContent = '00:00';
        recStatus.textContent = 'IDLE';
        recStatus.className = 'rec-status';
    }
}

// ── Status polling ──

// Cached previous values to avoid redundant DOM writes
let _prevRecState = null;
let _prevRecElapsed = '';
let _prevTracking = null;
let _prevBeat = null;
let _prevSession = '';
let _prevTotal = '';
let _prevCount = '';
let _prevMidi = null;

async function getStatus() {
    try {
        const r = await fetch('/status');
        const d = await r.json();

        // Beat — only update if changed
        if (d.current_beat !== _prevBeat) {
            _prevBeat = d.current_beat;
            updateBeatIndicator(d.current_beat);
        }

        // Practice timer — only update if changed
        if (d.practice) {
            const s = formatTime(d.practice.current_session);
            const t = formatTime(d.practice.total);
            const c = String(d.practice.session_count);
            if (s !== _prevSession) { _prevSession = s; sessionTimeEl.textContent = s; }
            if (t !== _prevTotal) { _prevTotal = t; totalTimeEl.textContent = t; }
            if (c !== _prevCount) { _prevCount = c; sessionCountEl.textContent = c; }
            // MIDI idle pause indicator
            const paused = !!d.practice.midi_paused;
            timerPaused.classList.toggle('visible', paused);
            sessionTimeEl.style.opacity = paused ? '0.4' : '1';
        }

        // Tracking — only update DOM when values actually change
        if (d.tracking) {
            const prev = _prevTracking;
            const cur = d.tracking;

            if (!prev || prev.enabled !== cur.enabled) {
                isTracking = cur.enabled;
                updateTrackingUI();
            }

            if (cur.enabled) {
                const handText = cur.hands_detected ? 'Detected' : 'Not found';
                const handClass = 'tracking-detail-value ' +
                    (cur.hands_detected ? 'detected' : 'not-detected');
                if (!prev || prev.hands_detected !== cur.hands_detected) {
                    trackingHands.textContent = handText;
                    trackingHands.className = handClass;
                }
                if (!prev || prev.num_wrists !== cur.num_wrists) {
                    trackingWrists.textContent = cur.num_wrists;
                }
            } else if (!prev || prev.enabled !== cur.enabled) {
                trackingHands.textContent = '--';
                trackingHands.className = 'tracking-detail-value';
                trackingWrists.textContent = '0';
            }

            _prevTracking = { ...cur };
        }

        // Recording — only update DOM when changed
        if (d.recording) {
            const rs = d.recording.state;
            if (rs !== _prevRecState) {
                // Saving just finished → refresh recording list
                if (_prevRecState === 'saving' && rs === 'idle') {
                    loadRecordings();
                    if (!isRunning && !isTracking && !isMidiConnected) stopStatusPolling();
                }
                _prevRecState = rs;
                recState = rs;
                isRecording = rs === 'recording';
                updateRecUI();
            }
            if (rs === 'recording') {
                const et = formatTime(d.recording.elapsed);
                if (et !== _prevRecElapsed) {
                    _prevRecElapsed = et;
                    recElapsed.textContent = et;
                }
            }
        }

        // MIDI — only update DOM when changed
        if (d.midi) {
            const mc = d.midi;
            if (!_prevMidi || _prevMidi.enabled !== mc.enabled) {
                isMidiConnected = mc.enabled;
                updateMidiUI();
            }
            if (mc.enabled) {
                if (!_prevMidi || _prevMidi.last_note !== mc.last_note) {
                    midiNote.textContent = mc.last_note_name || '--';
                }
                if (!_prevMidi || _prevMidi.last_velocity !== mc.last_velocity) {
                    midiVelocity.textContent = mc.last_velocity || '--';
                }
                if (!_prevMidi || _prevMidi.body_yaw !== mc.body_yaw) {
                    midiBody.textContent = mc.body_yaw + '\u00b0';
                }
                if (!_prevMidi || _prevMidi.notes_count !== mc.notes_count) {
                    midiNotesCount.textContent = mc.notes_count;
                }
            }
            _prevMidi = { ...mc };
        }

        return d;
    } catch (e) {
        console.error('getStatus:', e);
        return null;
    }
}

function startStatusPolling() {
    if (statusPollInterval) return;
    statusPollInterval = setInterval(getStatus, 100);
}

function stopStatusPolling() {
    if (statusPollInterval) {
        clearInterval(statusPollInterval);
        statusPollInterval = null;
    }
}

// ── UI Updates ──

function updateToggleButton() {
    if (isRunning) {
        toggleBtn.classList.add('running');
        toggleBtn.querySelector('.play-icon').textContent = '\u23F9';
        toggleBtn.querySelector('.btn-text').textContent = 'STOP';
    } else {
        toggleBtn.classList.remove('running');
        toggleBtn.querySelector('.play-icon').textContent = '\u25B6';
        toggleBtn.querySelector('.btn-text').textContent = 'START';
    }
}

function updateTrackingUI() {
    if (isTracking) {
        trackingToggleBtn.classList.add('active');
        trackingToggleBtn.querySelector('.tracking-btn-text').textContent = 'Disable Tracking';
        trackingStatus.textContent = 'ON';
        trackingStatus.className = 'tracking-status on';
    } else {
        trackingToggleBtn.classList.remove('active');
        trackingToggleBtn.querySelector('.tracking-btn-text').textContent = 'Enable Tracking';
        trackingStatus.textContent = 'OFF';
        trackingStatus.className = 'tracking-status';
    }
}

function updateBeatDots(numBeats) {
    beatIndicator.innerHTML = '';
    for (let i = 1; i <= numBeats; i++) {
        const dot = document.createElement('div');
        dot.className = 'beat-dot';
        dot.dataset.beat = i;
        beatIndicator.appendChild(dot);
    }
}

function updateBeatIndicator(currentBeat) {
    const dots = beatIndicator.querySelectorAll('.beat-dot');
    dots.forEach((dot, i) => {
        if (i + 1 === currentBeat) {
            dot.classList.add('active');
            dot.classList.toggle('downbeat', currentBeat === 1);
        } else {
            dot.classList.remove('active', 'downbeat');
        }
    });
}

function clearActiveBeat() {
    beatIndicator.querySelectorAll('.beat-dot')
        .forEach(d => d.classList.remove('active', 'downbeat'));
}

// ── Event Listeners ──

bpmSlider.addEventListener('input', e => { bpmValue.textContent = e.target.value; });
bpmSlider.addEventListener('change', e => { setBpm(e.target.value); });

toggleBtn.addEventListener('click', () => {
    isRunning ? stopMetronome() : startMetronome();
});

timeSignatureSelect.addEventListener('change', e => {
    setTimeSignature(e.target.value);
});

presetButtons.forEach(btn => {
    btn.addEventListener('click', () => setBpm(btn.dataset.bpm));
});

resetBtn.addEventListener('click', resetPractice);

trackingToggleBtn.addEventListener('click', () => {
    isTracking ? stopTracking() : startTracking();
});

recToggleBtn.addEventListener('click', () => {
    if (recState === 'recording') stopRecording();
    else if (recState === 'idle') startRecording();
});

smoothingSlider.addEventListener('input', e => {
    const val = (parseInt(e.target.value) / 100).toFixed(2);
    smoothingValue.textContent = val;
});

smoothingSlider.addEventListener('change', e => {
    setSmoothing(parseInt(e.target.value) / 100);
});

// ── MIDI Event Listeners ──

midiRefreshBtn.addEventListener('click', loadMidiPorts);

midiToggleBtn.addEventListener('click', () => {
    isMidiConnected ? disconnectMidi() : connectMidi();
});

midiAmpSlider.addEventListener('input', e => {
    midiAmpValue.textContent = e.target.value + '%';
});

midiAmpSlider.addEventListener('change', e => {
    setMidiAmplitude(parseInt(e.target.value) / 100);
});

// ── Init ──

document.addEventListener('DOMContentLoaded', async () => {
    bpmValue.textContent = 120;
    bpmSlider.value = 120;
    timeSigValue.textContent = '4/4';
    updateBeatDots(4);

    const status = await getStatus();
    if (status) {
        const bpm = status.bpm ?? 120;
        const ts = status.time_signature ?? 4;

        bpmValue.textContent = bpm;
        bpmSlider.value = bpm;
        timeSignatureSelect.value = ts;
        timeSigValue.textContent = getTimeSigText(ts);
        updateBeatDots(ts);

        isRunning = status.running ?? false;
        updateToggleButton();

        if (status.tracking) {
            isTracking = status.tracking.enabled;
            updateTrackingUI();
            if (status.tracking.smoothing) {
                const sv = status.tracking.smoothing;
                smoothingSlider.value = Math.round(sv * 100);
                smoothingValue.textContent = sv.toFixed(2);
            }
        }

        if (status.recording) {
            recState = status.recording.state;
            isRecording = recState === 'recording';
            updateRecUI();
        }

        if (status.midi) {
            isMidiConnected = status.midi.enabled;
            updateMidiUI();
            if (status.midi.amplitude != null) {
                const pct = Math.round(status.midi.amplitude * 100);
                midiAmpSlider.value = pct;
                midiAmpValue.textContent = pct + '%';
            }
        }

        if (isRunning || isTracking || isRecording || isMidiConnected) startStatusPolling();
    }

    loadRecordings();
    loadMidiPorts();
});
