function App() {
    const [query, setQuery] = React.useState('');
    const [results, setResults] = React.useState(null);

    const execute = async () => {
        const res = await fetch('/sql', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({query})
        });
        setResults(await res.json());
    };

    return (
        <div className="container" style={{padding: '2rem'}}>
            <header className="page-header">
                <h1>{$node.toUpperCase()} Agency - Local Interface</h1>
            </header>
            <div className="card">
                <div className="card-header">Local SQL Console</div>
                <div className="card-body">
                    <textarea 
                        className="form-control" 
                        rows={5} 
                        value={query} 
                        onChange={e => setQuery(e.target.value)} 
                        placeholder="SELECT * FROM table..."
                    />
                    <button className="btn btn-primary" onClick={execute} style={{marginTop: '1rem'}}>Execute</button>
                    {results && (
                        <pre className="query-results" style={{marginTop: '1rem'}}>
                            {JSON.stringify(results, null, 2)}
                        </pre>
                    )}
                </div>
            </div>
        </div>
    );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
