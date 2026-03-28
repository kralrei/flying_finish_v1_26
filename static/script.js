const socket = io();
let isFetching = false;
let socketFetchTimeout = null;

socket.on('connect', () => {
    updateSyncIndicator(true);
    const connStatus = document.getElementById('connectionStatus');
    if (connStatus) {
        connStatus.innerHTML = '<i class="fas fa-wifi"></i> Connected';
        connStatus.className = 'connected';
    }
});

socket.on('disconnect', () => {
    updateSyncIndicator(false);
    const connStatus = document.getElementById('connectionStatus');
    if (connStatus) {
        connStatus.innerHTML = '<i class="fas fa-wifi"></i> Disconnected';
        connStatus.className = 'disconnected';
    }
});

function updateSyncIndicator(active) {
    const dots = document.querySelectorAll('.sync-dot');
    dots.forEach(dot => {
        dot.style.background = active ? '#10b981' : '#ef4444';
        dot.style.boxShadow = active ? '0 0 10px rgba(16, 185, 129, 0.4)' : '0 0 10px rgba(239, 68, 68, 0.4)';
    });
}

socket.on('new_data', (data) => {
    console.log('Real-time update received:', data);
    clearTimeout(socketFetchTimeout);
    socketFetchTimeout = setTimeout(fetchEvents, 300);
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
    if (isFetching) return;
    isFetching = true;
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
            
            // Logika Filter Pintar Berdasarkan Halaman (TC / Start / Timing)
            const path = window.location.pathname;
            let racingEvents = [];
            
            if (path.includes('/tc')) {
                // Hanya tampilkan data dari HP ber-label TC
                racingEvents = events.filter(e => e.Line_Status === 'TC');
            } else if (path.includes('/start')) {
                // Hanya tampilkan data dari HP ber-label START
                racingEvents = events.filter(e => e.Line_Status === 'START');
            } else {
                // Default: Halaman Timing/Flying Finish (F1, F2, FM)
                racingEvents = events.filter(e => ['F1', 'F2', 'FM'].includes(e.Line_Status));
            }

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

        // Hanya hitung event balapan (F1, F2, FM) untuk Total Passing agar SYS tidak masuk
        const passingEvents = events.filter(e => ['F1', 'F2', 'FM'].includes(e.Line_Status));
        const totalEvents = passingEvents.length;
        
        const f1Count = events.filter(e => e.Line_Status === 'F1').length;
        const f2Count = events.filter(e => e.Line_Status === 'F2').length;
        const fmCount = events.filter(e => e.Line_Status === 'FM').length;

        animateCounter('statTotal', totalEvents);
        animateCounter('statF1A', f1Count);
        animateCounter('statF1B', f2Count);
        animateCounter('statFM', fmCount);

    } catch (err) {
        console.error('Failed to fetch events:', err);
    } finally {
        isFetching = false;
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

function showNewEventModal() {
    document.getElementById('newEventModal').classList.add('active');
}

function hideNewEventModal() {
    document.getElementById('newEventModal').classList.remove('active');
}

async function submitNewEvent() {
    const name = document.getElementById('modalEventName').value;
    const start = document.getElementById('modalStartDate').value;
    const end = document.getElementById('modalEndDate').value;
    const loc = document.getElementById('modalLocation').value;
    const total_ss = document.getElementById('modalTotalSS').value || 1;

    if (!name) { alert("Please enter an Event Name"); return; }

    try {
        const res = await fetch('/api/events/new_event', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                event_name: name,
                start_date: start,
                end_date: end,
                koordinat: loc,
                total_ss: total_ss
            })
        });
        if (res.ok) {
            window.location.href = '/hq?success=true';
        } else {
            alert("Failed to create new event");
        }
    } catch (e) {
        console.error('Failed to create new event:', e);
    }
}

function viewEventDetails(eventId) {
    if (!eventId) return;
    window.location.href = `/hq?view_id=${eventId}`;
}

