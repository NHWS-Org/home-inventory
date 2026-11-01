import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { loginUser, getUserInfo } from '../api'
import { useAuth } from '../useAuth'
import { User } from '../types'

function LoginPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const { setUser } = useAuth()

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      const data = await loginUser(username, password)
      localStorage.setItem('access_token', data.access_token)
      const userInfo = await getUserInfo()
      if (userInfo && typeof userInfo === 'object' && 'username' in userInfo) {
        setUser(userInfo as User)
      } else {
        console.error('Formato utente non valido ricevuto da getUserInfo:', userInfo)
      }
      navigate('/')
    } catch (err: unknown) {
      localStorage.removeItem('access_token');
      console.error('Login error:', err)
  
      if (
        typeof err === 'object' &&
        err !== null &&
        'response' in err &&
        typeof (err as { response?: { data?: { detail?: string } } }).response?.data?.detail === 'string'
      ) {
        setError((err as { response?: { data?: { detail?: string } } }).response!.data!.detail!)
      } else if (err instanceof Error) {
        setError(`Errore: ${err.message}`)
      } else {
        setError('Errore durante il login')
      }
    }
  }

  return (
    <div className="flex items-center justify-center h-screen bg-gray-100 dark:bg-gray-800">
      <form onSubmit={handleLogin} className="bg-white dark:bg-gray-900 p-8 rounded shadow-md w-full max-w-sm">
        <h2 className="text-2xl font-bold mb-6 text-center">Login</h2>
        {error && <p className="text-red-500 text-sm mb-4">{error}</p>}
        <div className="mb-4">
          <label className="block text-sm font-medium mb-1" htmlFor="username">Username</label>
          <input
            id="username"
            type="text"
            className="w-full border px-3 py-2 rounded"
            value={username}
            onChange={e => setUsername(e.target.value)}
            autoCapitalize="none"
            autoCorrect="off"
            required
          />
        </div>
        <div className="mb-6">
          <label className="block text-sm font-medium mb-1" htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            className="w-full border px-3 py-2 rounded"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
          />
        </div>
        <button
          type="submit"
          className="w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 px-4 rounded"
        >
          Login
        </button>
        <p className="text-sm mt-4 text-center">
          Non hai un account? <a href="/register" className="text-blue-600 hover:underline">Registrati</a>
        </p>
      </form>
    </div>
  )
}

export default LoginPage