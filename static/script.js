// Init Socket.IO for Real-time push
const socket = io();
socket.on('new_data', (data) => {
    console.log('Real-time update received:', data);
    fetchEvents(); // Push UI update immediately
});

// Setup Audio Context for playing Beeps
const audioCtx = new (window.AudioContext || window.webkitAudioContext)();


// Animate Counter Function
function animateCounter(id, target) {
  const el = document.getElementById(id);
  if (!el) return;
  
  const currentText = el.textContent || "0";
  const start = parseInt(currentText.replace(/,/g, '')) || 0;
  if (start === target) return; // No change, no animation

  const duration = 800;
  const startTime = performance.now();
  
  function step(currentTime) {
    const progress = Math.min((currentTime - startTime) / duration, 1);
    const easeProgress = 1 - Math.pow(1 - progress, 3);
    const current = Math.floor(start + (target - start) * easeProgress);
    el.textContent = current.toLocaleString();
    if (progress < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

// Init on Startup
document.addEventListener('DOMContentLoaded', () => {
  
  // Animate initial stats if present
  ['statTotal', 'statF1A', 'statF1B', 'statFM'].forEach(id => {
    const el = document.getElementById(id);
    if (el && el.textContent) animateCounter(id, parseInt(el.textContent));
  });
});

// Make sure audio context resumes on first user interaction
document.body.addEventListener('click', () => {
    if (audioCtx.state === 'suspended') audioCtx.resume();
}, { once: true });

function playBeep(type) {
    if (window.BEEP_ENABLED === false) return;
    
    // Suara beep hanya aktif pada halaman Timing
    const isTimingPage = document.getElementById('timingEventsBody') || document.getElementById('timingLeftBody');
    if (!isTimingPage) return;

    if (audioCtx.state === 'suspended') audioCtx.resume();
    
    const oscillator = audioCtx.createOscillator();
    const gainNode = audioCtx.createGain();
    
    oscillator.connect(gainNode);
    gainNode.connect(audioCtx.destination);
    
    if (type === 'F1') {
        oscillator.type = 'sine';
        oscillator.frequency.value = 1800; // High pitch for F1 (Left)
    } else if (type === 'F2') {
        oscillator.type = 'triangle';
        oscillator.frequency.value = 1400; // Lower pitch for F2 (Right)
    } else {
        oscillator.type = 'square';
        oscillator.frequency.value = 600; // Mid pitch for Manual
    }
    
    gainNode.gain.setValueAtTime(0.1, audioCtx.currentTime); // Volume
    oscillator.start();
    oscillator.stop(audioCtx.currentTime + 0.15); // 150ms beep
}

let lastEventId = null;
let justSwitchedSS = false;

async function fetchEvents() {
    try {
        const ssSelector = document.getElementById('ssSelector');
        // Filter by SS only on Timing page
        const ssParam = ssSelector ? ssSelector.value : '';
        const url = ssParam ? `/api/events?ss=${ssParam}` : '/api/events';
        const response = await fetch(url);
        const events = await response.json();
        
        if (events.length > 0) {
            if (lastEventId !== null && !justSwitchedSS) {
                const newEvents = events.filter(e => e.id > lastEventId);
                if (newEvents.length > 0) {
                    // Only play beep for racing events, not SYS logs
                    const firstEventStyle = newEvents[0].Line_Status;
                    if (['F1', 'F2', 'FM'].includes(firstEventStyle)) {
                        playBeep(firstEventStyle);
                    }
                }
            }
            lastEventId = events[0].id;
            justSwitchedSS = false;
        }

        // Store focused element ID to restore focus after re-render
        const focusedEl = document.activeElement;
        const focusedId = (focusedEl && focusedEl.tagName === 'INPUT') ? focusedEl.getAttribute('data-id') : null;
        const focusedValue = (focusedEl && focusedEl.tagName === 'INPUT') ? focusedEl.value : null;

        // --- DASHBOARD TABLE ---
        const tbody = document.getElementById('liveEventsBody');
        if (tbody) {
            tbody.innerHTML = '';
            events.slice(0, 20).forEach((event, index) => {
                const tr = document.createElement('tr');
                const isSYS = event.Line_Status === 'SYS';
                const descStr = isSYS ? '' : (event.send ? '<span class="status-badge sent">SEND</span>' : '-');
                const displayTime = isSYS ? `<i style="color: #64748b;">${event.Time_Stamp}</i>` : event.Time_Stamp;
                
                tr.innerHTML = `
                    <td>${index + 1}</td>
                    <td><span class="event-type ${event.Line_Status}">${event.Line_Status}</span></td>
                    <td>${displayTime}</td>
                    <td>${descStr}</td>
                `;
                tbody.appendChild(tr);
            });
        }

        // --- TIMING PAGE: SINGLE TRACK ---
        const timingBody = document.getElementById('timingEventsBody');
        if (timingBody) {
            timingBody.innerHTML = '';
            // Only show racing events (F1, F2, FM)
            const racingEvents = events.filter(e => ['F1', 'F2', 'FM'].includes(e.Line_Status));
            racingEvents.forEach((event, index) => {
                const tr = document.createElement('tr');
                const isFocused = (focusedId == event.id);
                const valToDisplay = isFocused ? focusedValue : (event.No_start || '');
                
                tr.innerHTML = `
                    <td>${index + 1}</td>
                    <td><span style="font-weight: bold; color: #2980b9;">${event.SS || '1'}</span></td>
                    <td>
                        <input type="text" data-id="${event.id}" value="${valToDisplay}" 
                               onkeydown="if(event.key==='Enter') updateNS(${event.id}, this.value)" 
                               class="ns-input ${event.Line_Status}"
                               style="width: 80px; text-align: center; border: 2px solid #dee2e6; border-radius: 6px; font-weight: bold;">
                    </td>
                    <td>${event.Time_Stamp}</td>
                `;
                timingBody.appendChild(tr);
            });
            // Restore focus if needed
            if (focusedId) {
                const newEl = document.querySelector(`input[data-id="${focusedId}"]`);
                if (newEl) {
                    newEl.focus();
                    // Move cursor to end
                    const val = newEl.value;
                    newEl.value = '';
                    newEl.value = val;
                }
            }
        }

        // --- TIMING PAGE: DOUBLE TRACK ---
        const leftBody = document.getElementById('timingLeftBody');
        const rightBody = document.getElementById('timingRightBody');
        if (leftBody && rightBody) {
            leftBody.innerHTML = '';
            rightBody.innerHTML = '';
            
            const f1List = events.filter(e => e.Line_Status === 'F1');
            const f2List = events.filter(e => e.Line_Status === 'F2');
            // Manual FM events typically belong to both/either in some setups, 
            // but the user wants data timestamp from controller or manual 
            // so we already have F1 and F2 filtered above. 
            // If FM should be in one of these, it needs to be included.
            // For now, these lists already handle F1 and F2 specific tracks.

            f1List.forEach((event, index) => {
                const tr = document.createElement('tr');
                const isFocused = (focusedId == event.id);
                const valToDisplay = isFocused ? focusedValue : (event.No_start || '');
                tr.innerHTML = `
                    <td>${index + 1}</td>
                    <td><span style="font-weight: bold; color: #2980b9;">${event.SS || '1'}</span></td>
                    <td><input type="text" data-id="${event.id}" value="${valToDisplay}" onkeydown="if(event.key==='Enter') updateNS(${event.id}, this.value)" class="ns-input F1" style="width: 80px; text-align: center; border: 2px solid #dee2e6; border-radius: 6px; font-weight: bold;"></td>
                    <td>${event.Time_Stamp}</td>
                `;
                leftBody.appendChild(tr);
            });
            f2List.forEach((event, index) => {
                const tr = document.createElement('tr');
                const isFocused = (focusedId == event.id);
                const valToDisplay = isFocused ? focusedValue : (event.No_start || '');
                tr.innerHTML = `
                    <td>${index + 1}</td>
                    <td><span style="font-weight: bold; color: #2980b9;">${event.SS || '1'}</span></td>
                    <td><input type="text" data-id="${event.id}" value="${valToDisplay}" onkeydown="if(event.key==='Enter') updateNS(${event.id}, this.value)" class="ns-input F2" style="width: 80px; text-align: center; border: 2px solid #dee2e6; border-radius: 6px; font-weight: bold;"></td>
                    <td>${event.Time_Stamp}</td>
                `;
                rightBody.appendChild(tr);
            });
        }

        // Update stats blocks dynamically with animation
        const totalEvents = events.length;
        const f1Count = events.filter(e => e.Line_Status === 'F1').length;
        const f2Count = events.filter(e => e.Line_Status === 'F2').length;
        const fmCount = events.filter(e => e.Line_Status === 'FM').length;

        animateCounter('statTotal', totalEvents);
        animateCounter('statF1A', f1Count);
        animateCounter('statF1B', f2Count);
        animateCounter('statFM', fmCount);

    } catch (err) {
        console.error('Failed to fetch events:', err);
    }
}

async function updateNS(eventId, value) {
    try {
        await fetch('/api/events/update_ns', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ id: eventId, ns_number: value })
        });
    } catch (e) {
        console.error('Failed to update NS:', e);
    }
}

