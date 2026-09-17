
const { useState, useEffect } = React;

function App() {
    const [query, setQuery] = useState('');
    const [results, setResults] = useState(null);
    const [form, setForm] = useState({
        vehicle_mark: '',
        reported_stolen_on: '',
        fir_number: '',
        status: 'Active',
    });
    const [insertResult, setInsertResult] = useState(null);
    const [activeTab, setActiveTab] = useState('ui');

    const executeSql = async () => {
        try {
            const res = await fetch('/sql', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({query})
            });
            const data = await res.json();
            setResults(data);
        } catch (e) {
            setResults({error: e.message});
        }
    };

    const submitForm = async (e) => {
        e.preventDefault();
        const sql = `INSERT INTO stolen_vehicles (vehicle_mark, reported_stolen_on, fir_number, status) VALUES ('${form.vehicle_mark}', '${form.reported_stolen_on}', '${form.fir_number}', '${form.status}')`;
        try {
            const res = await fetch('/sql', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({query: sql})
            });
            const data = await res.json();
            setInsertResult(data);
            if(data.success) {
                setForm({ vehicle_mark: '', reported_stolen_on: '', fir_number: '', status: 'Active' });
            }
        } catch (e) {
            setInsertResult({error: e.message});
        }
    };

    const handleFormChange = (e) => {
        setForm({...form, [e.target.name]: e.target.value});
    };

    return (
        <div style={{ maxWidth: '800px', margin: '40px auto', fontFamily: 'system-ui, sans-serif' }}>
            <h1 style={{ borderBottom: '2px solid #0056b3', paddingBottom: '10px', color: '#0056b3' }}>Police Agency Node</h1>
            <div style={{ display: 'flex', gap: '10px', marginBottom: '20px' }}>
                <button 
                    onClick={() => setActiveTab('ui')}
                    style={{ padding: '8px 16px', background: activeTab === 'ui' ? '#0056b3' : '#eee', color: activeTab === 'ui' ? '#fff' : '#333', border: 'none', cursor: 'pointer', borderRadius: '4px' }}
                >Add Record</button>
                <button 
                    onClick={() => setActiveTab('sql')}
                    style={{ padding: '8px 16px', background: activeTab === 'sql' ? '#0056b3' : '#eee', color: activeTab === 'sql' ? '#fff' : '#333', border: 'none', cursor: 'pointer', borderRadius: '4px' }}
                >Manual SQL</button>
            </div>

            {activeTab === 'ui' && (
                <div style={{ background: '#f8f9fa', padding: '20px', borderRadius: '8px', border: '1px solid #ddd' }}>
                    <h3>Report Stolen Vehicle</h3>
                    <form onSubmit={submitForm} style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                        <div>
                            <label style={{ display: 'block', fontWeight: 'bold' }}>Vehicle Mark (Plate)</label>
                            <input name="vehicle_mark" value={form.vehicle_mark} onChange={handleFormChange} required style={{ width: '100%', padding: '8px', border: '1px solid #ccc', borderRadius: '4px' }} />
                        </div>
                        <div>
                            <label style={{ display: 'block', fontWeight: 'bold' }}>Reported On (YYYY-MM-DD)</label>
                            <input type="date" name="reported_stolen_on" value={form.reported_stolen_on} onChange={handleFormChange} required style={{ width: '100%', padding: '8px', border: '1px solid #ccc', borderRadius: '4px' }} />
                        </div>
                        <div>
                            <label style={{ display: 'block', fontWeight: 'bold' }}>FIR Number</label>
                            <input name="fir_number" value={form.fir_number} onChange={handleFormChange} required style={{ width: '100%', padding: '8px', border: '1px solid #ccc', borderRadius: '4px' }} />
                        </div>
                        <div>
                            <label style={{ display: 'block', fontWeight: 'bold' }}>Status</label>
                            <select name="status" value={form.status} onChange={handleFormChange} required style={{ width: '100%', padding: '8px', border: '1px solid #ccc', borderRadius: '4px' }}>
                                <option value="Active">Active</option>
                                <option value="Recovered">Recovered</option>
                                <option value="Closed">Closed</option>
                            </select>
                        </div>
                        <button type="submit" style={{ padding: '10px', background: '#28a745', color: '#fff', border: 'none', cursor: 'pointer', borderRadius: '4px', fontWeight: 'bold' }}>Save Record</button>
                    </form>
                    {insertResult && (
                        <div style={{ marginTop: '20px', padding: '15px', background: insertResult.success ? '#d4edda' : '#f8d7da', color: insertResult.success ? '#155724' : '#721c24', borderRadius: '4px' }}>
                            {insertResult.success ? "Success! Record added." : `Error: ${insertResult.error}`}
                        </div>
                    )}
                </div>
            )}

            {activeTab === 'sql' && (
                <div style={{ background: '#f8f9fa', padding: '20px', borderRadius: '8px', border: '1px solid #ddd' }}>
                    <h3>SQL Console</h3>
                    <textarea 
                        value={query} 
                        onChange={e => setQuery(e.target.value)}
                        placeholder="SELECT * FROM stolen_vehicles"
                        style={{ width: '100%', height: '100px', padding: '10px', fontFamily: 'monospace', border: '1px solid #ccc', borderRadius: '4px' }}
                    />
                    <br/><br/>
                    <button onClick={executeSql} style={{ padding: '10px 20px', background: '#0056b3', color: '#fff', border: 'none', cursor: 'pointer', borderRadius: '4px', fontWeight: 'bold' }}>Execute</button>

                    {results && (
                        <div style={{ marginTop: '20px' }}>
                            {results.error ? (
                                <div style={{ color: 'red' }}>Error: {results.error}</div>
                            ) : (
                                <div style={{ overflowX: 'auto' }}>
                                    <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: '10px' }}>
                                        <thead>
                                            <tr>
                                                {results.columns?.map(c => <th key={c} style={{ border: '1px solid #ddd', padding: '8px', background: '#eee' }}>{c}</th>)}
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {results.rows?.map((r, i) => (
                                                <tr key={i}>
                                                    {r.map((val, j) => <td key={j} style={{ border: '1px solid #ddd', padding: '8px' }}>{val}</td>)}
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
