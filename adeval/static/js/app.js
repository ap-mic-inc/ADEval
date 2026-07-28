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
            mcpToken: '',
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

        // Normalize a single tool call string so 'Add(b="1", a=2)' and 'add(a=2, b=1)'
        // compare equal. Shared by the run loop and the metrics below.
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
            const args = match[2].split(',').map(a => normalizeArg(a.trim().toLowerCase())).filter(a => a);
            args.sort();
            return args.length ? `${name}(${args.join(', ')})` : name;
        };

        const toolName = (t) => t.split('(')[0].trim().toLowerCase();
        const splitTools = (s) => (s || '').split('\n').map(t => t.trim()).filter(t => t);

        // A case counts as "called a tool" only when the runner actually parsed a
        // functionCall out of the event stream. 'None' means the model answered from
        // its own knowledge; 'Error' means the request never reached the agent.
        const hasToolCall = (c) => {
            const raw = (c.actualTools || '').trim();
            return !!raw && raw !== 'None' && raw !== 'Error';
        };

        const evalStats = computed(() => {
            const cases = testCases.value;
            const total = cases.length;
            const pass = cases.filter(c => c.status === 'PASS').length;
            const fail = cases.filter(c => c.status === 'FAIL').length;
            const pending = cases.filter(c => !c.status).length;

            // Metrics are only meaningful for cases that have been run.
            const evaluated = cases.filter(c => c.status);
            const called = evaluated.filter(hasToolCall).length;

            // Accuracy is scored only against cases that declare expected tools.
            const scorable = evaluated.filter(c => splitTools(c.expectedTools).length > 0);

            let nameHit = 0;
            let argHit = 0;
            for (const c of scorable) {
                const expected = splitTools(c.expectedTools);
                const actual = splitTools(c.actualTools);

                // Subset semantics: every expected tool must appear among the actual
                // calls. Extra calls (e.g. list_containers to locate a name first) do
                // not fail the case — that is legitimate agent behaviour, not an error.
                const actualNames = new Set(actual.map(toolName));
                if (expected.every(e => actualNames.has(toolName(e)))) nameHit++;

                const actualFull = new Set(actual.map(normalizeTool));
                if (expected.every(e => actualFull.has(normalizeTool(e)))) argHit++;
            }

            const pct = (n, d) => d > 0 ? Math.round((n / d) * 100) : 0;

            return {
                total,
                pass,
                fail,
                pending,
                passRate: pct(pass, total),
                failRate: pct(fail, total),
                evaluated: evaluated.length,
                scorable: scorable.length,
                called,
                calledRate: pct(called, evaluated.length),
                nameHit,
                nameRate: pct(nameHit, scorable.length),
                argHit,
                argRate: pct(argHit, scorable.length)
            };
        });

        // --- Benchmark / radar ---------------------------------------------

        const RADAR_COLORS = [
            '#6366f1', '#f43f5e', '#10b981', '#f59e0b', '#8b5cf6', '#06b6d4',
            '#ec4899', '#84cc16'
        ];

        // Benchmark compares experiments against each other, so it is a global
        // view rather than a tab belonging to the currently selected experiment.
        const view = ref('experiment');

        const benchmark = ref({
            selected: [],
            axes: [],
            results: [],
            mcpUrl: '',
            mcpToken: '',
            isLoading: false,
            error: ''
        });

        // How each axis is computed, surfaced behind the ⓘ next to the radar so
        // a number on the chart can always be traced back to its definition.
        const showMetricHelp = ref(false);
        const METRIC_HELP = [
            { name: '工具呼叫率', how: '期望使用工具的題目中，模型實際發出工具呼叫的比例。', note: '分母只含正向題；逾時或連線失敗算沒有呼叫。' },
            { name: '函式名正確率', how: '期望的工具名稱是否全部出現在實際呼叫中。', note: '子集判定：多叫了別的工具不扣分。' },
            { name: '參數正確率', how: '期望的每個呼叫都要被滿足：工具名相同，且期望的每個參數都存在、值相等。', note: '子集判定：多帶可選參數（如 limit=50）不扣分，改由「額外參數率」揭露。' },
            { name: '呈現品質', how: 'LLM judge 依回答的組織、完整度與可讀性評分，取全題平均。', note: '只看寫得好不好，不看數字對不對——格式漂亮但資料是編的，這一軸仍會拿高分。' },
            { name: '答案正確率', how: '把回答與「實際執行期望工具所得到的真實資料」比對，由 LLM 判斷是否如實反映。', note: '與呈現品質刻意正交。曾出現呈現 98 分、正確率 0 分的案例：表格排得漂亮，整張資料卻是模型自己編的。' },
            { name: '呼叫工具次數吻合度', how: '實際呼叫次數與期望次數的接近程度，取全題平均。', note: '多叫或少叫都會低於 100%。只看次數，不看用了哪些工具或參數對不對；先探索再動作的模型會因為步數變多而降低。' },
            { name: '唯讀遵循度', how: '呼叫到的工具全部屬於 MCP 標記 readOnlyHint 的題目比例。', note: '需填入 MCP URL 才會計算；逾時與棄權不算違規。' },
            { name: '避免誤呼叫', how: '不該用工具的負向題中，模型正確棄權的比例。', note: '只有測資含負向題時才會出現這一軸。' },
            { name: '額外參數率', how: '參數答對的題目中，另外多帶了可選參數的比例。', note: '僅供參考，不計入雷達圖也不扣分——它反映風格，不是錯誤。' }
        ];

        const openBenchmark = () => {
            view.value = 'benchmark';
            // Default to comparing everything that looks like a benchmark run.
            if (!benchmark.value.selected.length) {
                benchmark.value.selected = experiments.value
                    .filter(e => e.name && e.name.includes(' @ '))
                    .map(e => e.id);
            }
            loadBenchmark();
        };

        const openExperimentView = () => { view.value = 'experiment'; };

        const toggleBenchmarkExp = (id) => {
            const idx = benchmark.value.selected.indexOf(id);
            if (idx === -1) benchmark.value.selected.push(id);
            else benchmark.value.selected.splice(idx, 1);
            loadBenchmark();
        };

        // --- 實驗矩陣：列=模型、欄=測資組 -----------------------------------
        // 一個模型跑 N 組測資就產生 N 個實驗，攤平成一排 chip 到幾十個就選不動了。
        // 拆成矩陣後，「看某模型的難度梯度」是選一整列，「跨模型比同一組」是選一整欄，
        // 剛好對應實際會做的兩種比較。
        const benchmarkGrid = computed(() => {
            const runs = experiments.value.filter(e => e.name && e.name.includes(' @ '));
            const datasets = [], models = [], cell = {};
            for (const e of runs) {
                const [ds, model] = e.name.split(' @ ');
                if (!datasets.includes(ds)) datasets.push(ds);
                if (!models.includes(model)) models.push(model);
                cell[`${model}||${ds}`] = e.id;
            }
            // 難度組照 easy→medium→hard 排，其餘維持出現順序
            const rank = d => ['easy', 'medium', 'hard'].findIndex(k => d.endsWith(k));
            datasets.sort((a, b) => {
                const ra = rank(a), rb = rank(b);
                if (ra !== -1 && rb !== -1) return ra - rb;
                if (ra !== -1) return -1;
                if (rb !== -1) return 1;
                return 0;
            });
            return { datasets, models, cell, total: runs.length };
        });

        const isPicked = (id) => !!id && benchmark.value.selected.includes(id);

        const cellId = (model, ds) => benchmarkGrid.value.cell[`${model}||${ds}`];

        const applySelection = (ids, on) => {
            const set = new Set(benchmark.value.selected);
            ids.filter(Boolean).forEach(id => on ? set.add(id) : set.delete(id));
            benchmark.value.selected = [...set];
            loadBenchmark();
        };

        const rowIds = (model) => benchmarkGrid.value.datasets.map(d => cellId(model, d));
        const colIds = (ds) => benchmarkGrid.value.models.map(m => cellId(m, ds));

        // 整列／整欄的按鈕是切換：全選中就取消，否則補齊
        const toggleRow = (model) => {
            const ids = rowIds(model).filter(Boolean);
            applySelection(ids, !ids.every(isPicked));
        };
        const toggleCol = (ds) => {
            const ids = colIds(ds).filter(Boolean);
            applySelection(ids, !ids.every(isPicked));
        };
        const rowPicked = (model) => {
            const ids = rowIds(model).filter(Boolean);
            return ids.length > 0 && ids.every(isPicked);
        };
        const colPicked = (ds) => {
            const ids = colIds(ds).filter(Boolean);
            return ids.length > 0 && ids.every(isPicked);
        };
        const selectAllRuns = () => applySelection(
            Object.values(benchmarkGrid.value.cell), true);
        const clearRuns = () => { benchmark.value.selected = []; loadBenchmark(); };

        const loadBenchmark = async () => {
            if (!benchmark.value.selected.length) {
                benchmark.value.results = [];
                return;
            }
            benchmark.value.isLoading = true;
            benchmark.value.error = '';
            try {
                const data = await fetchMetricsApi({
                    expIds: benchmark.value.selected,
                    mcpUrl: benchmark.value.mcpUrl || undefined,
                    mcpToken: benchmark.value.mcpToken || undefined
                });
                if (data.detail) throw new Error(data.detail);
                benchmark.value.axes = data.axes || [];
                benchmark.value.results = data.results || [];
            } catch (e) {
                benchmark.value.error = e.message || '無法取得指標';
                benchmark.value.results = [];
            } finally {
                benchmark.value.isLoading = false;
            }
        };

        // Axes are only drawn when at least one selected model has a value for
        // them -- read-only compliance is absent unless an MCP URL was supplied.
        const radarAxes = computed(() => {
            const present = new Set();
            for (const r of benchmark.value.results) {
                Object.keys(r.radar || {}).forEach(k => present.add(k));
            }
            return benchmark.value.axes.filter(a => present.has(a));
        });

        // The viewBox is wider than tall so the axis labels, which stick out
        // horizontally, stay inside it -- the SVG must not need overflow:visible
        // or the polygon bleeds over the card it sits in.
        const RADAR_W = 620;
        const RADAR_H = 440;
        const RADAR_CX = RADAR_W / 2;
        const RADAR_CY = RADAR_H / 2;
        const RADAR_R = 150;
        const RADAR_LABEL_GAP = 34;

        const radarPoint = (axisIndex, radius) => {
            const n = radarAxes.value.length || 1;
            // Start at 12 o'clock and go clockwise.
            const angle = (Math.PI * 2 * axisIndex) / n - Math.PI / 2;
            return {
                x: RADAR_CX + radius * Math.cos(angle),
                y: RADAR_CY + radius * Math.sin(angle)
            };
        };

        const radarValuePoint = (axisIndex, value) =>
            radarPoint(axisIndex, (Math.max(0, Math.min(100, value)) / 100) * RADAR_R);

        const radarRings = computed(() => {
            const n = radarAxes.value.length;
            if (n < 3) return [];
            return [20, 40, 60, 80, 100].map(pct => ({
                pct,
                labelY: RADAR_CY - (pct / 100) * RADAR_R,
                points: radarAxes.value
                    .map((_, i) => radarValuePoint(i, pct))
                    .map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`)
                    .join(' ')
            }));
        });

        // Clicking an axis label focuses that metric: the spoke highlights and a
        // breakdown of every model's score on it appears beside the chart.
        const selectedAxis = ref(null);
        const selectAxis = (label) => {
            selectedAxis.value = selectedAxis.value === label ? null : label;
        };
        // A stale selection (axis no longer present) would leave an empty panel.
        watch(radarAxes, (axes) => {
            if (selectedAxis.value && !axes.includes(selectedAxis.value)) {
                selectedAxis.value = null;
            }
        });

        const radarSpokes = computed(() =>
            radarAxes.value.map((label, i) => {
                const end = radarValuePoint(i, 100);
                const labelPos = radarPoint(i, RADAR_R + RADAR_LABEL_GAP);
                const dx = labelPos.x - RADAR_CX;
                return {
                    label,
                    active: selectedAxis.value === label,
                    x2: end.x, y2: end.y,
                    lx: labelPos.x, ly: labelPos.y,
                    anchor: Math.abs(dx) < 8 ? 'middle' : (dx > 0 ? 'start' : 'end')
                };
            })
        );

        // 一個軸「沒有資料」與「得 0 分」是兩回事：純負向資料集沒有工具呼叫率／
        // 函式名／參數正確率可言，compute_metrics 因此回傳 None，radar_profile 也
        // 已把該軸略去。若在前端用 ?? 0 補上，畫出來會像是那組表現極差。
        const hasAxis = (series, axis) => typeof series?.radar?.[axis] === 'number';

        const radarSeries = computed(() =>
            benchmark.value.results.map((r, idx) => {
                const color = RADAR_COLORS[idx % RADAR_COLORS.length];
                // 缺值的軸不產生頂點，多邊形直接跳過它連向下一個有資料的軸。
                const pts = radarAxes.value.map((axis, i) => {
                    const present = typeof r.radar?.[axis] === 'number';
                    const value = present ? r.radar[axis] : null;
                    const p = radarValuePoint(i, present ? value : 0);
                    return { x: p.x, y: p.y, axis, value, present,
                             active: selectedAxis.value === axis };
                });
                const values = pts.filter(p => p.present).map(p => p.value);
                const avg = values.length ? values.reduce((s, v) => s + v, 0) / values.length : 0;
                return {
                    id: r.id,
                    label: r.appName || r.name,
                    name: r.name,
                    color,
                    avg: Math.round(avg * 10) / 10,
                    metrics: r.metrics,
                    radar: r.radar,
                    dots: pts.filter(p => p.present),
                    points: pts.filter(p => p.present)
                        .map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
                };
            })
        );

        const radarBest = computed(() => {
            const best = {};
            for (const axis of radarAxes.value) {
                const vals = radarSeries.value.filter(s => hasAxis(s, axis)).map(s => s.radar[axis]);
                if (vals.length) best[axis] = Math.max(...vals);
            }
            return best;
        });

        // Ranking of every model on the focused axis, best first.
        // 沒有這個指標的實驗直接不列入，排 0% 會誤導成墊底。
        const axisDetail = computed(() => {
            const axis = selectedAxis.value;
            if (!axis) return null;
            const rows = radarSeries.value
                .filter(s => hasAxis(s, axis))
                .map(s => ({ label: s.label, name: s.name, color: s.color, value: s.radar[axis] }))
                .sort((a, b) => b.value - a.value);
            const best = rows.length ? rows[0].value : 0;
            rows.forEach(r => { r.isBest = r.value === best; });
            const omitted = radarSeries.value.filter(s => !hasAxis(s, axis))
                .map(s => s.name || s.label);
            return { axis, rows, omitted };
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
                    mcpToken: genConfig.value.mcpToken || undefined,
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
            view.value = 'experiment';
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

            // normalizeTool is shared with evalStats so the live run and the
            // reported metrics cannot drift apart.

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
            view, openBenchmark, openExperimentView,
            benchmark, toggleBenchmarkExp, loadBenchmark,
            benchmarkGrid, isPicked, cellId, toggleRow, toggleCol,
            rowPicked, colPicked, selectAllRuns, clearRuns,
            showMetricHelp, METRIC_HELP,
            radarAxes, radarRings, radarSpokes, radarSeries, radarBest,
            selectedAxis, selectAxis, axisDetail,
            radarW: RADAR_W, radarH: RADAR_H, radarCx: RADAR_CX, radarCy: RADAR_CY,
            toggleTheme, toggleSidebar, fetchApps, addCase, removeCase, runSingle, runAll, runComparison,
            handleFileUpload, exportQuestionBank, exportResults,
            createNewExperiment, loadExperiment, saveCurrentExperiment, deleteExperiment, copyTrace
        };
    }
}).mount('#app');
