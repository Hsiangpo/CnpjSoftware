import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_stylesheet_defines_all_used_custom_properties():
    css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"--([a-zA-Z0-9_-]+)\s*:", css))
    used = set(re.findall(r"var\(--([a-zA-Z0-9_-]+)\)", css))

    assert sorted(used - defined) == []


def test_app_references_existing_dom_ids():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    ids = set(re.findall(r'id="([^"]+)"', html))
    referenced_ids = set(re.findall(r'getElementById\("([^"]+)"\)', script))

    assert sorted(referenced_ids - ids) == []


def test_layout_and_proxy_fields_exist_in_index():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

    assert 'class="workspace-grid"' in html
    assert 'class="workspace-side"' in html
    assert 'class="workspace-main"' in html
    assert 'id="proxyHostInput"' in html
    assert 'id="proxyRegionInput"' in html
    assert 'id="proxyUsernameInput"' in html
    assert 'id="proxyPasswordInput"' in html
    assert 'id="proxyProtocolInput"' in html
    assert 'id="proxySessionInput"' in html


def test_index_uses_local_icon_asset():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

    assert "https://unpkg.com" not in html
    assert "@latest" not in html
    assert "/static/lucide.min.js" in html
    assert (ROOT / "static" / "lucide.min.js").exists()


def test_running_job_keeps_start_button_disabled_after_source_summary_render():
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    ids = sorted(set(re.findall(r'getElementById\("([^"]+)"\)', script)) | {"jobPulseDot", "apiBadgeDot"})
    harness = f"""
const fs = require("fs");
const vm = require("vm");
const script = fs.readFileSync({json.dumps(str(ROOT / "static" / "app.js"))}, "utf8");
function makeClassList() {{
  const values = new Set();
  return {{
    add: (...items) => items.forEach((item) => values.add(item)),
    remove: (...items) => items.forEach((item) => values.delete(item)),
    toggle: (item, force) => {{
      const enabled = force === undefined ? !values.has(item) : Boolean(force);
      if (enabled) values.add(item); else values.delete(item);
      return enabled;
    }},
    contains: (item) => values.has(item),
  }};
}}
function makeElement(id) {{
  return {{
    id,
    value: "",
    textContent: "",
    innerHTML: "",
    disabled: false,
    placeholder: "",
    options: [],
    style: {{}},
    classList: makeClassList(),
    addEventListener: () => undefined,
    querySelectorAll: () => [],
  }};
}}
const elements = Object.fromEntries({json.dumps(ids)}.map((id) => [id, makeElement(id)]));
const context = {{
  console,
  alert: () => undefined,
  navigator: {{ clipboard: {{ writeText: async () => undefined }} }},
  document: {{ getElementById: (id) => elements[id] || makeElement(id) }},
  window: {{ clearInterval: () => undefined, setInterval: () => 1 }},
  fetch: async (url) => {{
    if (url === "/api/settings") {{
      return {{ ok: true, json: async () => ({{ llm_api_key: "", llm_model: "gpt-5.4-mini", system_concurrency: 8, blurpath_proxy_ports: [15129], blurpath_available_proxy_ports: [15129], provider_order: ["brasilapi", "cnpjbiz"] }}) }};
    }}
        if (url === "/api/health") {{
          return {{ ok: true, json: async () => ({{ has_llm_key: true, system_concurrency: 8, blurpath_proxy_configured: true, browser_proxy: {{ ports: [15129] }} }}) }};
        }}
    if (url === "/api/source-files") {{
      return {{ ok: true, json: async () => ({{ input_dir: "cnpj", output_dir: "output", files: [] }}) }};
    }}
    if (url === "/api/output-files") {{
      return {{ ok: true, json: async () => ({{ files: [] }}) }};
    }}
    return {{ ok: true, json: async () => ({{}}) }};
  }},
}};
context.window.document = context.document;
context.globalThis = context;
vm.createContext(context);
vm.runInContext(script + "\\nglobalThis.__uiTest = {{ state, renderSourceSummary, syncFilterButtons }};", context);
context.__uiTest.state.sourceFiles = [{{ name: "sample.xlsx", source_type: "xlsx", size_bytes: 10, count: 2, unique_count: 1, resume: {{ done_count: 0, total_count: 1 }}, output_name: "sample-responsaveis.xlsx" }}];
context.__uiTest.state.selectedSourceName = "sample.xlsx";
context.__uiTest.state.lastJob = {{ status: "running", results: [], input_cnpjs: ["03541629000137"] }};
context.__uiTest.state.jobId = "job-1";
context.__uiTest.state.queueRunning = true;
context.__uiTest.renderSourceSummary();
context.__uiTest.syncFilterButtons();
console.log(JSON.stringify({{ startDisabled: elements.startButton.disabled, retryDisabled: elements.runFailedButton.disabled }}));
"""

    result = subprocess.run(
        ["node", "-e", harness],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])

    assert payload == {"startDisabled": True, "retryDisabled": True}


