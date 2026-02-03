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

async function runSseApi(apiUrl, payload, onEvent) {
    const res = await fetch('/api/run-sse-proxy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...payload, apiUrl })
    });

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();

        for (const line of lines) {
            if (line.startsWith('data: ')) {
                try {
                    const data = JSON.parse(line.slice(6));
                    onEvent(data);
                } catch (e) {
                    console.error("Failed to parse SSE data", e);
                }
            }
        }
    }
}