async function toggleActivation(eventId, activate) {
    if (!eventId) return;
    const targetId = activate ? eventId : '0'; // Deactivate sets ID to '0'
    try {
        const res = await fetch('/api/events/switch', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ event_id: targetId })
        });
        if (res.ok) {
            window.location.href = `/hq?view_id=${eventId}&message=Event ${activate ? 'Activated' : 'Deactivated'}`;
        }
    } catch (e) {
        console.error('Toggle error:', e);
    }
}

function enableHqEditing() {
    const fields = ['eventNameInput', 'startDateInput', 'endDateInput', 'koordinatInput', 'totalSsInput'];
    fields.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.disabled = false;
            el.style.background = '#fff';
            el.style.border = '2px solid #6366f1';
        }
    });
    document.getElementById('saveEventBtn').style.display = 'block';
    document.getElementById('editBtn').style.display = 'none';
}

async function deleteEvent(eventId) {
    if (!eventId) return;
    if (confirm("WARNING: This will PERMANENTLY delete this event and ALL its timing data from BOTH local and cloud. This cannot be undone. Area you sure?")) {
        try {
            const res = await fetch('/api/events/delete', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ event_id: eventId })
            });
            const data = await res.json();
            if (res.ok) {
                alert("Event Deleted Successfully.");
                window.location.href = '/hq';
            } else {
                alert("Error: " + data.error);
            }
        } catch (e) {
            console.error('Delete error:', e);
        }
    }
}