def test_render_results_updates_metrics_and_analysis_meta_without_reasoning_text():
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    ids = sorted(set(re.findall(r'getElementById\("([^"]+)"\)', script)) | {"jobPulseDot", "apiBadgeDot"})
    harness = f"""
const fs = require("fs");
const vm = require("vm");
const script = fs.readFileSync({json.dumps(str(ROOT / "static" / "app.js"))}, "utf8");
function makeClassList() {{
  const values = new Set();
  return {{
    add: (...items) => items.forEach((item) => values.add(item)),
    remove: (...items) => items.forEach((item) => values.delete(item)),
    toggle: (item, force) => {{
      const enabled = force === undefined ? !values.has(item) : Boolean(force);
      if (enabled) values.add(item); else values.delete(item);
      return enabled;
    }},
    contains: (item) => values.has(item),
  }};
}}
function makeElement(id) {{
  return {{
    id,
    value: "",
    textContent: "",
    innerHTML: "",
    disabled: false,
    placeholder: "",
    options: [],
    style: {{}},
    classList: makeClassList(),
    addEventListener: () => undefined,
    querySelectorAll: () => [],
  }};
}}
const elements = Object.fromEntries({json.dumps(ids)}.map((id) => [id, makeElement(id)]));
const context = {{
  console,
  alert: () => undefined,
  navigator: {{ clipboard: {{ writeText: async () => undefined }} }},
  document: {{ getElementById: (id) => elements[id] || makeElement(id) }},
  window: {{ clearInterval: () => undefined, setInterval: () => 1 }},
  fetch: async () => ({{ ok: true, json: async () => ({{}}) }}),
}};
context.window.document = context.document;
context.globalThis = context;
vm.createContext(context);
vm.runInContext(script + "\\nglobalThis.__uiTest = {{ state, renderResults }};", context);
context.__uiTest.renderResults({{
  job_id: "job-1",
  status: "completed",
  input_cnpjs: ["1", "2", "3", "4"],
  results: [
    {{
      input_cnpj: "1",
      normalized_cnpj: "1",
      status: "success",
      company: {{ legal_name: "Empresa A", url: "https://cnpj.biz/1", source_provider: "brasilapi" }},
      responsible: {{ names: ["Pessoa A"], role: "Diretor", confidence: 0.98, analysis_source: "llm", model_used: "gpt-5.4-mini", reasoning: "ok" }},
      provider_trace: [],
    }},
    {{
      input_cnpj: "2",
      normalized_cnpj: "2",
      status: "partial_success",
      company: {{ legal_name: "Empresa B", url: "https://cnpj.biz/2", source_provider: "cnpjbiz.browser" }},
      responsible: {{ names: ["Pessoa B"], role: "Socio", confidence: 0.72, analysis_source: "rule_fallback", model_used: "", reasoning: "fallback" }},
      provider_trace: [],
    }},
    {{
      input_cnpj: "3",
      normalized_cnpj: "3",
      status: "fetch_error",
      error: "timeout",
      provider_trace: [],
    }}
  ]
}});
console.log(JSON.stringify({{
  pending: elements.inputCount.textContent,
  completed: elements.doneCount.textContent,
  normal: elements.normalCount ? elements.normalCount.textContent : null,
  abnormal: elements.issueCount.textContent,
  html: elements.resultBody.innerHTML,
}}));
"""

    result = subprocess.run(
        ["node", "-e", harness],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])

    assert payload["pending"] == "1"
    assert payload["completed"] == "3"
    assert payload["normal"] == "1"
    assert payload["abnormal"] == "2"
    assert "gpt-5.4-mini" in payload["html"]
    assert "rule_fallback" in payload["html"]
    assert 'class="reason-text">fallback<' not in payload["html"]
    assert 'class="reason-text">ok<' not in payload["html"]


