import { useCallback, useEffect, useRef, useState, useSyncExternalStore, type KeyboardEvent, type ReactNode } from "react";
import { cleanupDeviceSessions, getDeviceSessions, getUserInfo, revokeDeviceSession, updateMe, type DeviceSession } from "../api";
import { Link, useLocation } from "react-router-dom";
import { FiAlertCircle, FiCheckCircle, FiChevronDown, FiClock, FiSlash } from "react-icons/fi";
import PushNotificationsPanel from "../components/PushNotificationsPanel";
import NotificationPreferences from "../components/NotificationPreferences";
import { disablePushForBrowser, type PushBrowserState } from "../utils/pushNotifications";
import { SESSION_RENEWED } from "../utils/sessionRenewal";
import { useAuth } from "../useAuth";

const desktopQuery = "(min-width: 768px)";

function subscribeDesktopLayout(onChange: () => void) {
  const media = window.matchMedia(desktopQuery);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

function isDesktopLayout() {
  return window.matchMedia(desktopQuery).matches;
}

type ProfileTab = "personal" | "password" | "push" | "notifications" | "devices";

function ProfileSection({ title, headingId, badge, children, sectionId, desktop, active }: {
  title: string;
  headingId?: string;
  badge?: ReactNode;
  children: ReactNode;
  sectionId: ProfileTab;
  desktop: boolean;
  active: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div
      id={`profile-panel-${sectionId}`}
      role={desktop ? "tabpanel" : undefined}
      aria-labelledby={desktop ? `profile-tab-${sectionId}` : undefined}
      hidden={desktop && !active}
      tabIndex={desktop ? 0 : undefined}
      className="min-w-0 focus-visible:outline-2 focus-visible:outline-blue-500"
    >
      <details
        className={desktop ? "group" : "group rounded-xl border border-gray-200 dark:border-gray-700"}
        open={desktop || expanded}
        onToggle={event => { if (!desktop) setExpanded(event.currentTarget.open); }}
      >
        <summary hidden={desktop} className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-3 rounded-xl px-4 py-3 hover:bg-gray-50 focus-visible:outline-2 focus-visible:outline-blue-500 dark:hover:bg-gray-800">
          <h2 id={desktop ? undefined : headingId} className="text-base font-bold">{title}</h2>
          <span className="flex shrink-0 items-center gap-3">
            {badge}
            <FiChevronDown aria-hidden="true" className="transition-transform group-open:rotate-180" />
          </span>
        </summary>
        <div className={desktop ? "space-y-4" : "space-y-4 border-t border-gray-200 p-4 dark:border-gray-700"}>
          {desktop && <h2 id={headingId} className="text-lg font-bold">{title}</h2>}
          {children}
        </div>
      </details>
    </div>
  );
}

export function PushStatusBadge({ state }: { state: PushBrowserState }) {
  const active = state === "active";
  const checking = state === "checking";
  const error = state === "error";
  const label = checking ? "Verifica notifiche push in corso"
    : error ? "Stato notifiche push non disponibile"
    : active ? "Notifiche push attive su questo browser"
    : "Notifiche push non attive su questo browser";
  const Icon = checking ? FiClock : error ? FiAlertCircle : active ? FiCheckCircle : FiSlash;
  return (
    <span role="status" title={label} className={
      error ? "text-amber-700 dark:text-amber-400"
        : active ? "text-green-700 dark:text-green-400" : "text-gray-500 dark:text-gray-400"
    }>
      <Icon aria-hidden="true" className="h-5 w-5" />
      <span className="sr-only">{label}</span>
    </span>
  );
}

export function DeviceCountBadge({ status, sessions }: {
  status: "loading" | "ready" | "error";
  sessions: DeviceSession[];
}) {
  const count = sessions.filter((session) => !session.revoked_at && !session.is_expired).length;
  const label = status === "loading" ? "Verifica dispositivi in corso"
    : status === "error" ? "Numero dispositivi non disponibile"
    : `${count} ${count === 1 ? "sessione attiva" : "sessioni attive"}`;
  return (
    <span role="status" title={label} className="inline-flex min-w-7 items-center justify-center rounded-full bg-gray-100 px-2 py-0.5 text-sm font-medium text-gray-700 dark:bg-gray-800 dark:text-gray-200">
      <span aria-hidden="true">{status === "ready" ? count : status === "loading" ? "…" : "!"}</span>
      <span className="sr-only">{label}</span>
    </span>
  );
}

const ProfilePage = () => {
  const { user } = useAuth();
  const location = useLocation();
  const previousPath = (location.state as { from?: string } | null)?.from;
  const returnPath = previousPath?.startsWith("/") && !previousPath.startsWith("/profile") ? previousPath : "/";
  const [email, setEmail] = useState("");
  const [initialEmail, setInitialEmail] = useState("");
  const [maskedEmail, setMaskedEmail] = useState("");
  const [editEmail, setEditEmail] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [message, setMessage] = useState("");
  const [passwordMessage, setPasswordMessage] = useState("");
  const [showMessage, setShowMessage] = useState(false);
  const [showPasswordMessage, setShowPasswordMessage] = useState(false);
  const [messageCountdown, setMessageCountdown] = useState(5);
  const [passwordCountdown, setPasswordCountdown] = useState(5);
  const [isPasswordError, setIsPasswordError] = useState(false);
  const [deviceSessions, setDeviceSessions] = useState<DeviceSession[]>([]);
  const [sessionMessage, setSessionMessage] = useState("");
  const [sessionNotice, setSessionNotice] = useState("");
  const [sessionsBusy, setSessionsBusy] = useState(false);
  const [sessionsStatus, setSessionsStatus] = useState<"loading" | "ready" | "error">("loading");
  const [pushState, setPushState] = useState<PushBrowserState>("checking");
  const desktop = useSyncExternalStore(subscribeDesktopLayout, isDesktopLayout, () => false);
  const [activeTab, setActiveTab] = useState<ProfileTab>("personal");
  const sessionsRequest = useRef(0);

  const emailInputRef = useRef<HTMLInputElement | null>(null);
  const tabs = ([
    { id: "personal", title: "Dati Anagrafici", badge: null },
    { id: "password", title: "Cambia Password", badge: null },
    { id: "push", title: "Attivazione notifiche push", badge: <PushStatusBadge state={pushState} /> },
    { id: "notifications", title: "Preferenze notifiche", badge: null },
    { id: "devices", title: "Dispositivi connessi", badge: <DeviceCountBadge status={sessionsStatus} sessions={deviceSessions} /> },
  ] satisfies { id: ProfileTab; title: string; badge: ReactNode }[])
    .filter(tab => tab.id !== "push" || user?.role?.name !== "viewer");
  const selectedTab = tabs.some(tab => tab.id === activeTab) ? activeTab : "personal";

  function navigateTabs(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next: number;
    switch (event.key) {
      case "ArrowRight": next = (index + 1) % tabs.length; break;
      case "ArrowLeft": next = (index + tabs.length - 1) % tabs.length; break;
      case "Home": next = 0; break;
      case "End": next = tabs.length - 1; break;
      default: return;
    }
    event.preventDefault();
    setActiveTab(tabs[next].id);
    document.getElementById(`profile-tab-${tabs[next].id}`)?.focus();
  }

  useEffect(() => {
    getUserInfo()
      .then((user) => {
        if (typeof user === "object" && user !== null) {
          if ("email" in user) {
            const actualEmail = (user as { email: string }).email || "";
            setEmail(actualEmail);
            setInitialEmail(actualEmail);
          }
          if ("email_masked" in user) setMaskedEmail((user as { email_masked: string }).email_masked || "");
        }
      })
      .catch(() => {
        setMessage("Errore nel recupero delle informazioni utente.");
      });
  }, []);

  const refreshSessions = useCallback(async () => {
    const request = ++sessionsRequest.current;
    try {
      const sessions = await getDeviceSessions();
      if (request === sessionsRequest.current) {
        setDeviceSessions(sessions);
        setSessionsStatus("ready");
      }
    } catch {
      if (request === sessionsRequest.current) setSessionsStatus("error");
    }
  }, []);

  useEffect(() => {
    const requestRef = sessionsRequest;
    refreshSessions();
    window.addEventListener(SESSION_RENEWED, refreshSessions);
    window.addEventListener("focus", refreshSessions);
    const timer = window.setInterval(refreshSessions, 60_000);
    return () => {
      requestRef.current++;
      window.clearInterval(timer);
      window.removeEventListener(SESSION_RENEWED, refreshSessions);
      window.removeEventListener("focus", refreshSessions);
    };
  }, [refreshSessions]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        editEmail &&
        emailInputRef.current &&
        !emailInputRef.current.contains(event.target as Node) &&
        (email === "" || email === initialEmail)
      ) {
        setEditEmail(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [editEmail, email, initialEmail]);

  const handleProfileSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await updateMe(email, '');
      setMessage("Dati anagrafici aggiornati con successo.");
      setShowMessage(true);
      setMessageCountdown(5);
      const countdownInterval = setInterval(() => {
        setMessageCountdown(prev => {
          if (prev <= 1) {
            clearInterval(countdownInterval);
            setShowMessage(false);
            return 5;
          }
          return prev - 1;
        });
      }, 1000);
      const updatedUser = await getUserInfo();
      if (typeof updatedUser === "object" && updatedUser !== null && "email" in updatedUser) {
        setEmail((updatedUser as { email: string }).email || "");
        setInitialEmail((updatedUser as { email: string }).email || "");
        if ("email_masked" in updatedUser) {
          setMaskedEmail((updatedUser as { email_masked: string }).email_masked || "");
        }
      }
      setEditEmail(false);
    } catch {
      setMessage("Errore nell'aggiornamento dei dati anagrafici.");
      setShowMessage(true);
      setMessageCountdown(5);
      const countdownInterval = setInterval(() => {
        setMessageCountdown(prev => {
          if (prev <= 1) {
            clearInterval(countdownInterval);
            setShowMessage(false);
            return 5;
          }
          return prev - 1;
        });
      }, 1000);
      setEditEmail(false);
    }
  };

  const handlePasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!password || !confirmPassword) {
      setPasswordMessage("Le password non possono essere vuote.");
      setIsPasswordError(true);
      setShowPasswordMessage(true);
      setPasswordCountdown(10);
      const countdownInterval = setInterval(() => {
        setPasswordCountdown((prev) => {
          if (prev <= 1) {
            clearInterval(countdownInterval);
            setShowPasswordMessage(false);
            return 10;
          }
          return prev - 1;
        });
      }, 1000);
      return;
    }

    if (password !== confirmPassword) {
      setPasswordMessage("Le password non coincidono.");
      setIsPasswordError(true);
      setShowPasswordMessage(true);
      setPasswordCountdown(10);
      const countdownInterval = setInterval(() => {
        setPasswordCountdown((prev) => {
          if (prev <= 1) {
            clearInterval(countdownInterval);
            setShowPasswordMessage(false);
            return 10;
          }
          return prev - 1;
        });
      }, 1000);
      return;
    }

    try {
      await updateMe("", password);
      setPasswordMessage("Password aggiornata con successo.");
      setIsPasswordError(false);
      setPassword("");
      setConfirmPassword("");
    } catch {
      setPasswordMessage("Errore nell'aggiornamento della password.");
      setIsPasswordError(true);
    }

    setShowPasswordMessage(true);
    setPasswordCountdown(5);
    const countdownInterval = setInterval(() => {
      setPasswordCountdown((prev) => {
        if (prev <= 1) {
          clearInterval(countdownInterval);
          setShowPasswordMessage(false);
          return 5;
        }
        return prev - 1;
      });
    }, 1000);
  };

  const handleRevokeSession = async (session: DeviceSession) => {
    if (sessionsBusy) return;
    setSessionsBusy(true);
    setSessionMessage("");
    setSessionNotice("");
    try {
      if (session.is_current && user?.username) {
        await disablePushForBrowser(user.username);
      }
      await revokeDeviceSession(session.id);
      sessionsRequest.current++;
      if (session.is_current) {
        localStorage.removeItem("access_token");
        window.location.assign("/login");
        return;
      }
      setDeviceSessions((sessions) =>
        sessions.map((item) =>
          item.id === session.id ? { ...item, revoked_at: new Date().toISOString() } : item
        )
      );
      void refreshSessions();
    } catch {
      setSessionMessage("Errore nella disconnessione del dispositivo.");
    } finally {
      setSessionsBusy(false);
    }
  };

  const handleCleanupSessions = async () => {
    if (sessionsBusy) return;
    setSessionsBusy(true);
    setSessionMessage("");
    setSessionNotice("");
    try {
      const deleted = await cleanupDeviceSessions();
      setSessionNotice(`Sessioni eliminate: ${deleted}. I dispositivi attivi restano connessi.`);
      await refreshSessions();
    } catch {
      setSessionMessage("Pulizia delle sessioni non riuscita. Riprovare.");
    } finally {
      setSessionsBusy(false);
    }
  };

  return (
    <div className="w-full min-w-0 max-w-md mx-auto mt-4 p-4 bg-white dark:bg-gray-900 dark:text-white shadow-md rounded space-y-3 md:max-w-full md:mx-0 md:mt-0 md:shadow-none md:rounded-none">
      <Link to={returnPath} className="inline-flex min-h-11 items-center rounded-xl bg-gray-100 px-4 font-medium text-blue-700 hover:bg-gray-200 dark:bg-gray-800 dark:text-blue-300 dark:hover:bg-gray-700">
        ← Torna indietro
      </Link>
      {desktop && (
        <div role="tablist" aria-label="Sezioni profilo" className="sticky top-0 z-10 mb-4 flex flex-wrap gap-2 border-b border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-900">
          {tabs.map((tab, index) => (
            <button
              key={tab.id}
              id={`profile-tab-${tab.id}`}
              type="button"
              role="tab"
              aria-selected={selectedTab === tab.id}
              aria-controls={`profile-panel-${tab.id}`}
              tabIndex={selectedTab === tab.id ? 0 : -1}
              onClick={() => setActiveTab(tab.id)}
              onKeyDown={event => navigateTabs(event, index)}
              className={`flex min-h-11 items-center gap-2 px-4 py-2 transition-colors focus-visible:outline-2 focus-visible:outline-blue-500 ${
                selectedTab === tab.id
                  ? "border-b-2 border-blue-500 font-semibold text-blue-600 dark:border-blue-400 dark:text-blue-400"
                  : "text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
              }`}
            >
              {tab.title}{tab.badge}
            </button>
          ))}
        </div>
      )}
      <ProfileSection title="Dati Anagrafici" sectionId="personal" desktop={desktop} active={selectedTab === "personal"}>
        <form onSubmit={handleProfileSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-100">Email</label>
            {!editEmail ? (
              <p
                className="mt-1 block w-full px-3 py-2 border border-gray-300 rounded cursor-pointer text-gray-600 bg-gray-100 dark:bg-gray-600 dark:text-gray-100"
                onClick={() => {
                  setEditEmail(true);
                  setTimeout(() => {
                    emailInputRef.current?.focus();
                  }, 0);
                }}
              >
                {maskedEmail || "Nessuna email fornita"}
              </p>
            ) : (
              <input
                ref={emailInputRef}
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="mt-1 block w-full px-3 py-2 border border-gray-300 rounded"
              />
            )}
          </div>
          <button
            type="submit"
            disabled={!editEmail}
            className={`w-full text-white py-2 px-4 rounded ${
              editEmail ? 'bg-blue-600 hover:bg-blue-700' : 'bg-gray-400 cursor-not-allowed'
            }`}
          >
            Salva Dati
          </button>
        </form>
        {message && showMessage && (
          <p
            className="mt-4 text-sm text-center transition-opacity duration-1000 text-green-600"
            style={{ opacity: messageCountdown / 5 }}
          >
            {message} (chiude tra {messageCountdown}s)
          </p>
        )}
      </ProfileSection>

      <ProfileSection title="Cambia Password" sectionId="password" desktop={desktop} active={selectedTab === "password"}>
        <form onSubmit={handlePasswordSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-100">Nuova Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 block w-full px-3 py-2 border border-gray-300 rounded"
              autoComplete="new-password"
              autoCapitalize="off"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-100">Ripeti Password</label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="mt-1 block w-full px-3 py-2 border border-gray-300 rounded"
              autoComplete="new-password"
              autoCapitalize="off"
            />
          </div>
          {(password || confirmPassword) && (
            <div>
              {password === confirmPassword ? (
                <span className="text-green-600">✔️ Le password coincidono</span>
              ) : (
                <span className="text-red-600">❌ Le password non coincidono</span>
              )}
            </div>
          )}
          <button
            type="submit"
            disabled={!!((password || confirmPassword) && password !== confirmPassword) || (password == '' && confirmPassword == '')}
            className={`w-full  text-white py-2 px-4 rounded  ${
              ((password || confirmPassword) && password !== confirmPassword) ||
              (password == '' && confirmPassword == '')
                ? 'bg-gray-400 cursor-not-allowed'
                : 'bg-blue-600 hover:bg-blue-700'
            }`}
          >
            Salva Password
          </button>
        </form>
        {passwordMessage && showPasswordMessage && (
          <p
            className={`mt-4 text-sm text-center transition-opacity duration-1000 ${
              isPasswordError ? "text-red-600" : "text-green-600"
            }`}
            style={{ opacity: passwordCountdown / (isPasswordError ? 10 : 5) }}
          >
            {passwordMessage} (chiude tra {passwordCountdown}s)
          </p>
        )}
      </ProfileSection>

      {user?.role?.name === "viewer"
        ? <ProfileSection title="Preferenze notifiche" sectionId="notifications" desktop={desktop} active={selectedTab === "notifications"}><p className="text-sm">Le notifiche delle modifiche sono riservate a chi può modificare inventari e liste. Gli utenti con sola lettura non le ricevono.</p></ProfileSection>
        : <>
            <ProfileSection title="Attivazione notifiche push" sectionId="push" desktop={desktop} active={selectedTab === "push"} headingId="profile-push-heading" badge={<PushStatusBadge state={pushState} />}><PushNotificationsPanel state={pushState} setState={setPushState} /></ProfileSection>
            <ProfileSection title="Preferenze notifiche" sectionId="notifications" desktop={desktop} active={selectedTab === "notifications"} headingId="notification-preferences-heading"><NotificationPreferences /></ProfileSection>
          </>}

      <ProfileSection title="Dispositivi connessi" sectionId="devices" desktop={desktop} active={selectedTab === "devices"} headingId="profile-devices-heading" badge={<DeviceCountBadge status={sessionsStatus} sessions={deviceSessions} />}>
        <p className="mb-2 text-sm">Elimina subito solo le tue sessioni scadute o disconnesse, senza disconnettere i dispositivi attivi.</p>
        <button type="button" onClick={handleCleanupSessions} disabled={sessionsBusy}
          className="mb-3 min-h-11 rounded border px-3 py-2 text-sm disabled:opacity-50">
          {sessionsBusy ? "Operazione in corso..." : "Pulisci sessioni scadute / disconnesse"}
        </button>
        {sessionNotice && <p role="status" className="mb-3 text-sm">{sessionNotice}</p>}
        {sessionMessage && <p role="alert" className="mb-3 text-sm text-red-600">{sessionMessage}</p>}
        {sessionsStatus === "error" && (
          <div className="mb-3 text-sm">
            <p role="alert" className="text-red-600">Errore nel recupero dei dispositivi.</p>
            <button type="button" onClick={() => void refreshSessions()} className="min-h-11 rounded border px-3">Riprova</button>
          </div>
        )}
        {sessionsStatus === "loading" ? (
          <p role="status" className="text-sm">Caricamento dispositivi...</p>
        ) : sessionsStatus === "error" ? null : deviceSessions.length === 0 ? (
          <p className="text-sm text-gray-600 dark:text-gray-300">Nessun dispositivo registrato.</p>
        ) : (
          <ul aria-labelledby="profile-devices-heading" tabIndex={0}
            className="max-h-80 sm:max-h-96 overflow-y-auto overscroll-contain space-y-3 rounded p-1 focus-visible:outline-2 focus-visible:outline-blue-500">
            {deviceSessions.map((session) => {
              const isExpired = session.is_expired;
              const isRevoked = Boolean(session.revoked_at);
              return (
                <li key={session.id} className="rounded border border-gray-300 p-3 dark:border-gray-700 [overflow-wrap:anywhere]">
                  <p className="font-medium">
                    {[session.device_type, session.browser, session.operating_system].filter(Boolean).join(" · ")}
                  </p>
                  <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">
                    Accesso: {new Date(session.created_at).toLocaleString()}
                  </p>
                  <p className="text-sm text-gray-600 dark:text-gray-300">
                    Valida fino al: {new Date(session.expires_at).toLocaleString()}
                  </p>
                  {(session.region || session.language || session.timezone) && (
                    <p className="text-sm text-gray-600 dark:text-gray-300">
                      {[session.region, session.language, session.timezone].filter(Boolean).join(" · ")}
                    </p>
                  )}
                  <p className="mt-1 text-sm">
                    {isRevoked ? "Disconnesso" : isExpired ? "Sessione scaduta" : "Attivo"}
                    {session.is_current && !isRevoked && " · Questo dispositivo"}
                  </p>
                  {!isRevoked && !isExpired && (
                    <button
                      type="button"
                      onClick={() => handleRevokeSession(session)}
                      disabled={sessionsBusy}
                      className="mt-2 min-h-11 rounded bg-red-600 px-3 py-1 text-sm text-white hover:bg-red-700 disabled:opacity-50"
                    >
                      Disconnetti dispositivo
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </ProfileSection>
    </div>
  );
};

export default ProfilePage;
