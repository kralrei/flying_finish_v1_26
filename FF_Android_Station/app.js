/* --- APP LOGIC FOR FF ANDROID STATION --- */

const API_SYNC_URL = '/api/external_timing'; // Sync with Cloud
const API_EVENTS_URL = '/api/events/new_event'; // Fetch list of events

let serialPort;
let serialReader;
let serialBuffer = "";

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
    updateOnlineStatus();
    window.addEventListener('online', updateOnlineStatus);
    window.addEventListener('offline', updateOnlineStatus);
    
    // Load local records to UI
    renderLocalList();
    
    // Sync Interval
    setInterval(syncDataToCloud, 5000);
});

function updateOnlineStatus() {
    const netStatus = document.getElementById('netStatus');
    if (navigator.onLine) {
        netStatus.innerHTML = '<i class="fas fa-wifi"></i> CLOUD: ONLINE';
        netStatus.classList.remove('status-offline');
        netStatus.classList.add('status-online');
    } else {
        netStatus.innerHTML = '<i class="fas fa-wifi"></i> CLOUD: OFFLINE';
        netStatus.classList.remove('status-online');
        netStatus.classList.add('status-offline');
    }
}

// SERIAL USB-OTG LOGIC
async function connectUSB() {
    if (!('serial' in navigator)) {
        alert("Browser tidak mendukung Web Serial. Gunakan Chrome terbaru di Android.");
        return;
    }

    try {
        serialPort = await navigator.serial.requestPort();
        await serialPort.open({ baudRate: 9600 });
        
        const usbStatus = document.getElementById('usbStatus');
        const btnConnect = document.getElementById('btnConnect');
        
        usbStatus.innerHTML = '<i class="fas fa-microchip"></i> DECODER: ONLINE';
        usbStatus.classList.remove('status-offline');
        usbStatus.classList.add('status-online');
        
        btnConnect.style.background = "rgba(16, 185, 129, 0.2)";
        btnConnect.style.color = "#10b981";
        btnConnect.innerHTML = '<i class="fas fa-check"></i> DECODER CONNECTED';
        btnConnect.disabled = true;

        readSerialLoop();
    } catch (e) {
        alert("Gagal koneksi: " + e.message);
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
                
                // Decoder protocol split by semicolon (;)
                while (serialBuffer.includes(';')) {
                    const parts = serialBuffer.split(';', 2);
                    const line = parts[0].trim();
                    serialBuffer = parts[1];
                    if (line) handleDecoderInput(line);
                }
            }
        } catch (error) {
            console.error(error);
        } finally {
            serialReader.releaseLock();
        }
    }
}

function handleDecoderInput(message) {
    if (!message.startsWith('$')) return;
    const cleanMsg = message.substring(1);
    
    // Checksum verification (same as Python logic)
    const starIdx = cleanMsg.indexOf('*');
    if (starIdx === -1) return;
    
    const rawData = cleanMsg.substring(0, starIdx);
    const checksum = cleanMsg.substring(starIdx + 1);
    
    let expected = 0;
    for (let i = 0; i < rawData.length; i++) expected ^= rawData.charCodeAt(i);
    
    if (expected.toString(16).toUpperCase().padStart(2, '0') === checksum.toUpperCase()) {
        const parts = rawData.split(',');
        if (parts.length >= 2) {
            const line = parts[0];
            const ts = parts[1];
            
            // Format time: HHMMSSmmm -> HH:MM:SS.mmm
            let formattedTime = ts;
            if (ts.length >= 7 && /^\d+$/.test(ts)) {
                formattedTime = `${ts.substring(0,2)}:${ts.substring(2,4)}:${ts.substring(4,6)}.${ts.substring(6)}`;
            }
            
            saveTimingToDB(line, formattedTime);
        }
    }
}

async function saveTimingToDB(line, time) {
    const raceId = document.getElementById('raceSelector').value || "0";
    const ss = document.getElementById('ssSelector').value || "1";
    
    const id = await FF_DB.addLocalTiming(raceId, ss, line, time);
    console.log("Recorded to Offline DB:", id);
    
    // Refresh UI
    renderLocalList();
    
    // Play sound or vibration (haptic feedback for track marshals)
    if (navigator.vibrate) navigator.vibrate(100);
}

// SYNC LOGIC: OFFLINE TO ONLINE
async function syncDataToCloud() {
    if (!navigator.onLine) return;

    const unsynced = await FF_DB.getUnsynced();
    if (unsynced.length === 0) return;

    console.log(`Syncing ${unsynced.length} records to Cloud...`);
    
    for (const record of unsynced) {
        try {
            const res = await fetch(API_SYNC_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    line: record.line,
                    timestamp: record.timestamp,
                    ss: record.ss,
                    race_id: record.race_id
                })
            });

            if (res.ok) {
                await FF_DB.markSynced(record.id);
            }
        } catch (e) {
            console.error("Sync partial error:", e);
            break; // Stop sync if error occurs
        }
    }
    
    renderLocalList();
}

async function renderLocalList() {
    const listF1 = document.getElementById('listF1');
    const listF2 = document.getElementById('listF2');
    if (!listF1 || !listF2) return;

    const recentRecords = await db.timings.orderBy('id').reverse().limit(50).toArray();
    
    const countF1 = recentRecords.filter(r => r.line === 'F1').length;
    const countF2 = recentRecords.filter(r => r.line === 'F2').length;
    
    document.getElementById('countF1').innerText = countF1;
    document.getElementById('countF2').innerText = countF2;

    listF1.innerHTML = '';
    listF2.innerHTML = '';

    recentRecords.forEach(r => {
        const row = document.createElement('div');
        row.className = 'timing-row';
        row.innerHTML = `
            <span class="row-time">${r.timestamp}</span>
            <span class="badge-sync ${r.is_synced ? 'synced' : ''}">
                <i class="fas ${r.is_synced ? 'fa-cloud-upload-alt' : 'fa-clock'}"></i>
            </span>
        `;
        
        if (r.line === 'F1') listF1.appendChild(row);
        else if (r.line === 'F2') listF2.appendChild(row);
    });
}

function handleManual(line) {
    const now = new Date();
    const time = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}.${String(now.getMilliseconds()).padStart(3,'0')}`;
    saveTimingToDB(line, time);
}
