import { useEffect, useState } from 'react'

interface HealthResponse {
  status: string
}

function App() {
  const [health, setHealth] = useState('checking...')

  useEffect(() => {
    fetch('/api/health')
      .then((response) => response.json() as Promise<HealthResponse>)
      .then((data) => setHealth(data.status))
      .catch(() => setHealth('unreachable'))
  }, [])

  return (
    <main>
      <h1>Oral Korean</h1>
      <p>Backend status: {health}</p>
    </main>
  )
}

export default App
