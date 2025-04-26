/**
 *  Myo visualizer - frontend 
 */

// Buttons & UI elements
const scanBtn = document.getElementById("scan-btn");
const connectBtn = document.getElementById("connect-btn");
const disconnectBtn = document.getElementById("disconnect-btn");
const resetBtn = document.getElementById("reset-btn");
const vibrateBtn = document.getElementById("vibrate-btn");
const deviceList = document.getElementById("device-list");
const batteryBadge = document.getElementById("battery-badge");
const pauseBtn = document.getElementById("pause-btn");
const emgModeSelect = document.getElementById("emg-mode-select");
const imuModeSelect = document.getElementById("imu-mode-select");
const freeRecordBtn = document.getElementById("free-record-btn");
const timerRecordBtn = document.getElementById("start-timer-btn");
const recordIndicator = document.getElementById("recording-indicator");
const optionsBtn = document.getElementById("options-btn");
const optionsPanel = document.getElementById("options-panel");
const chartSizeSlider = document.getElementById("chart-size-slider");

let latestIMU = null;
let selectedAddress = null;
let pollTimer = null;
let emgPaused = false;

let recording = false;
let recordedData = [];

let savePath = "";

let timerId = null;
let isRawMode = false;
let currentLabel = "";

// Helper for POST JSON
async function postJSON(url, data = {}) {
    const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
    });
    return res;
}

// Utility to update connection badge
function setStatus(text, colorClass, battery = null, model = null, firmware = null) {
  const badge = document.getElementById("status-badge");
  badge.textContent = text;
  badge.className = "badge " + colorClass;  

  if (battery == null) {
      batteryBadge.classList.add("d-none");
  } else {
      batteryBadge.textContent = battery + " %";
      batteryBadge.classList.remove("d-none");
  }

  const modelBadge = document.getElementById("model-badge");
  if (model == null) {
      modelBadge.classList.add("d-none");
  } else {
      modelBadge.textContent = model;
      modelBadge.classList.remove("d-none");
  }

  const firmwareBadge = document.getElementById("firmware-badge");
  if (firmware == null) {
      firmwareBadge.classList.add("d-none");
  } else {
      firmwareBadge.textContent = "v" + firmware;
      firmwareBadge.classList.remove("d-none");
  }
}

