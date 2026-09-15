import { AlertTriangle, Copy, KeyRound, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { isUnauthorizedError } from '../../api'
import type { ConnectionState } from '../../appTypes'
import { formatTime } from '../../utils/format'
import { Button } from '../ui/Button'
import { Callout } from '../ui/Card'
import { Input } from '../ui/Field'

export function ConnectionBanner({ connection, error, onRetry, onApiKey }: { connection: ConnectionState; error: string; onRetry: () => void; onApiKey: (key: string) => void }) {
  const [keyInput, setKeyInput] = useState('')
  if (!error && connection.backendStatus !== 'failed')
    return null
  if (isUnauthorizedError(connection.lastError || error)) {
    return (
      <Callout
        tone="info"
        icon={<KeyRound />}
        title="API key required"
        actions={(
          <form
            className="flex flex-wrap gap-2"
            onSubmit={event => {
              event.preventDefault()
              onApiKey(keyInput.trim())
              setKeyInput('')
            }}
          >
            <Input type="password" aria-label="AgentMesh API key" placeholder="AGENTMESH_API_KEY" className="w-60" value={keyInput} onChange={event => setKeyInput(event.target.value)} />
            <Button type="submit" variant="primary" icon={<KeyRound />} disabled={!keyInput.trim()}>Unlock</Button>
          </form>
        )}
      >
        This server runs with AGENTMESH_AUTH_MODE=api_key. The key is stored in this browser only.
      </Callout>
    )
  }
  const diagnostics = {
    failed_endpoint: connection.lastFailedEndpoint,
    error: connection.lastError || error,
    backend_status: connection.backendStatus,
    live_status: connection.liveStatus,
    last_successful_refresh: connection.lastSuccessfulRefresh,
    last_live_event: connection.lastLiveEvent,
    retry_count: connection.retryCount,
  }
  return (
    <Callout
      tone="warning"
      icon={<AlertTriangle />}
      title="Could not reach the AgentMesh API"
      actions={(
        <>
          <Button icon={<RefreshCw />} onClick={onRetry}>Retry</Button>
          <Button variant="ghost" icon={<Copy />} onClick={() => void navigator.clipboard?.writeText(JSON.stringify(diagnostics, null, 2))}>Copy diagnostics</Button>
        </>
      )}
    >
      {connection.lastFailedEndpoint ?? 'A request'} failed{connection.lastSuccessfulRefresh ? `; last successful refresh at ${formatTime(connection.lastSuccessfulRefresh)}` : ''}. Retries: {connection.retryCount}.
    </Callout>
  )
}
