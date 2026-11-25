"use strict";

const get = (id) => document.getElementById(id);
const state = {card: null, result: null, photo: null, probe: null, mode: "probe", chart: "profile", busy: false};
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
  for (const point of result.reference.points) {
    ctx.strokeStyle = point.usable ? "#8ee3c6" : "#c4887b";
    ctx.strokeRect(point.x - 5, point.y - 5, 10, 10);
  }
  const colors = {bright: "#e5a461", dark: "#9c9bf5", within: "#84b7a8"};
  for (const row of result.profile) {
    if (!row.classification) {
      ctx.fillStyle = "#6b7f8c";
      ctx.fillRect(row.x, row.y, 1, 1);
      continue;
    }
    ctx.fillStyle = colors[row.classification];
    ctx.fillRect(row.x - 1, row.y, 3, 1);
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
    : Math.ceil(Math.max(10, cfg.limit,
      ...result.profile.map((row) => Math.abs(row.delta ?? 0))));
  const min = coverage ? 0 : -bound;
  const xAt = (x) => 42 + (width - 79) * (x - lo) / Math.max(1, hi - lo);
  const yAt = (y) => height - 26 - (height - 46) * (y - min) / (bound - min);
  get("chart-title").textContent = coverage ? "各原列亮暗越限" : "原列相对亮度";
  get("chart-caption").textContent = coverage ? "琥珀偏亮 · 紫色偏暗 · 原片 X" : "相对当地参考 · 原片 Y";

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
  } else {
    let segment = [];
    const flush = () => {
      if (segment.length) plot(segment, "#84dbc0");
      segment = [];
    };
    for (const row of result.profile) {
      if (row.delta === null) flush();
      else segment.push([row.y, row.delta]);
    }
    flush();
    ctx.setLineDash([5, 4]);
    plot([[lo, cfg.limit], [hi, cfg.limit]], "#e4a86f");
    plot([[lo, -cfg.limit], [hi, -cfg.limit]], "#a6a4f1");
    ctx.setLineDash([]);
  }
}

function paintReferences() {
  const holder = get("reference-points");
  holder.replaceChildren();
  const cfg = state.card.settings;
  const total = state.result.reference.total;
  if (!total) holder.append(Object.assign(document.createElement("p"), {textContent: "还没有参考点"}));
  for (const point of state.result.reference.points) {
    const row = document.createElement("div");
    row.className = "reference-point" + (point.usable ? "" : " unusable");
    const label = document.createElement("span");
    label.textContent = point.usable ? "RGB " + point.rgb.join("/")
      : "不采用 · 有通道为0或255";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "移除";
    remove.addEventListener("click", () => {
      cfg.references.splice(point.index, 1);
      state.probe = null;
      action(save);
    });
    row.append(document.createTextNode("(" + point.x + ", " + point.y + ") "), label, remove);
    holder.append(row);
  }
  const {usable, triangles} = state.result.reference;
  get("reference-info").textContent = total === 0
    ? "还没有参考点；至少需要三个不截断且不共线的参考点。"
    : usable < 3 || triangles === 0
      ? "需要至少三个不截断且不共线的参考点才能围住被读像素；当前可用 " + usable + " 个。"
      : "可用参考点 " + usable + "/" + total + " · 可围住的三角 " + triangles + " 个";
}

async function save() {
  const fields = Object.fromEntries(settings.map((field) => [field.dataset.setting, Number(field.value)]));
  const references = state.card.settings.references;
  const card = await api(route(""), {
    method: "PATCH", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({revision: state.card.revision, name: get("name").value,
                          settings: {...fields, references}}),
  });
  await open(card);
  await library();
}

function pointLabel(point) {
  const meaning = {bright: "偏亮", dark: "偏暗", within: "限内"};
  const kind = point.classification ? meaning[point.classification]
    : (point.inside ? "无参考" : "框外");
  const local = point.reference === null ? "当地参考 —" : "当地参考 " + point.reference.toFixed(2);
  const delta = point.delta === null ? "偏差 —" : "偏差 " + signed(point.delta);
  return "(" + point.x + ", " + point.y + ") · RGB " + point.rgb.join("/") +
    " · 亮度 " + point.brightness.toFixed(2) + " · " + local + " · " + delta + " · " + kind;
}

function signed(value) {
  return (value > 0 ? "+" : "") + value.toFixed(2);
}

function show() {
  const {card, result} = state;
  get("workspace").hidden = false;
  get("empty").hidden = true;
  if (!Array.isArray(card.settings.references)) {
    card.settings.references = result.reference.points.map(({x, y}) => ({x, y}));
  }
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
  get("delta-value").textContent = reading && reading.delta_mean !== null
    ? signed(reading.delta_mean) : "—";
  paintReferences();
  get("delta-unit").textContent = "亮度级";
  get("measurement-state").textContent = "原片 X " + result.focus;
  get("selected-level").textContent = reading
    ? "均亮 " + reading.mean_luma.toFixed(2) + " · 偏亮 " + reading.bright + " · 偏暗 " + reading.dark +
      (reading.delta_mean === null ? " · 该列没有可围住的位置" :
       (reading.unreferenced ? " · 无参考 " + reading.unreferenced + " 行" : ""))
    : "截线在测量框外";
  for (const [id, filename] of Object.entries({proof: "proof.png", csv: "profile.csv", zip: "observation.zip"})) {
    get(id).href = "/panelpatch" + route("/export/" + filename) + savedQuery();
  }
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

function addReference(x, y) {
  const {width, height} = state.card;
  const references = state.card.settings.references;
  if (!Number.isInteger(x) || !Number.isInteger(y) || x < 0 || y < 0 || x >= width || y >= height) {
    throw new Error("参考点需要原片范围内的整数坐标");
  }
  if (references.some((point) => point.x === x && point.y === y)) {
    throw new Error("这个位置已经有参考点");
  }
  if (references.length >= 12) throw new Error("参考点最多12个");
  references.push({x, y});
}

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
      addReference(x, y);
      await save();
      await probe(x, y);
      notice("已加入实际原片参考点 (" + x + ", " + y + ")。");
    }
  });
});
get("probe-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(() => probe(get("probe-x").value, get("probe-y").value));
});
get("calibration").addEventListener("submit", (event) => {
  event.preventDefault();
  action(save);
});
get("add-reference").addEventListener("click", () => action(async () => {
  const x = Number(get("probe-x").value);
  const y = Number(get("probe-y").value);
  addReference(x, y);
  await save();
  await probe(x, y);
  notice("已加入参考点 (" + x + ", " + y + ")。");
}));
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