async function saveRaceSetupJSON() {
    const beep = document.getElementById('beepSoundInput').value;
    const precision = document.getElementById('timePrecisionInput').value;
    try {
        const res = await fetch('/api/save_race_setup', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ beep_sound: beep, time_precision: precision })
        });
        if (res.ok) {
            location.reload(); 
        }
    } catch (e) {
        console.error('Failed to save race setup:', e);
    }
}

async function createNewEvent() {
    if (confirm("Start a new event? This will create a fresh session and clear all fields below.")) {
        try {
            // Step 1: Clear visually immediately
            const fields = ['eventNameInput', 'startDateInput', 'endDateInput', 'operatorInput', 'koordinatInput'];
            fields.forEach(id => {
                const el = document.getElementById(id);
                if (el) el.value = '';
            });

            // Step 2: Send to server
            const res = await fetch('/api/events/new_event', { method: 'POST' });
            if (res.ok) {
                location.reload(); 
            }
        } catch (e) {
            console.error('Failed to create new event:', e);
        }
    }
}

async function switchEvent(eventId) {
    if (!eventId) return;
    try {
        const res = await fetch('/api/events/switch', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ event_id: eventId })
        });
        if (res.ok) {
            location.reload();
        }
    } catch (e) {
        console.error('Failed to switch event:', e);
    }
}