def test_render_results_uses_unique_abnormal_counts_and_enables_retry_for_partial():
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    ids = sorted(set(re.findall(r'getElementById\("([^"]+)"\)', script)) | {"jobPulseDot", "apiBadgeDot"})
    harness = f"""
const fs = require("fs");
const vm = require("vm");
const script = fs.readFileSync({json.dumps(str(ROOT / "static" / "app.js"))}, "utf8");
function makeClassList() {{
  const values = new Set();
  return {{
    add: (...items) => items.forEach((item) => values.add(item)),
    remove: (...items) => items.forEach((item) => values.delete(item)),
    toggle: (item, force) => {{
      const enabled = force === undefined ? !values.has(item) : Boolean(force);
      if (enabled) values.add(item); else values.delete(item);
      return enabled;
    }},
    contains: (item) => values.has(item),
  }};
}}
function makeElement(id) {{
  return {{
    id,
    value: "",
    textContent: "",
    innerHTML: "",
    disabled: false,
    placeholder: "",
    options: [],
    style: {{}},
    classList: makeClassList(),
    addEventListener: () => undefined,
    querySelectorAll: () => [],
  }};
}}
const elements = Object.fromEntries({json.dumps(ids)}.map((id) => [id, makeElement(id)]));
const context = {{
  console,
  alert: () => undefined,
  navigator: {{ clipboard: {{ writeText: async () => undefined }} }},
  document: {{ getElementById: (id) => elements[id] || makeElement(id) }},
  window: {{ clearInterval: () => undefined, setInterval: () => 1 }},
  fetch: async () => ({{ ok: true, json: async () => ({{}}) }}),
}};
context.window.document = context.document;
context.globalThis = context;
vm.createContext(context);
vm.runInContext(script + "\\nglobalThis.__uiTest = {{ renderResults, syncRunButtons }};", context);
context.__uiTest.renderResults({{
  job_id: "job-1",
  status: "completed",
  input_cnpjs: ["1", "2", "2", "3"],
  results: [
    {{
      input_cnpj: "1",
      normalized_cnpj: "1",
      status: "success",
      company: {{ legal_name: "Empresa A", url: "https://cnpj.biz/1", source_provider: "brasilapi" }},
      responsible: {{ names: ["Pessoa A"], role: "Diretor", confidence: 0.98, analysis_source: "llm", model_used: "gpt-5.4-mini", reasoning: "ok" }},
      provider_trace: [],
    }},
    {{
      input_cnpj: "2",
      normalized_cnpj: "2",
      status: "partial_success",
      company: {{ legal_name: "Empresa B", url: "https://cnpj.biz/2", source_provider: "cnpjbiz.browser" }},
      responsible: {{ names: ["Pessoa B"], role: "Socio", confidence: 0.72, analysis_source: "rule_fallback", model_used: "", reasoning: "fallback" }},
      provider_trace: [],
    }},
    {{
      input_cnpj: "2",
      normalized_cnpj: "2",
      status: "partial_success",
      company: {{ legal_name: "Empresa B", url: "https://cnpj.biz/2", source_provider: "cnpjbiz.browser" }},
      responsible: {{ names: ["Pessoa B"], role: "Socio", confidence: 0.72, analysis_source: "rule_fallback", model_used: "", reasoning: "fallback" }},
      provider_trace: [],
    }},
    {{
      input_cnpj: "3",
      normalized_cnpj: "3",
      status: "blocked_by_cloudflare",
      error: "blocked",
      provider_trace: [],
    }}
  ]
}});
context.__uiTest.syncRunButtons();
console.log(JSON.stringify({{
  pending: elements.inputCount.textContent,
  completed: elements.doneCount.textContent,
  normal: elements.normalCount.textContent,
  abnormal: elements.issueCount.textContent,
  retryDisabled: elements.runFailedButton.disabled,
}}));
"""

    result = subprocess.run(
        ["node", "-e", harness],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])

    assert payload["pending"] == "0"
    assert payload["completed"] == "3"
    assert payload["normal"] == "1"
    assert payload["abnormal"] == "2"
    assert payload["retryDisabled"] is False


