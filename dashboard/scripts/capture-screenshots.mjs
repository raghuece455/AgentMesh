import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { get } from 'node:http'
import { resolve, join } from 'node:path'
import { tmpdir } from 'node:os'

const baseUrl = process.env.AGENTMESH_DASHBOARD_URL ?? 'http://127.0.0.1:8790'
const chromePath = process.env.CHROME_PATH ?? findChrome()
const outDir = resolve(process.env.AGENTMESH_SCREENSHOT_DIR ?? 'screenshots')
const debugPort = Number(process.env.AGENTMESH_SCREENSHOT_DEBUG_PORT ?? String(9700 + Math.floor(Math.random() * 300)))
const profileDir = join(tmpdir(), `agentmesh-dashboard-shots-${Date.now()}`)
const theme = process.env.AGENTMESH_SCREENSHOT_THEME ?? 'dark'

async function main() {
  if (!chromePath) {
    console.error('Chrome was not found. Set CHROME_PATH to capture screenshots.')
    process.exit(1)
  }

  mkdirSync(outDir, { recursive: true })
  const chrome = spawn(chromePath, [`--remote-debugging-port=${debugPort}`, `--user-data-dir=${profileDir}`, '--headless=new', '--disable-gpu', '--no-first-run', '--hide-scrollbars', '--window-size=1600,1100', baseUrl], { stdio: ['ignore', 'ignore', 'ignore'] })

  try {
    const client = await connect(debugPort)
    await client.send('Page.enable')
    await client.send('Runtime.enable')
    // A fixed 1600x1000 viewport, so every screenshot has the same size regardless of window chrome.
    await client.send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false })
    // Screenshots use the dark theme; ?theme= applies it without touching the browser's saved choice.
    await client.send('Page.navigate', { url: `${baseUrl}/?theme=${theme}` })
    await waitFor(client, 'Trace volume')
    await waitFor(client, 'replay-regression-demo')
    await shot(client, 'overview-trace-launchpad.png')
    await click(client, 'Traces')
    await waitFor(client, 'More filters')
    await clickRow(client, 'research-writer-reviewer')
    await waitFor(client, 'Timeline')
    await waitFor(client, 'model.response')
    await shot(client, 'trace-detail-cockpit.png')
    await click(client, 'Sessions')
    await waitFor(client, 'demo-chat-1001')
    await waitFor(client, 'Turn 3')
    await shot(client, 'sessions.png')
    await clickLast(client, 'Open trace')
    await waitFor(client, 'Insights')
    await waitFor(client, 'identical arguments')
    await shot(client, 'trace-insights.png')
    await click(client, 'Workflows')
    await waitFor(client, 'Latest run')
    await shot(client, 'workflow-graph.png')
    await click(client, 'Costs')
    await waitFor(client, 'Monthly budget')
    await shot(client, 'cost-center.png')
    await click(client, 'Replay')
    await waitFor(client, 'Replay a trace')
    await click(client, 'Replay full trace')
    await waitFor(client, 'Replay result')
    await shot(client, 'replay-studio.png')
    await click(client, 'Connect')
    await waitFor(client, 'Connect your agents')
    await shot(client, 'connect.png')
    await click(client, 'Datasets')
    await waitFor(client, 'support-bot prompt-v2')
    await shot(client, 'datasets-experiments.png')
    await click(client, 'Compare')
    await waitFor(client, 'Regressed')
    await waitFor(client, 'model call timed out')
    await shot(client, 'experiment-compare.png')
    await click(client, 'Alerts')
    await waitFor(client, 'Agent tool loops')
    await waitFor(client, 'Swarm too large')
    await waitFor(client, 'Recent notifications')
    await shot(client, 'alerts.png')
    await click(client, 'Swarms')
    await waitFor(client, 'market research')
    await clickRow(client, 'market research')
    await waitFor(client, 'planner started 6 agents')
    await sleep(1200) // let the graph fit its view
    await shot(client, 'swarm.png')
    await click(client, 'Access')
    await waitFor(client, 'Destinations and resources')
    await waitFor(client, 'pastebin.com')
    await clickRow(client, 'pastebin.com')
    await waitFor(client, 'first seen')
    await shot(client, 'access.png')
    // An active halt for the Guardrails screenshot, released again afterwards.
    const halt = await client.send('Runtime.evaluate', {
      expression: `fetch('/api/halts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scope: 'agent', value: 'research_swarm', reason: 'Fan-out spiked to 40 sub-agents in two minutes' }) }).then(response => response.json()).then(item => item.halt_id)`,
      awaitPromise: true,
      returnByValue: true,
    })
    await click(client, 'Guardrails')
    await waitFor(client, 'production-safety')
    await waitFor(client, 'Agents are stopped')
    await shot(client, 'guardrails.png')
    await click(client, 'Approvals')
    await waitFor(client, 'issue_refund')
    await waitFor(client, 'Approve')
    await shot(client, 'approvals.png')
    await client.send('Runtime.evaluate', { expression: `fetch('/api/halts/${halt.result.result.value}/release', { method: 'POST' })`, awaitPromise: true })
    client.close()
    console.log(`Screenshots written to ${outDir}`)
  }
  finally {
    await stopProcessTree(chrome)
    await removeWithRetry(profileDir)
  }
}

