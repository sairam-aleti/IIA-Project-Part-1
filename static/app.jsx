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
    if (f === 'STOLEN' || f === 'SUSPICIOUS') return 'red';
    if (f === 'UNINSURED' || f === 'SCRAPPED' || f === 'UNREGISTERED') return 'orange';
    if (f === 'INSUFFICIENT_EVIDENCE') return 'accent';
    return 'neutral';
}

const OUTCOMES = {
    COMPLIANT:             { label: 'Compliant',           cls: 'status-clear',   badge: 'green'   },
    UNINSURED:             { label: 'Uninsured',           cls: 'status-warning', badge: 'orange'  },
    SUSPICIOUS:            { label: 'Suspicious',          cls: 'status-danger',  badge: 'red'     },
    INSUFFICIENT_EVIDENCE: { label: 'Insufficient evidence', cls: 'status-warning', badge: 'accent' },
};

function outcomeMeta(outcome) {
    return OUTCOMES[outcome] || { label: outcome || 'Unknown', cls: 'status-warning', badge: 'neutral' };
}

function fmtConfidence(c) {
    if (c === null || c === undefined) return 'withheld';
    return `${(c * 100).toFixed(0)}%`;
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
            fetch(`${API}/api/v1/vehicles/flagged?limit=1000`).then(r => r.json()),
            fetch(`${API}/api/v1/unresolved?limit=1`).then(r => r.json()),
        ]).then(([flagged, unresolved]) => {
            const summary = flagged.outcome_summary || {};
            setStats({
                total: flagged.total_known,
                compliant: flagged.total_known - flagged.total_flagged,
                uninsured: summary.UNINSURED || 0,
                suspicious: summary.SUSPICIOUS || 0,
                abstained: summary.INSUFFICIENT_EVIDENCE || 0,
                unattributed: unresolved.total || 0,
                adjudication: flagged.adjudication_required || 0,
            });
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
                toast(err.detail?.message || 'Lookup failed', 'error');
                return;
            }
            const data = await res.json();
            if (data.assessment?.outcome === 'INSUFFICIENT_EVIDENCE') {
                toast('Resolved, but the system declines to conclude', 'info');
            }
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
                        <div className="stat-value">{stats.suspicious}</div>
                        <div className="stat-label">Suspicious</div>
                    </div>
                    <div className="stat-card muted">
                        <div className="stat-value">{stats.abstained + stats.unattributed}</div>
                        <div className="stat-label">Insufficient Evidence</div>
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
    const a = d.assessment || {};
    const meta = outcomeMeta(a.outcome);
    const contradictions = d.contradictions || [];
    const periods = d.insurance_at?.periods || [];
    const sightings = d.sightings || [];
    const priorFindings = d.prior_findings || [];
    const [filing, setFiling] = useState(false);

    const bannerCls = meta.cls;
    const bannerText = a.outcome === 'COMPLIANT'
        ? `Compliant \u2014 ${a.reasons?.[0] || 'no adverse findings.'}`
        : `${meta.label.toUpperCase()}${flags.length ? ': ' + flags.join(', ') : ''}`;

    const fileReport = async () => {
        setFiling(true);
        try {
            const res = await fetch(`${API}/api/v1/vehicle/${encodeURIComponent(d.canonical_mark || d.query)}/report`, { method: 'POST' });
            const body = await res.json();
            if (body.filing?.filed) {
                toast(`Filed with the Ministry as ${body.filing.report_ref}`, 'success');
            } else {
                toast(body.filing?.reason || 'Nothing to file', 'info');
            }
        } catch {
            toast('Failed to file report', 'error');
        } finally {
            setFiling(false);
        }
    };

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
                <span className="mono" style={{ fontSize:'1.1rem', fontWeight:600 }}>{d.canonical_mark || d.query}</span>
                <Badge type={meta.badge}>{meta.label}</Badge>
                <span style={{ flex: 1 }}></span>
                {a.reportable && (
                    <button className="btn btn-outline btn-sm" onClick={fileReport} disabled={filing}>
                        {filing ? 'Filing...' : 'Report to Ministry'}
                    </button>
                )}
                {d.canonical_mark && (
                    <button className="btn btn-outline btn-sm" onClick={() => onNavigate('edit', { plate: d.canonical_mark })}>Edit</button>
                )}
            </div>

            <div className={`status-banner ${bannerCls}`}>{bannerText}</div>

            <div className="report-grid">
                <div className="card card-full">
                    <div className="card-header">Assessment</div>
                    <div className="card-body">
                        <table className="info-table"><tbody>
                            <tr><td>Outcome</td><td><Badge type={meta.badge}>{a.outcome}</Badge></td></tr>
                            <tr><td>Confidence</td><td>{fmtConfidence(a.confidence)}
                                <div style={{ fontSize:'0.75rem', opacity:0.6 }}>{a.confidence_basis}</div></td></tr>
                            <tr><td>Assessed at</td><td>{a.assessed_at ? fmtDate(a.assessed_at) : '\u2014'}
                                <div style={{ fontSize:'0.75rem', opacity:0.6 }}>{a.assessment_basis}</div></td></tr>
                            {a.requires_adjudication && (
                                <tr><td>Adjudication</td><td><Badge type="orange">required</Badge></td></tr>
                            )}
                        </tbody></table>

                        {(a.reasons || []).length > 0 && (
                            <div style={{ marginTop: 14 }}>
                                <div className="form-section-title">Reasons</div>
                                <ul style={{ margin:'6px 0 0 18px', fontSize:'0.85rem', lineHeight:1.65 }}>
                                    {a.reasons.map((r, i) => <li key={i}>{r}</li>)}
                                </ul>
                            </div>
                        )}

                        {(a.rules_applied || []).length > 0 && (
                            <div style={{ marginTop: 14 }}>
                                <div className="form-section-title">Rules applied</div>
                                <div style={{ marginTop: 6, display:'flex', flexWrap:'wrap', gap:6 }}>
                                    {a.rules_applied.map(r => <Badge key={r} type="neutral">{r}</Badge>)}
                                </div>
                            </div>
                        )}
                    </div>
                </div>

                {contradictions.length > 0 && (
                    <div className="card card-full">
                        <div className="card-header">Cross-source contradictions ({contradictions.length})</div>
                        <div className="card-body" style={{ padding: 0 }}>
                            <table className="prov-table">
                                <thead><tr><th>Kind</th><th>Sources</th><th>Detail</th><th>What it could mean</th></tr></thead>
                                <tbody>
                                    {contradictions.map((c, i) => (
                                        <tr key={i}>
                                            <td className="mono">{c.kind}</td>
                                            <td>{(c.sources || []).join(', ')}</td>
                                            <td>{c.detail}</td>
                                            <td>{c.resolved_by_rule
                                                ? <span>Resolved by <span className="mono">{c.resolved_by_rule}</span></span>
                                                : c.implication}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}

                <div className="card">
                    <div className="card-header">Identity resolution</div>
                    <div className="card-body">
                        <table className="info-table"><tbody>
                            <tr><td>Query</td><td className="mono">{d.query}</td></tr>
                            <tr><td>Canonical mark</td><td className="mono">{d.canonical_mark || '\u2014'}</td></tr>
                            <tr><td>Well formed</td><td>{d.identity?.wellformed
                                ? <Badge type="green">yes</Badge> : <Badge type="orange">no</Badge>}</td></tr>
                            <tr><td>Method</td><td className="mono">{d.identity?.method}</td></tr>
                            <tr><td>Link score</td><td>{d.identity?.score}</td></tr>
                        </tbody></table>
                        <div className="form-section-title" style={{ marginTop: 12 }}>Raw values held per source</div>
                        <table className="info-table"><tbody>
                            {(d.identity?.links || []).map((l, i) => (
                                <tr key={i}>
                                    <td>{l.source}</td>
                                    <td className="mono">{JSON.stringify(l.raw_value)}</td>
                                </tr>
                            ))}
                        </tbody></table>
                        <div className="form-section-title" style={{ marginTop: 12 }}>Source reachability</div>
                        <table className="info-table"><tbody>
                            {Object.entries(d.source_status || {}).map(([src, st]) => (
                                <tr key={src}><td>{src}</td><td>
                                    <Badge type={st === 'present' ? 'green' : st === 'absent' ? 'neutral' : 'orange'}>{st}</Badge>
                                </td></tr>
                            ))}
                        </tbody></table>
                    </div>
                </div>

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
                    <div className="card-header">Insurance, at the moment observed</div>
                    <div className="card-body">
                        <table className="info-table"><tbody>
                            <tr><td>State</td><td>
                                {d.insurance_at?.state === 'covered' && <Badge type="green">covered</Badge>}
                                {d.insurance_at?.state === 'lapsed' && <Badge type="orange">lapsed</Badge>}
                                {d.insurance_at?.state === 'never_recorded' && <Badge type="red">no policy on record</Badge>}
                                {d.insurance_at?.state === 'unknown' && <Badge type="accent">source unreachable</Badge>}
                            </td></tr>
                            <tr><td>Assessed at</td><td>{fmtDate(d.insurance_at?.assessed_at)}</td></tr>
                            <tr><td>Policies on record</td><td>{d.insurance_at?.policy_count ?? 0}</td></tr>
                        </tbody></table>

                        {periods.length > 0 && (
                            <>
                                <div className="form-section-title" style={{ marginTop: 12 }}>Policy history</div>
                                <table className="info-table"><tbody>
                                    {periods.map((pd, i) => (
                                        <tr key={i}>
                                            <td className="mono" style={{ fontSize:'0.78rem' }}>
                                                {pd.cover_begins} &rarr; {pd.cover_ends}
                                            </td>
                                            <td>
                                                {pd.in_force_at_assessment
                                                    ? <Badge type="green">in force</Badge>
                                                    : <Badge type="neutral">{pd.declared_state}</Badge>}
                                                {pd.label_contradicts_dates && <Badge type="orange">stale label</Badge>}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody></table>
                            </>
                        )}
                    </div>
                </div>

                <div className="card">
                    <div className="card-header">Police Record</div>
                    <div className="card-body">
                        <table className="info-table"><tbody>
                            <tr><td>Stolen</td><td>{d.is_stolen ? <Badge type="red">YES</Badge> : <Badge type="green">NO</Badge>}</td></tr>
                            <tr><td>FIR Number</td><td>{d.fir_number || '\u2014'}</td></tr>
                            <tr><td>Scrapped</td><td>{d.is_scrapped ? <Badge type="orange">YES</Badge> : <Badge type="neutral">NO</Badge>}</td></tr>
                            <tr><td>Recovered on</td><td>{fmtDate(d.enforcement?.recovered_on)}</td></tr>
                            <tr><td>Register entry</td><td><Badge type={d.enforcement?.status === 'present' ? 'neutral' : 'green'}>
                                {d.enforcement?.status === 'present' ? 'on register' : 'nothing reported'}</Badge></td></tr>
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

                <div className="card">
                    <div className="card-header">Sightings ({sightings.length})</div>
                    <div className="card-body" style={{ maxHeight: 240, overflowY: 'auto' }}>
                        {sightings.length === 0 ? (
                            <div style={{ fontSize:'0.85rem', opacity:0.65 }}>
                                Never observed on the road, so there is no moment at which to assess compliance.
                            </div>
                        ) : (
                            <table className="info-table"><tbody>
                                {sightings.slice(0, 12).map((sg, i) => (
                                    <tr key={i}>
                                        <td style={{ fontSize:'0.78rem' }}>{fmtDateTime(sg.at)}</td>
                                        <td style={{ fontSize:'0.78rem' }}>{sg.place}
                                            <span style={{ opacity:0.55 }}> &nbsp;read {(sg.read_quality*100).toFixed(0)}%</span>
                                        </td>
                                    </tr>
                                ))}
                            </tbody></table>
                        )}
                    </div>
                </div>

                {priorFindings.length > 0 && (
                    <div className="card">
                        <div className="card-header">Previously reported to the Ministry ({priorFindings.length})</div>
                        <div className="card-body" style={{ maxHeight: 240, overflowY: 'auto' }}>
                            <table className="info-table"><tbody>
                                {priorFindings.map((f, i) => (
                                    <tr key={i}>
                                        <td style={{ fontSize:'0.78rem' }}>{fmtDate(f.raised_on)}</td>
                                        <td><Badge type={outcomeMeta(f.finding).badge}>{f.finding}</Badge>
                                            <span style={{ opacity:0.55, fontSize:'0.78rem' }}> &nbsp;{f.severity}</span></td>
                                    </tr>
                                ))}
                            </tbody></table>
                        </div>
                    </div>
                )}

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
                                <thead><tr><th>Attribute</th><th>Source</th><th>Local Column</th><th>Confidence</th><th>Derivation</th><th>Retrieved At</th></tr></thead>
                                <tbody>
                                    {provRows.map((r, i) => (
                                        <tr key={i}>
                                            <td>{r.field}</td>
                                            <td>{r.source}</td>
                                            <td className="mono">{r.column || r.local_column || '\u2014'}</td>
                                            <td>{fmtConfidence(r.confidence)}</td>
                                            <td style={{ fontSize:'0.78rem', opacity:0.75 }}>{r.derivation || '\u2014'}</td>
                                            <td>{fmtDateTime(r.retrieved_at)}</td>
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
            const res = await fetch(`${API}/api/v1/vehicles?limit=1000`);
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
        fetch(`${API}/api/v1/vehicles/flagged?limit=1000`).then(r => r.json()).then(setData)
            .catch(() => toast('Failed to load flagged vehicles', 'error'));
    }, []);

    const viewReport = async (plate) => {
        const res = await fetch(`${API}/api/v1/vehicle/${encodeURIComponent(plate)}`);
        if (res.ok) { onNavigate('detail', { report: await res.json() }); }
    };

    const filtered = data ? (filter === 'ALL' ? data.vehicles
        : data.vehicles.filter(v => v.outcome === filter || (v.flags || []).includes(filter))) : [];

    return (
        <div className="page-enter">
            <div className="section-header">
                <h2>Flagged Vehicles</h2>
                <div className="section-desc">Every vehicle whose assessment is not compliant, including those the system declines to conclude on.</div>
            </div>

            {data && (
                <div className="stats-row" style={{ marginBottom: 20 }}>
                    <div className="stat-card accent"><div className="stat-value">{data.total_flagged}</div><div className="stat-label">Total Flagged</div></div>
                    <div className="stat-card orange"><div className="stat-value">{data.outcome_summary?.UNINSURED || 0}</div><div className="stat-label">Uninsured</div></div>
                    <div className="stat-card red"><div className="stat-value">{data.outcome_summary?.SUSPICIOUS || 0}</div><div className="stat-label">Suspicious</div></div>
                    <div className="stat-card muted"><div className="stat-value">{data.adjudication_required || 0}</div><div className="stat-label">Need Adjudication</div></div>
                </div>
            )}

            <div style={{ marginBottom: 16 }}>
                <select className="form-select" value={filter} onChange={e => setFilter(e.target.value)} style={{ maxWidth: 180 }}>
                    <option value="ALL">All outcomes</option>
                    <option value="UNINSURED">Uninsured</option>
                    <option value="SUSPICIOUS">Suspicious</option>
                    <option value="INSUFFICIENT_EVIDENCE">Insufficient evidence</option>
                    <option value="STOLEN">Flag: stolen</option>
                    <option value="SCRAPPED">Flag: scrapped</option>
                    <option value="UNREGISTERED">Flag: unregistered</option>
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
                <h2>Discovered Schema Mapping</h2>
                <div className="section-desc">
                    Every global attribute is matched to a local column at run time. The matcher's
                    vocabulary contains plain-language descriptions of the global schema and no local
                    column names, so nothing here is hardcoded.
                </div>
            </div>

            <div className="global-key-box">
                <div className="gk-label">Matcher mode</div>
                <div className="gk-value">{data.mode}</div>
                <div className="gk-concept">
                    {data.semantic_available
                        ? 'Semantic (sentence-transformers) + lexical (Levenshtein) + type compatibility.'
                        : `Semantic scoring unavailable — running on lexical + type only. ${data.semantic_unavailable_reason || ''}`}
                    {' '}Threshold {data.threshold}; matches below it are left unmapped rather than forced.
                </div>
            </div>

            <div className="mapping-grid">
                {Object.entries(data.sources || {}).map(([source, info]) => {
                    const attrs = Object.entries(info.attributes || {});
                    return (
                        <div className="mapping-card" key={source}>
                            <div className="mapping-source">{source}</div>
                            <div className="mapping-row">
                                <span className="label">Table</span>
                                <span className="value">{info.table}</span>
                            </div>
                            <div className="mapping-row">
                                <span className="label">Mapped</span>
                                <span className="value">{attrs.length} of {attrs.length + (info.unmapped || []).length}</span>
                            </div>
                            <table className="info-table" style={{ marginTop: 10 }}><tbody>
                                {attrs.map(([attr, m]) => (
                                    <tr key={attr}>
                                        <td style={{ fontSize: '0.78rem' }}>{attr}</td>
                                        <td className="mono" style={{ fontSize: '0.78rem' }}>
                                            {m.column}
                                            <span style={{ opacity: 0.55 }}> &nbsp;{Number(m.score).toFixed(2)}</span>
                                            {m.instance !== null && m.instance !== undefined && (
                                                <Badge type="accent">inst {Number(m.instance).toFixed(2)}</Badge>
                                            )}
                                        </td>
                                    </tr>
                                ))}
                                {(info.unmapped || []).map(attr => (
                                    <tr key={attr}>
                                        <td style={{ fontSize: '0.78rem', opacity: 0.6 }}>{attr}</td>
                                        <td><Badge type="orange">unmapped</Badge></td>
                                    </tr>
                                ))}
                            </tbody></table>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}


// ============================================================
// Ministry report log
// ============================================================

function ReportsPage({ onNavigate, toast }) {
    const [data, setData] = useState(null);
    const [sweeping, setSweeping] = useState(false);
    const [expanded, setExpanded] = useState(null);

    const load = () => {
        fetch(`${API}/api/v1/reports?limit=300`).then(r => r.json()).then(setData)
            .catch(() => toast('Failed to load the report log', 'error'));
    };
    useEffect(() => { load(); }, []);

    const sweep = async () => {
        setSweeping(true);
        try {
            const res = await fetch(`${API}/api/v1/sweep?limit=200`, { method: 'POST' });
            const body = await res.json();
            toast(`Assessed ${body.assessed}, filed ${body.filed} findings`, 'success');
            load();
        } catch {
            toast('Sweep failed', 'error');
        } finally {
            setSweeping(false);
        }
    };

    return (
        <div className="page-enter">
            <div className="section-header">
                <h2>Ministry Report Log</h2>
                <div className="section-desc">
                    Findings written to mot.db, the fifth source. Adverse findings and abstentions are
                    both recorded: a report that the system looked and could not tell is itself
                    information an officer needs.
                </div>
            </div>

            <div style={{ marginBottom: 16 }}>
                <button className="btn btn-primary" onClick={sweep} disabled={sweeping}>
                    {sweeping ? <><span className="spinner"></span>Sweeping...</> : 'Run compliance sweep'}
                </button>
            </div>

            {data === null ? (
                <div className="loading-text"><span className="spinner"></span>Loading...</div>
            ) : (
                <div className="card">
                    <div className="card-body" style={{ padding: 0, maxHeight: 560, overflowY: 'auto' }}>
                        <table className="data-table">
                            <thead><tr><th>Reference</th><th>Vehicle</th><th>Finding</th><th>Severity</th><th>Confidence</th><th>Raised</th><th></th></tr></thead>
                            <tbody>
                                {data.reports.map(r => (
                                    <React.Fragment key={r.report_ref}>
                                        <tr>
                                            <td className="mono">{r.report_ref}</td>
                                            <td className="mono">{r.mark}</td>
                                            <td><Badge type={outcomeMeta(r.finding).badge}>{r.finding}</Badge></td>
                                            <td>{r.severity}</td>
                                            <td>{fmtConfidence(r.confidence)}</td>
                                            <td>{fmtDateTime(r.raised_on)}</td>
                                            <td>
                                                <button className="btn btn-ghost btn-sm"
                                                    onClick={() => setExpanded(expanded === r.report_ref ? null : r.report_ref)}>
                                                    {expanded === r.report_ref ? 'Hide' : 'Evidence'}
                                                </button>
                                            </td>
                                        </tr>
                                        {expanded === r.report_ref && (
                                            <tr>
                                                <td colSpan={7} style={{ background:'rgba(127,127,127,0.06)' }}>
                                                    <pre className="mono" style={{ fontSize:'0.74rem', whiteSpace:'pre-wrap', margin:0 }}>
                                                        {JSON.stringify(r.evidence, null, 2)}
                                                    </pre>
                                                </td>
                                            </tr>
                                        )}
                                    </React.Fragment>
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
// Reads the system cannot attribute
// ============================================================

function UnresolvedPage({ onNavigate, toast }) {
    const [data, setData] = useState(null);

    useEffect(() => {
        fetch(`${API}/api/v1/unresolved?limit=300`).then(r => r.json()).then(setData)
            .catch(() => toast('Failed to load unattributed reads', 'error'));
    }, []);

    return (
        <div className="page-enter">
            <div className="section-header">
                <h2>Unattributed Reads</h2>
                <div className="section-desc">
                    Plates the cameras recorded that resolve to no vehicle in any register. Something
                    was on the road; the system cannot say what. Each is either an unregistered
                    vehicle or a character-level misread, and Part A cannot distinguish the two, so it
                    declines to conclude rather than guessing.
                </div>
            </div>

            {data === null ? (
                <div className="loading-text"><span className="spinner"></span>Loading...</div>
            ) : (
                <>
                    <div className="stats-row" style={{ marginBottom: 20 }}>
                        <div className="stat-card accent">
                            <div className="stat-value">{data.total}</div>
                            <div className="stat-label">Unattributed Marks</div>
                        </div>
                        <div className="stat-card muted">
                            <div className="stat-value">{data.reads.filter(r => !r.wellformed).length}</div>
                            <div className="stat-label">Fail Plate Grammar</div>
                        </div>
                        <div className="stat-card orange">
                            <div className="stat-value">{data.reads.reduce((n, r) => n + r.read_count, 0)}</div>
                            <div className="stat-label">Total Reads Affected</div>
                        </div>
                    </div>

                    <div className="card">
                        <div className="card-body" style={{ padding: 0, maxHeight: 520, overflowY: 'auto' }}>
                            <table className="data-table">
                                <thead><tr><th>Mark read</th><th>Plate grammar</th><th>Confusable key</th><th>Reads</th><th>Last seen</th><th>Outcome</th></tr></thead>
                                <tbody>
                                    {data.reads.map(r => (
                                        <tr key={r.canonical_mark}>
                                            <td className="mono">{r.canonical_mark}</td>
                                            <td>{r.wellformed
                                                ? <Badge type="neutral">valid</Badge>
                                                : <Badge type="orange">invalid</Badge>}</td>
                                            <td className="mono" style={{ fontSize:'0.78rem', opacity:0.7 }}>{r.confusable_key}</td>
                                            <td>{r.read_count}</td>
                                            <td style={{ fontSize:'0.78rem' }}>{fmtDateTime(r.sightings?.[0]?.at)}</td>
                                            <td><Badge type="accent">abstained</Badge></td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <div className="card" style={{ marginTop: 16 }}>
                        <div className="card-header">Where Part B picks this up</div>
                        <div className="card-body" style={{ fontSize:'0.87rem', lineHeight:1.7 }}>
                            The confusable key collapses glyphs the ANPR stack confuses (O with 0, B with 8,
                            I with 1), so two marks sharing a key are candidates for the same vehicle. Part A
                            computes the key but does not act on it, because acting on it means producing a
                            match that might be wrong. Part B will turn each of these rows into a ranked
                            candidate set with probabilities, and report only when the leading candidate
                            clears a threshold.
                        </div>
                    </div>
                </>
            )}
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
        { id: 'unresolved', label: 'Unattributed' },
        { id: 'reports', label: 'Reports' },
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
        case 'unresolved': content = <UnresolvedPage onNavigate={navigate} toast={addToast} />; break;
        case 'reports': content = <ReportsPage onNavigate={navigate} toast={addToast} />; break;
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
                        <span className="header-subtitle">GAV Mediator &mdash; Part A</span>
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
                CSE656 Information Integration &amp; Application &mdash; IIIT Delhi &nbsp;|&nbsp; Part A: traditional data integration
            </footer>
        </>
    );
}

// Mount
const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