def test_initial_state_disables_retry_failed_without_job():
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    ids = sorted(set(re.findall(r'getElementById\("([^"]+)"\)', script)) | {"jobPulseDot", "apiBadgeDot"})
    harness = f"""
const fs = require("fs");
const vm = require("vm");
const script = fs.readFileSync({json.dumps(str(ROOT / "static" / "app.js"))}, "utf8");
function makeClassList() {{
  const values = new Set();
  return {{
    add: (...items) => items.forEach((item) => values.add(item)),
    remove: (...items) => items.forEach((item) => values.delete(item)),
    toggle: (item, force) => {{
      const enabled = force === undefined ? !values.has(item) : Boolean(force);
      if (enabled) values.add(item); else values.delete(item);
      return enabled;
    }},
    contains: (item) => values.has(item),
  }};
}}
function makeElement(id) {{
  return {{
    id,
    value: "",
    textContent: "",
    innerHTML: "",
    disabled: false,
    placeholder: "",
    options: [],
    style: {{}},
    classList: makeClassList(),
    addEventListener: () => undefined,
    querySelectorAll: () => [],
  }};
}}
const elements = Object.fromEntries({json.dumps(ids)}.map((id) => [id, makeElement(id)]));
const context = {{
  console,
  alert: () => undefined,
  navigator: {{ clipboard: {{ writeText: async () => undefined }} }},
  document: {{ getElementById: (id) => elements[id] || makeElement(id) }},
  window: {{ clearInterval: () => undefined, setInterval: () => 1 }},
  fetch: async () => ({{ ok: true, json: async () => ({{}}) }}),
}};
context.window.document = context.document;
context.globalThis = context;
vm.createContext(context);
vm.runInContext(script + "\\nglobalThis.__uiTest = {{ syncFilterButtons }};", context);
context.__uiTest.syncFilterButtons();
console.log(JSON.stringify({{
  retryDisabled: elements.runFailedButton.disabled,
  copyDisabled: elements.copyFailedButton.disabled,
}}));
"""

    result = subprocess.run(
        ["node", "-e", harness],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])

    assert payload == {"retryDisabled": True, "copyDisabled": True}


