function App() {
    const [query, setQuery] = React.useState('');
    const [results, setResults] = React.useState(null);
    const [form, setForm] = React.useState({
        vehicle_mark: '',
        insurer: '',
        policy_number: '',
        cover_start: '',
        cover_upto: '',
        status: '',

    });
    const [insertResult, setInsertResult] = React.useState(null);
    const [activeTab, setActiveTab] = React.useState('ui');

    const executeSql = async () => {
        const res = await fetch('/sql', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({query})
        });
        setResults(await res.json());
    };

    const submitForm = async (e) => {
        e.preventDefault();
        
        // Generate SQL INSERT query
        const columns = Object.keys(form).join(', ');
        const values = Object.values(form).map(v => "'" + v.replace(/'/g, "''") + "'").join(', ');
        const sql = INSERT INTO insurance_policies ( + columns + ) VALUES ( + values + );
        
        const res = await fetch('/sql', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({query: sql})
        });
        const data = await res.json();
        setInsertResult(data);
        if (data.success) {
            setForm({         vehicle_mark: '',
        insurer: '',
        policy_number: '',
        cover_start: '',
        cover_upto: '',
        status: '',
 });
        }
    };

    return (
        <div className="container" style={{padding: '2rem'}}>
            <header className="page-header" style={{marginBottom: '2rem'}}>
                <h1>{$node.toUpperCase()} Agency - Local Interface</h1>
                <p>Manage your local database before it is integrated by the Mediator.</p>
                <div className="btn-group" style={{marginTop: '1rem'}}>
                    <button className={tn  + (activeTab === 'ui' ? 'btn-primary' : 'btn-outline-primary')} onClick={() => setActiveTab('ui')}>Add via UI</button>
                    <button className={tn  + (activeTab === 'sql' ? 'btn-primary' : 'btn-outline-primary')} onClick={() => setActiveTab('sql')}>Manual SQL Console</button>
                </div>
            </header>

            {activeTab === 'ui' && (
                <div className="card">
                    <div className="card-header">Add New Record</div>
                    <div className="card-body">
                        <form onSubmit={submitForm}>
                    <div className="form-group" style={{marginBottom: '1rem'}}>
                        <label>Plate Number</label>
                        <input className="form-control" type="text" value={form.vehicle_mark} onChange={e => setForm({...form, vehicle_mark: e.target.value})} />
                    </div>
                    <div className="form-group" style={{marginBottom: '1rem'}}>
                        <label>Insurer</label>
                        <input className="form-control" type="text" value={form.insurer} onChange={e => setForm({...form, insurer: e.target.value})} />
                    </div>
                    <div className="form-group" style={{marginBottom: '1rem'}}>
                        <label>Policy Number</label>
                        <input className="form-control" type="text" value={form.policy_number} onChange={e => setForm({...form, policy_number: e.target.value})} />
                    </div>
                    <div className="form-group" style={{marginBottom: '1rem'}}>
                        <label>Start Date</label>
                        <input className="form-control" type="text" value={form.cover_start} onChange={e => setForm({...form, cover_start: e.target.value})} />
                    </div>
                    <div className="form-group" style={{marginBottom: '1rem'}}>
                        <label>Expiry Date</label>
                        <input className="form-control" type="text" value={form.cover_upto} onChange={e => setForm({...form, cover_upto: e.target.value})} />
                    </div>
                    <div className="form-group" style={{marginBottom: '1rem'}}>
                        <label>Status</label>
                        <input className="form-control" type="text" value={form.status} onChange={e => setForm({...form, status: e.target.value})} />
                    </div>

                            <button type="submit" className="btn btn-success">Save Record</button>
                        </form>
                        {insertResult && (
                            <div className={lert  + (insertResult.success ? 'alert-success' : 'alert-danger')} style={{marginTop: '1rem'}}>
                                {insertResult.success ? 'Record added successfully!' : 'Error: ' + insertResult.error}
                            </div>
                        )}
                    </div>
                </div>
            )}

            {activeTab === 'sql' && (
                <div className="card">
                    <div className="card-header">Local SQL Console</div>
                    <div className="card-body">
                        <div className="alert alert-info">
                            <strong>Table Available:</strong> $tableName
                        </div>
                        <textarea 
                            className="form-control" 
                            rows={5} 
                            value={query} 
                            onChange={e => setQuery(e.target.value)} 
                            placeholder="SELECT * FROM insurance_policies"
                            style={{fontFamily: 'monospace'}}
                        />
                        <button className="btn btn-primary" onClick={executeSql} style={{marginTop: '1rem'}}>Execute Query</button>
                        {results && (
                            <pre className="query-results" style={{marginTop: '1rem', backgroundColor: '#f8f9fa', padding: '1rem', borderRadius: '4px'}}>
                                {JSON.stringify(results, null, 2)}
                            </pre>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
