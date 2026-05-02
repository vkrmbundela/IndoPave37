document.addEventListener('DOMContentLoaded', () => {
    // Init with default Layers
    addLayerRow(3000, 0.35, 120); // BC
    addLayerRow(500, 0.35, 250);  // Base
    addLayerRow(100, 0.40, 0);    // Subgrade (Infinite)

    // Init with critical points
    addDefaultPoints();
});

// --- State Management ---
let chartInstance = null;

// --- Layer Table Functions ---
function addLayerRow(E = 3000, nu = 0.35, h = 100) {
    const tbody = document.querySelector('#layer-table tbody');
    const tr = document.createElement('tr');
    tr.innerHTML = `
        <td>Layer ${tbody.children.length + 1}</td>
        <td><input type="number" step="0.1" value="${E}" class="inp-E"></td>
        <td><input type="number" step="0.01" value="${nu}" class="inp-nu"></td>
        <td><input type="number" step="1" value="${h}" class="inp-h"></td>
        <td><button class="btn btn-danger" onclick="removeRow(this)">x</button></td>
    `;
    tbody.appendChild(tr);
    updateLayerLabels();
}

function updateLayerLabels() {
    const rows = document.querySelectorAll('#layer-table tbody tr');
    rows.forEach((row, index) => {
        row.cells[0].textContent = `Layer ${index + 1}`;
        // Last layer thickness handling?
        // User inputs 0 for infinite usually.
    });
}


// --- Point Table Functions ---
function addPointRow(z = 0, r = 0) {
    const tbody = document.querySelector('#point-table tbody');
    const tr = document.createElement('tr');
    tr.innerHTML = `
        <td><input type="number" step="1" value="${z}" class="inp-z"></td>
        <td><input type="number" step="1" value="${r}" class="inp-r"></td>
        <td><button class="btn btn-danger" onclick="removeRow(this)">x</button></td>
    `;
    tbody.appendChild(tr);
}

function addDefaultPoints() {
    // Clear list
    document.querySelector('#point-table tbody').innerHTML = '';

    // Add criticals from typical pavement analysis
    // 1. Surface (0,0) - Deflection
    addPointRow(0, 0);

    // 2. Interface 1 (Bottom of BC) - Tensile Strain
    // Need to know thickness first.
    // Let's iterate inputs to find depths.
    const layers = getLayerData();
    let currentDepth = 0;
    layers.forEach(l => {
        if (l.h > 0) {
            currentDepth += l.h;
            // Add point at interface
            addPointRow(currentDepth, 0);
        }
    });

    // 3. Top of Subgrade
    // Already covered if we iterate all layers.
}

function removeRow(btn) {
    btn.closest('tr').remove();
    updateLayerLabels();
}

// --- Data Extraction ---
function getLayerData() {
    const rows = document.querySelectorAll('#layer-table tbody tr');
    const data = [];
    rows.forEach(row => {
        data.push({
            E: parseFloat(row.querySelector('.inp-E').value),
            nu: parseFloat(row.querySelector('.inp-nu').value),
            h: parseFloat(row.querySelector('.inp-h').value)
        });
    });
    return data;
}

function getPointData() {
    const rows = document.querySelectorAll('#point-table tbody tr');
    const data = [];
    rows.forEach(row => {
        data.push({
            z: parseFloat(row.querySelector('.inp-z').value),
            r: parseFloat(row.querySelector('.inp-r').value)
        });
    });
    return data;
}

