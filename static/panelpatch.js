"use strict";

const get = (id) => document.getElementById(id);
const state = {card: null, result: null, photo: null, probe: null, mode: "probe", chart: "profile", busy: false, line: null, adoptedLine: null};
const settings = [...document.querySelectorAll("[data-setting]")];

async function api(path, options) {
  const response = await fetch("/panelpatch" + path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "请求失败，请检查输入后重试。");
  return body;
}

function route(tail) {
  return "/cards/" + state.card.id + tail;
}

function savedQuery() {
  return "?revision=" + state.card.revision;
}

function notice(message, target = "notice") {
  const element = get(target);
  element.textContent = message;
  element.hidden = !message;
}

async function action(work, target = "notice") {
  if (state.busy) return;
  state.busy = true;
  document.querySelectorAll("button, select").forEach((node) => { node.disabled = true; });
  notice("", target);
  try {
    await work();
  } catch (error) {
    notice(error.message, target);
  } finally {
    state.busy = false;
    document.querySelectorAll("button, select").forEach((node) => { node.disabled = false; });
    if (get("line-summary")) renderLineReview();
  }
}

async function library() {
  const {cards} = await api("/cards");
  const select = get("library");
  select.replaceChildren(new Option("选取已存卡片", ""));
  for (const card of cards) select.append(new Option(card.name, card.id));
  select.value = state.card?.id || "";
}

function paintSource() {
  const canvas = get("capture");
  const ctx = canvas.getContext("2d");
  const {photo, card, probe} = state;
  if (!photo) return;
  canvas.width = card.width;
  canvas.height = card.height;
  ctx.drawImage(photo, 0, 0);
  const cfg = card.settings;
  const {result} = state;
  ctx.lineWidth = 2;
  ctx.strokeStyle = "#7cadd4";
  ctx.setLineDash([6,5]);
  ctx.strokeRect(cfg.left,cfg.top,cfg.right-cfg.left,cfg.bottom-cfg.top);
  ctx.setLineDash([]);
  if (result.profile.length) {
    ctx.strokeStyle = "#e4deab";
    ctx.beginPath();
    ctx.moveTo(result.focus,cfg.top);
    ctx.lineTo(result.focus,cfg.bottom);
    ctx.stroke();
  }
  ctx.strokeStyle = "#8ee3c6";
  ctx.strokeRect(cfg.ref_x - 5, cfg.ref_y - 5, 10, 10);
  const colors = {bright: "#e5a461", dark: "#9c9bf5", within: "#84b7a8"};
  for (const row of result.profile) {
    ctx.fillStyle = colors[row.classification];
    ctx.fillRect(row.x - 1, row.y, 3, 1);
  }
  if (state.line && !state.adoptedLine) {
    ctx.strokeStyle = "#ff7ae8";
    ctx.lineWidth = 1.5;
    for (const point of state.line.points || []) {
      ctx.beginPath();
      ctx.arc(point.x, point.y, 4.5, 0, Math.PI * 2);
      ctx.stroke();
    }
  }
  if (state.adoptedLine) {
    for (const point of state.adoptedLine.points || []) {
      ctx.beginPath();
      ctx.arc(point.x, point.y, 5, 0, Math.PI * 2);
      ctx.fillStyle = "#0b1018";
      ctx.fill();
    }
    for (const point of state.adoptedLine.points || []) {
      ctx.beginPath();
      ctx.arc(point.x, point.y, 3.25, 0, Math.PI * 2);
      ctx.fillStyle = "#ff3df0";
      ctx.fill();
    }
  }
  if (probe) {
    ctx.strokeStyle = "#30393b";
    ctx.strokeRect(probe.x - 5, probe.y - 5, 10, 10);
  }
}

