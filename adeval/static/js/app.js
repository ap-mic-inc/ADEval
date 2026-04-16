const { createApp, ref, onMounted, computed, watch } = Vue;

createApp({
    setup() {
        const tab = ref('single');
        const isSidebarOpen = ref(true);
        const isDark = ref(localStorage.getItem('theme') === 'dark');
        const isFetching = ref(false);
        const saveStatus = ref('synced'); // 'synced', 'saving', 'error'
        const config = ref({ 
            apiUrl: 'http://localhost:8000', 
            userId: 'eval-user', 
            verifyArgs: false,
            enableJudge: false
        });
        const apps = ref(['MathAgent']);
        const experiments = ref([]);
        const currentExp = ref(null);
        const isRunning = ref(false);
        const isComparing = ref(false);
        const isGenerating = ref(false);
        const showGenerateModal = ref(false);
        const genConfig = ref({
            mcpUrl: '',
            num: 5,
            tools: null,
            desc: '',
            lang: 'zh-tw'
        });
        const progress = ref(0);
        const single = ref({ appName: '', q: '1234 + 5678 = ?', state: '{}', result: null });
        const compare = ref({
            agent1: '',
            agent2: '',
            query: '',
            events1: [],
            events2: [],
            usage1: null,
            usage2: null
        });

        const testCases = computed(() => currentExp.value ? currentExp.value.testCases : []);

        const evalStats = computed(() => {
            const cases = testCases.value;
            const total = cases.length;
            const pass = cases.filter(c => c.status === 'PASS').length;
            const fail = cases.filter(c => c.status === 'FAIL').length;
            const pending = cases.filter(c => !c.status).length;
            
            return {
                total,
                pass,
                fail,
                pending,
                passRate: total > 0 ? Math.round((pass / total) * 100) : 0,
                failRate: total > 0 ? Math.round((fail / total) * 100) : 0
            };
        });

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

        const toggleSidebar = () => {
            isSidebarOpen.value = !isSidebarOpen.value;
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
            try {
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
            } catch (e) {
                console.error("Failed to create experiment", e);
                alert("Failed to create experiment.");
            }
        };

        const generateExperiment = async () => {
            if (!genConfig.value.mcpUrl) return alert("Please enter MCP URL");
            isGenerating.value = true;
            try {
                const newExp = await generateExperimentApi({
                    mcpUrl: genConfig.value.mcpUrl,
                    num: genConfig.value.num,
                    tools: genConfig.value.tools,
                    desc: genConfig.value.desc,
                    lang: genConfig.value.lang,
                    appName: single.value.appName
                });
                await fetchExperiments();
                loadExperiment(newExp);
                showGenerateModal.value = false;
                alert(`Successfully generated ${newExp.testCases.length} cases!`);
            } catch (e) {
                console.error("Generation failed", e);
                alert("Generation failed: " + (e.detail || e.message || "Unknown error"));
            } finally {
                isGenerating.value = false;
            }
        };

        const loadExperiment = (exp) => {
            currentExp.value = JSON.parse(JSON.stringify(exp));
            config.value.userId = exp.userId || 'eval-user';
            config.value.apiUrl = exp.apiUrl || 'http://localhost:8000';
            single.value.appName = exp.testCases[0]?.appName || apps.value[0];
            
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
                const match = t.match(/^([^(]+)\((.*)\)$/);
                if (!match) return t.trim().toLowerCase();
                const name = match[1].trim().toLowerCase();
                const normalizeArg = (a) => {
                    const eqIdx = a.indexOf('=');
                    if (eqIdx === -1) return a;
                    const k = a.slice(0, eqIdx).trim();
                    const v = a.slice(eqIdx + 1).trim().replace(/^["']|["']$/g, '');
                    return `${k}=${v}`;
                };
                const args = (match[2] || '').split(',')
                    .map(a => normalizeArg(a.trim().toLowerCase()))
                    .filter(a => a)
                    .sort()
                    .join(', ');
                return `${name}(${args})`;
            };

            try {
                for (let i = 0; i < cases.length; i++) {
                    const c = cases[i];
                    try {
                        const payload = {
                            eval_req: {
                                app_name: c.appName, 
                                question: c.q, 
                                state: c.state,
                                api_url: config.value.apiUrl,
                                user_id: config.value.userId 
                            },
                            judge: config.value.enableJudge,
                            expected_tools: c.expectedTools
                        };

                        const data = await runTestApi(payload);
                        
                        const actualToolsStr = data.tools || "None";
                        const actualToolsList = actualToolsStr.split('\n').map(t => normalizeTool(t));

                        const expectedToolsList = (c.expectedTools || "").split('\n').map(t => t.trim()).filter(t => t);
                        
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
                        c.judgeScore = data.judgeScore;
                        c.judgeExplanation = data.judgeExplanation;
                        c.status = (toolPass && (c.expectedAnswer ? (data.answer || "").toLowerCase().includes(c.expectedAnswer.toLowerCase()) : true)) ? 'PASS' : 'FAIL';
                    } catch (e) { 
                        c.status = 'FAIL'; 
                        c.actualAnswer = e.message; 
                    }
                    progress.value = Math.round(((i + 1) / cases.length) * 100);
                    await saveCurrentExperiment();
                }
            } finally {
                isRunning.value = false;
            }
        };

        const handleFileUpload = (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = async (ev) => {
                const lines = ev.target.result.split('\n');
                const newCases = lines.slice(1).filter(l => l.trim()).map(line => {
                    const parts = line.split(/,(?=(?:(?:[^"]*"){2})*[^"]*$)/);
                    const clean = (s) => s ? s.trim().replace(/^"|"$/g, '').replace(/""/g, '"').trim() : '';
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
                `"${c.appName}","${(c.q || '').replace(/"/g, '""')}","${(c.state || '{}').replace(/"/g, '""')}","${(c.expectedTools || '').replace(/"/g, '""')}","${(c.expectedAnswer || '').replace(/"/g, '""')}"`
            );
            const now = new Date().toISOString().replace(/[:T]/g, '_').slice(0, 19);
            downloadCSV(`question_bank_${currentExp.value.name}_${now}.csv`, headers, rows);
        };

        const exportResults = () => {
            if (!currentExp.value) return;
            const headers = "App Name,Question,Session State,Expected Tools,Expected Answer,Actual Tools,Actual Answer,Status,Judge Score,Judge Reason\n";
            const rows = currentExp.value.testCases.map(c =>
                `"${c.appName}","${(c.q || '').replace(/"/g, '""')}","${(c.state || '{}').replace(/"/g, '""')}","${(c.expectedTools || '').replace(/"/g, '""')}","${(c.expectedAnswer || '').replace(/"/g, '""')}","${(c.actualTools || '').replace(/"/g, '""')}","${(c.actualAnswer || '').replace(/"/g, '""')}","${c.status || ''}","${c.judgeScore || ''}","${(c.judgeExplanation || '').replace(/"/g, '""')}"`
            );
            const now = new Date().toISOString().replace(/[:T]/g, '_').slice(0, 19);
            downloadCSV(`eval_results_${currentExp.value.name}_${now}.csv`, headers, rows);
        };

        const copyTrace = (data) => {
            navigator.clipboard.writeText(JSON.stringify(data, null, 4));
            alert('Trace copied to clipboard!');
        };

        const runComparison = async () => {
            if (!compare.value.agent1 || !compare.value.agent2 || !compare.value.query) return; 
            isComparing.value = true;
            compare.value.events1 = [];
            compare.value.events2 = [];
            
            const runAgent = async (agentName, eventsKey, usageKey) => {
                try {
                    const data = await runTestApi({
                        app_name: agentName,
                        question: compare.value.query,
                        state: '{}',
                        api_url: config.value.apiUrl,
                        user_id: config.value.userId
                    });
                    compare.value[eventsKey] = data.raw_response;
                    const lastEvent = [...data.raw_response].reverse().find(e => e.usageMetadata);
                    if (lastEvent) compare.value[usageKey] = lastEvent.usageMetadata;
                } catch (e) { console.error(e); }
            };

            await Promise.all([
                runAgent(compare.value.agent1, 'events1', 'usage1'),
                runAgent(compare.value.agent2, 'events2', 'usage2')
            ]);
            isComparing.value = false;
        };

        onMounted(() => {
            fetchExperiments();
            updateThemeClass(isDark.value);
        });

        return { 
            tab, isSidebarOpen, isDark, isFetching, saveStatus, config, apps, experiments, currentExp, testCases, evalStats, single, isRunning, isComparing, progress, compare,
            isGenerating, showGenerateModal, genConfig, generateExperiment,
            toggleTheme, toggleSidebar, fetchApps, addCase, removeCase, runSingle, runAll, runComparison,
            handleFileUpload, exportQuestionBank, exportResults,
            createNewExperiment, loadExperiment, saveCurrentExperiment, deleteExperiment, copyTrace
        };
    }
}).mount('#app');