async function switchEvent(eventId) {
    // Legacy switch handler if needed elsewhere
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

async function refreshStartingList() {
    const viewId = document.getElementById('view_id_hidden')?.value;
    if (!viewId) return;
    
    try {
        const res = await fetch(`/api/starting_list/${viewId}`);
        const data = await res.json();
        const tbody = document.getElementById('startingListBody');
        if (!tbody) return;
        
        tbody.innerHTML = '';
        if (data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:20px; color:#94a3b8;">Lineup is empty</td></tr>';
            return;
        }
        
        data.forEach((entry, index) => {
            const tr = document.createElement('tr');
            tr.style.borderBottom = '1px solid #f1f5f9';
            tr.innerHTML = `
                <td style="padding:12px;">${index + 1}</td>
                <td style="padding:12px; font-weight:bold;">${entry.ns || '-'}</td>
                <td style="padding:12px;">${entry.driver || '-'}</td>
                <td style="padding:12px;">${entry.co_driver || '-'}</td>
                <td style="padding:12px;">${entry.car || '-'}</td>
                <td style="padding:12px;"><span style="background:#eef2ff; color:#6366f1; padding:2px 8px; border-radius:4px; font-weight:600;">${entry.eligibility || '-'}</span></td>
                <td style="padding:12px;">
                    <button onclick="deleteStartingEntryJS('${entry.id}')" style="background:none; border:none; color:#ef4444; cursor:pointer;">
                        <i class="fas fa-trash"></i>
                    </button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error('Failed to load starting list:', e);
    }
}

async function addStartingEntry() {
    const viewId = document.getElementById('view_id_hidden')?.value;
    if (!viewId) return;
    
    const ns = document.getElementById('start_ns').value;
    const driver = document.getElementById('start_driver').value;
    const codriver = document.getElementById('start_codriver').value;
    const car = document.getElementById('start_car').value;
    const eligibility = document.getElementById('start_eligibility').value;
    
    if (!ns || !driver) {
        alert("NS and Driver are required!");
        return;
    }
    
    try {
        const res = await fetch('/api/starting_list/upsert', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                race_id: viewId,
                ns: ns,
                driver: driver,
                co_driver: codriver,
                car: car,
                eligibility: eligibility
            })
        });
        if (res.ok) {
            // Clear inputs
            ['start_ns', 'start_driver', 'start_codriver', 'start_car', 'start_eligibility'].forEach(id => {
                document.getElementById(id).value = '';
            });
            refreshStartingList();
        }
    } catch (e) {
        console.error('Failed to add entry:', e);
    }
}

async function handleImportFile(event) {
    const file = event.target.files[0];
    if (!file) return;
    const viewId = document.getElementById('view_id_hidden')?.value;
    if (!viewId) return;

    const reader = new FileReader();
    reader.onload = async (e) => {
        const text = e.target.result;
        const lines = text.split('\n');
        const entries = [];

        lines.forEach(line => {
            const trimmed = line.trim();
            if (!trimmed) return;
            
            // Format: NS <tab/spaces> Driver <tab/spaces> Co-Driver <tab/spaces> Car <tab/spaces> Eligibility
            // Kita coba pakai pemisahan TAB dulu, jika gagal coba spasi ganda
            let parts = trimmed.split('\t');
            if (parts.length < 3) {
                // Mencoba memisahkan berdasarkan minimal 2 spasi agar nama driver tidak terpotong
                parts = trimmed.split(/\s{2,}/);
            }

            if (parts.length >= 3) {
                entries.push({
                    ns: parts[0]?.trim(),
                    driver: parts[1]?.trim(),
                    co_driver: parts[2]?.trim(),
                    car: parts[3]?.trim() || '-',
                    eligibility: parts[4]?.trim() || '-'
                });
            }
        });

        if (entries.length > 0) {
            try {
                const res = await fetch('/api/starting_list/bulk_import', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ race_id: viewId, entries: entries })
                });
                if (res.ok) {
                    alert(`Successfully imported ${entries.length} entries!`);
                    refreshStartingList();
                }
            } catch (err) {
                console.error("Bulk Import failed:", err);
            }
        } else {
            alert("No valid data found in file. Format: NS [TAB] Driver [TAB] Co-Driver [TAB] Car [TAB] Eligibility");
        }
    };
    reader.readAsText(file);
    event.target.value = ''; // Reset input
}

async function deleteStartingEntryJS(id) {
    if (!confirm("Are you sure?")) return;
    try {
        const res = await fetch('/api/starting_list/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ id: id })
        });
        if (res.ok) refreshStartingList();
    } catch (e) {
        console.error('Failed to delete entry:', e);
    }
}

// Global initialization
document.addEventListener('DOMContentLoaded', () => {
    // Initial call for HQ page
    if (document.getElementById('startingListBody')) {
        refreshStartingList();
    }

    // Polling only on pages with live data
    if (document.getElementById('liveEventsBody') || (document.getElementById('timingEventsBody'))) {
        setInterval(fetchEvents, 2000);
        fetchEvents();
    }

    // SS Selector initialization
    const ssSelector = document.getElementById('ssSelector');
    if (ssSelector) {
        const savedSS = localStorage.getItem('current_ss');
        if (savedSS) ssSelector.value = savedSS;

        ssSelector.addEventListener('change', async (e) => {
            const ss = e.target.value;
            localStorage.setItem('current_ss', ss);
            try {
                await fetch('/api/update_ss', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ ss: ss })
                });
                await fetch('/api/events/sync_ss', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ ss: ss })
                });
                justSwitchedSS = true; 
                fetchEvents();
            } catch (err) {
                console.error("Failed to update SS:", err);
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
async function syncDatabase() {
    const btn = document.getElementById('syncDbBtn');
    if (!btn) return;
    
    const originalHTML = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Syncing...';
    
    try {
        const res = await fetch('/api/sync_db', { method: 'POST' });
        const data = await res.json();
        
        if (res.ok) {
            alert("Success: " + data.message);
            location.reload();
        } else {
            alert("Sync Failed: " + (data.message || "Unknown error"));
        }
    } catch (e) {
        alert("Connection error during sync");
    } finally {
        btn.innerHTML = originalHTML;
        btn.disabled = false;
    }
}
async function pullEvents() {
    if (!confirm("Tarik daftar event terbaru dari HQ Cloud?")) return;
    
    try {
        const btn = document.querySelector('button[onclick="pullEvents()"]');
        btn.disabled = true;
        const originalHTML = btn.innerHTML;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Pulling...';
        
        const response = await fetch('/api/pull_cloud_events');
        const result = await response.json();
        
        if (result.success) {
            alert(result.message);
            location.reload(); 
        } else {
            alert("Gagal: " + result.message);
            btn.disabled = false;
            btn.innerHTML = originalHTML;
        }
    } catch (err) {
        alert("Error: " + err.message);
    }
}
