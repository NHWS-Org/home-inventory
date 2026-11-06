import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { loginDestination } from '../utils/loginRedirect'
import { FiEye, FiEyeOff, FiLoader } from 'react-icons/fi'
import { loginUser, getUserInfo } from '../api'
import { useAuth } from '../useAuth'
import { User } from '../types'

function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const destination = loginDestination(location.search)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const { setUser } = useAuth()

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)
    try {
      const data = await loginUser(username, password)
      localStorage.setItem('access_token', data.access_token)
      const userInfo = await getUserInfo()
      if (userInfo && typeof userInfo === 'object' && 'username' in userInfo) {
        setUser(userInfo as User)
      } else {
        console.error('Formato utente non valido ricevuto da getUserInfo:', userInfo)
      }
      navigate(destination, { replace: true })
    } catch (err: unknown) {
      setIsLoading(false)
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
          <div className="relative">
            <input
              id="password"
              type={showPassword ? 'text' : 'password'}
              className="w-full border px-3 py-2 pr-10 rounded dark:bg-gray-800 dark:text-white dark:border-gray-700"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
            />
            <button
              type="button"
              onClick={() => setShowPassword(prev => !prev)}
              aria-label={showPassword ? 'Nascondi password' : 'Mostra password'}
              title={showPassword ? 'Nascondi password' : 'Mostra password'}
              className="absolute inset-y-0 right-0 flex items-center px-3 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded-r"
            >
              {showPassword ? (
                <FiEyeOff className="h-5 w-5" aria-hidden="true" />
              ) : (
                <FiEye className="h-5 w-5" aria-hidden="true" />
              )}
            </button>
          </div>
        </div>
        <button
          type="submit"
          disabled={isLoading}
          aria-busy={isLoading}
          className="flex w-full items-center justify-center gap-2 rounded bg-blue-600 px-4 py-2 font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isLoading ? (
            <>
              <FiLoader className="h-5 w-5 animate-spin" aria-hidden="true" />
              <span>Accesso in corso...</span>
            </>
          ) : (
            'Login'
          )}
        </button>
        <p className="text-sm mt-4 text-center">
          Non hai un account? <a href={destination === '/' ? '/register' : `/register?${new URLSearchParams({ returnTo: destination })}`} className="text-blue-600 hover:underline">Registrati</a>
        </p>
      </form>
    </div>
  )
}

export default LoginPage