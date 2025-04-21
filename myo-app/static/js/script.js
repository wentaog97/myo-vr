/**
 *  Myo visualizer - frontend 
 */

// Utility to update connection badge
function setStatus(text, colorClass, battery = null) {
    const badge = document.getElementById("status-badge");
    badge.textContent = text;
    badge.className = "badge " + colorClass;  
    if (battery == null) {
        batteryBadge.classList.add("d-none");
    } else {
        batteryBadge.textContent = battery + " %";
        batteryBadge.classList.remove("d-none");
    }
}

// Buttons & UI elements
const scanBtn = document.getElementById("scan-btn");
const connectBtn = document.getElementById("connect-btn");
const disconnectBtn = document.getElementById("disconnect-btn");
const resetBtn = document.getElementById("reset-btn");
const vibrateBtn = document.getElementById("vibrate-btn");
const deviceList = document.getElementById("device-list");
const batteryBadge = document.getElementById("battery-badge");
const pauseBtn = document.getElementById("pause-btn");
const recordBtn = document.getElementById("record-btn");
const labelInput = document.getElementById("data-label");

let latestIMU = null;
let selectedAddress = null;
let pollTimer = null;
let emgPaused = false;

let recording = false;
let recordedData = [];

let savePath = "";

// Helper for POST JSON
async function postJSON(url, data = {}) {
    const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
    });
    return res;
}

// Poll myo status every 5 s while connected
async function pollStatus() {
    try {
        const resp = await fetch("/status");
        const js   = await resp.json();
        if (js.connected) {
            setStatus("Connected", "bg-success", js.battery);
        } else {
            clearInterval(pollTimer);
            pollTimer = null;
            setStatus("Disconnected", "bg-secondary");
            toggleButtons(false);
        }
    } catch (e) {
        console.error(e);
    }
}

// Scan for devices
scanBtn.addEventListener("click", async () => {
    setStatus("Scanning...", "bg-info");
    deviceList.innerHTML = "";
    connectBtn.disabled = true;

    try {
        const resp = await fetch("/scan");
        const devices = await resp.json();

        if (devices.length === 0) {
        setStatus("No devices", "bg-secondary");
        return;
        }

        devices.forEach((d) => {
            const li = document.createElement("li");
            li.className = "list-group-item list-group-item-action";
            li.textContent = `${d.name} (${d.address})`;
            li.addEventListener("click", () => {
                [...deviceList.children].forEach((c) => c.classList.remove("active"));
                li.classList.add("active");
                selectedAddress = d.address;
                connectBtn.disabled = false;
                setStatus("Ready to connect", "bg-warning");
            });
            deviceList.appendChild(li);
        });
        setStatus("Select a device", "bg-warning");
    } catch (e) {
        setStatus("Scan failed", "bg-danger");
        console.error(e);
    }
    
});

// Connect
connectBtn.addEventListener("click", async () => {
    if (!selectedAddress) return;
    setStatus("Connecting...", "bg-info");
    try {
        const res = await postJSON("/connect", { address: selectedAddress });
        const js = await res.json();
        if (res.ok && js.success) {
            setStatus("Connected", "bg-success");   
            toggleButtons(true);
            pollStatus();                          
            pollTimer = setInterval(pollStatus, 5000);
        } else {
            setStatus(js.message || "Connect error", "bg-danger");
        }
    } catch (e) {
        setStatus("Connect failed", "bg-danger");
        console.error(e);
    }
});

// Disconnect
disconnectBtn.addEventListener("click", async () => {
    try {
        await postJSON("/disconnect");
    } finally {
        setStatus("Disconnected", "bg-secondary");
        toggleButtons(false);
        clearInterval(pollTimer);
        pollTimer = null;
        batteryBadge.classList.add("d-none");
    }
});

// Reset / Turn off
resetBtn.addEventListener("click", async () => {
    await postJSON("/reset");
});

// Vibrate (medium)
vibrateBtn.addEventListener("click", async () => {
    await postJSON("/vibrate", { pattern: "medium" });
});


pauseBtn.addEventListener("click", () => {
    emgPaused = !emgPaused;
    pauseBtn.textContent = emgPaused ? "Resume Stream" : "Pause Stream";
});

