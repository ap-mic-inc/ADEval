async function apiCall(path, method = 'GET', body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(path, opts);
    return res.json();
}

async function fetchExperimentsApi() {
    return await apiCall('/api/experiments');
}

async function saveExperimentApi(exp) {
    return await apiCall('/api/experiments', 'POST', exp);
}

async function deleteExperimentApi(id) {
    return await fetch(`/api/experiments/${id}`, { method: 'DELETE' });
}

async function listAppsApi(apiUrl) {
    const data = await apiCall(`/api/list-apps?api_url=${encodeURIComponent(apiUrl)}`);
    return data.apps ? data.apps.map(a => typeof a === 'string' ? a : (a.name || 'Unknown')) : [];
}

async function runTestApi(payload) {
    return await apiCall('/api/run-test', 'POST', payload);
}
