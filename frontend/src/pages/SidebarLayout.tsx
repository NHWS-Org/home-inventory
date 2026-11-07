import { version as frontendVersion } from '../../package.json';
import { ReactNode, useState, useEffect } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { Dialog } from '@headlessui/react'
import GlobalBarcodeScan from '../components/GlobalBarcodeScan'
import NotificationBell from '../components/NotificationBell'
import NotificationClickReader from '../components/NotificationClickReader'
import { useAuth } from '../useAuth'
import { getApiVersion } from '../api'
import { FiLogOut, FiCompass, FiBox, FiCheckSquare, FiSettings, FiLogIn, FiUser, FiSun, FiMoon, FiMonitor, FiInfo } from 'react-icons/fi'
import { useBottomSheetDrag } from '../components/useBottomSheetDrag'

type ThemeMode = 'light' | 'dark' | 'system'

const THEME_STORAGE_KEY = 'theme-mode'

function getStoredTheme(): ThemeMode {
  const stored = localStorage.getItem(THEME_STORAGE_KEY)
  return stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'system'
}

interface SidebarLayoutProps {
  children: ReactNode
}

export default function SidebarLayout({ children }: SidebarLayoutProps) {
  const location = useLocation()
  const [apiVersion, setApiVersion] = useState<string | null>(null)
  const [themeMode, setThemeMode] = useState<ThemeMode>(getStoredTheme)
  const [accountOpen, setAccountOpen] = useState(false)

  const auth = useAuth()
  const { logout } = auth
  const user = auth.user ?? null
  const isInventoryDetail = /^\/inventories\/[^/]+/.test(location.pathname)
  const isChecklistDetail = /^\/checklists\/[^/]+/.test(location.pathname)
  const isItemDetail = isInventoryDetail || isChecklistDetail
  const mobileSectionTitle = isInventoryDetail ? 'Inventari'
    : isChecklistDetail ? 'Liste'
      : location.pathname === '/' ? 'Home'
      : location.pathname === '/inventories' ? 'Inventari'
        : location.pathname === '/checklists' ? 'Liste'
          : location.pathname.startsWith('/settings') ? 'Impostazioni'
            : location.pathname === '/about' ? 'About'
              : location.pathname === '/profile' ? 'Profilo'
                : location.pathname === '/notifications' ? 'Centro notifiche'
                : null

  useEffect(() => {
    getApiVersion()
      .then((data) => setApiVersion(data.version))
      .catch(() => setApiVersion(null))
  }, [])

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    const updateTheme = () => {
      const isDark = themeMode === 'dark' || (themeMode === 'system' && mediaQuery.matches)
      document.documentElement.classList.toggle('dark', isDark)
      document.documentElement.style.colorScheme = isDark ? 'dark' : 'light'
    }

    localStorage.setItem(THEME_STORAGE_KEY, themeMode)
    updateTheme()
    if (themeMode === 'system') {
      mediaQuery.addEventListener('change', updateTheme)
      return () => mediaQuery.removeEventListener('change', updateTheme)
    }
  }, [themeMode])

  const closeAccount = () => setAccountOpen(false)
  const accountSheetDrag = useBottomSheetDrag(closeAccount)
  const themeModes: ThemeMode[] = ['light', 'dark', 'system']
  const themeLabels: Record<ThemeMode, string> = {
    light: 'Chiaro',
    dark: 'Scuro',
    system: 'Sistema',
  }
  const themeIcons = {
    light: FiSun,
    dark: FiMoon,
    system: FiMonitor,
  }
  const ThemeIcon = themeIcons[themeMode]
  const nextTheme = themeLabels[themeModes[(themeModes.indexOf(themeMode) + 1) % themeModes.length]]
  const navItemClass = (isActive: boolean) =>
    `flex min-h-14 min-w-0 flex-1 flex-col items-center justify-center gap-1 rounded-xl px-0.5 py-1 text-center transition-colors ${
      isActive
        ? 'bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-200'
        : 'text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800'
    }`

  return (
    <div className="flex h-screen overflow-hidden">
      {user && <div className="fixed right-20 top-4 z-50 rounded bg-white text-gray-900 dark:bg-gray-900 dark:text-white md:hidden">
        <NotificationBell key={user.id} />
      </div>}
      <button
        type="button"
        onClick={() => setAccountOpen(true)}
        aria-label="Apri account e preferenze"
        title="Account e preferenze"
        className="fixed left-4 top-4 z-50 flex h-12 w-12 items-center justify-center rounded-xl bg-gray-800 text-xl text-white shadow-md hover:bg-gray-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 md:hidden"
      >
        <FiUser aria-hidden="true" />
      </button>
      {/* Sidebar */}
      <div
        className="relative hidden h-screen w-64 shrink-0 flex-col bg-gray-800 p-4 text-white dark:bg-gray-800 dark:text-gray-300 md:flex"
      >
        {user && user.username ? (
          <div className="mb-6">
            <p className="font-semibold capitalize">Ciao, {user.username}</p>
            <p className="text-sm capitalize text-gray-300">{user.role?.name}</p>
            <Link to="/profile" state={{ from: location.pathname + location.search }} className="text-blue-300 text-sm block mt-1">
              <span className="flex items-center gap-2"><FiUser className="shrink-0"/>Gestione profilo</span>
            </Link>
            <button
              onClick={() => {
                logout()
                  .then(() => {
                    window.location.href = '/'
                  })
                  .catch(() => {
                    window.location.href = '/'
                  })
              }}
              className="text-red-400 text-sm mt-1 block text-left flex items-center gap-1"
            >
              <FiLogOut className="inline" />
              <span>Logout</span>
            </button>
          </div>
        ) : (
          <Link to="/login" className="block text-blue-300 mb-4">
            <span className="flex items-center gap-2"><FiLogIn className="shrink-0"/>Login / Registrazione</span>
          </Link>
        )}

        <nav className="space-y-2">
          <NavLink
            to="/"
            className={({ isActive }) =>
              `flex items-center gap-3 hover:text-blue-300 ` +
              (isActive
                ? 'bg-gradient-to-r from-blue-500 to-blue-700 text-white rounded-xl px-4 py-3'
                : 'px-4 py-3')
            }
          >
            <FiCompass className="text-lg shrink-0" />
            <span>Home</span>
          </NavLink>
          {user && user.username && (
            <NavLink
              to="/inventories"
              className={({ isActive }) =>
                `flex items-center gap-3 hover:text-blue-300 ` +
                (isActive
                  ? 'bg-gradient-to-r from-blue-500 to-blue-700 text-white rounded-xl px-4 py-3'
                  : 'px-4 py-3')
              }
            >
              <FiBox className="text-lg shrink-0" />
              <span>Inventari</span>
            </NavLink>
          )}
          {user && user.username && (
            <NavLink
              to="/checklists"
              className={({ isActive }) =>
                `flex items-center gap-3 hover:text-blue-300 ` +
                (isActive
                  ? 'bg-gradient-to-r from-blue-500 to-blue-700 text-white rounded-xl px-4 py-3'
                  : 'px-4 py-3')
              }
            >
              <FiCheckSquare className="text-lg shrink-0" />
              <span>Liste</span>
            </NavLink>
          )}
          {user && user.username && user.role?.name === 'admin' && (
            <NavLink
              to="/settings"
              className={({ isActive }) =>
                `flex items-center gap-3 hover:text-blue-300 ` +
                (isActive
                  ? 'bg-gradient-to-r from-blue-500 to-blue-700 text-white rounded-xl px-4 py-3'
                  : 'px-4 py-3')
              }
            >
              <FiSettings className="text-lg shrink-0" />
              <span>Impostazioni</span>
            </NavLink>
          )}
          <NavLink
            to="/about"
            className={({ isActive }) =>
              `flex items-center gap-3 hover:text-blue-300 ` +
              (isActive
                ? 'bg-gradient-to-r from-blue-500 to-blue-700 text-white rounded-xl px-4 py-3'
                : 'px-4 py-3')
            }
          >
            <FiInfo className="text-lg shrink-0" />
            <span>About</span>
          </NavLink>
          {user && <NotificationBell key={user.id} />}
        </nav>

        <div className="mt-6 border-t border-gray-600 pt-4">
          <button
            type="button"
            onClick={() => setThemeMode(themeModes[(themeModes.indexOf(themeMode) + 1) % themeModes.length])}
            aria-label={`Tema ${themeLabels[themeMode]}. Passa a ${nextTheme}`}
            title={`Tema: ${themeLabels[themeMode]} · clicca per ${nextTheme.toLowerCase()}`}
            className="flex w-full items-center justify-center rounded-lg px-4 py-3 text-gray-300 transition-colors hover:bg-gray-700 hover:text-white"
          >
            <ThemeIcon className="text-xl" aria-hidden="true" />
          </button>
        </div>

        {/* Footer */}
        <div className="absolute bottom-4 left-4 right-4 text-xs text-gray-400">
          <hr className="mb-2 border-gray-600" />
          <p>API v{apiVersion ?? '...'}</p>
          <p>Frontend v{frontendVersion}</p>
          <p className="mt-1">
            © 2025-{new Date().getFullYear()} <a href="https://github.com/napalmz" target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline">napalmz</a>
          </p>
        </div>

      </div>
      {/* Contenuto */}
      <div className={`ml-0 w-full flex-1 overflow-auto px-4 pb-28 dark:bg-gray-900 dark:text-white sm:px-6 md:p-6 ${isItemDetail ? 'pt-40 md:pt-6' : 'pt-16 md:pt-6'}`}>
        <NotificationClickReader />
        {location.pathname.startsWith('/settings') && <h1 className="mb-5 hidden text-2xl font-bold md:block">Impostazioni</h1>}
        {children}
      </div>
      <GlobalBarcodeScan />

      <div aria-hidden="true" className={`pointer-events-none fixed inset-x-0 top-0 z-40 bg-white/95 backdrop-blur dark:bg-gray-900/95 md:hidden ${isItemDetail ? 'h-40' : 'h-16'}`} />
      {mobileSectionTitle && <div className={`pointer-events-none fixed inset-x-0 top-4 z-[45] flex h-12 items-center justify-center pl-20 text-center ${location.pathname === '/notifications' ? 'text-base' : 'text-xl'} font-bold md:hidden ${user ? 'pr-40' : 'pr-20'}`}>{mobileSectionTitle}</div>}

      <nav aria-label="Navigazione principale" className="fixed inset-x-0 bottom-0 z-40 flex items-stretch gap-0.5 border-t border-gray-200 bg-white/95 px-1 pt-1 pb-[calc(env(safe-area-inset-bottom))] shadow-[0_-4px_16px_rgba(0,0,0,0.08)] backdrop-blur dark:border-gray-700 dark:bg-gray-900/95 md:hidden">
        <NavLink to="/" end className={({ isActive }) => navItemClass(isActive)}>
          <FiCompass className="text-xl" aria-hidden="true" /><span className="text-[11px] leading-tight">Home</span>
        </NavLink>
        {user?.username && <NavLink to="/inventories" className={({ isActive }) => navItemClass(isActive)}>
          <FiBox className="text-xl" aria-hidden="true" /><span className="text-[11px] leading-tight">Inventari</span>
        </NavLink>}
        {user?.username && <NavLink to="/checklists" className={({ isActive }) => navItemClass(isActive)}>
          <FiCheckSquare className="text-xl" aria-hidden="true" /><span className="text-[11px] leading-tight">Liste</span>
        </NavLink>}
        {user?.username && user.role?.name === 'admin' && <NavLink to="/settings" className={({ isActive }) => navItemClass(isActive)}>
          <FiSettings className="text-xl" aria-hidden="true" /><span className="break-words text-[11px] leading-tight">Impostazioni</span>
        </NavLink>}
        <NavLink to="/about" className={({ isActive }) => navItemClass(isActive)}>
          <FiInfo className="text-xl" aria-hidden="true" /><span className="text-[11px] leading-tight">About</span>
        </NavLink>
      </nav>

      <Dialog open={accountOpen} onClose={closeAccount} className="relative z-[70] md:hidden">
        <div className="fixed inset-0 bg-black/40" aria-hidden="true" />
        <div className="fixed inset-0 flex items-end justify-center">
          <Dialog.Panel
            style={{ transform: `translateY(${accountSheetDrag.offset}px)`, transition: accountSheetDrag.isDragging ? 'none' : 'transform 220ms ease-out' }}
            className="max-h-[80dvh] w-full overflow-y-auto rounded-t-3xl bg-white p-5 pb-[calc(env(safe-area-inset-bottom)+1rem)] shadow-2xl dark:bg-gray-900 dark:text-white"
          >
            <button type="button" aria-label="Chiudi o trascina verso il basso" {...accountSheetDrag.gripProps} className="mx-auto mb-3 flex h-8 w-16 touch-none items-center justify-center">
              <span className="h-1 w-10 rounded-full bg-gray-300 dark:bg-gray-600" aria-hidden="true" />
            </button>
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <Dialog.Title className="text-lg font-semibold">{user?.username ? `Ciao, ${user.username}` : 'Account'}</Dialog.Title>
                {user?.role?.name && <p className="mt-1 text-sm capitalize text-gray-500 dark:text-gray-400">{user.role.name}</p>}
              </div>
              <button type="button" onClick={closeAccount} aria-label="Chiudi" className="grid h-10 w-10 shrink-0 place-items-center rounded-xl text-2xl text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800">×</button>
            </div>

            {user?.username ? (
              <div className="mb-5 grid gap-2">
                <Link to="/profile" state={{ from: location.pathname + location.search }} onClick={closeAccount} className="flex min-h-12 items-center gap-3 rounded-xl bg-blue-50 px-4 font-medium text-blue-800 dark:bg-blue-950/50 dark:text-blue-200">
                  <FiUser aria-hidden="true" /> Gestione profilo
                </Link>
                <button
                  type="button"
                  onClick={() => {
                    void logout().catch(() => undefined).finally(() => { window.location.href = '/'; });
                  }}
                  className="flex min-h-12 items-center gap-3 rounded-xl bg-red-50 px-4 text-left font-medium text-red-700 dark:bg-red-950/40 dark:text-red-300"
                >
                  <FiLogOut aria-hidden="true" /> Esci
                </button>
              </div>
            ) : (
              <Link to="/login" onClick={closeAccount} className="mb-5 flex min-h-12 items-center gap-3 rounded-xl bg-blue-600 px-4 font-medium text-white">
                <FiLogIn aria-hidden="true" /> Login / Registrazione
              </Link>
            )}

            <section aria-label="Scelta tema">
              <h3 className="mb-2 text-sm font-medium text-gray-600 dark:text-gray-300">Tema</h3>
              <div className="grid grid-cols-3 gap-2">
                {themeModes.map((mode) => {
                  const Icon = themeIcons[mode];
                  return (
                    <button key={mode} type="button" aria-pressed={themeMode === mode} onClick={() => setThemeMode(mode)} className={`flex min-h-12 items-center justify-center gap-2 rounded-xl border px-2 text-sm font-medium ${themeMode === mode ? 'border-blue-600 bg-blue-50 text-blue-800 dark:bg-blue-950/50 dark:text-blue-200' : 'border-gray-200 text-gray-700 dark:border-gray-700 dark:text-gray-200'}`}>
                      <Icon aria-hidden="true" /> {themeLabels[mode]}
                    </button>
                  );
                })}
              </div>
            </section>
          </Dialog.Panel>
        </div>
      </Dialog>
    </div>
  )
}