// --- Analysis ---
async function runAnalysis() {
    const statusDiv = document.getElementById('status-indicator');
    statusDiv.textContent = "Computing...";
    statusDiv.style.color = "var(--accent-warning)";

    // 1. Prepare Payload
    const layers = getLayerData();
    const points = getPointData();
    const loadN = parseFloat(document.getElementById('wheel-load').value);
    const pressureMPa = parseFloat(document.getElementById('tire-pressure').value);

    // Send load directly — backend handles radius calculation
    const wheelType = document.getElementById('wheel-type').value;
    const wheelSpacing = parseFloat(document.getElementById('wheel-spacing').value) || 310;

    // Validate inputs
    if (layers.length < 2) {
        alert("Need at least 2 layers (one finite + subgrade).");
        statusDiv.textContent = "Error";
        statusDiv.style.color = "#ef4444";
        return;
    }
    if (layers[layers.length - 1].h !== 0) {
        alert("Last layer must have thickness = 0 (half-space).");
        statusDiv.textContent = "Error";
        statusDiv.style.color = "#ef4444";
        return;
    }
    if (points.length < 1) {
        alert("Need at least 1 evaluation point.");
        statusDiv.textContent = "Error";
        statusDiv.style.color = "#ef4444";
        return;
    }
    for (const l of layers) {
        if (l.E <= 0 || l.nu <= 0 || l.nu >= 0.5) {
            alert("Invalid layer: E must be > 0, Poisson must be 0 < nu < 0.5");
            statusDiv.textContent = "Error";
            statusDiv.style.color = "#ef4444";
            return;
        }
    }

    const payload = {
        layers: layers,
        wheel_load: loadN,
        tire_pressure: pressureMPa,
        points: points,
        wheel_type: wheelType,
        wheel_spacing: wheelSpacing
    };

    try {
        // 2. Call API
        const response = await fetch('/api/solve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!response.ok) throw new Error("Server Error");

        const data = await response.json();

        // 3. Update UI
        updateResults(data);
        updateChart(data);

        statusDiv.textContent = "Complete";
        statusDiv.style.color = "var(--accent-success)";

    } catch (e) {
        statusDiv.textContent = "Error";
        statusDiv.style.color = "#ef4444";
        console.error(e);
        alert("Analysis failed. Check console.");
    }
}

function updateResults(data) {
    // Summary Cards
    document.getElementById('res-max-disp').textContent = data.max_disp.toFixed(3);
    document.getElementById('res-max-eps-t').textContent = (data.max_strain_t * 1e6).toFixed(1);
    document.getElementById('res-max-eps-c').textContent = (data.max_strain_c * 1e6).toFixed(1);

    // Table
    const tbody = document.querySelector('#results-table tbody');
    tbody.innerHTML = '';

    data.results.forEach(res => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${res.z.toFixed(1)}</td>
            <td>${res.r.toFixed(1)}</td>
            <td>${res.sigma_z.toFixed(4)}</td>
            <td>${res.sigma_r.toFixed(4)}</td>
            <td>${res.sigma_t.toFixed(4)}</td>
            <td>${res.disp_z.toFixed(4)}</td>
            <td>${(res.eps_z * 1e6).toFixed(1)}</td>
            <td>${(res.eps_t * 1e6).toFixed(1)}</td>
        `;
        tbody.appendChild(tr);
    });
}

function updateChart(data) {
    const ctx = document.getElementById('depth-chart').getContext('2d');

    // Extract Z and Stress/Strain
    const z_vals = data.results.map(r => r.z);
    const labels = z_vals;

    // Sort by Z for chart
    // Assuming points might be out of order? 
    // Usually sorted by input. Let's trust input order or sort.

    const datasets = [
        {
            label: 'Sigma Z (MPa)',
            data: data.results.map(r => r.sigma_z),
            borderColor: '#ff7d00', // Orange
            backgroundColor: 'rgba(255, 125, 0, 0.1)',
            tension: 0.1
        },
        {
            label: 'Disp Z (mm)',
            data: data.results.map(r => r.disp_z),
            borderColor: '#10b981', // Green
            backgroundColor: 'rgba(16, 185, 129, 0.1)',
            tension: 0.1,
            yAxisID: 'y1'
        }
    ];

    if (chartInstance) chartInstance.destroy();

    chartInstance = new Chart(ctx, {
        type: 'line',
        data: { labels: labels, datasets: datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    title: { display: true, text: 'Depth (mm)', color: '#4b5563' },
                    grid: { color: 'rgba(0,0,0,0.05)' },
                    ticks: { color: '#1a1a1a' }
                },
                y: {
                    title: { display: true, text: 'Stress (MPa)', color: '#4b5563' },
                    grid: { color: 'rgba(0,0,0,0.05)' },
                    ticks: { color: '#1a1a1a' }
                },
                y1: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    title: { display: true, text: 'Deflection (mm)', color: '#4b5563' },
                    grid: { drawOnChartArea: false },
                    ticks: { color: '#1a1a1a' }
                }
            },
            plugins: {
                legend: { labels: { color: '#1a1a1a' } }
            }
        }
    });
}


// --- Dual Wheel Toggle ---
function toggleSpacing() {
    const wheelType = document.getElementById('wheel-type').value;
    const spacingRow = document.getElementById('spacing-row');
    spacingRow.style.display = (wheelType === 'Dual') ? 'block' : 'none';
}


// --- Optimization Logic ---

function switchTab(tabName) {
    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));

    // Show selected
    document.getElementById(`tab-${tabName}`).style.display = 'block';

    // Update button (find by text or index? naive approach)
    const btns = document.querySelectorAll('.tab-btn');
    if (tabName === 'analysis') btns[0].classList.add('active');
    else btns[1].classList.add('active');

    // Toggle Results
    document.querySelectorAll('.results-content').forEach(el => el.style.display = 'none');
    document.getElementById(`results-${tabName}`).style.display = 'block';
}

function addOptLayerRow(type = "BC", min = 30, max = 50) {
    const tbody = document.querySelector('#opt-layer-table tbody');
    const tr = document.createElement('tr');
    tr.innerHTML = `
        <td>
            <select class="inp-type">
                <option value="BC" ${type === 'BC' ? 'selected' : ''}>BC</option>
                <option value="DBM" ${type === 'DBM' ? 'selected' : ''}>DBM</option>
                <option value="WMM" ${type === 'WMM' ? 'selected' : ''}>WMM</option>
                <option value="GSB" ${type === 'GSB' ? 'selected' : ''}>GSB</option>
            </select>
        </td>
        <td><input type="number" step="5" value="${min}" class="inp-min"></td>
        <td><input type="number" step="5" value="${max}" class="inp-max"></td>
        <td><button class="btn btn-danger" onclick="removeRow(this)">x</button></td>
    `;
    tbody.appendChild(tr);
}

// Init Opt Defaults
document.addEventListener('DOMContentLoaded', () => {
    // ... existing init ...
    // Add default optimization layers
    addOptLayerRow("BC", 30, 50);
    addOptLayerRow("DBM", 50, 90);
    addOptLayerRow("WMM", 200, 300);
    addOptLayerRow("GSB", 150, 250);
});

async function runOptimization() {
    const statusDiv = document.getElementById('status-indicator');
    statusDiv.textContent = "Optimizing...";
    statusDiv.style.color = "var(--accent-warning)";

    // 1. Gather Inputs
    const cvpd = parseFloat(document.getElementById('opt-cvpd').value);
    const growth = parseFloat(document.getElementById('opt-growth').value);
    const life = parseFloat(document.getElementById('opt-life').value);
    const vdf = parseFloat(document.getElementById('opt-vdf').value);
    const lane = parseFloat(document.getElementById('opt-lane').value);
    const cbr = parseFloat(document.getElementById('opt-cbr').value);
    const reliability = document.getElementById('opt-reliability').value;

    const rows = document.querySelectorAll('#opt-layer-table tbody tr');
    const layers = [];
    rows.forEach(row => {
        layers.push({
            layer_type: row.querySelector('.inp-type').value,
            min_thickness: parseFloat(row.querySelector('.inp-min').value),
            max_thickness: parseFloat(row.querySelector('.inp-max').value)
        });
    });

    const payload = {
        cvpd: cvpd, growth_rate: growth, design_life: life,
        vdf: vdf, lane_factor: lane,
        subgrade_cbr: cbr, reliability: reliability,
        layers: layers
    };

    try {
        const response = await fetch('/api/optimize', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!response.ok) throw new Error("Optimization Failed");

        const data = await response.json();

        // Update UI
        document.getElementById('opt-cost').textContent = Math.round(data.cost).toLocaleString();
        document.getElementById('opt-co2').textContent = data.co2 ? data.co2.toFixed(1) : '--';

        const adqEl = document.getElementById('opt-adequacy');
        adqEl.textContent = data.is_adequate ? "ADEQUATE" : "INADEQUATE";
        adqEl.style.color = data.is_adequate ? "var(--accent-success)" : "#ef4444";

        if (data.details) {
            document.getElementById('opt-msa').textContent =
                data.details.msa ? data.details.msa.toFixed(1) : '--';

            // Show structural details
            const detailsDiv = document.getElementById('opt-structural-details');
            if (data.details.CDF_fatigue !== undefined) {
                detailsDiv.style.display = '';
                document.getElementById('opt-cdf-f').textContent =
                    data.details.CDF_fatigue.toFixed(3);
                document.getElementById('opt-cdf-r').textContent =
                    data.details.CDF_rutting.toFixed(3);
                document.getElementById('opt-eps-t').textContent =
                    data.details.eps_t ? (data.details.eps_t * 1e6).toFixed(1) : '--';
                document.getElementById('opt-eps-v').textContent =
                    data.details.eps_v ? (data.details.eps_v * 1e6).toFixed(1) : '--';
            }
        }

        const tbody = document.querySelector('#opt-results-table tbody');
        tbody.innerHTML = '';
        data.optimal_layers.forEach(l => {
            const tr = document.createElement('tr');
            tr.innerHTML = `<td>${l.type}</td><td><strong>${l.thickness}</strong></td>`;
            tbody.appendChild(tr);
        });

        statusDiv.textContent = "Optimization Complete";
        statusDiv.style.color = "var(--accent-success)";

    } catch (e) {
        statusDiv.textContent = "Error";
        console.error(e);
        alert("Optimization failed: " + e.message);
    }
}
