import React, { lazy, Suspense } from "react";
import { BrowserRouter as Router, Routes, Route, Navigate, Outlet } from 'react-router-dom'
import ProtectedRoute    from "./pages/ProtectedRoute"
import SidebarLayout     from './pages/SidebarLayout'
import Spinner           from './components/Spinner'
import EnvBadge          from './components/EnvBadge'
import { getApiVersion } from "./api";
import { version as frontendVersion } from '../package.json';

const WelcomePage       = lazy(() => import('./pages/WelcomePage'))
const LoginPage         = lazy(() => import('./pages/LoginPage'))
const RegisterPage      = lazy(() => import('./pages/RegisterPage'))
const ProfilePage       = lazy(() => import('./pages/ProfilePage'))
const NotificationsPage = lazy(() => import('./pages/NotificationsPage'))
const FilterManagementPage = lazy(() => import('./pages/FilterManagementPage'))
const SettingsPage      = lazy(() => import('./pages/SettingsPage'))
const AboutPage         = lazy(() => import('./pages/AboutPage'))
const GenericListPage   = lazy(() => import('./pages/GenericListPage'))
const GenericDetailPage = lazy(() => import('./pages/GenericDetailPage'))

function getFrontendVersion(): string {
  // Usa la versione dal package.json (iniettata in build) oppure fallback
  return frontendVersion || "0.0.0";
}

function parseVersion(version: string): [number, number] {
  const [major, minor] = version.split(".").map(Number);
  return [major || 0, minor || 0];
}

function App() {
  const [versionError, setVersionError] = React.useState<string | null>(null);

  React.useEffect(() => {
    getApiVersion().then(({ version }) => {
      const frontendVersion = getFrontendVersion();
      const [fmj, fmn] = parseVersion(frontendVersion);
      const [bmj, bmn] = parseVersion(version);
      if (fmj !== bmj || fmn !== bmn) {
        setVersionError(
          `Versione frontend ${frontendVersion} e backend ${version} non compatibili. Contatta l'amministratore.`
        );
      }
    }).catch(() => {
      setVersionError("Impossibile verificare la versione del backend.");
    });
  }, []);

  if (versionError) {
    return (
      <div className="p-8 text-center text-red-600 dark:text-red-400">
        <h1 className="text-2xl font-bold mb-2">Errore di versione</h1>
        <p>{versionError}</p>
      </div>
    );
  }

  return (
    <Router>
      <EnvBadge />
      <Routes>
        <Route element={<SidebarLayout><Suspense fallback={<Spinner />}><Outlet /></Suspense></SidebarLayout>}>
          <Route path="/" element={<WelcomePage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="/inventories" element={
            <ProtectedRoute>
              <GenericListPage />{/* <InventoryListPage /> */}
            </ProtectedRoute>
          } />
          <Route path="/checklists" element={
            <ProtectedRoute>
              <GenericListPage />{/* <ChecklistListPage /> */}
            </ProtectedRoute>
          } />
          <Route path="/profile" element={
            <ProtectedRoute>
              <ProfilePage />
            </ProtectedRoute>
          } />
          <Route path="/notifications" element={
            <ProtectedRoute>
              <NotificationsPage />
            </ProtectedRoute>
          } />
          <Route path="/filters" element={
            <ProtectedRoute>
              <FilterManagementPage />
            </ProtectedRoute>
          } />
          <Route path="/triggers" element={
            <ProtectedRoute>
              <FilterManagementPage />
            </ProtectedRoute>
          } />
          <Route path="/settings" element={
            <ProtectedRoute requireAdmin={true}>
              <SettingsPage />
            </ProtectedRoute>
          } />
          <Route path="/inventories/:id" element={
            <ProtectedRoute>
              <GenericDetailPage />
            </ProtectedRoute>
          } />
          <Route path="/checklists/:id" element={
            <ProtectedRoute>
              <GenericDetailPage />
            </ProtectedRoute>
          } />
          {/* Aggiungi qui eventuali altre rotte visibili nel layout*/}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
        </Route>

        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </Router>
  )
}

export default App
