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
    
    // Set flag to beep if data coming from serial port or manual timestamp
    if (data.status === 'event' || data.status === 'manual') {
        window.PENDING_BEEP = true;
    }

    clearTimeout(socketFetchTimeout);
    socketFetchTimeout = setTimeout(() => fetchEvents(), 300);
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

  // Restore Manual Mode UI from localStorage
  updateManualUI();
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
    
    if (type === 'F1' || type === 'M1') {
        oscillator.type = 'sine';
        oscillator.frequency.value = 1800; // High pitch for F1 (Left)
    } else if (type === 'F2' || type === 'M2') {
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
window.PENDING_BEEP = false;

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
                    // Beep ONLY if triggered by local/manual update (window.PENDING_BEEP)
                    // and not from automated sync/polling
                    if (window.PENDING_BEEP) {
                        const firstEventStyle = newEvents[0].Line_Status;
                        if (['F1', 'F2', 'FM', 'M1', 'M2', 'MM'].includes(firstEventStyle)) {
                            playBeep(firstEventStyle);
                        }
                    }
                }
            }
            lastEventId = events[0].id;
            justSwitchedSS = false;
            window.PENDING_BEEP = false; // Reset after use
        }

        // Store focused element ID and FIELD to restore focus after re-render
        const focusedEl = document.activeElement;
        const focusedId = (focusedEl && focusedEl.tagName === 'INPUT') ? focusedEl.getAttribute('data-id') : null;
        const focusedField = (focusedEl && focusedEl.tagName === 'INPUT') ? focusedEl.getAttribute('data-field') : 'ns';
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
        
        // --- LIVE QUEUE: CARS IN STAGE (Flying Finish Page) ---
        const liveQueue = document.getElementById('liveQueue');
        if (liveQueue) {
            // Find cars that started but haven't finished yet
            const started = events.filter(e => e.Line_Status === 'START' && e.No_start);
            const finishedNS = new Set(events.filter(e => ['F1', 'F2', 'FM', 'M1', 'M2', 'MM'].includes(e.Line_Status)).map(e => e.No_start));
            
            const inStage = started.filter(e => !finishedNS.has(e.No_start)).reverse(); // Show oldest starts first? 
            
            if (inStage.length === 0) {
                liveQueue.innerHTML = '<span style="color: #94a3b8; font-size: 0.9rem; font-style: italic;">No cars active</span>';
            } else {
                liveQueue.innerHTML = '';
                inStage.forEach(event => {
                    const pill = document.createElement('div');
                    pill.style.background = 'linear-gradient(135deg, #10b981 0%, #059669 100%)';
                    pill.style.color = 'white';
                    pill.style.padding = '8px 15px';
                    pill.style.borderRadius = '20px';
                    pill.style.fontWeight = 'bold';
                    pill.style.fontSize = '1rem';
                    pill.style.boxShadow = '0 2px 8px rgba(16, 185, 129, 0.3)';
                    pill.style.cursor = 'help';
                    pill.style.display = 'flex';
                    pill.style.alignItems = 'center';
                    pill.style.gap = '5px';
                    pill.style.animation = 'pulse-shadow 2s infinite';
                    
                    // Detail di Popup/Title (English Format: HH:MM)
                    const shortTime = event.Time_Stamp ? event.Time_Stamp.substring(0, 5) : '--:--';
                    pill.title = `#${event.No_start}\nSTART TIME : ${shortTime}`;
                    pill.innerHTML = `#${event.No_start}`;
                    
                    liveQueue.appendChild(pill);
                });
            }
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
                // Default: Halaman Timing/Flying Finish (F1, F2, FM, M1, M2, MM)
                racingEvents = events.filter(e => ['F1', 'F2', 'FM', 'M1', 'M2', 'MM'].includes(e.Line_Status));
            }

            racingEvents.forEach((event, index) => {
                const tr = document.createElement('tr');
                const isFocused = (focusedId == event.id && focusedField === 'ns');
                const nsToDisplay = isFocused ? focusedValue : (event.No_start || '');
                
                const isTimeFocused = (focusedId == event.id && focusedField === 'time');
                const timeToDisplay = isTimeFocused ? focusedValue : (event.Time_Stamp || '');

                const isPenFocused = (focusedId == event.id && focusedField === 'pen');
                const penToDisplay = isPenFocused ? focusedValue : (event.penalty || 0);

                const isTCStart = path.includes('/tc') || path.includes('/start');
                
                const isRestart = racingEvents.slice(index + 1).some(e => e.No_start === event.No_start && e.No_start !== '' && e.No_start !== '-');
                let displayStatus = isRestart ? 'RESTART' : event.Line_Status;
                
                // TC Page Specific: Change RESTART to TC CORRECTION
                if (path.includes('/tc') && isRestart) {
                    displayStatus = 'TC CORRECTION';
                }
                
                const statusClass = displayStatus.replace(/\s+/g, '-');
                tr.innerHTML = `
                    <td>${index + 1}</td>
                    <td><span style="font-weight: bold; color: #2980b9;">${event.SS || '1'}</span></td>
                    <td>
                        <input type="text" data-id="${event.id}" data-field="ns" value="${nsToDisplay}" 
                               onkeydown="if(event.key==='Enter') { updateNS('${event.id}', this.value); this.blur(); }" 
                               class="ns-input ${statusClass}"
                               style="width: 80px; text-align: center; border: 2px solid #dee2e6; border-radius: 6px; font-weight: bold;">
                    </td>
                    <td style="font-family: 'Courier New', monospace; font-weight: bold; color: #10b981;">${event.elapsed || '-'}</td>
                    ${isTCStart ? '' : `
                    <td>
                        <input type="number" data-id="${event.id}" data-field="pen" value="${penToDisplay}" 
                               onkeydown="if(event.key==='Enter') { updatePenalty('${event.id}', this.value); this.blur(); }" 
                               class="pen-input"
                               style="width: 60px; text-align: center; border: 2px solid #edeff2; border-radius: 6px; color: #e74c3c; font-weight: bold;">
                    </td>
                    `}
                    <td>
                        <input type="text" data-id="${event.id}" data-field="time" value="${timeToDisplay}" 
                               onkeydown="if(event.key==='Enter') { updateTime('${event.id}', this.value); this.blur(); }"
                               style="width: 130px; text-align: center; border: 2px solid #edeff2; border-radius: 6px; font-family: 'Courier New', monospace; font-weight: bold; background: #fdfdfd;">
                    </td>
                    <td><span class="event-type ${statusClass}">${displayStatus}</span></td>
                    <td>
                        <button onclick="deleteTimingRecord('${event.id}')" class="btn danger" style="padding: 5px 10px; font-size: 0.7rem;">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                `;
                timingBody.appendChild(tr);
            });
            // Restore focus if needed
            if (focusedId) {
                const newEl = document.querySelector(`input[data-id="${focusedId}"][data-field="${focusedField}"]`);
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
            
            const f1List = events.filter(e => e.Line_Status === 'F1' || e.Line_Status === 'M1');
            const f2List = events.filter(e => e.Line_Status === 'F2' || e.Line_Status === 'M2');
            // Manual FM events typically belong to both/either in some setups, 
            // but the user wants data timestamp from controller or manual 
            // so we already have F1 and F2 filtered above. 
            // If FM should be in one of these, it needs to be included.
            // For now, these lists already handle F1 and F2 specific tracks.

            f1List.forEach((event, index) => {
                const tr = document.createElement('tr');
                const isFocused = (focusedId == event.id && focusedField === 'ns');
                const valToDisplay = isFocused ? focusedValue : (event.No_start || '');
                const isTimeFocused = (focusedId == event.id && focusedField === 'time' && event.Line_Status==='F1'); 
                const timeToDisplay = isTimeFocused ? focusedValue : (event.Time_Stamp || '');

                const isRestart = f1List.slice(index + 1).some(e => e.No_start === event.No_start && e.No_start !== '' && e.No_start !== '-');
                const displayStatus = isRestart ? 'RESTART' : event.Line_Status;

                tr.innerHTML = `
                    <td>${index + 1}</td>
                    <td><span style="font-weight: bold; color: #2980b9;">${event.SS || '1'}</span></td>
                    <td><input type="text" data-id="${event.id}" data-field="ns" value="${valToDisplay}" onkeydown="if(event.key==='Enter') { updateNS('${event.id}', this.value); this.blur(); }" class="ns-input F1" style="width: 80px; text-align: center; border: 2px solid #dee2e6; border-radius: 6px; font-weight: bold;"></td>
                    <td style="font-family: 'Courier New', monospace; font-weight: bold; color: #10b981;">${event.elapsed || '-'}</td>
                    <td>
                        <input type="number" data-id="${event.id}" data-field="pen" value="${event.penalty || 0}" 
                               onkeydown="if(event.key==='Enter') { updatePenalty('${event.id}', this.value); this.blur(); }" 
                               class="pen-input"
                               style="width: 60px; text-align: center; border: 2px solid #edeff2; border-radius: 6px; color: #e74c3c; font-weight: bold;">
                    </td>
                    <td>
                        <input type="text" data-id="${event.id}" data-field="time" value="${timeToDisplay}" 
                               onkeydown="if(event.key==='Enter') { updateTime('${event.id}', this.value); this.blur(); }"
                               style="width: 130px; text-align: center; border: 2px solid #edeff2; border-radius: 6px; font-family: 'Courier New', monospace; font-weight: bold;">
                    </td>
                    <td><span class="event-type ${displayStatus}">${displayStatus}</span></td>
                    <td>
                        <button onclick="deleteTimingRecord('${event.id}')" class="btn danger" style="padding: 5px 10px; font-size: 0.7rem;">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                `;
                leftBody.appendChild(tr);
            });
            f2List.forEach((event, index) => {
                const tr = document.createElement('tr');
                const isFocused = (focusedId == event.id && focusedField === 'ns');
                const valToDisplay = isFocused ? focusedValue : (event.No_start || '');
                const isTimeFocused = (focusedId == event.id && focusedField === 'time' && event.Line_Status==='F2'); 
                const timeToDisplay = isTimeFocused ? focusedValue : (event.Time_Stamp || '');

                const isRestart = f2List.slice(index + 1).some(e => e.No_start === event.No_start && e.No_start !== '' && e.No_start !== '-');
                const displayStatus = isRestart ? 'RESTART' : event.Line_Status;

                tr.innerHTML = `
                    <td>${index + 1}</td>
                    <td><span style="font-weight: bold; color: #2980b9;">${event.SS || '1'}</span></td>
                    <td><input type="text" data-id="${event.id}" data-field="ns" value="${valToDisplay}" onkeydown="if(event.key==='Enter') { updateNS('${event.id}', this.value); this.blur(); }" class="ns-input F2" style="width: 80px; text-align: center; border: 2px solid #dee2e6; border-radius: 6px; font-weight: bold;"></td>
                    <td style="font-family: 'Courier New', monospace; font-weight: bold; color: #10b981;">${event.elapsed || '-'}</td>
                    <td>
                        <input type="number" data-id="${event.id}" data-field="pen" value="${event.penalty || 0}" 
                               onkeydown="if(event.key==='Enter') { updatePenalty('${event.id}', this.value); this.blur(); }" 
                               class="pen-input"
                               style="width: 60px; text-align: center; border: 2px solid #edeff2; border-radius: 6px; color: #e74c3c; font-weight: bold;">
                    </td>
                    <td>
                        <input type="text" data-id="${event.id}" data-field="time" value="${timeToDisplay}" 
                               onkeydown="if(event.key==='Enter') { updateTime('${event.id}', this.value); this.blur(); }"
                               style="width: 130px; text-align: center; border: 2px solid #edeff2; border-radius: 6px; font-family: 'Courier New', monospace; font-weight: bold;">
                    </td>
                    <td><span class="event-type ${displayStatus}">${displayStatus}</span></td>
                    <td>
                        <button onclick="deleteTimingRecord('${event.id}')" class="btn danger" style="padding: 5px 10px; font-size: 0.7rem;">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                `;
                rightBody.appendChild(tr);
            });
        }
        
        // --- FINISH STOP PAGE ---
        const stopBody = document.getElementById('stopBody');
        if (stopBody) {
            stopBody.innerHTML = '';
            
            // Map records by NS for matching
            const startMap = {};
            const finishMap = {};
            const uniqueNS = new Set();
            
            events.forEach(e => {
                if (!e.No_start) return;
                uniqueNS.add(e.No_start);
                
                if (e.Line_Status === 'START') {
                    if (!startMap[e.No_start]) startMap[e.No_start] = e.Time_Stamp;
                } else if (['F1', 'F2', 'FM'].includes(e.Line_Status)) {
                    if (!finishMap[e.No_start]) finishMap[e.No_start] = e.Time_Stamp;
                }
            });
            
            // Convert to array and sort by NS
            const stopData = Array.from(uniqueNS).map(ns => {
                const start = startMap[ns];
                const finish = finishMap[ns];
                let elapsed = '-';
                
                if (start && finish) {
                    // ATURAN RALLY: Start time selalu dihitung di awal menit (SS.xxx = 00.000)
                    // Kita ambil hanya jam dan menit dari 'start'
                    let startParts = start.split(':');
                    let startTruncated = `${startParts[0]}:${startParts[1]}:00.000`;
                    
                    let diff = timeToMs(finish) - timeToMs(startTruncated);
                    if (diff < 0) diff += 86400000; 
                    elapsed = msToTime(diff);
                }
                
                return { ns, start: start || '-', finish: finish || '-', elapsed };
            });
            
            // Sort: Data terbaru masuk (Finish time) berada di paling atas
            stopData.sort((a, b) => {
                // Yang belum finish ditaruh di bawah, atau urutkan berdasarkan waktu finish
                if (a.finish === '-' && b.finish !== '-') return 1;
                if (a.finish !== '-' && b.finish === '-') return -1;
                if (a.finish === '-' && b.finish === '-') return 0;
                
                // Gunakan timeToMs untuk membandingkan jam finish secara akurat
                return timeToMs(b.finish) - timeToMs(a.finish);
            });
            
            if (stopData.length === 0) {
                stopBody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:20px; color:#94a3b8;">No results for this SS yet</td></tr>';
            } else {
                // Hitung jumlah yang sudah finish agar nomor urut konsisten (1 tetap di bawah)
                const totalFinished = stopData.filter(r => r.finish !== '-').length;
                
                stopData.forEach((row, index) => {
                    const tr = document.createElement('tr');
                    // Jika belum finish, nomor urut bisa kosong atau tanda hubung
                    let rowNum = row.finish !== '-' ? (totalFinished - index) : '-';
                    
                    tr.innerHTML = `
                        <td>${rowNum}</td>
                        <td style="font-weight: 800; color: #1e293b;">${row.ns}</td>
                        <td style="color: #64748b;">${row.start}</td>
                        <td style="color: #2563eb; font-weight: 600;">${row.finish}</td>
                        <td style="font-family: 'Courier New', monospace; font-weight: bold; color: #10b981; font-size: 1.1rem;">${row.elapsed}</td>
                    `;
                    stopBody.appendChild(tr);
                });
            }
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

function timeToMs(timeStr) {
    if (!timeStr || typeof timeStr !== 'string' || !timeStr.includes(':')) return 0;
    try {
        const parts = timeStr.split('.');
        const hms = parts[0].split(':');
        
        let h = 0, m = 0, s = 0;
        
        if (hms.length === 3) {
            h = parseInt(hms[0], 10) || 0;
            m = parseInt(hms[1], 10) || 0;
            s = parseInt(hms[2], 10) || 0;
        } else if (hms.length === 2) {
            // Data START biasanya hanya HH:MM, jadi kita anggap JAM dan MENIT
            h = parseInt(hms[0], 10) || 0;
            m = parseInt(hms[1], 10) || 0;
            s = 0;
        }
        
        const msPart = parts[1] ? parts[1].substring(0, 3).padEnd(3, '0') : '000';
        const ms = parseInt(msPart, 10) || 0;
        
        return (h * 3600000) + (m * 60000) + (s * 1000) + ms;
    } catch (e) {
        console.error("Error parsing time:", timeStr, e);
        return 0;
    }
}

function msToTime(msValue) {
    const precision = window.TIME_PRECISION || 3;
    if (isNaN(msValue) || msValue < 0) {
        const placeholder = "".padEnd(precision, '-');
        return `--:--:--${precision > 0 ? '.' + placeholder : ''}`;
    }
    const h = Math.floor(msValue / 3600000);
    const m = Math.floor((msValue % 3600000) / 60000);
    const s = Math.floor((msValue % 60000) / 1000);
    const ms = msValue % 1000;
    
    const msStr = String(ms).padStart(3, '0').substring(0, precision);
    const finalTime = `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    
    return precision > 0 ? `${finalTime}.${msStr}` : finalTime;
}

async function deleteTimingRecord(id) {
    if (!confirm("Hapus data finish ini dari Local & Cloud?")) return;
    try {
        const res = await fetch('/api/events/delete_timing', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ id: id })
        });
        if (res.ok) fetchEvents();
    } catch (e) {
        console.error('Delete error:', e);
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

async function updatePenalty(eventId, value) {
    try {
        await fetch('/api/events/update_penalty', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ id: eventId, penalty: parseInt(value) || 0 })
        });
    } catch (e) {
        console.error('Failed to update penalty:', e);
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
    if (document.getElementById('liveEventsBody') || (document.getElementById('timingEventsBody')) || document.getElementById('stopBody')) {
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

let isManualMode = localStorage.getItem('isManualMode') === 'true';

function updateManualUI() {
    const btn = document.getElementById('manualToggleBtn');
    const text = document.getElementById('manualToggleText');
    const clock = document.getElementById('liveClockDisplay');
    if (!btn || !text) return;

    if (isManualMode) {
        btn.style.background = '#ef4444'; // Bright red
        btn.style.boxShadow = '0 0 20px rgba(239, 68, 68, 0.5)';
        text.textContent = 'Manual: ON';
        if (clock) {
            clock.style.background = '#ef4444';
            clock.style.color = '#fff';
            clock.style.borderColor = '#fff';
        }
    } else {
        btn.style.background = '#95a5a6'; // Inactive gray
        btn.style.boxShadow = 'none';
        text.textContent = 'Manual: OFF';
        if (clock) {
            clock.style.background = '#fff';
            clock.style.color = '#e74c3c';
            clock.style.borderColor = '#e74c3c';
        }
    }
}

function toggleManualMode() {
    isManualMode = !isManualMode;
    localStorage.setItem('isManualMode', isManualMode);
    updateManualUI();
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
    
    // Main Display (respecting TIME_PRECISION)
    if (liveClockElem) {
        const precision = window.TIME_PRECISION !== undefined ? window.TIME_PRECISION : 3;
        if (precision > 0) {
            const msString = String(now.getMilliseconds()).padStart(3, '0').slice(0, precision);
            liveClockElem.textContent = `${h}:${m}:${s}.${msString}`;
        } else {
            liveClockElem.textContent = `${h}:${m}:${s}`;
        }
    }

    // Sidebar Clock (standard HH:MM:SS)
    if (sidebarClockElem) {
        sidebarClockElem.textContent = `${h}:${m}:${s}`;
    }
    
    requestAnimationFrame(updateClock);
}
requestAnimationFrame(updateClock);

// Keyboard Shortcuts (F10=LEFT, F11=RIGHT)
window.addEventListener('keydown', (e) => {
    // Only trigger if not typing in an input field
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

    if (e.key === 'F10') {
        e.preventDefault();
        sendManual('M1');
    } else if (e.key === 'F11') {
        e.preventDefault();
        sendManual('M2');
    }
});

async function sendManual(command, force = false) {
    if (!isManualMode && !force) {
        alert("Tekan tombol 'Manual: OFF' terlebih dahulu untuk menyalakan mode manual!");
        return;
    }
    
    // Haptic feedback for mobile
    if (window.navigator && window.navigator.vibrate) {
        window.navigator.vibrate(50);
    }
    
    const now = new Date();
    const h = String(now.getHours()).padStart(2, '0');
    const m = String(now.getMinutes()).padStart(2, '0');
    const s = String(now.getSeconds()).padStart(2, '0');
    
    const precision = window.TIME_PRECISION !== undefined ? window.TIME_PRECISION : 3;
    const captureMs = String(now.getMilliseconds()).padStart(3, '0').slice(0, precision);
    const captureTime = precision > 0 ? `${h}:${m}:${s}.${captureMs}` : `${h}:${m}:${s}`;

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
function pullEvents() {
    if (!confirm("Tarik daftar event terbaru dari HQ Cloud?")) return;
    
    try {
        const btn = document.querySelector('button[onclick="pullEvents()"]');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Pulling...';
        }
        
        fetch('/api/pull_cloud_events')
            .then(res => res.json())
            .then(result => {
                if (result.success) {
                    alert(result.message);
                    location.reload(); 
                } else {
                    alert("Gagal: " + result.message);
                    if (btn) {
                        btn.disabled = false;
                        btn.innerHTML = '<i class="fas fa-sync"></i> Pull Cloud';
                    }
                }
            });
    } catch (err) {
        alert("Error: " + err.message);
    }
}

// HQ REGULATION MODAL LOGIC
function showRegulationModal(type) {
    const modal = document.getElementById('regulationModal');
    const title = document.getElementById('modalRegTitle');
    const container = document.getElementById('regInputsContainer');
    const typeInput = document.getElementById('modalRegType');
    
    if (!modal || !container) return;
    
    typeInput.value = type;
    container.innerHTML = '';
    
    if (type === 'Penalty') {
        title.innerHTML = '<i class="fas fa-stopwatch"></i> Penalty Regulation';
        container.innerHTML = `
            <div class="form-group">
                <label>Jump Start Penalty (seconds):</label>
                <input type="number" id="reg_jump_start" value="10" class="input-modern">
            </div>
            <div class="form-group">
                <label>Wrong Route Penalty (seconds):</label>
                <input type="number" id="reg_wrong_route" value="60" class="input-modern">
            </div>
            <div class="form-group">
                <label>Missing Point Penalty (seconds):</label>
                <input type="number" id="reg_missing_point" value="300" class="input-modern">
            </div>
        `;
    } else if (type === 'Track') {
        title.innerHTML = '<i class="fas fa-road"></i> Track Configuration';
        container.innerHTML = `
            <div class="form-group">
                <label>Track Length (KM):</label>
                <input type="text" id="reg_track_length" placeholder="e.g. 4.5" class="input-modern">
            </div>
            <div class="form-group">
                <label>Surface Type:</label>
                <select id="reg_surface" class="input-modern">
                    <option value="Asphalt">Asphalt</option>
                    <option value="Gravel">Gravel</option>
                    <option value="Dirt">Dirt</option>
                    <option value="Mixed">Mixed</option>
                </select>
            </div>
        `;
    } else if (type === 'Officer') {
        title.innerHTML = '<i class="fas fa-user-shield"></i> Officer Assignment';
        container.innerHTML = `
            <div class="form-group">
                <label>Chief Steward:</label>
                <input type="text" id="reg_chief" placeholder="Name" class="input-modern">
            </div>
            <div class="form-group">
                <label>Clerk of the Course:</label>
                <input type="text" id="reg_clerk" placeholder="Name" class="input-modern">
            </div>
            <div class="form-group">
                <label>Chief Timer:</label>
                <input type="text" id="reg_timer" placeholder="Name" class="input-modern">
            </div>
        `;
    }
    
    modal.classList.add('active');
}

function hideRegulationModal() {
    document.getElementById('regulationModal').classList.remove('active');
}

function saveRegulation() {
    // Collect data based on type
    const type = document.getElementById('modalRegType').value;
    alert(`Regulation for ${type} saved successfully! (Simulation)`);
    hideRegulationModal();
}

async function updateTime(id, newTime) {
    if (!newTime) return;
    
    // Auto-format: 0915 -> 09:15:00.000
    let formatted = newTime.trim();
    if (/^\d{4}$/.test(formatted)) {
        formatted = `${formatted.substring(0,2)}:${formatted.substring(2,4)}:00.000`;
    } else if (formatted.length === 5 && formatted.includes(':')) {
        formatted = `${formatted}:00.000`;
    } else if (formatted.length === 8 && formatted.split(':').length === 3) {
        formatted = `${formatted}.000`;
    }
    
    try {
        await fetch('/api/events/update_time', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ id: id, time: formatted })
        });
        fetchEvents();
    } catch (e) {
        console.error('Failed to update time:', e);
    }
}

/* --- WEB SERIAL API FOR ANDROID --- */
let serialPort;
let serialReader;
let serialBuffer = '';

// Check if browser supports Web Serial
if ('serial' in navigator) {
    const usbControls = document.getElementById('usbControls');
    if (usbControls) usbControls.style.display = 'flex';
}

async function connectUSB() {
    try {
        serialPort = await navigator.serial.requestPort();
        await serialPort.open({ baudRate: 9600 });
        
        const usbStatus = document.getElementById('usbStatus');
        const connectBtn = document.getElementById('connectUsbBtn');
        
        if (usbStatus) {
            usbStatus.innerHTML = '<i class="fas fa-microchip"></i> USB: ONLINE';
            usbStatus.style.color = '#10b981';
        }
        if (connectBtn) connectBtn.style.display = 'none';

        readSerialLoop();
    } catch (e) {
        console.error('Serial Connection Error:', e);
        alert("Gagal koneksi USB: " + e.message);
    }
}

async function readSerialLoop() {
    while (serialPort.readable) {
        serialReader = serialPort.readable.getReader();
        try {
            while (true) {
                const { value, done } = await serialReader.read();
                if (done) break;
                
                const text = new TextDecoder().decode(value);
                serialBuffer += text;
                
                while (serialBuffer.includes(';')) {
                    const parts = serialBuffer.split(';', 2);
                    const line = parts[0].trim();
                    serialBuffer = parts[1];
                    if (line) processExternalMessage(line);
                }
            }
        } catch (error) {
            console.error('Read Error:', error);
        } finally {
            serialReader.releaseLock();
        }
    }
}

function processExternalMessage(message) {
    if (!message.startsWith('$')) return;
    const cleanMsg = message.substring(1);
    
    const starIdx = cleanMsg.indexOf('*');
    if (starIdx === -1) return;
    
    const rawData = cleanMsg.substring(0, starIdx);
    const checksum = cleanMsg.substring(starIdx + 1);
    
    let expected = 0;
    for (let i = 0; i < rawData.length; i++) expected ^= rawData.charCodeAt(i);
    
    if (expected.toString(16).toUpperCase().padStart(2, '0') === checksum.toUpperCase()) {
        const parts = rawData.split(',');
        if (parts.length >= 2) {
            const lineStatus = parts[0];
            const timestampRaw = parts[1];
            
            const precision = window.TIME_PRECISION || 3;
            let formattedTime = timestampRaw;
            
            if (timestampRaw.length >= 7 && /^\d+$/.test(timestampRaw)) {
                const h = timestampRaw.substring(0,2);
                const m = timestampRaw.substring(2,4);
                const s = timestampRaw.substring(4,6);
                const ms = timestampRaw.substring(6, 6 + precision);
                formattedTime = `${h}:${m}:${s}.${ms}`;
            }

            reportExternalTiming(lineStatus, formattedTime);
        }
    }
}

async function reportExternalTiming(line, time) {
    const ssSelector = document.getElementById('ssSelector');
    const ss = ssSelector ? ssSelector.value : '1';
    
    try {
        const res = await fetch('/api/external_timing', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                line: line,
                timestamp: time,
                ss: ss
            })
        });
        if (res.ok) {
            window.PENDING_BEEP = true; 
        }
    } catch (e) {
        console.error('Report Error:', e);
    }
}