// Polling every 2 seconds for live updates
setInterval(fetchEvents, 2000);
fetchEvents();

// Initial Setup for SS Selector (if on Timing page)
document.addEventListener('DOMContentLoaded', () => {
    const ssSelector = document.getElementById('ssSelector');
    if (ssSelector) {
        // Load saved SS
        const savedSS = localStorage.getItem('current_ss');
        if (savedSS) ssSelector.value = savedSS;

        // Save on change
        ssSelector.addEventListener('change', async (e) => {
            const ss = e.target.value;
            localStorage.setItem('current_ss', ss);
            try {
                await fetch('/api/update_ss', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ ss: ss })
                });
                // Auto Upload: Sync unsent records for this SS
                await fetch('/api/events/sync_ss', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ ss: ss })
                });
                justSwitchedSS = true; 
                fetchEvents(); // Refresh visually
            } catch (err) {
                console.error("Failed to update SS on server:", err);
            }
        });
    }
});

function toggleConnection() {
    const btn = document.getElementById('serialActionBtn');
    if (btn && btn.classList.contains('danger')) {
        disconnectSerial();
    } else {
        connectSerial();
    }
}

async function connectSerial() {
    const port = document.getElementById('comPort').value;
    const btn = document.getElementById('serialActionBtn');
    try {
        const res = await fetch('/connect', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ port: port, baudrate: 9600 })
        });
        if (res.ok) {
            if (btn) {
                btn.className = 'btn danger';
                btn.innerHTML = '<i class="fas fa-unlink"></i> Disconnect';
            }
            const comPort = document.getElementById('comPort');
            if (comPort) comPort.disabled = true;
            const status = document.getElementById('connectionStatus');
            if (status) {
                status.className = 'status connected';
                status.innerHTML = '<i class="fas fa-wifi"></i> Connected';
            }
        } else {
            alert("Failed to connect");
        }
    } catch (e) {
        alert("Connection error");
    }
}