def test_render_source_summary_uses_unique_counts_after_refresh():
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    ids = sorted(set(re.findall(r'getElementById\("([^"]+)"\)', script)) | {"jobPulseDot", "apiBadgeDot"})
    harness = f"""
const fs = require("fs");
const vm = require("vm");
const script = fs.readFileSync({json.dumps(str(ROOT / "static" / "app.js"))}, "utf8");
function makeClassList() {{
  const values = new Set();
  return {{
    add: (...items) => items.forEach((item) => values.add(item)),
    remove: (...items) => items.forEach((item) => values.delete(item)),
    toggle: (item, force) => {{
      const enabled = force === undefined ? !values.has(item) : Boolean(force);
      if (enabled) values.add(item); else values.delete(item);
      return enabled;
    }},
    contains: (item) => values.has(item),
  }};
}}
function makeElement(id) {{
  return {{
    id,
    value: "",
    textContent: "",
    innerHTML: "",
    disabled: false,
    placeholder: "",
    options: [],
    style: {{}},
    classList: makeClassList(),
    addEventListener: () => undefined,
    querySelectorAll: () => [],
  }};
}}
const elements = Object.fromEntries({json.dumps(ids)}.map((id) => [id, makeElement(id)]));
const context = {{
  console,
  alert: () => undefined,
  navigator: {{ clipboard: {{ writeText: async () => undefined }} }},
  document: {{ getElementById: (id) => elements[id] || makeElement(id) }},
  window: {{ clearInterval: () => undefined, setInterval: () => 1 }},
  fetch: async () => ({{ ok: true, json: async () => ({{}}) }}),
}};
context.window.document = context.document;
context.globalThis = context;
vm.createContext(context);
vm.runInContext(script + "\\nglobalThis.__uiTest = {{ state, renderSourceSummary }};", context);
context.__uiTest.state.sourceFiles = [{{
  name: "sample.xlsx",
  source_type: "xlsx",
  size_bytes: 10,
  count: 3998,
  unique_count: 3790,
  normal_count: 3570,
  abnormal_count: 220,
  resume: {{ done_count: 3998, total_count: 3998 }},
  output_name: "sample-responsaveis.xlsx",
  output_exists: true,
  output_size_bytes: 1024,
  output_modified_at: 1710000000,
}}];
context.__uiTest.state.selectedSourceName = "sample.xlsx";
context.__uiTest.renderSourceSummary();
console.log(JSON.stringify({{
  pending: elements.inputCount.textContent,
  completed: elements.doneCount.textContent,
  normal: elements.normalCount.textContent,
  abnormal: elements.issueCount.textContent,
}}));
"""

    result = subprocess.run(
        ["node", "-e", harness],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])

    assert payload == {"pending": "0", "completed": "3790", "normal": "3570", "abnormal": "220"}