recordBtn.addEventListener("click", () => {
    if (!recording) {
        const labelInput = document.getElementById("data-label");
        currentLabel = labelInput.value.trim() || "unlabeled";
    }
    recording = !recording;
    recordBtn.textContent = recording ? "Stop Recording" : "Start Recording";

    if (!recording && recordedData.length > 0 && savePath) {
        const labelInput = document.getElementById("data-label");
        currentLabel = labelInput.value.trim() || "unlabeled";

        let finalPath = savePath.replace(/\/$/, "");
        const now = new Date();
        const timestampStr = now.toISOString().replace(/[:.]/g, "-");
        const fileName = `myo_raw_${currentLabel}_${timestampStr}.csv`;
        finalPath += `/${fileName}`;

        fetch("/save-data", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: finalPath, data: recordedData }),
        }).then(() => {
            alert("Data saved to " + finalPath);
            recordedData = [];
        }).catch((err) => {
            console.error("Save error", err);
            alert("Failed to save data.");
        });
    }
});

document.getElementById("settings-toggle").addEventListener("click", () => {
    const panel = document.getElementById("settings-panel");
    panel.classList.toggle("d-none");
});

document.getElementById("save-settings-btn").addEventListener("click", () => {
    const input = document.getElementById("save-path");
    savePath = input.value.trim();

    const msg = document.getElementById("settings-saved-msg");
    msg.classList.remove("d-none");
    setTimeout(() => msg.classList.add("d-none"), 2000);
});

function toggleButtons(connected) {
    disconnectBtn.disabled = !connected;
    resetBtn.disabled = !connected;
    vibrateBtn.disabled = !connected;
    connectBtn.disabled = connected;
}

// 8‑channel EMG scope
const emgCharts = [];
const MAX_POINTS = 200; // ~1 s of data at 200 Hz

// create the canvases on page load
(() => {
  const wrap = document.getElementById("emg-charts");
  for (let ch = 0; ch < 8; ch++) {
    const c = document.createElement("canvas");
    
    c.style.width = "100%";
    c.height = 100; 

    wrap.appendChild(c);
    emgCharts[ch] = new Chart(c.getContext("2d"), {
      type: "line",
      data: {
        labels: Array(MAX_POINTS).fill(""),
        datasets: [
          {
            label: "Ch " + ch,
            data: Array(MAX_POINTS).fill(0),
            fill: false,
            borderWidth: 1,
          },
        ],
      },
      options: {
        animation: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { display: false },
          y: { suggestedMin: -128, suggestedMax: 127 },
        },
      },
    });
  }
})();

function pushFrame(frame) {

    if (emgPaused) return;

    frame.forEach((val, ch) => {
        const d = emgCharts[ch].data.datasets[0].data;
        d.push(val);
        if (d.length > MAX_POINTS) d.shift();
        emgCharts[ch].update("none");
    });
}

// Socket.IO: receive packets {"t": float, "samples": [[8],[8]]}
const socket = io();

socket.on("emg", (msg) => {
    if (recording) {
        msg.samples.forEach(sample => {
            recordedData.push({
                timestamp: Date.now(),
                emg: sample,
                imu: latestIMU,
                label: currentLabel,
            });
        });
    }    
    msg.samples.forEach(pushFrame);
});

socket.on("imu", (msg) => {
    latestIMU = msg;
    if (msg.quat) {
        applyQuaternionToCube(msg.quat);
    }
});

function applyQuaternionToCube([w, x, y, z]) {
    const quat = new THREE.Quaternion(x, y, z, w);
    cube.quaternion.slerp(quat, 0.2); 
}

// IMU Cube to visualize rotation (Currently only quat rotation so far)
const cubeDiv = document.getElementById("imu-canvas");
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(
    75,
    cubeDiv.clientWidth / cubeDiv.clientHeight,
    0.1,
    1000
);
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(cubeDiv.clientWidth, cubeDiv.clientHeight);
cubeDiv.appendChild(renderer.domElement);

const geometry = new THREE.BoxGeometry();
const material = new THREE.MeshNormalMaterial();
const cube = new THREE.Mesh(geometry, material);
scene.add(cube);

camera.position.z = 3;

function animate() {
    requestAnimationFrame(animate);
    renderer.render(scene, camera);
}

animate();