async function getKoordinat(btnElement) {
    const originalHTML = btnElement.innerHTML;
    btnElement.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Wait...';
    btnElement.disabled = true;
    
    try {
        const res = await fetch('/api/get_location', { method: 'POST' });
        const data = await res.json();
        
        if (res.ok) {
            document.getElementById('koordinatInput').value = data.location;
        } else {
            alert("Error: " + (data.error || "Failed to get location"));
        }
    } catch(e) {
        alert("Connection error fetching location");
    }
    
    btnElement.innerHTML = originalHTML;
    btnElement.disabled = false;
}

async function clearTable() {
    if (confirm('Are you sure you want to clear the logs for the CURRENT active race?')) {
        try {
            await fetch('/api/events/clear', { method: 'POST' });
            fetchEvents();
        } catch (e) {
            console.error('Failed to clear events:', e);
        }
    }
}

async function disconnectSerial() {
    const btn = document.getElementById('serialActionBtn');
    try {
        await fetch('/disconnect');
        if (btn) {
            btn.className = 'btn primary';
            btn.innerHTML = '<i class="fas fa-link"></i> Connect';
        }
        const comPort = document.getElementById('comPort');
        if (comPort) comPort.disabled = false;
        const status = document.getElementById('connectionStatus');
        if (status) {
            status.className = 'status disconnected';
            status.innerHTML = '<i class="fas fa-wifi"></i> Disconnected';
        }
    } catch (e) {
        console.error(e);
    }
}

let isManualMode = false;
function toggleManualMode() {
    isManualMode = !isManualMode;
    const btn = document.getElementById('manualToggleBtn');
    const text = document.getElementById('manualToggleText');
    const clock = document.getElementById('liveClockDisplay');
    if (isManualMode) {
        btn.style.background = '#e74c3c'; // Active red
        text.textContent = 'Manual: ON';
        if (clock) {
            clock.style.background = '#e74c3c';
            clock.style.color = '#fff';
        }
    } else {
        btn.style.background = '#95a5a6'; // Inactive gray
        text.textContent = 'Manual: OFF';
        if (clock) {
            clock.style.background = '#fff';
            clock.style.color = '#e74c3c';
        }
    }
}

let liveClockElem = null;
let sidebarClockElem = null;
function updateClock() {
    if (!liveClockElem) liveClockElem = document.getElementById('liveClockDisplay');
    if (!sidebarClockElem) sidebarClockElem = document.getElementById('sidebarClock');
    
    const now = new Date();
    const h = String(now.getHours()).padStart(2, '0');
    const m = String(now.getMinutes()).padStart(2, '0');
    const s = String(now.getSeconds()).padStart(2, '0');
    
    // Main Display (with precision)
    if (liveClockElem) {
        const precision = window.TIME_PRECISION || 3;
        const msString = String(now.getMilliseconds()).padStart(3, '0').slice(0, precision);
        liveClockElem.textContent = `${h}:${m}:${s}.${msString}`;
    }

    // Sidebar Clock (standard HH:MM:SS)
    if (sidebarClockElem) {
        sidebarClockElem.textContent = `${h}:${m}:${s}`;
    }
    
    requestAnimationFrame(updateClock);
}
requestAnimationFrame(updateClock);

async function sendManual(command) {
    if (!isManualMode) {
        alert("Tekan tombol 'Manual: OFF' terlebih dahulu untuk menyalakan mode manual!");
        return;
    }
    const now = new Date();
    const h = String(now.getHours()).padStart(2, '0');
    const m = String(now.getMinutes()).padStart(2, '0');
    const s = String(now.getSeconds()).padStart(2, '0');
    
    const precision = window.TIME_PRECISION || 3;
    const captureMs = String(now.getMilliseconds()).padStart(3, '0').slice(0, precision);
    const captureTime = `${h}:${m}:${s}.${captureMs}`;

    try {
        await fetch('/api/manual_command', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ command: command, timestamp: captureTime })
        });
        
        playBeep(command); // Directly play beep on visual client for feedback
        fetchEvents(); // Immediately fetch to update the log
    } catch (e) {
        console.error('Failed to send manual command:', e);
    }
}