def test_start_adhoc_retry_job_posts_single_cnpj_job():
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    ids = sorted(set(re.findall(r'getElementById\("([^"]+)"\)', script)) | {"jobPulseDot", "apiBadgeDot"})
    harness = f"""
const fs = require("fs");
const vm = require("vm");
const script = fs.readFileSync({json.dumps(str(ROOT / "static" / "app.js"))}, "utf8");
function makeClassList() {{
  const values = new Set();
  return {{
    add: (...items) => items.forEach((item) => values.add(item)),
    remove: (...items) => items.forEach((item) => values.delete(item)),
    toggle: (item, force) => {{
      const enabled = force === undefined ? !values.has(item) : Boolean(force);
      if (enabled) values.add(item); else values.delete(item);
      return enabled;
    }},
    contains: (item) => values.has(item),
  }};
}}
function makeElement(id) {{
  return {{
    id,
    value: "",
    textContent: "",
    innerHTML: "",
    disabled: false,
    placeholder: "",
    options: [],
    style: {{}},
    classList: makeClassList(),
    addEventListener: () => undefined,
    querySelectorAll: () => [],
  }};
}}
const elements = Object.fromEntries({json.dumps(ids)}.map((id) => [id, makeElement(id)]));
const requests = [];
const context = {{
  console,
  alert: () => undefined,
  navigator: {{ clipboard: {{ writeText: async () => undefined }} }},
  document: {{ getElementById: (id) => elements[id] || makeElement(id) }},
  window: {{ clearInterval: () => undefined, setInterval: () => 1 }},
  fetch: async (url, options = undefined) => {{
    requests.push({{ url, options }});
    if (url === "/api/jobs") {{
      return {{ ok: true, json: async () => ({{ job_id: "job-1", status: "queued", input_cnpjs: ["03541629000137"], results: [] }}) }};
    }}
    return {{ ok: true, json: async () => ({{}}) }};
  }},
}};
context.window.document = context.document;
context.globalThis = context;
vm.createContext(context);
vm.runInContext(script + "\\nglobalThis.__uiTest = {{ startAdhocRetryJob }};", context);
(async () => {{
  await context.__uiTest.startAdhocRetryJob("03541629000137");
  console.log(JSON.stringify(requests));
}})();
"""

    result = subprocess.run(
        ["node", "-e", harness],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    requests = json.loads(result.stdout.strip().splitlines()[-1])

    job_requests = [item for item in requests if item["url"] == "/api/jobs"]
    assert len(job_requests) == 1
    assert json.loads(job_requests[0]["options"]["body"]) == {"cnpjs": ["03541629000137"]}


def test_start_adhoc_retry_job_uses_retry_one_endpoint_when_current_job_exists():
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    ids = sorted(set(re.findall(r'getElementById\("([^"]+)"\)', script)) | {"jobPulseDot", "apiBadgeDot"})
    harness = f"""
const fs = require("fs");
const vm = require("vm");
const script = fs.readFileSync({json.dumps(str(ROOT / "static" / "app.js"))}, "utf8");
function makeClassList() {{
  const values = new Set();
  return {{
    add: (...items) => items.forEach((item) => values.add(item)),
    remove: (...items) => items.forEach((item) => values.delete(item)),
    toggle: (item, force) => {{
      const enabled = force === undefined ? !values.has(item) : Boolean(force);
      if (enabled) values.add(item); else values.delete(item);
      return enabled;
    }},
    contains: (item) => values.has(item),
  }};
}}
function makeElement(id) {{
  return {{
    id,
    value: "",
    textContent: "",
    innerHTML: "",
    disabled: false,
    placeholder: "",
    options: [],
    style: {{}},
    classList: makeClassList(),
    addEventListener: () => undefined,
    querySelectorAll: () => [],
  }};
}}
const elements = Object.fromEntries({json.dumps(ids)}.map((id) => [id, makeElement(id)]));
const requests = [];
const context = {{
  console,
  alert: () => undefined,
  navigator: {{ clipboard: {{ writeText: async () => undefined }} }},
  document: {{ getElementById: (id) => elements[id] || makeElement(id) }},
  window: {{ clearInterval: () => undefined, setInterval: () => 1 }},
  fetch: async (url, options = undefined) => {{
    requests.push({{ url, options }});
    if (url.includes('/retry-one')) {{
      return {{ ok: true, json: async () => ({{ job_id: "job-2", status: "queued", input_cnpjs: ["03541629000137"], results: [] }}) }};
    }}
    return {{ ok: true, json: async () => ({{}}) }};
  }},
}};
context.window.document = context.document;
context.globalThis = context;
vm.createContext(context);
vm.runInContext(script + "\\nglobalThis.__uiTest = {{ state, startAdhocRetryJob }};", context);
context.__uiTest.state.jobId = "job-parent";
(async () => {{
  await context.__uiTest.startAdhocRetryJob("03541629000137");
  console.log(JSON.stringify(requests));
}})();
"""

    result = subprocess.run(
        ["node", "-e", harness],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    requests = json.loads(result.stdout.strip().splitlines()[-1])

    retry_requests = [item for item in requests if item["url"] == "/api/jobs/job-parent/retry-one"]
    assert len(retry_requests) == 1
    assert json.loads(retry_requests[0]["options"]["body"]) == {"cnpj": "03541629000137"}


def test_queue_failed_retry_item_caps_at_three_rounds():
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    ids = sorted(set(re.findall(r'getElementById\("([^"]+)"\)', script)) | {"jobPulseDot", "apiBadgeDot"})
    harness = f"""
const fs = require("fs");
const vm = require("vm");
const script = fs.readFileSync({json.dumps(str(ROOT / "static" / "app.js"))}, "utf8");
function makeClassList() {{
  const values = new Set();
  return {{
    add: (...items) => items.forEach((item) => values.add(item)),
    remove: (...items) => items.forEach((item) => values.delete(item)),
    toggle: (item, force) => {{
      const enabled = force === undefined ? !values.has(item) : Boolean(force);
      if (enabled) values.add(item); else values.delete(item);
      return enabled;
    }},
    contains: (item) => values.has(item),
  }};
}}
function makeElement(id) {{
  return {{
    id,
    value: "",
    textContent: "",
    innerHTML: "",
    disabled: false,
    placeholder: "",
    options: [],
    style: {{}},
    classList: makeClassList(),
    addEventListener: () => undefined,
    querySelectorAll: () => [],
  }};
}}
const elements = Object.fromEntries({json.dumps(ids)}.map((id) => [id, makeElement(id)]));
const context = {{
  console,
  alert: () => undefined,
  navigator: {{ clipboard: {{ writeText: async () => undefined }} }},
  document: {{ getElementById: (id) => elements[id] || makeElement(id) }},
  window: {{ clearInterval: () => undefined, setInterval: () => 1 }},
  fetch: async () => ({{ ok: true, json: async () => ({{}}) }}),
}};
context.window.document = context.document;
context.globalThis = context;
vm.createContext(context);
vm.runInContext(script + "\\nglobalThis.__uiTest = {{ buildFailedRetryQueueItem }};", context);
const job = {{
  job_id: "job-1",
  status: "completed",
  source_name: "sample.xlsx",
  filename: "sample.xlsx",
  input_cnpjs: ["1", "2"],
  results: [
    {{ input_cnpj: "1", normalized_cnpj: "1", status: "success" }},
    {{ input_cnpj: "2", normalized_cnpj: "2", status: "fetch_error" }}
  ]
}};
const round1 = context.__uiTest.buildFailedRetryQueueItem(job, 1);
const round3 = context.__uiTest.buildFailedRetryQueueItem(job, 3);
const round4 = context.__uiTest.buildFailedRetryQueueItem(job, 4);
console.log(JSON.stringify({{ round1, round3, round4 }}));
"""

    result = subprocess.run(
        ["node", "-e", harness],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])

    assert payload["round1"]["retryAttempt"] == 1
    assert payload["round3"]["retryAttempt"] == 3
    assert payload["round4"] is None


def test_append_queue_item_dedupes_same_retry_round():
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    ids = sorted(set(re.findall(r'getElementById\("([^"]+)"\)', script)) | {"jobPulseDot", "apiBadgeDot"})
    harness = f"""
const fs = require("fs");
const vm = require("vm");
const script = fs.readFileSync({json.dumps(str(ROOT / "static" / "app.js"))}, "utf8");
function makeClassList() {{
  const values = new Set();
  return {{
    add: (...items) => items.forEach((item) => values.add(item)),
    remove: (...items) => items.forEach((item) => values.delete(item)),
    toggle: (item, force) => {{
      const enabled = force === undefined ? !values.has(item) : Boolean(force);
      if (enabled) values.add(item); else values.delete(item);
      return enabled;
    }},
    contains: (item) => values.has(item),
  }};
}}
function makeElement(id) {{
  return {{
    id,
    value: "",
    textContent: "",
    innerHTML: "",
    disabled: false,
    placeholder: "",
    options: [],
    style: {{}},
    classList: makeClassList(),
    addEventListener: () => undefined,
    querySelectorAll: () => [],
  }};
}}
const elements = Object.fromEntries({json.dumps(ids)}.map((id) => [id, makeElement(id)]));
const context = {{
  console,
  alert: () => undefined,
  navigator: {{ clipboard: {{ writeText: async () => undefined }} }},
  document: {{ getElementById: (id) => elements[id] || makeElement(id) }},
  window: {{ clearInterval: () => undefined, setInterval: () => 1 }},
  fetch: async () => ({{ ok: true, json: async () => ({{}}) }}),
}};
context.window.document = context.document;
context.globalThis = context;
vm.createContext(context);
vm.runInContext(script + "\\nglobalThis.__uiTest = {{ state, appendQueueItem, buildFailedRetryQueueItem }};", context);
const job = {{ job_id: "job-1", status: "completed", source_name: "sample.xlsx", filename: "sample.xlsx", input_cnpjs: ["1"], results: [{{ input_cnpj: "1", normalized_cnpj: "1", status: "fetch_error" }}] }};
const item = context.__uiTest.buildFailedRetryQueueItem(job, 1);
context.__uiTest.appendQueueItem(item);
context.__uiTest.appendQueueItem(item);
console.log(JSON.stringify(context.__uiTest.state.sourceQueue));
"""

    result = subprocess.run(
        ["node", "-e", harness],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])

    assert len(payload) == 1
