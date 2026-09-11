/**
 * MoT Vehicle Status — React Application
 * Full CRUD interface with dashboard, vehicle management, and schema mapping.
 */

const { useState, useEffect, useCallback, useRef } = React;
const API = window.location.origin;

// ============================================================
// Utility Helpers
// ============================================================

function fmtDate(s) {
    if (!s) return '\u2014';
    try { return new Date(s).toLocaleDateString('en-IN', { year:'numeric', month:'short', day:'numeric' }); }
    catch { return s; }
}

function fmtDateTime(s) {
    if (!s) return '\u2014';
    try { return new Date(s).toLocaleString('en-IN', { year:'numeric', month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' }); }
    catch { return s; }
}

function Badge({ type, children }) {
    const cls = { green:'badge-green', red:'badge-red', orange:'badge-orange', neutral:'badge-neutral', accent:'badge-accent' };
    return <span className={`badge ${cls[type] || 'badge-neutral'}`}>{children}</span>;
}

function flagColor(f) {
    if (f === 'STOLEN') return 'red';
    if (f === 'UNINSURED') return 'orange';
    return 'neutral';
}

// ============================================================
// Toast System
// ============================================================

function ToastContainer({ toasts }) {
    return (
        <div className="toast-container">
            {toasts.map(t => <div key={t.id} className={`toast ${t.type}`}>{t.msg}</div>)}
        </div>
    );
}

function useToasts() {
    const [toasts, setToasts] = useState([]);
    const add = useCallback((msg, type = 'info') => {
        const id = Date.now();
        setToasts(prev => [...prev, { id, msg, type }]);
        setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 3500);
    }, []);
    return [toasts, add];
}

// ============================================================
// Confirm Modal
// ============================================================

function ConfirmModal({ title, message, onConfirm, onCancel }) {
    return (
        <div className="modal-overlay" onClick={onCancel}>
            <div className="modal" onClick={e => e.stopPropagation()}>
                <h3>{title}</h3>
                <p>{message}</p>
                <div className="modal-actions">
                    <button className="btn btn-outline" onClick={onCancel}>Cancel</button>
                    <button className="btn btn-danger" onClick={onConfirm}>Delete</button>
                </div>
            </div>
        </div>
    );
}

// ============================================================
// Dashboard Page
// ============================================================

function DashboardPage({ onNavigate, toast }) {
    const [stats, setStats] = useState(null);
    const [plate, setPlate] = useState('');
    const [searching, setSearching] = useState(false);

    useEffect(() => {
        Promise.all([
            fetch(`${API}/api/v1/vehicles`).then(r => r.json()),
            fetch(`${API}/api/v1/vehicles/flagged`).then(r => r.json()),
        ]).then(([all, flagged]) => {
            setStats({ total: all.total, ...flagged.flag_summary });
        }).catch(() => toast('Failed to load dashboard stats', 'error'));
    }, []);

    const doSearch = async () => {
        const p = plate.trim().toUpperCase();
        if (!p) return;
        setSearching(true);
        try {
            const res = await fetch(`${API}/api/v1/vehicle/${encodeURIComponent(p)}`);
            if (!res.ok) {
                const err = await res.json();
                toast(err.detail?.message || 'Vehicle not found', 'error');
                return;
            }
            const data = await res.json();
            onNavigate('detail', { report: data });
        } catch {
            toast('Failed to connect to API', 'error');
        } finally {
            setSearching(false);
        }
    };

    return (
        <div className="page-enter">
            {stats && (
                <div className="stats-row">
                    <div className="stat-card accent">
                        <div className="stat-value">{stats.total}</div>
                        <div className="stat-label">Total Vehicles</div>
                    </div>
                    <div className="stat-card orange">
                        <div className="stat-value">{stats.uninsured}</div>
                        <div className="stat-label">Uninsured</div>
                    </div>
                    <div className="stat-card red">
                        <div className="stat-value">{stats.stolen}</div>
                        <div className="stat-label">Stolen</div>
                    </div>
                    <div className="stat-card muted">
                        <div className="stat-value">{stats.scrapped}</div>
                        <div className="stat-label">Scrapped</div>
                    </div>
                </div>
            )}

            <div className="search-container">
                <div className="search-title">Vehicle Status Lookup</div>
                <div className="search-subtitle">
                    Query the federated GAV mediator across all 4 data sources
                </div>
                <div className="search-bar">
                    <input
                        className="search-input"
                        placeholder="Enter registration number, e.g. AB12CD3456"
                        value={plate}
                        onChange={e => setPlate(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && doSearch()}
                        spellCheck={false}
                        autoComplete="off"
                    />
                    <button className="btn btn-primary" onClick={doSearch} disabled={searching}>
                        {searching ? <><span className="spinner"></span>Searching...</> : 'Search'}
                    </button>
                </div>
            </div>
        </div>
    );
}

// ============================================================
// Vehicle Detail Page
// ============================================================

function DetailPage({ report, onNavigate, toast }) {
    const [showProv, setShowProv] = useState(false);
    const d = report;
    const flags = d.flags || [];

    let bannerCls = 'status-clear', bannerText = 'Vehicle is clear -- no flags detected.';
    if (flags.includes('STOLEN')) {
        bannerCls = 'status-danger';
        bannerText = `ALERT: Vehicle is flagged as ${flags.join(', ')}.`;
    } else if (flags.length > 0) {
        bannerCls = 'status-warning';
        bannerText = `WARNING: Vehicle is flagged as ${flags.join(', ')}.`;
    }

    const provRows = [];
    function walk(obj, prefix) {
        if (!obj) return;
        for (const [k, v] of Object.entries(obj)) {
            if (v && typeof v === 'object' && v.source) {
                provRows.push({ field: prefix ? `${prefix}.${k}` : k, ...v });
            } else if (v && typeof v === 'object') {
                walk(v, prefix ? `${prefix}.${k}` : k);
            }
        }
    }
    walk(d.provenance, '');

    return (
        <div className="page-enter">
            <div style={{ marginBottom: 20, display:'flex', gap:10, alignItems:'center' }}>
                <button className="btn btn-ghost" onClick={() => onNavigate('dashboard')}>Back</button>
                <span className="mono" style={{ fontSize:'1.1rem', fontWeight:600 }}>{d.vehicle_identifier}</span>
                <button className="btn btn-outline btn-sm" onClick={() => onNavigate('edit', { plate: d.vehicle_identifier })}>Edit</button>
            </div>

            <div className={`status-banner ${bannerCls}`}>{bannerText}</div>

            <div className="report-grid">
                <div className="card">
                    <div className="card-header">Vehicle Information</div>
                    <div className="card-body">
                        <table className="info-table"><tbody>
                            <tr><td>Registration</td><td>{d.vehicle_identifier}</td></tr>
                            <tr><td>Owner</td><td>{d.owner || '\u2014'}</td></tr>
                            <tr><td>Vehicle Class</td><td>{d.vehicle_class || '\u2014'}</td></tr>
                            <tr><td>Registration Date</td><td>{fmtDate(d.registration_date)}</td></tr>
                            <tr><td>Chassis No.</td><td>{d.chassis_no || '\u2014'}</td></tr>
                        </tbody></table>
                    </div>
                </div>

                <div className="card">
                    <div className="card-header">Insurance Status</div>
                    <div className="card-body">
                        <table className="info-table"><tbody>
                            <tr><td>Status</td><td>{d.is_insured ? <Badge type="green">INSURED</Badge> : <Badge type="red">UNINSURED</Badge>}</td></tr>
                            <tr><td>Policy No.</td><td>{d.insurance_details?.policy_no || '\u2014'}</td></tr>
                            <tr><td>Insurer</td><td>{d.insurance_details?.insurer || '\u2014'}</td></tr>
                            <tr><td>Start Date</td><td>{fmtDate(d.insurance_details?.start_date)}</td></tr>
                            <tr><td>Expiry Date</td><td>{fmtDate(d.insurance_details?.expiry_date)}</td></tr>
                        </tbody></table>
                    </div>
                </div>

                <div className="card">
                    <div className="card-header">Police Record</div>
                    <div className="card-body">
                        <table className="info-table"><tbody>
                            <tr><td>Stolen</td><td>{d.is_stolen ? <Badge type="red">YES</Badge> : <Badge type="green">NO</Badge>}</td></tr>
                            <tr><td>FIR Number</td><td>{d.fir_number || '\u2014'}</td></tr>
                            <tr><td>Scrapped</td><td>{d.is_scrapped ? <Badge type="orange">YES</Badge> : <Badge type="neutral">NO</Badge>}</td></tr>
                        </tbody></table>
                    </div>
                </div>

                <div className="card">
                    <div className="card-header">Last Seen (Camera)</div>
                    <div className="card-body">
                        <table className="info-table"><tbody>
                            <tr><td>Timestamp</td><td>{fmtDateTime(d.last_seen?.timestamp)}</td></tr>
                            <tr><td>Location</td><td>{d.last_seen?.location || '\u2014'}</td></tr>
                            <tr><td>OCR Confidence</td><td>{d.last_seen?.ocr_confidence ? `${(d.last_seen.ocr_confidence*100).toFixed(0)}%` : '\u2014'}</td></tr>
                        </tbody></table>
                    </div>
                </div>

                <div className="card card-full">
                    <div className="card-header">
                        Data Provenance Trace
                        <button className="btn btn-ghost btn-sm" onClick={() => setShowProv(!showProv)}>
                            {showProv ? 'Hide' : 'Show'}
                        </button>
                    </div>
                    {showProv && (
                        <div className="card-body" style={{ maxHeight: 360, overflowY: 'auto', padding: 0 }}>
                            <table className="prov-table">
                                <thead><tr><th>Field</th><th>Source DB</th><th>Table</th><th>Local Column</th><th>Retrieved At</th></tr></thead>
                                <tbody>
                                    {provRows.map((r, i) => (
                                        <tr key={i}>
                                            <td>{r.field}</td><td>{r.source}</td><td>{r.table}</td>
                                            <td>{r.local_column}</td><td>{fmtDateTime(r.retrieved_at)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

// ============================================================
// All Vehicles Page
// ============================================================

function AllVehiclesPage({ onNavigate, toast }) {
    const [vehicles, setVehicles] = useState(null);
    const [filter, setFilter] = useState('');
    const [delModal, setDelModal] = useState(null);

    const load = async () => {
        try {
            const res = await fetch(`${API}/api/v1/vehicles`);
            const data = await res.json();
            setVehicles(data.vehicles);
        } catch {
            toast('Failed to load vehicles', 'error');
        }
    };

    useEffect(() => { load(); }, []);

    const doDelete = async (plate) => {
        try {
            const res = await fetch(`${API}/api/v1/vehicle/${plate}`, { method: 'DELETE' });
            if (res.ok) {
                toast(`Vehicle ${plate} deleted`, 'success');
                load();
            } else {
                toast('Delete failed', 'error');
            }
        } catch {
            toast('Delete failed', 'error');
        }
        setDelModal(null);
    };

    const viewReport = async (plate) => {
        const res = await fetch(`${API}/api/v1/vehicle/${encodeURIComponent(plate)}`);
        if (res.ok) {
            const data = await res.json();
            onNavigate('detail', { report: data });
        }
    };

    const filtered = vehicles ? vehicles.filter(v =>
        v.vehicle_identifier.toLowerCase().includes(filter.toLowerCase()) ||
        (v.owner || '').toLowerCase().includes(filter.toLowerCase())
    ) : [];

    return (
        <div className="page-enter">
            <div className="section-header">
                <h2>All Vehicles Directory</h2>
                <div className="section-actions">
                    <div className="filter-bar">
                        <input className="form-input" placeholder="Search by plate or owner..." value={filter} onChange={e => setFilter(e.target.value)} />
                    </div>
                    <button className="btn btn-primary btn-sm" onClick={() => onNavigate('add')}>Add Vehicle</button>
                    <button className="btn btn-outline btn-sm" onClick={load}>Refresh</button>
                </div>
            </div>

            {vehicles === null ? (
                <div className="loading-text"><span className="spinner"></span>Loading vehicles...</div>
            ) : (
                <div className="card">
                    <div className="card-body" style={{ padding: 0, maxHeight: 600, overflowY: 'auto' }}>
                        <table className="data-table">
                            <thead><tr>
                                <th>Vehicle ID</th><th>Owner</th><th>Flags</th>
                                <th>Insured</th><th>Stolen</th><th>Scrapped</th><th>Actions</th>
                            </tr></thead>
                            <tbody>
                                {filtered.map(v => (
                                    <tr key={v.vehicle_identifier}>
                                        <td className="mono">{v.vehicle_identifier}</td>
                                        <td>{v.owner || '\u2014'}</td>
                                        <td>
                                            <div className="flags-cell">
                                                {v.flags.length > 0
                                                    ? v.flags.map(f => <Badge key={f} type={flagColor(f)}>{f}</Badge>)
                                                    : <Badge type="green">CLEAR</Badge>}
                                            </div>
                                        </td>
                                        <td>{v.is_insured ? <Badge type="green">Yes</Badge> : <Badge type="red">No</Badge>}</td>
                                        <td>{v.is_stolen ? <Badge type="red">Yes</Badge> : <Badge type="green">No</Badge>}</td>
                                        <td>{v.is_scrapped ? <Badge type="orange">Yes</Badge> : <Badge type="neutral">No</Badge>}</td>
                                        <td>
                                            <div style={{ display:'flex', gap: 4 }}>
                                                <button className="btn btn-ghost btn-sm" onClick={() => viewReport(v.vehicle_identifier)}>View</button>
                                                <button className="btn btn-ghost btn-sm" onClick={() => onNavigate('edit', { plate: v.vehicle_identifier })}>Edit</button>
                                                <button className="btn btn-ghost btn-sm" style={{ color: 'var(--red)' }} onClick={() => setDelModal(v.vehicle_identifier)}>Del</button>
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                        {filtered.length === 0 && <div className="empty-state"><p>No vehicles match your search.</p></div>}
                    </div>
                </div>
            )}

            {delModal && (
                <ConfirmModal
                    title="Delete Vehicle"
                    message={`Are you sure you want to delete vehicle ${delModal} from all 4 databases? This cannot be undone.`}
                    onConfirm={() => doDelete(delModal)}
                    onCancel={() => setDelModal(null)}
                />
            )}
        </div>
    );
}

// ============================================================
// Add Vehicle Page
// ============================================================

function AddVehiclePage({ onNavigate, toast }) {
    const [form, setForm] = useState({
        plate: '', owner_name: '', vehicle_class: 'Sedan', registration_date: '',
        chassis_no: '', policy_no: '', insurer_name: 'AutoGuard Ltd',
        start_date: '', expiry_date: '', insurance_status: 'Active',
        is_stolen: false, fir_number: '', is_scrapped: false,
    });
    const [saving, setSaving] = useState(false);

    const set = (k, v) => setForm(prev => ({ ...prev, [k]: v }));

    const submit = async (e) => {
        e.preventDefault();
        if (!form.plate.trim()) { toast('Plate number is required', 'error'); return; }
        setSaving(true);
        try {
            const res = await fetch(`${API}/api/v1/vehicle`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ...form, plate: form.plate.trim().toUpperCase() }),
            });
            const data = await res.json();
            if (res.ok) {
                toast(`Vehicle ${form.plate.toUpperCase()} created successfully`, 'success');
                onNavigate('vehicles');
            } else {
                toast(data.detail?.message || 'Failed to create vehicle', 'error');
            }
        } catch {
            toast('Failed to connect to API', 'error');
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="page-enter">
            <div className="section-header">
                <h2>Register New Vehicle</h2>
                <div className="section-desc">This will insert records into all 4 source databases (RTO, Insurance, Police, Camera).</div>
            </div>

            <div className="card">
                <div className="card-body">
                    <form onSubmit={submit}>
                        <div className="form-grid">
                            <div className="form-section-title">Vehicle Details (RTO)</div>

                            <div className="form-group">
                                <label className="form-label">Plate Number *</label>
                                <input className="form-input" placeholder="e.g. AB12CD3456" value={form.plate} onChange={e => set('plate', e.target.value)} required />
                            </div>
                            <div className="form-group">
                                <label className="form-label">Owner Name</label>
                                <input className="form-input" placeholder="Full name" value={form.owner_name} onChange={e => set('owner_name', e.target.value)} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">Vehicle Class</label>
                                <select className="form-select" value={form.vehicle_class} onChange={e => set('vehicle_class', e.target.value)}>
                                    <option>Sedan</option><option>SUV</option><option>Hatchback</option>
                                    <option>Motorcycle</option><option>Truck</option>
                                </select>
                            </div>
                            <div className="form-group">
                                <label className="form-label">Registration Date</label>
                                <input className="form-input" type="date" value={form.registration_date} onChange={e => set('registration_date', e.target.value)} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">Chassis Number</label>
                                <input className="form-input" placeholder="Auto-generated if blank" value={form.chassis_no} onChange={e => set('chassis_no', e.target.value)} />
                            </div>

                            <div className="form-section-title">Insurance Details</div>

                            <div className="form-group">
                                <label className="form-label">Policy Number</label>
                                <input className="form-input" placeholder="Auto-generated if blank" value={form.policy_no} onChange={e => set('policy_no', e.target.value)} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">Insurer</label>
                                <select className="form-select" value={form.insurer_name} onChange={e => set('insurer_name', e.target.value)}>
                                    <option>AutoGuard Ltd</option><option>SecureDrive Insurance</option>
                                    <option>SafeJourney</option><option>National Vehicle Insurers</option>
                                </select>
                            </div>
                            <div className="form-group">
                                <label className="form-label">Start Date</label>
                                <input className="form-input" type="date" value={form.start_date} onChange={e => set('start_date', e.target.value)} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">Expiry Date</label>
                                <input className="form-input" type="date" value={form.expiry_date} onChange={e => set('expiry_date', e.target.value)} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">Insurance Status</label>
                                <select className="form-select" value={form.insurance_status} onChange={e => set('insurance_status', e.target.value)}>
                                    <option>Active</option><option>Expired</option><option>Cancelled</option>
                                </select>
                            </div>

                            <div className="form-section-title">Police Record</div>

                            <div className="form-group">
                                <div className="form-checkbox-row">
                                    <input type="checkbox" className="form-checkbox" id="is_stolen" checked={form.is_stolen} onChange={e => set('is_stolen', e.target.checked)} />
                                    <label className="form-checkbox-label" htmlFor="is_stolen">Reported Stolen</label>
                                </div>
                            </div>
                            <div className="form-group">
                                <label className="form-label">FIR Number</label>
                                <input className="form-input" placeholder="If stolen" value={form.fir_number} onChange={e => set('fir_number', e.target.value)} disabled={!form.is_stolen} />
                            </div>
                            <div className="form-group">
                                <div className="form-checkbox-row">
                                    <input type="checkbox" className="form-checkbox" id="is_scrapped" checked={form.is_scrapped} onChange={e => set('is_scrapped', e.target.checked)} />
                                    <label className="form-checkbox-label" htmlFor="is_scrapped">Marked as Scrapped</label>
                                </div>
                            </div>

                            <div className="form-actions">
                                <button type="button" className="btn btn-outline" onClick={() => onNavigate('vehicles')}>Cancel</button>
                                <button type="submit" className="btn btn-primary" disabled={saving}>
                                    {saving ? <><span className="spinner"></span>Saving...</> : 'Register Vehicle'}
                                </button>
                            </div>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    );
}

// ============================================================
// Edit Vehicle Page
// ============================================================

function EditVehiclePage({ plate, onNavigate, toast }) {
    const [loading, setLoading] = useState(true);
    const [form, setForm] = useState({});
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        fetch(`${API}/api/v1/vehicle/${encodeURIComponent(plate)}`)
            .then(r => r.json())
            .then(d => {
                setForm({
                    owner_name: d.owner || '',
                    vehicle_class: d.vehicle_class || 'Sedan',
                    chassis_no: d.chassis_no || '',
                    policy_no: d.insurance_details?.policy_no || '',
                    insurer_name: d.insurance_details?.insurer || 'AutoGuard Ltd',
                    start_date: d.insurance_details?.start_date?.split('T')[0] || '',
                    expiry_date: d.insurance_details?.expiry_date?.split('T')[0] || '',
                    insurance_status: d.insurance_details?.raw_status || 'Active',
                    is_stolen: d.is_stolen || false,
                    fir_number: d.fir_number || '',
                    is_scrapped: d.is_scrapped || false,
                });
                setLoading(false);
            })
            .catch(() => { toast('Failed to load vehicle data', 'error'); onNavigate('vehicles'); });
    }, [plate]);

    const set = (k, v) => setForm(prev => ({ ...prev, [k]: v }));

    const submit = async (e) => {
        e.preventDefault();
        setSaving(true);
        try {
            const res = await fetch(`${API}/api/v1/vehicle/${plate}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(form),
            });
            if (res.ok) {
                toast(`Vehicle ${plate} updated successfully`, 'success');
                onNavigate('vehicles');
            } else {
                toast('Update failed', 'error');
            }
        } catch {
            toast('Failed to connect to API', 'error');
        } finally {
            setSaving(false);
        }
    };

    if (loading) return <div className="loading-text"><span className="spinner"></span>Loading vehicle data...</div>;

    return (
        <div className="page-enter">
            <div className="section-header">
                <h2>Edit Vehicle: <span className="mono">{plate}</span></h2>
                <div className="section-desc">Update fields across the source databases. Only changed fields are written.</div>
            </div>

            <div className="card">
                <div className="card-body">
                    <form onSubmit={submit}>
                        <div className="form-grid">
                            <div className="form-section-title">Vehicle Details (RTO)</div>

                            <div className="form-group">
                                <label className="form-label">Owner Name</label>
                                <input className="form-input" value={form.owner_name} onChange={e => set('owner_name', e.target.value)} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">Vehicle Class</label>
                                <select className="form-select" value={form.vehicle_class} onChange={e => set('vehicle_class', e.target.value)}>
                                    <option>Sedan</option><option>SUV</option><option>Hatchback</option>
                                    <option>Motorcycle</option><option>Truck</option>
                                </select>
                            </div>
                            <div className="form-group">
                                <label className="form-label">Chassis Number</label>
                                <input className="form-input" value={form.chassis_no} onChange={e => set('chassis_no', e.target.value)} />
                            </div>

                            <div className="form-section-title">Insurance Details</div>

                            <div className="form-group">
                                <label className="form-label">Policy Number</label>
                                <input className="form-input" value={form.policy_no} onChange={e => set('policy_no', e.target.value)} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">Insurer</label>
                                <select className="form-select" value={form.insurer_name} onChange={e => set('insurer_name', e.target.value)}>
                                    <option>AutoGuard Ltd</option><option>SecureDrive Insurance</option>
                                    <option>SafeJourney</option><option>National Vehicle Insurers</option>
                                </select>
                            </div>
                            <div className="form-group">
                                <label className="form-label">Start Date</label>
                                <input className="form-input" type="date" value={form.start_date} onChange={e => set('start_date', e.target.value)} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">Expiry Date</label>
                                <input className="form-input" type="date" value={form.expiry_date} onChange={e => set('expiry_date', e.target.value)} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">Insurance Status</label>
                                <select className="form-select" value={form.insurance_status} onChange={e => set('insurance_status', e.target.value)}>
                                    <option>Active</option><option>Expired</option><option>Cancelled</option>
                                </select>
                            </div>

                            <div className="form-section-title">Police Record</div>

                            <div className="form-group">
                                <div className="form-checkbox-row">
                                    <input type="checkbox" className="form-checkbox" id="edit_stolen" checked={form.is_stolen} onChange={e => set('is_stolen', e.target.checked)} />
                                    <label className="form-checkbox-label" htmlFor="edit_stolen">Reported Stolen</label>
                                </div>
                            </div>
                            <div className="form-group">
                                <label className="form-label">FIR Number</label>
                                <input className="form-input" value={form.fir_number} onChange={e => set('fir_number', e.target.value)} disabled={!form.is_stolen} />
                            </div>
                            <div className="form-group">
                                <div className="form-checkbox-row">
                                    <input type="checkbox" className="form-checkbox" id="edit_scrapped" checked={form.is_scrapped} onChange={e => set('is_scrapped', e.target.checked)} />
                                    <label className="form-checkbox-label" htmlFor="edit_scrapped">Marked as Scrapped</label>
                                </div>
                            </div>

                            <div className="form-actions">
                                <button type="button" className="btn btn-outline" onClick={() => onNavigate('vehicles')}>Cancel</button>
                                <button type="submit" className="btn btn-primary" disabled={saving}>
                                    {saving ? <><span className="spinner"></span>Saving...</> : 'Save Changes'}
                                </button>
                            </div>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    );
}

// ============================================================
// Flagged Vehicles Page
// ============================================================

function FlaggedPage({ onNavigate, toast }) {
    const [data, setData] = useState(null);
    const [filter, setFilter] = useState('ALL');

    useEffect(() => {
        fetch(`${API}/api/v1/vehicles/flagged`).then(r => r.json()).then(setData)
            .catch(() => toast('Failed to load flagged vehicles', 'error'));
    }, []);

    const viewReport = async (plate) => {
        const res = await fetch(`${API}/api/v1/vehicle/${encodeURIComponent(plate)}`);
        if (res.ok) { onNavigate('detail', { report: await res.json() }); }
    };

    const filtered = data ? (filter === 'ALL' ? data.vehicles : data.vehicles.filter(v => v.flags.includes(filter))) : [];

    return (
        <div className="page-enter">
            <div className="section-header">
                <h2>Flagged Vehicles</h2>
                <div className="section-desc">Vehicles flagged as uninsured, stolen, or scrapped across all data sources.</div>
            </div>

            {data && (
                <div className="stats-row" style={{ marginBottom: 20 }}>
                    <div className="stat-card accent"><div className="stat-value">{data.total_flagged}</div><div className="stat-label">Total Flagged</div></div>
                    <div className="stat-card orange"><div className="stat-value">{data.flag_summary.uninsured}</div><div className="stat-label">Uninsured</div></div>
                    <div className="stat-card red"><div className="stat-value">{data.flag_summary.stolen}</div><div className="stat-label">Stolen</div></div>
                    <div className="stat-card muted"><div className="stat-value">{data.flag_summary.scrapped}</div><div className="stat-label">Scrapped</div></div>
                </div>
            )}

            <div style={{ marginBottom: 16 }}>
                <select className="form-select" value={filter} onChange={e => setFilter(e.target.value)} style={{ maxWidth: 180 }}>
                    <option value="ALL">All Flags</option>
                    <option value="UNINSURED">Uninsured</option>
                    <option value="STOLEN">Stolen</option>
                    <option value="SCRAPPED">Scrapped</option>
                </select>
            </div>

            {data === null ? (
                <div className="loading-text"><span className="spinner"></span>Loading...</div>
            ) : (
                <div className="card">
                    <div className="card-body" style={{ padding: 0, maxHeight: 500, overflowY: 'auto' }}>
                        <table className="data-table">
                            <thead><tr><th>Vehicle ID</th><th>Owner</th><th>Flags</th><th>Action</th></tr></thead>
                            <tbody>
                                {filtered.map(v => (
                                    <tr key={v.vehicle_identifier}>
                                        <td className="mono">{v.vehicle_identifier}</td>
                                        <td>{v.owner || '\u2014'}</td>
                                        <td><div className="flags-cell">{v.flags.map(f => <Badge key={f} type={flagColor(f)}>{f}</Badge>)}</div></td>
                                        <td><button className="btn btn-ghost btn-sm" onClick={() => viewReport(v.vehicle_identifier)}>View Report</button></td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
        </div>
    );
}

// ============================================================
// Schema Mapping Page
// ============================================================

function SchemaPage({ toast }) {
    const [data, setData] = useState(null);

    useEffect(() => {
        fetch(`${API}/api/v1/schema-mapping`).then(r => r.json()).then(setData)
            .catch(() => toast('Failed to load schema mapping', 'error'));
    }, []);

    if (!data) return <div className="loading-text"><span className="spinner"></span>Loading schema mapping...</div>;

    return (
        <div className="page-enter">
            <div className="section-header">
                <h2>Algorithmic Schema Mapping</h2>
                <div className="section-desc">Column mappings discovered automatically using sentence-transformers and Levenshtein distance. No joins were hardcoded.</div>
            </div>

            <div className="global-key-box">
                <div className="gk-label">Global Key</div>
                <div className="gk-value">{data.global_key}</div>
                <div className="gk-concept">Target concept: "{data.target_concept}"</div>
            </div>

            <div className="mapping-grid">
                {Object.entries(data.mapping).map(([source, info]) => {
                    const conf = (info.confidence * 100).toFixed(1);
                    return (
                        <div className="mapping-card" key={source}>
                            <div className="mapping-source">{source}</div>
                            <div className="mapping-row"><span className="label">Table</span><span className="value">{info.table}</span></div>
                            <div className="mapping-row"><span className="label">Local Key</span><span className="value">{info.local_key}</span></div>
                            <div className="conf-bar-wrap">
                                <div className="conf-label-row"><span className="label">Match Confidence</span><span className="value">{conf}%</span></div>
                                <div className="conf-bar"><div className="conf-fill" style={{ width: `${conf}%` }}></div></div>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

// ============================================================
// App Root
// ============================================================

function App() {
    const [page, setPage] = useState('dashboard');
    const [pageData, setPageData] = useState({});
    const [toasts, addToast] = useToasts();

    const navigate = (p, data = {}) => {
        setPage(p);
        setPageData(data);
    };

    const tabs = [
        { id: 'dashboard', label: 'Dashboard' },
        { id: 'vehicles', label: 'All Vehicles' },
        { id: 'flagged', label: 'Flagged' },
        { id: 'schema', label: 'Schema Mapping' },
    ];

    let content;
    switch (page) {
        case 'dashboard': content = <DashboardPage onNavigate={navigate} toast={addToast} />; break;
        case 'vehicles': content = <AllVehiclesPage onNavigate={navigate} toast={addToast} />; break;
        case 'detail': content = <DetailPage report={pageData.report} onNavigate={navigate} toast={addToast} />; break;
        case 'add': content = <AddVehiclePage onNavigate={navigate} toast={addToast} />; break;
        case 'edit': content = <EditVehiclePage plate={pageData.plate} onNavigate={navigate} toast={addToast} />; break;
        case 'flagged': content = <FlaggedPage onNavigate={navigate} toast={addToast} />; break;
        case 'schema': content = <SchemaPage toast={addToast} />; break;
        default: content = <DashboardPage onNavigate={navigate} toast={addToast} />;
    }

    return (
        <>
            <ToastContainer toasts={toasts} />

            <header className="header">
                <div className="header-inner">
                    <div className="header-brand" style={{ cursor: 'pointer' }} onClick={() => navigate('dashboard')}>
                        <h1><span>MoT</span> Vehicle Status</h1>
                        <span className="header-subtitle">GAV Mediator System</span>
                    </div>
                    <nav className="header-nav">
                        {tabs.map(t => (
                            <button
                                key={t.id}
                                className={`nav-btn ${page === t.id ? 'active' : ''}`}
                                onClick={() => navigate(t.id)}
                            >{t.label}</button>
                        ))}
                    </nav>
                </div>
            </header>

            <main className="main-content">{content}</main>

            <footer className="footer">
                CSE656 Information Integration &amp; Application &mdash; IIIT Delhi &nbsp;|&nbsp; GAV Mediator System v1.0
            </footer>
        </>
    );
}

// Mount
const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