function paintChart() {
  const canvas = get("chart");
  const ctx = canvas.getContext("2d");
  const {width, height} = canvas;
  const {result, card} = state;
  const cfg = card.settings;
  const coverage = state.chart === "coverage";
  const lo = coverage ? cfg.left : cfg.top;
  const hi = coverage ? cfg.right : cfg.bottom;
  const bound = coverage ? Math.max(1, ...result.coverage.map((row) => Math.max(row.bright, row.dark)))
    : Math.ceil(Math.max(10, cfg.limit, ...result.profile.map((row) => Math.abs(row.delta))));
  const min = coverage ? 0 : -bound;
  const xAt = (x) => 42 + (width - 79) * (x - lo) / Math.max(1, hi - lo);
  const yAt = (y) => height - 26 - (height - 46) * (y - min) / (bound - min);
  get("chart-title").textContent = coverage ? "各原列亮暗越限" : "原列相对亮度";
  get("chart-caption").textContent = coverage ? "琥珀偏亮 · 紫色偏暗 · 原片 X" : "相对参考 · 原片 Y";

  ctx.fillStyle = "#17232e";
  ctx.fillRect(0, 0, width, height);
  ctx.font = "12px monospace";
  ctx.fillStyle = "#aabdce";
  ctx.strokeStyle = "#344858";
  for (const level of [min, Math.round((min + bound) / 2), bound]) {
    ctx.fillText(level, 8, yAt(level) + 3);
    ctx.beginPath();
    ctx.moveTo(xAt(lo), yAt(level));
    ctx.lineTo(xAt(hi), yAt(level));
    ctx.stroke();
  }
  ctx.fillText(String(lo), xAt(lo), height - 7);
  ctx.fillText(String(hi), xAt(hi) - 15, height - 7);
  ctx.lineWidth = 2;
  const plot = (values, color) => {
    ctx.strokeStyle = color;
    ctx.beginPath();
    values.forEach(([x,y], i) => {
      if (i) ctx.lineTo(xAt(x), yAt(y));
      else ctx.moveTo(xAt(x), yAt(y));
    });
    ctx.stroke();
  };
  if (coverage) {
    plot(result.coverage.map((row) => [row.x, row.bright]), "#e4a86f");
    plot(result.coverage.map((row) => [row.x, row.dark]), "#a6a4f1");
    const line = state.adoptedLine || state.line;
    if (line) {
      const adopted = Boolean(state.adoptedLine);
      for (const point of line.points || []) {
        ctx.beginPath();
        ctx.arc(xAt(point.x), yAt(0), adopted ? 3.5 : 4.5, 0, Math.PI * 2);
        if (adopted) {
          ctx.fillStyle = "#ff3df0";
          ctx.fill();
          ctx.lineWidth = 1;
          ctx.strokeStyle = "#0b1018";
          ctx.stroke();
        } else {
          ctx.strokeStyle = "#ff7ae8";
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }
      }
    }
  } else {
    plot(result.profile.map((row) => [row.y, row.delta]), "#84dbc0");
    ctx.setLineDash([5, 4]);
    plot([[lo, cfg.limit], [hi, cfg.limit]], "#e4a86f");
    plot([[lo, -cfg.limit], [hi, -cfg.limit]], "#a6a4f1");
    ctx.setLineDash([]);
  }
  canvas.classList.toggle("selectable-line", Boolean(coverage && state.adoptedLine));
}

function pointLabel(point) {
  const meaning = {bright: "偏亮", dark: "偏暗", within: "限内"};
  const kind = meaning[point.classification] || "框外";
  return "(" + point.x + ", " + point.y + ") · RGB " + point.rgb.join("/") +
    " · 亮度 " + point.brightness.toFixed(2) + " · 偏差 " + signed(point.delta) + " · " + kind;
}

function signed(value) {
  return (value > 0 ? "+" : "") + value.toFixed(2);
}

function lineText(line) {
  const kind = line.kind === "dark" ? "偏暗" : "偏亮";
  const excess = line.average_excess ?? line.mean_excess ?? 0;
  return kind + "线 · " + line.columns + " 个原列（X " + line.start_x + "–" + line.end_x +
    "）· Y " + line.y_min + "–" + line.y_max + " · 平均超限 " + excess.toFixed(2);
}

