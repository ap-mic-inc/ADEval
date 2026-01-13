const { createApp, ref, onMounted, computed, watch } = Vue;

createApp({
    setup() {
        const tab = ref('single');
        const isDark = ref(localStorage.getItem('theme') === 'dark');
        const isFetching = ref(false);
        const saveStatus = ref('synced'); // 'synced', 'saving', 'error'
        const config = ref({ apiUrl: 'http://localhost:8000', userId: 'eval-user', verifyArgs: false });
        const apps = ref(['MathAgent']);
        const experiments = ref([]);
        const currentExp = ref(null);
        const isRunning = ref(false);
        const progress = ref(0);
        const single = ref({ appName: '', q: '1234 + 5678 = ?', state: '{}', result: null });

        const testCases = computed(() => currentExp.value ? currentExp.value.testCases : []);

        const updateThemeClass = (val) => {
            if (val) {
                document.documentElement.classList.add('dark');
            } else {
                document.documentElement.classList.remove('dark');
            }
        };

        const toggleTheme = () => {
            isDark.value = !isDark.value;
            localStorage.setItem('theme', isDark.value ? 'dark' : 'light');
            updateThemeClass(isDark.value);
        };

        const fetchExperiments = async () => {
            try {
                const data = await fetchExperimentsApi();
                experiments.value = data;
                if (data.length && !currentExp.value) {
                    loadExperiment(data[0]);
                }
            } catch (e) {
                console.error("Failed to fetch experiments", e);
            }
        };

        const createNewExperiment = async () => {
            const newExp = {
                id: 'exp_' + Math.random().toString(36).substr(2, 9),
                name: 'New Experiment ' + (experiments.value.length + 1),
                userId: config.value.userId,
                apiUrl: config.value.apiUrl,
                testCases: [
                    { appName: apps.value[0] || 'MathAgent', q: '1+1=?', state: '{}', expectedTools: 'add', expectedAnswer: '2', status: null, rawResponse: null }
                ]
            };
            await saveExperimentApi(newExp);
            await fetchExperiments();
            loadExperiment(newExp);
        };

        const loadExperiment = (exp) => {
            currentExp.value = JSON.parse(JSON.stringify(exp));
            config.value.userId = exp.userId || 'eval-user';
            config.value.apiUrl = exp.apiUrl || 'http://localhost:8000';
            single.value.appName = exp.testCases[0]?.appName || apps.value[0];
            single.value.state = '{}';
            fetchApps();
        };

        const saveCurrentExperiment = async () => {
            if (!currentExp.value) return;
            saveStatus.value = 'saving';
            try {
                currentExp.value.userId = config.value.userId;
                currentExp.value.apiUrl = config.value.apiUrl;
                await saveExperimentApi(currentExp.value);
                const idx = experiments.value.findIndex(e => e.id === currentExp.value.id);
                if (idx !== -1) {
                    experiments.value[idx].name = currentExp.value.name;
                    experiments.value[idx].userId = currentExp.value.userId;
                    experiments.value[idx].apiUrl = currentExp.value.apiUrl;
                }
                saveStatus.value = 'synced';
            } catch (e) {
                console.error("Save failed", e);
                saveStatus.value = 'error';
            }
        };

        const deleteExperiment = async (id) => {
            if (confirm('Permanently delete this experiment?')) {
                await deleteExperimentApi(id);
                if (currentExp.value?.id === id) currentExp.value = null;
                await fetchExperiments();
            }
        };

        const fetchApps = async () => {
            isFetching.value = true;
            try {
                const fetchedApps = await listAppsApi(config.value.apiUrl);
                apps.value = fetchedApps;
                if (apps.value.length && !single.value.appName) single.value.appName = apps.value[0];
            } catch (e) { 
                console.error("Fetch apps failed", e); 
            } finally { 
                setTimeout(() => isFetching.value = false, 500); 
            } 
        };

        const addCase = () => {
            currentExp.value.testCases.push({ appName: apps.value[0], q: '', state: '{}', expectedTools: '', expectedAnswer: '', status: null, rawResponse: null });
            saveCurrentExperiment();
        };

        const removeCase = (idx) => {
            currentExp.value.testCases.splice(idx, 1);
            saveCurrentExperiment();
        };

        const runSingle = async () => {
            isRunning.value = true;
            try {
                const data = await runTestApi({
                    app_name: single.value.appName,
                    question: single.value.q,
                    state: single.value.state,
                    api_url: config.value.apiUrl,
                    user_id: config.value.userId
                });
                single.value.result = data;
            } finally { isRunning.value = false; }
        };

        const runAll = async () => {
            if (!currentExp.value) return;
            isRunning.value = true;
            progress.value = 0;
            const cases = currentExp.value.testCases;

            const normalizeTool = (t) => {
                const match = t.match(/^([^(]+)\(.*\)$/);
                if (!match) return t.trim().toLowerCase();
                const name = match[1].trim().toLowerCase();
                const args = match[2].split(',')
                    .map(a => a.trim().toLowerCase())
                    .filter(a => a)
                    .sort()
                    .join(', ');
                return `${name}(${args})`;
            };

            for (let i = 0; i < cases.length; i++) {
                const c = cases[i];
                try {
                    const data = await runTestApi({ 
                        app_name: c.appName, 
                        question: c.q, 
                        state: c.state,
                        api_url: config.value.apiUrl,
                        user_id: config.value.userId 
                    });
                    
                    const actualToolsStr = data.tools || "None";
                    const actualToolsList = actualToolsStr.split('\n').map(t => normalizeTool(t));

                    const expectedToolsInput = (c.expectedTools || "");
                    const expectedToolsList = expectedToolsInput.split('\n').filter(s => s.trim());
                    
                    let toolPass = true;
                    for (const et of expectedToolsList) {
                        if (config.value.verifyArgs) {
                            const normalizedEt = normalizeTool(et);
                            if (!actualToolsList.includes(normalizedEt)) {
                                toolPass = false;
                                break;
                            }
                        } else {
                            const toolNameOnly = et.split('(')[0].trim().toLowerCase();
                            const exists = actualToolsList.some(at => at.startsWith(toolNameOnly + '(') || at === toolNameOnly);
                            if (!exists) {
                                toolPass = false;
                                break;
                            }
                        }
                    }
                    
                    c.actualTools = data.tools;
                    c.actualAnswer = data.answer;
                    c.rawResponse = data.raw_response;
                    c.showTrace = false;
                    c.status = (toolPass && (c.expectedAnswer ? (data.answer || "").toLowerCase().includes(c.expectedAnswer.toLowerCase()) : true)) ? 'PASS' : 'FAIL';
                } catch (e) { 
                    c.status = 'FAIL'; 
                    c.actualTools = "Error";
                    c.actualAnswer = e.message; 
                } 
                progress.value = Math.round(((i + 1) / cases.length) * 100);
            }
            await saveCurrentExperiment();
            isRunning.value = false;
        };

        const handleFileUpload = (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = async (ev) => {
                const lines = ev.target.result.split('\n');
                const newCases = lines.slice(1).filter(l => l.trim()).map(line => {
                    const parts = line.match(/(".*?"|[^",\s]+)(?=\s*,|\s*$)/g) || line.split(',');
                    const clean = (s) => s ? s.replace(/^"|"$/g, '').trim() : '';
                    return {
                        appName: clean(parts[0]) || apps.value[0],
                        q: clean(parts[1]) || '',
                        state: clean(parts[2]) || '{}',
                        expectedTools: clean(parts[3]) || '',
                        expectedAnswer: clean(parts[4]) || '',
                        status: null,
                        rawResponse: null
                    };
                });
                currentExp.value.testCases = newCases;
                await saveCurrentExperiment();
            };
            reader.readAsText(file);
        };

        const downloadCSV = (filename, headers, rows) => {
            const content = headers + rows.join("\n");
            const blob = new Blob([content], {type: 'text/csv;charset=utf-8;'});
            const link = document.createElement("a");
            link.setAttribute("href", URL.createObjectURL(blob));
            link.setAttribute("download", filename);
            link.click();
        };

        const exportQuestionBank = () => {
            if (!currentExp.value) return;
            const headers = "App Name,Question,Session State,Expected Tools,Expected Answer\n";
            const rows = currentExp.value.testCases.map(c => 
                `"${c.appName}","${c.q}","${(c.state || '{}').replace(/"/g, '""')}","${c.expectedTools}","${c.expectedAnswer || ''}"`
            );
            const now = new Date().toISOString().replace(/[:T]/g, '_').slice(0, 19);
            downloadCSV(`question_bank_${currentExp.value.name}_${now}.csv`, headers, rows);
        };

        const exportResults = () => {
            if (!currentExp.value) return;
            const headers = "App Name,Question,Session State,Expected Tools,Expected Answer,Actual Tools,Actual Answer,Status\n";
            const rows = currentExp.value.testCases.map(c => 
                `"${c.appName}","${c.q}","${(c.state || '{}').replace(/"/g, '""')}","${c.expectedTools}","${c.expectedAnswer || ''}","${c.actualTools || ''}","${c.actualAnswer || ''}","${c.status || ''}"`
            );
            const now = new Date().toISOString().replace(/[:T]/g, '_').slice(0, 19);
            downloadCSV(`eval_results_${currentExp.value.name}_${now}.csv`, headers, rows);
        };

        const copyTrace = (data) => {
            navigator.clipboard.writeText(JSON.stringify(data, null, 4));
            alert('Trace copied to clipboard!');
        };

        onMounted(() => {
            fetchExperiments();
            if (!localStorage.getItem('theme') && window.matchMedia('(prefers-color-scheme: dark)').matches) {
                isDark.value = true;
            }
            updateThemeClass(isDark.value);
        });

        return { 
            tab, isDark, isFetching, saveStatus, config, apps, experiments, currentExp, testCases, single, isRunning, progress, 
            toggleTheme, fetchApps, addCase, removeCase, runSingle, runAll, 
            handleFileUpload, exportQuestionBank, exportResults,
            createNewExperiment, loadExperiment, saveCurrentExperiment, deleteExperiment, copyTrace
        };
    }
}).mount('#app');