function findChrome() {
  return [
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
    'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
  ].find(existsSync)
}

function getJson(port, path) {
  return new Promise((resolve, reject) => {
    get({ host: '127.0.0.1', port, path }, response => {
      let data = ''
      response.on('data', chunk => data += chunk)
      response.on('end', () => resolve(JSON.parse(data)))
    }).on('error', reject)
  })
}

async function connect(port) {
  for (let attempt = 0; attempt < 60; attempt++) {
    try {
      const pages = await getJson(port, '/json')
      const page = pages.find(item => item.type === 'page' && item.webSocketDebuggerUrl)
      if (page)
        return new Client(page.webSocketDebuggerUrl)
    }
    catch {}
    await sleep(250)
  }
  throw new Error('Chrome debugging target not found')
}

class Client {
  constructor(url) {
    this.id = 0
    this.pending = new Map()
    this.socket = new WebSocket(url)
    this.ready = new Promise(resolve => this.socket.onopen = resolve)
    this.socket.onmessage = event => {
      const message = JSON.parse(event.data)
      if (message.id && this.pending.has(message.id)) {
        this.pending.get(message.id)(message)
        this.pending.delete(message.id)
      }
    }
  }
  async send(method, params = {}) {
    await this.ready
    return new Promise(resolve => {
      const id = ++this.id
      this.pending.set(id, resolve)
      this.socket.send(JSON.stringify({ id, method, params }))
    })
  }
  close() { this.socket.close() }
}

async function waitFor(client, text) {
  for (let attempt = 0; attempt < 80; attempt++) {
    const result = await client.send('Runtime.evaluate', { expression: `document.body.innerText.includes(${JSON.stringify(text)})`, returnByValue: true })
    if (result.result.result.value)
      return
    await sleep(500)
  }
  const result = await client.send('Runtime.evaluate', { expression: 'document.body.innerText.slice(0, 1200)', returnByValue: true })
  throw new Error(`Timed out waiting for ${text}. Visible text: ${result.result.result.value ?? '<empty>'}`)
}

async function click(client, label) {
  await client.send('Runtime.evaluate', { expression: `[...document.querySelectorAll('button')].find(item => item.textContent.trim().startsWith(${JSON.stringify(label)}))?.click()` })
}

async function clickRow(client, text) {
  // Click the first table row that mentions `text`.
  await client.send('Runtime.evaluate', {
    expression: `[...document.querySelectorAll('tbody tr')].find(row => row.innerText.includes(${JSON.stringify(text)}))?.click()`,
  })
}

async function clickLast(client, label) {
  await client.send('Runtime.evaluate', { expression: `[...document.querySelectorAll('button')].filter(item => item.textContent.trim().startsWith(${JSON.stringify(label)})).pop()?.click()` })
}

async function shot(client, name) {
  await client.send('Runtime.evaluate', { expression: 'window.scrollTo(0, 0)' })
  await sleep(600)
  const result = await client.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
  writeFileSync(join(outDir, name), Buffer.from(result.result.data, 'base64'))
}

async function stopProcessTree(child) {
  if (!child.pid)
    return

  if (process.platform === 'win32') {
    await new Promise(resolve => {
      const killer = spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: ['ignore', 'ignore', 'ignore'] })
      killer.on('exit', resolve)
      killer.on('error', resolve)
    })
    return
  }

  child.kill('SIGTERM')
  await new Promise(resolve => {
    const timer = setTimeout(resolve, 1500)
    child.on('exit', () => {
      clearTimeout(timer)
      resolve()
    })
  })
}

async function removeWithRetry(path) {
  for (let attempt = 0; attempt < 12; attempt++) {
    try {
      rmSync(path, { recursive: true, force: true })
      return
    }
    catch {
      await sleep(250)
    }
  }
  console.warn(`Could not remove temporary Chrome profile: ${path}`)
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

main().catch(error => {
  console.error(error?.stack ?? error?.message ?? error)
  process.exit(1)
})