// Poll myo status every 5 s while connected
async function pollStatus() {
    try {
        const resp = await fetch("/status");
        const js   = await resp.json();
        if (js.connected) {
            setStatus("Connected", "bg-success", js.battery, js.model, js.firmware);        
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

function showToast(message) {
  const toastBody = document.getElementById("toast-body");
  toastBody.textContent = message;
  const toastEl = document.getElementById("liveToast");
  const toast = new bootstrap.Toast(toastEl);
  toast.show();
}

async function updateMode() {
  const emgMode = parseInt(emgModeSelect.value, 16);
  const imuMode = parseInt(imuModeSelect.value, 16);

  try {
      const res = await postJSON("/update-mode", {
          emg_mode: emgMode,
          imu_mode: imuMode
      });

      const js = await res.json();
      if (res.ok && js.success) {
        showToast(`Updated: EMG Mode set to ${emgMode === 0x03 ? "Raw" : (emgMode === 0x02 ? "Filtered" : "None")}, IMU Mode set to ${["None", "Data", "Events", "All", "Raw"][imuMode]}`);
      } else {
        showToast(`Failed to update mode: ${js.error || "Unknown error"}`);
      }
  } catch (e) {
      console.error("Mode update failed", e);
      showToast("Failed to update mode.");
  }
}

emgModeSelect.addEventListener("change", updateMode);
imuModeSelect.addEventListener("change", updateMode);

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
      const emgMode = parseInt(emgModeSelect.value, 16);
      const imuMode = parseInt(imuModeSelect.value, 16);

      const res = await postJSON("/connect", { 
          address: selectedAddress,
          emg_mode: emgMode,
          imu_mode: imuMode
      });

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

// Ensure device disconnects when window is closed
window.addEventListener("beforeunload", () => {
  try {
      navigator.sendBeacon("/disconnect");
  } catch (e) {
      console.error("Failed to auto-disconnect", e);
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

function updateRecordingUI(isRecording, source) {
  const activeBtn = source === "free" ? freeRecordBtn : timerRecordBtn;
  const otherBtn = source === "free" ? timerRecordBtn : freeRecordBtn;

  if (isRecording) {
    activeBtn.classList.remove("btn-outline-primary");
    activeBtn.classList.add("btn-danger");
    activeBtn.textContent = "Stop";
    otherBtn.disabled = true;
    recordIndicator.classList.remove("d-none");
  } else {
    freeRecordBtn.classList.remove("btn-danger");
    freeRecordBtn.classList.add("btn-outline-primary");
    freeRecordBtn.textContent = "Free Record";

    timerRecordBtn.classList.remove("btn-danger");
    timerRecordBtn.classList.add("btn-outline-primary");
    timerRecordBtn.textContent = "Timer Record";

    freeRecordBtn.disabled = false;
    timerRecordBtn.disabled = false;

    recordIndicator.classList.add("d-none");
  }
}

optionsBtn.addEventListener("click", (e) => {
  e.stopPropagation(); // Prevent closing immediately
  optionsPanel.classList.toggle("d-none");
});

// Hide the panel when clicking outside
document.addEventListener("click", (e) => {
  if (!optionsPanel.contains(e.target) && e.target !== optionsBtn) {
      optionsPanel.classList.add("d-none");
  }
});

chartSizeSlider.addEventListener("input", (e) => {
  const newHeight = parseInt(e.target.value);

  emgCharts.forEach((chart) => {
    const container = chart.canvas.parentNode;
    container.style.height = `${newHeight}px`;
  });
});


function startRecording(source, duration = null) {
  if (recording) {
    stopRecording();
    return;
  }

  const savePathInput = document.getElementById("record-save-path");
  const labelInput = document.getElementById("record-label");
  const rawSwitch = document.getElementById("raw-mode-switch");

  savePath = savePathInput.value.trim();
  currentLabel = labelInput.value.trim() || "unlabeled";
  isRawMode = rawSwitch.checked;
  recordedData = [];

  recording = true;
  updateRecordingUI(true, source);

  if (source === "timer" && duration > 0) {
    timerId = setTimeout(() => {
      stopRecording();
    }, duration * 1000);
  }
}

function stopRecording() {
  recording = false;
  updateRecordingUI(false);
  if (timerId) {
    clearTimeout(timerId);
    timerId = null;
  }

  if (recordedData.length > 0) {
    const now = new Date();
    const timestampStr = now.toISOString().replace(/[:.]/g, "-");
    const fileName = `myo_${isRawMode ? "hex" : "parsed"}_${currentLabel}_${timestampStr}.csv`;

    // If savePath is empty, just use fileName directly
    let finalPath = fileName;
    if (savePath) {
      finalPath = savePath.replace(/\/$/, "") + `/${fileName}`;
    }

    fetch("/save-data", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: finalPath, data: recordedData }),
    }).then(() => {
      showToast("Data saved to output folder!");
    }).catch((err) => {
      console.error("Save error", err);
      showToast("Failed to save data.");
    });
  }
}

freeRecordBtn.addEventListener("click", () => {
  startRecording("free");
});

timerRecordBtn.addEventListener("click", () => {
  const secs = parseFloat(document.getElementById("record-timer").value);
  if (!isNaN(secs) && secs > 0) {
    startRecording("timer", secs);
  } else {
    alert("Enter a valid duration in seconds.");
  }
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

// Ensure single instance of the tab
(function() {
  const TAB_KEY = 'myo-single-tab-id';
  const MY_TAB_ID = Date.now().toString() + Math.random().toString();

  // Register self
  localStorage.setItem(TAB_KEY, MY_TAB_ID);

  window.addEventListener('storage', (e) => {
      if (e.key === TAB_KEY && e.newValue !== MY_TAB_ID) {
          alert("Another Myo Control tab is already open. Closing this tab...");
          window.close();
      }
  });

  window.addEventListener('beforeunload', () => {
      // Only clear if it's still the owner
      if (localStorage.getItem(TAB_KEY) === MY_TAB_ID) {
          localStorage.removeItem(TAB_KEY);
      }
  });
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
      if (isRawMode && msg.raw) {
          recordedData.push({
              timestamp: Date.now(),
              type: "EMG",
              raw_hex: msg.raw,
              label: currentLabel,
          });
      } else {
          msg.samples.forEach(sample => {
              recordedData.push({
                  timestamp: Date.now(),
                  emg: sample,
                  imu: latestIMU,
                  label: currentLabel,
              });
          });
      }
  }
  msg.samples.forEach(pushFrame);
});

socket.on("imu", (msg) => {
  latestIMU = msg;
  if (recording && isRawMode && msg.raw) {
      recordedData.push({
          timestamp: Date.now(),
          type: "IMU",
          raw_hex: msg.raw,
          label: currentLabel,
      });
  }
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