function renderLineReview() {
  const summary = get("line-summary");
  const adopt = get("adopt-line");
  if (state.adoptedLine) {
    summary.textContent = "已采用：" + lineText(state.adoptedLine) +
      "。请在“沿面板分布”图点选该线经过的一列。";
    adopt.hidden = false;
    adopt.disabled = true;
    adopt.textContent = "已采用建议线";
    return;
  }
  adopt.disabled = false;
  if (state.line) {
    summary.textContent = "建议一条复核：" + lineText(state.line) + "。可采用后点选分布列。";
    adopt.hidden = false;
    adopt.textContent = "采用建议线";
  } else {
    summary.textContent = "未找到合格横线：须至少跨六个连续原列，每列只能取一个原像素；相邻列的 Y 最多差一，整条线最大和最小 Y 差不超过二，且整条同为真偏亮或真偏暗。";
    adopt.hidden = true;
  }
}

function show() {
  const {card, result} = state;
  state.line = result.recommended_line || result.horizontal_line || result.line || null;
  state.adoptedLine = result.adopted_line || card.adopted_line || null;
  get("workspace").hidden = false;
  get("empty").hidden = true;
  get("origin").textContent = (card.synthetic ? "合成练习图" : "导入原片") + " · 修订 " + card.revision;
  get("card-title").textContent = card.name;
  get("dimensions").textContent = card.width + " × " + card.height + " px · " + card.photo_name;
  get("name").value = card.name;
  for (const field of settings) field.value = card.settings[field.dataset.setting];
  get("probe-x").max = card.width - 1;
  get("probe-y").max = card.height - 1;
  get("probe-x").value = state.probe?.x ?? result.focus;
  get("probe-y").value = state.probe?.y ?? Math.round((card.settings.top+card.settings.bottom)/2);
  get("probe-result").textContent = state.probe ? pointLabel(state.probe) : "选择原片像素";
  const reading = result.reading;
  get("delta-value").textContent = reading ? signed(reading.delta_mean) : "—";
  get("reference-info").textContent = "实际参考亮度 " + result.reference.brightness.toFixed(2);
  get("delta-unit").textContent = "亮度级";
  get("measurement-state").textContent = "原片 X " + result.focus;
  get("selected-level").textContent = reading
    ? "均亮 " + reading.mean_luma.toFixed(2) + " · 偏亮 " + reading.bright + " · 偏暗 " + reading.dark
    : "截线在测量框外";
  for (const [id, filename] of Object.entries({proof: "proof.png", csv: "profile.csv", zip: "observation.zip"})) {
    get(id).href = "/panelpatch" + route("/export/" + filename) + savedQuery();
  }
  renderLineReview();
  paintSource();
  paintChart();
}

async function open(card) {
  const base = "/cards/" + card.id;
  const photo = new Image();
  photo.src = "/panelpatch" + base + "/capture.png";
  const [result] = await Promise.all([api(base + "/measurement?revision=" + card.revision), photo.decode()]);
  Object.assign(state, {card, result, photo, probe: null});
  get("library").value = card.id;
  show();
}

async function probe(x, y) {
  state.probe = await api(route("/probe") + savedQuery() + "&x=" + x + "&y=" + y);
  get("probe-x").value = x;
  get("probe-y").value = y;
  get("probe-result").textContent = pointLabel(state.probe);
  paintSource();
}

async function findLine() {
  const body = await api(route("/horizontal-line") + savedQuery());
  state.line = body.recommended_line || body.horizontal_line || body.line || null;
  renderLineReview();
  paintSource();
  paintChart();
  notice(state.line ? "已找到建议复核的横线。" : "没有找到符合全部连续性和偏差条件的横线。");
}

function setChartMode(mode) {
  state.chart = mode;
  document.querySelectorAll("[data-chart]").forEach((item) =>
    item.setAttribute("aria-pressed", String(item.dataset.chart === mode)));
  if (state.card) paintChart();
}

async function adoptLine() {
  const card = await api(route("/adopt-line"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({revision: state.card.revision}),
  });
  setChartMode("coverage");
  await open(card);
  setChartMode("coverage");
  notice("已采用建议线，请在“沿面板分布”图点选该线经过的一列。");
}

