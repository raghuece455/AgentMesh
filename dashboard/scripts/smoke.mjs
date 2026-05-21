import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { get } from 'node:http'
import { join, resolve } from 'node:path'
import { tmpdir } from 'node:os'

const baseUrl = process.env.AGENTMESH_DASHBOARD_URL ?? 'http://127.0.0.1:8790'
const chromePath = process.env.CHROME_PATH ?? findChrome()
const debugPort = Number(process.env.AGENTMESH_SMOKE_DEBUG_PORT ?? String(9300 + Math.floor(Math.random() * 400)))
const profileDir = join(tmpdir(), `agentmesh-dashboard-smoke-${Date.now()}`)
const screenshotDir = resolve(process.cwd(), 'smoke-artifacts')
const debug = process.env.AGENTMESH_SMOKE_DEBUG === '1'

async function main() {
  if (!chromePath)
    fail('Chrome was not found. Set CHROME_PATH to run dashboard smoke tests.')

  await assertServer(baseUrl)
  mkdirSync(screenshotDir, { recursive: true })

  const chrome = spawn(chromePath, [
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${profileDir}`,
    '--headless=new',
    '--disable-gpu',
    '--no-first-run',
    '--window-size=1600,1100',
    baseUrl,
  ], { stdio: ['ignore', 'ignore', 'ignore'] })

  try {
    const client = await connectToPage(debugPort)
    await client.send('Page.enable')
    await client.send('Runtime.enable')
    await client.send('Page.navigate', { url: baseUrl })
    await waitForText(client, ['Trace-first Agent Observability', 'Recent Traces', 'Failure Inbox', 'Provider Health'])
    await waitForText(client, ['replay-regression-demo'])
    await assertText(client, 'Cost Status')
    await assertText(client, 'Backend')
    await assertText(client, 'Open')
    await clickButtonByText(client, 'Open')
    await waitForText(client, ['Trace Explorer', 'Trace Detail', 'Span Tree', 'Waterfall Timeline', 'Inspector'])
    await assertText(client, 'Summary')
    await assertText(client, 'Cost')
    await assertText(client, 'Export OTEL JSON')
    await screenshot(client, join(screenshotDir, 'trace-detail-smoke.png'))
    await clickButtonByText(client, 'Costs')
    await waitForText(client, ['Cost Confidence', 'Cost By Workflow'])
    await clickButtonByText(client, 'Replay')
    await waitForText(client, ['Replay Controls', 'Replay Comparison'])
    client.close()
    console.log('Dashboard smoke test passed.')
  }
  finally {
    await stopProcessTree(chrome)
    await removeWithRetry(profileDir)
  }
}

function findChrome() {
  const candidates = process.platform === 'win32'
    ? [
        'C:/Program Files/Google/Chrome/Application/chrome.exe',
        'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
        'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
        'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
      ]
    : [
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/usr/bin/google-chrome',
        '/usr/bin/chromium',
        '/usr/bin/chromium-browser',
      ]
  return candidates.find(existsSync)
}

async function assertServer(url) {
  try {
    await fetch(url)
  }
  catch {
    fail(`Dashboard is not reachable at ${url}. Start it first or set AGENTMESH_DASHBOARD_URL.`)
  }
}

function getJson(port, path) {
  return new Promise((resolve, reject) => {
    get({ host: '127.0.0.1', port, path }, response => {
      let data = ''
      response.on('data', chunk => data += chunk)
      response.on('end', () => {
        try {
          resolve(JSON.parse(data))
        }
        catch (error) {
          reject(error)
        }
      })
    }).on('error', reject)
  })
}

async function connectToPage(port) {
  for (let attempt = 0; attempt < 60; attempt++) {
    try {
      const pages = await getJson(port, '/json')
      if (debug)
        console.log(`debug attempt ${attempt}: ${pages.map(item => `${item.type}:${item.url}`).join(' | ')}`)
      const page = pages.find(item => item.type === 'page' && item.webSocketDebuggerUrl)
      if (page)
        return new DevToolsClient(page.webSocketDebuggerUrl)
    }
    catch (error) {
      if (debug)
        console.log(`debug attempt ${attempt}: ${error?.message ?? error}`)
    }
    await sleep(250)
  }
  fail('Could not connect to Chrome debugging target.')
}

class DevToolsClient {
  constructor(url) {
    this.id = 0
    this.pending = new Map()
    this.socket = new WebSocket(url)
    this.ready = new Promise(resolve => {
      this.socket.onopen = resolve
    })
    this.socket.onmessage = event => {
      const message = JSON.parse(event.data)
      if (message.id && this.pending.has(message.id)) {
        this.pending.get(message.id)(message)
        this.pending.delete(message.id)
      }
      if (message.method === 'Runtime.exceptionThrown') {
        console.error(message.params.exceptionDetails.exception?.description ?? message.params.exceptionDetails.text)
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

  close() {
    this.socket.close()
  }
}

async function pageText(client) {
  const result = await client.send('Runtime.evaluate', { expression: 'document.body.innerText', returnByValue: true })
  return result.result.result.value ?? ''
}

async function waitForText(client, required) {
  for (let attempt = 0; attempt < 80; attempt++) {
    const text = await pageText(client)
    if (required.every(item => text.includes(item)))
      return
    await sleep(500)
  }
  const text = await pageText(client)
  fail(`Timed out waiting for page text: ${required.join(', ')}. Visible text: ${text.slice(0, 1200) || '<empty>'}`)
}

async function assertText(client, required) {
  const text = await pageText(client)
  if (!text.includes(required))
    fail(`Expected dashboard text not found: ${required}`)
}

async function clickButtonByText(client, text) {
  const expression = `
    (() => {
      const button = [...document.querySelectorAll('button')].find(item => item.textContent.trim().startsWith(${JSON.stringify(text)}));
      if (!button) return false;
      button.click();
      return true;
    })()
  `
  const result = await client.send('Runtime.evaluate', { expression, returnByValue: true })
  if (!result.result.result.value)
    fail(`Button not found: ${text}`)
}

async function screenshot(client, file) {
  const result = await client.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
  writeFileSync(file, Buffer.from(result.result.data, 'base64'))
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

function fail(message) {
  console.error(message)
  process.exit(1)
}

main().catch(error => {
  console.error(error?.stack ?? error?.message ?? error)
  process.exit(1)
})
