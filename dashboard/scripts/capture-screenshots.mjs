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

async function main() {
  if (!chromePath) {
    console.error('Chrome was not found. Set CHROME_PATH to capture screenshots.')
    process.exit(1)
  }

  mkdirSync(outDir, { recursive: true })
  const chrome = spawn(chromePath, [`--remote-debugging-port=${debugPort}`, `--user-data-dir=${profileDir}`, '--headless=new', '--disable-gpu', '--no-first-run', '--window-size=1600,1100', baseUrl], { stdio: ['ignore', 'ignore', 'ignore'] })

  try {
    const client = await connect(debugPort)
    await client.send('Page.enable')
    await client.send('Runtime.enable')
    await client.send('Page.navigate', { url: baseUrl })
    await waitFor(client, 'Recent Traces')
    await waitFor(client, 'replay-regression-demo')
    await shot(client, 'overview-trace-launchpad.png')
    await click(client, 'Open')
    await waitFor(client, 'Span Tree')
    await waitFor(client, 'Waterfall Timeline')
    await waitFor(client, 'Export OTEL JSON')
    await shot(client, 'trace-detail-cockpit.png')
    await click(client, 'Workflows')
    await waitFor(client, 'Temporal Execution View')
    await shot(client, 'workflow-graph.png')
    await click(client, 'Costs')
    await waitFor(client, 'Cost Confidence')
    await shot(client, 'cost-center.png')
    await click(client, 'Replay')
    await waitFor(client, 'Replay Controls')
    await shot(client, 'replay-studio.png')
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

async function shot(client, name) {
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