function linePointFromChartEvent(event) {
  if (!state.adoptedLine?.points?.length) return null;
  const canvas = get("chart");
  const rect = canvas.getBoundingClientRect();
  if (!rect.width) return null;
  const px = (event.clientX - rect.left) * canvas.width / rect.width;
  const cfg = state.card.settings;
  const lo = cfg.left;
  const hi = cfg.right;
  const plotWidth = canvas.width - 79;
  const span = Math.max(1, hi - lo);
  let nearest = null;
  let nearestDistance = Infinity;
  for (const point of state.adoptedLine.points) {
    const xPix = 42 + plotWidth * (point.x - lo) / span;
    const distance = Math.abs(xPix - px);
    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearest = point;
    }
  }
  return nearestDistance <= 18 ? nearest : null;
}

async function selectLineColumn(point) {
  let card = state.card;
  if (Number(card.settings.focus) !== Number(point.x)) {
    card = await api(route(""), {
      method: "PATCH",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({revision: card.revision, settings: {focus: point.x}}),
    });
    await open(card);
    setChartMode("coverage");
  }
  await probe(point.x, point.y);
  notice("截线和原片点读已落到该列实际采用的像素 (" + point.x + ", " + point.y + ")。");
}

get("find-line").addEventListener("click", () => action(findLine).finally(renderLineReview));
get("adopt-line").addEventListener("click", () => action(adoptLine).finally(renderLineReview));
get("chart").addEventListener("click", (event) => {
  if (!state.card || state.chart !== "coverage" || !state.adoptedLine) return;
  const point = linePointFromChartEvent(event);
  if (!point) {
    notice("请点选采用线实点所在的原列。");
    return;
  }
  action(() => selectLineColumn(point));
});

get("practice").addEventListener("click", () => action(async () => {
  await open(await api("/practice", {method: "POST"}));
  await library();
}));

get("library").addEventListener("change", () => {
  if (get("library").value) action(async () => open(await api("/cards/" + get("library").value)));
});
get("open-import").addEventListener("click", () => {
  notice("", "import-notice");
  get("import").showModal();
});
get("cancel-import").addEventListener("click", () => get("import").close());
get("upload").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const card = await api("/cards", {method: "POST", body: new FormData(event.target)});
    await open(card);
    await library();
    get("import").close();
    event.target.reset();
  }, "import-notice");
});
document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => {
  state.mode = button.dataset.mode;
  document.querySelectorAll("[data-mode]").forEach((item) =>
    item.setAttribute("aria-pressed", String(item === button)));
}));
get("capture").addEventListener("click", (event) => {
  if (!state.card) return;
  const canvas = event.currentTarget;
  const rect = canvas.getBoundingClientRect();
  const x = Math.max(0, Math.min(canvas.width - 1, Math.floor((event.clientX - rect.left) * canvas.width / rect.width)));
  const y = Math.max(0, Math.min(canvas.height - 1, Math.floor((event.clientY - rect.top) * canvas.height / rect.height)));
  action(async () => {
    await probe(x, y);
    if (state.mode === "mark") {
      settings.find((field) => field.dataset.setting === "focus").value = x;
      notice("已填入实际原片截线。");
    }
    if (state.mode === "reference") {
      settings.find((field) => field.dataset.setting === "ref_x").value = x;
      settings.find((field) => field.dataset.setting === "ref_y").value = y;
      notice("已填入实际原片参考点。");
    }
  });
});
get("probe-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(() => probe(get("probe-x").value, get("probe-y").value));
});
get("calibration").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const fields = Object.fromEntries(settings.map((field) => [field.dataset.setting, Number(field.value)]));
    const card = await api(route(""), {
      method: "PATCH", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({revision: state.card.revision, name: get("name").value, settings: fields}),
    });
    await open(card);
    await library();
  });
});
get("prepare").addEventListener("click", () => action(async () => {
  const {url} = await api(route("/prepare") + savedQuery(), {method: "POST"});
  location.assign(url);
}));
document.querySelectorAll("[data-chart]").forEach((button) => button.addEventListener("click", () => {
  state.chart = button.dataset.chart;
  document.querySelectorAll("[data-chart]").forEach((item) =>
    item.setAttribute("aria-pressed", String(item === button)));
  if (state.card) paintChart();
}));
action(library);
