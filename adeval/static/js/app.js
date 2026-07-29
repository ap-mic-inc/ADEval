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

        // --- 匯出獨立 HTML ------------------------------------------------
        // 產生一份不依賴本服務的報告：資料內嵌成 JSON，雷達圖與表格由檔案內的
        // 一小段 JS 依勾選狀態重繪。畫面上的雷達圖靠 Tailwind class 上色，複製
        // DOM 會掉樣式，所以這裡重新產生純 SVG，顏色全部寫成 inline 屬性。
        // 收到檔案的人不需要這台 server，也能自己篩選要比較哪幾個實驗。
        const exportBenchmarkHtml = () => {
            const series = radarSeries.value;
            const axes = radarAxes.value;
            if (!series.length) return;

            const payload = {
                axes,
                stamp: new Date().toLocaleString('zh-TW'),
                series: series.map(s => ({
                    id: s.id, label: s.label, name: s.name,
                    color: s.color, avg: s.avg, radar: s.radar,
                })),
                geom: { w: RADAR_W, h: RADAR_H, cx: RADAR_CX, cy: RADAR_CY, r: RADAR_R },
            };

            const html = `<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ADEval Benchmark — ${payload.stamp}</title>
<style>
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;padding:40px 24px;background:#0f172a;color:#e2e8f0;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang TC","Noto Sans TC",sans-serif}
.wrap{max-width:1400px;margin:0 auto}
h1{font-size:22px;font-weight:900;margin:0 0 4px}
.sub{color:#64748b;font-size:12px;font-weight:700;margin-bottom:24px}
.card{background:#1e293b;border:2px solid #334155;border-radius:24px;padding:24px;margin-bottom:20px}
.card.flush{padding:0;overflow:hidden}
.bar{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:14px}
.bar h2{font-size:10px;font-weight:900;color:#818cf8;text-transform:uppercase;letter-spacing:.12em;margin:0}
.count{font-size:10px;font-weight:900;color:#64748b}
.bar button{background:none;border:none;color:#64748b;font:inherit;font-size:10px;font-weight:900;
  text-transform:uppercase;letter-spacing:.12em;cursor:pointer;padding:0}
.bar button:hover{color:#818cf8}
.chips{overflow-x:auto}
.grid{border-collapse:separate;border-spacing:5px;font-size:11px}
.grid th{font-weight:900;white-space:nowrap;padding:0}
.grid thead th{font-size:10px;color:#64748b;cursor:pointer;text-align:center}
.grid thead th:hover,.grid thead th.on{color:#818cf8}
.grid tbody th{text-align:left;color:#94a3b8;cursor:pointer;padding-right:10px}
.grid tbody th:hover,.grid tbody th.on{color:#818cf8}
.cell{width:30px;height:30px;border-radius:9px;border:2px solid #334155;background:#0f172a;
  cursor:pointer;padding:0;transition:border-color .15s;color:transparent;font-size:11px}
.cell:hover{border-color:#6366f1}
.cell.on{color:#fff;border-color:currentColor}
.gap{display:inline-block;width:30px;height:30px;border-radius:9px;border:2px dashed #1e293b}
.chart{display:flex;gap:32px;align-items:center;flex-wrap:wrap}
svg{width:100%;max-width:620px;height:auto;flex:1 1 380px}
.legend{flex:1 1 280px;display:flex;flex-direction:column;gap:10px;min-width:0}
.item{display:flex;align-items:center;gap:12px;border:2px solid #334155;border-radius:16px;padding:12px 16px}
.dot{width:12px;height:12px;border-radius:50%;flex-shrink:0}
.meta{flex:1;min-width:0}
.label{font-weight:900;font-size:13px}
.name{color:#64748b;font-size:10px;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.avg{font-size:20px;font-weight:900;flex-shrink:0}
.scroll{overflow-x:auto}
table{border-collapse:collapse;font-size:13px;min-width:100%;width:max-content}
th,td{padding:14px 18px;text-align:right;white-space:nowrap}
thead{background:#172033}
thead th{color:#64748b;font-size:10px;font-weight:900;text-transform:uppercase;letter-spacing:.1em}
tbody tr{border-top:1px solid #334155}
tbody th{text-align:left;font-weight:900;color:#cbd5e1}
/* 指標名固定在左側，橫向捲動時仍看得到自己在讀哪一列 */
thead th:first-child,tbody th{position:sticky;left:0;z-index:1;background:#1e293b}
thead th:first-child{background:#172033;text-align:left}
td{font-variant-numeric:tabular-nums;font-weight:700;color:#94a3b8}
td.best{color:#34d399;font-weight:900}
td.na{color:#475569}
.ds2{font-size:9px;font-weight:700;color:#64748b;text-transform:none;letter-spacing:normal;margin-top:2px}
tr.sum{border-top:2px solid #475569;background:#172033}
tr.sum th{background:#172033}
tr.sum td{font-weight:900;font-size:15px}
.foot{color:#475569;font-size:11px;font-weight:700;padding:14px 18px;border-top:1px solid #334155}
.empty{color:#64748b;font-size:13px;font-weight:700;padding:40px;text-align:center}
#radar text{cursor:pointer}
.rank{border:2px solid #3730a3;border-radius:16px;overflow:hidden}
.rank .hd{display:flex;align-items:center;justify-content:space-between;
  background:#1e1b4b;padding:12px 18px}
.rank .hd b{color:#a5b4fc;font-size:13px;font-weight:900}
.rank .hd button{background:none;border:none;color:#64748b;font:inherit;font-size:10px;
  font-weight:900;text-transform:uppercase;letter-spacing:.1em;cursor:pointer}
.rank .hd button:hover{color:#f43f5e}
.rank .row{display:flex;align-items:center;gap:12px;padding:11px 18px;border-top:1px solid #334155}
.rank .no{width:20px;color:#475569;font-size:11px;font-weight:900}
.rank .val{font-family:ui-monospace,monospace;font-weight:900;font-size:13px;
  width:58px;text-align:right}
.rank .omit{padding:11px 18px;border-top:1px solid #334155;color:#475569;
  font-size:10px;font-weight:700;line-height:1.6}
tbody tr{cursor:pointer}
tbody tr.on{background:#1e1b4b}
tbody tr.on th{background:#1e1b4b;color:#a5b4fc}
@media print{
  body{background:#fff;color:#000}.card{background:#fff;border-color:#ddd}
  .bar,.chips{display:none}thead th:first-child,tbody th{background:#fff}
}
</style></head><body><div class="wrap">
<h1>效能雷達圖 — MCP 工具使用能力</h1>
<div class="sub">所有軸皆為 0–100%，越外圈越好　·　匯出於 ${payload.stamp}</div>

<div class="card">
  <div class="bar">
    <h2>顯示哪些實驗</h2>
    <span class="count" style="color:#475569">點格子選單一　·　點模型名選整列　·　點測資名選整欄</span>
    <span class="count" id="count"></span>
    <button id="all">全選</button>
    <button id="none">清除</button>
  </div>
  <div class="chips"><table class="grid" id="grid"></table></div>
</div>

<div class="card"><div class="chart">
  <svg id="radar" viewBox="0 0 ${RADAR_W} ${RADAR_H}" preserveAspectRatio="xMidYMid meet"></svg>
  <div class="legend" id="legend"></div>
</div></div>

<div class="card flush">
  <div class="scroll"><table id="table"></table></div>
  <div class="foot">綠色為該指標最佳值　·　「—」表示該實驗沒有這項指標（例如純負向資料集沒有工具呼叫率）</div>
</div>
</div>

<script>
const DATA = ${JSON.stringify(payload)};
const on = new Set(DATA.series.map(s => s.id));
let focused = null;
const g = DATA.geom;
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const pt = (i, r, n) => {
  const a = Math.PI * 2 * i / (n || 1) - Math.PI / 2;
  return [g.cx + Math.cos(a) * r, g.cy + Math.sin(a) * r];
};

function render() {
  const shown = DATA.series.filter(s => on.has(s.id));
  // 只保留至少一個選取實驗有資料的軸，否則畫出來會有空軸
  const axes = DATA.axes.filter(a => shown.some(s => typeof s.radar[a] === 'number'));
  const n = axes.length;

  document.getElementById('count').textContent = \`已選 \${shown.length} / \${DATA.series.length}\`;
  document.querySelectorAll('.cell').forEach(c => {
    const picked = on.has(c.dataset.id);
    c.classList.toggle('on', picked);
    c.style.background = picked ? c.dataset.color : '';
    c.style.borderColor = picked ? c.dataset.color : '';
  });
  document.querySelectorAll('.grid tbody th').forEach(th =>
    th.classList.toggle('on', GRID.models[th.dataset.model].every(id => on.has(id))));
  document.querySelectorAll('.grid thead th[data-ds]').forEach(th =>
    th.classList.toggle('on', GRID.datasets[th.dataset.ds].every(id => on.has(id))));

  const svg = document.getElementById('radar');
  if (!n) {
    svg.innerHTML = '';
    document.getElementById('legend').innerHTML = '<div class="empty">請至少選擇一個實驗</div>';
    document.getElementById('table').innerHTML = '';
    return;
  }

  const ring = r => axes.map((_, i) => pt(i, r, n).map(v => v.toFixed(1)).join(',')).join(' ');
  let out = [1, .8, .6, .4, .2]
    .map(f => \`<polygon points="\${ring(g.r * f)}" fill="none" stroke="#374151" stroke-width="1"/>\`).join('');
  out += axes.map((_, i) => {
    const [x, y] = pt(i, g.r, n);
    return \`<line x1="\${g.cx}" y1="\${g.cy}" x2="\${x.toFixed(1)}" y2="\${y.toFixed(1)}" stroke="#374151" stroke-width="1"/>\`;
  }).join('');
  out += shown.map(s => {
    const pts = axes.filter(a => typeof s.radar[a] === 'number').map(a => {
      const i = axes.indexOf(a);
      return pt(i, Math.max(0, Math.min(100, s.radar[a])) / 100 * g.r, n).map(v => v.toFixed(1)).join(',');
    }).join(' ');
    return \`<polygon points="\${pts}" fill="\${s.color}" fill-opacity="0.12" stroke="\${s.color}" stroke-width="2.5" stroke-linejoin="round"/>\`;
  }).join('');
  out += axes.map((a, i) => {
    const [x, y] = pt(i, g.r + 30, n);
    const dx = x - g.cx;
    const anchor = Math.abs(dx) < 8 ? 'middle' : (dx > 0 ? 'start' : 'end');
    const hot = a === focused;
    return \`<text x="\${x.toFixed(1)}" y="\${y.toFixed(1)}" text-anchor="\${anchor}" data-axis="\${esc(a)}" fill="\${hot ? '#818cf8' : '#9ca3af'}" style="font-size:13px;font-weight:800;text-decoration:\${hot ? 'underline' : 'none'}">\${esc(a)}</text>\`;
  }).join('');
  svg.innerHTML = out;

  const legendEl = document.getElementById('legend');
  if (focused && axes.includes(focused)) {
    // 聚焦某一軸時列出排名。沒有這項指標的實驗排除而非以 0 計，
    // 但要講明白是哪些被略過，否則看起來像漏掉。
    const rows = shown.filter(s => typeof s.radar[focused] === 'number')
      .sort((a, b) => b.radar[focused] - a.radar[focused]);
    const best = rows.length ? rows[0].radar[focused] : null;
    const omitted = shown.filter(s => typeof s.radar[focused] !== 'number');
    legendEl.innerHTML = \`<div class="rank">
      <div class="hd"><b>\${esc(focused)}</b><button id="unfocus">✕ 清除</button></div>
      \${rows.map((s, i) => \`<div class="row">
        <span class="no">\${i + 1}</span>
        <span class="dot" style="background:\${s.color}"></span>
        <div class="meta"><div class="label">\${esc(s.label)}</div><div class="name">\${esc(s.name)}</div></div>
        <span class="val" style="color:\${s.color}">\${s.radar[focused].toFixed(1)}%\${s.radar[focused] === best ? ' \u2605' : ''}</span>
      </div>\`).join('')}
      \${omitted.length ? \`<div class="omit">以下沒有這項指標，故未列入：\${omitted.map(s => esc(s.name)).join('、')}</div>\` : ''}
    </div>\`;
    const btn = document.getElementById('unfocus');
    if (btn) btn.onclick = () => { focused = null; render(); };
  } else {
    legendEl.innerHTML = shown.map(s => \`
      <div class="item">
        <span class="dot" style="background:\${s.color}"></span>
        <div class="meta"><div class="label">\${esc(s.label)}</div><div class="name">\${esc(s.name)}</div></div>
        <div class="avg" style="color:\${s.color}">\${s.avg}%</div>
      </div>\`).join('');
  }

  const head = '<thead><tr><th>指標</th>' +
    shown.map(s => \`<th><div style="color:\${s.color}">\${esc(s.label)}</div><div class="ds2">\${esc((s.name || '').split(' @ ')[0])}</div></th>\`).join('') + '</tr></thead>';
  const body = axes.map(a => {
    const vals = shown.filter(s => typeof s.radar[a] === 'number').map(s => s.radar[a]);
    const best = vals.length ? Math.max(...vals) : null;
    const cells = shown.map(s => {
      const v = s.radar[a];
      if (typeof v !== 'number') return '<td class="na">—</td>';
      return \`<td\${v === best ? ' class="best"' : ''}>\${v.toFixed(1)}%</td>\`;
    }).join('');
    return \`<tr data-axis="\${esc(a)}"\${a === focused ? ' class="on"' : ''}><th>\${esc(a)}</th>\${cells}</tr>\`;
  }).join('');
  const foot = '<tr class="sum"><th>綜合（軸平均）</th>' +
    shown.map(s => \`<td style="color:\${s.color}">\${s.avg}%</td>\`).join('') + '</tr>';
  document.getElementById('table').innerHTML = head + '<tbody>' + body + foot + '</tbody>';
}

// 攤平成一排 chip 時，數十個實驗根本選不動。拆成「模型 × 測資」矩陣後，
// 點列頭是看某模型的難度梯度，點欄頭是跨模型比同一組——正好是兩種常做的比較。
const GRID = (() => {
  const dsOrder = [], mdOrder = [], cell = {}, models = {}, datasets = {};
  DATA.series.forEach(s => {
    const parts = (s.name || '').split(' @ ');
    const ds = parts[0] || '(未命名)', md = parts[1] || s.label;
    if (!dsOrder.includes(ds)) dsOrder.push(ds);
    if (!mdOrder.includes(md)) mdOrder.push(md);
    cell[md + '||' + ds] = s;
    (models[md] = models[md] || []).push(s.id);
    (datasets[ds] = datasets[ds] || []).push(s.id);
  });
  const rank = d => ['easy', 'medium', 'hard'].findIndex(k => d.endsWith(k));
  dsOrder.sort((a, b) => {
    const ra = rank(a), rb = rank(b);
    if (ra !== -1 && rb !== -1) return ra - rb;
    if (ra !== -1) return -1;
    if (rb !== -1) return 1;
    return 0;
  });
  return { dsOrder, mdOrder, cell, models, datasets };
})();

document.getElementById('grid').innerHTML =
  '<thead><tr><th></th>' +
  GRID.dsOrder.map(ds => \`<th data-ds="\${esc(ds)}">\${esc(ds.replace(/^sqlite-/, ''))}</th>\`).join('') +
  '</tr></thead><tbody>' +
  GRID.mdOrder.map(md => '<tr><th data-model="' + esc(md) + '">' + esc(md) + '</th>' +
    GRID.dsOrder.map(ds => {
      const s = GRID.cell[md + '||' + ds];
      return s
        ? \`<td><button class="cell" data-id="\${esc(s.id)}" data-color="\${s.color}" title="\${esc(s.name)}">\u2713</button></td>\`
        : '<td><span class="gap" title="這個組合沒有跑過"></span></td>';
    }).join('') + '</tr>').join('') +
  '</tbody>';

const setMany = (ids, want) => { ids.forEach(id => want ? on.add(id) : on.delete(id)); render(); };
document.getElementById('grid').addEventListener('click', e => {
  const cell = e.target.closest('.cell');
  if (cell) { const id = cell.dataset.id; on.has(id) ? on.delete(id) : on.add(id); return render(); }
  const rowTh = e.target.closest('tbody th[data-model]');
  if (rowTh) { const ids = GRID.models[rowTh.dataset.model]; return setMany(ids, !ids.every(i => on.has(i))); }
  const colTh = e.target.closest('thead th[data-ds]');
  if (colTh) { const ids = GRID.datasets[colTh.dataset.ds]; return setMany(ids, !ids.every(i => on.has(i))); }
});
// 軸標籤與表格列都可點來聚焦，再點一次取消
const toggleAxis = a => { focused = (focused === a) ? null : a; render(); };
document.getElementById('radar').addEventListener('click', e => {
  const a = e.target.dataset && e.target.dataset.axis;
  if (a) toggleAxis(a);
});
document.getElementById('table').addEventListener('click', e => {
  const tr = e.target.closest('tr[data-axis]');
  if (tr) toggleAxis(tr.dataset.axis);
});
document.getElementById('all').onclick = () => { DATA.series.forEach(s => on.add(s.id)); render(); };
document.getElementById('none').onclick = () => { on.clear(); render(); };
render();
<\/script>
</body></html>`;

            const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = `adeval-benchmark-${new Date().toISOString().slice(0, 10)}.html`;
            a.click();
            URL.revokeObjectURL(a.href);
        };

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
            rowPicked, colPicked, selectAllRuns, clearRuns, exportBenchmarkHtml,
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
