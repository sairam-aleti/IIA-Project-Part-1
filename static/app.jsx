function App() {
    const [query, setQuery] = React.useState('');
    const [results, setResults] = React.useState(null);
    const [form, setForm] = React.useState({
        vehicle_mark: '',
        owner: '',
        vehicle_category: '',
        registered_on: '',
        chassis: '',
        propulsion: '',

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
        const sql = INSERT INTO vehicle_register ( + columns + ) VALUES ( + values + );
        
        const res = await fetch('/sql', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({query: sql})
        });
        const data = await res.json();
        setInsertResult(data);
        if (data.success) {
            setForm({         vehicle_mark: '',
        owner: '',
        vehicle_category: '',
        registered_on: '',
        chassis: '',
        propulsion: '',
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
                        <label>Owner Name</label>
                        <input className="form-control" type="text" value={form.owner} onChange={e => setForm({...form, owner: e.target.value})} />
                    </div>
                    <div className="form-group" style={{marginBottom: '1rem'}}>
                        <label>Vehicle Class</label>
                        <input className="form-control" type="text" value={form.vehicle_category} onChange={e => setForm({...form, vehicle_category: e.target.value})} />
                    </div>
                    <div className="form-group" style={{marginBottom: '1rem'}}>
                        <label>Registration Date</label>
                        <input className="form-control" type="text" value={form.registered_on} onChange={e => setForm({...form, registered_on: e.target.value})} />
                    </div>
                    <div className="form-group" style={{marginBottom: '1rem'}}>
                        <label>Chassis Number</label>
                        <input className="form-control" type="text" value={form.chassis} onChange={e => setForm({...form, chassis: e.target.value})} />
                    </div>
                    <div className="form-group" style={{marginBottom: '1rem'}}>
                        <label>Propulsion</label>
                        <input className="form-control" type="text" value={form.propulsion} onChange={e => setForm({...form, propulsion: e.target.value})} />
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
                            placeholder="SELECT * FROM vehicle_register"
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
