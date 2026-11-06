import { useState, useEffect } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { loginDestination, loginUrl } from "../utils/loginRedirect";
import { FiLoader } from "react-icons/fi";
import { registerUser, getSetting } from "../api";

export default function RegisterPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordMatch, setPasswordMatch] = useState<null | boolean>(null);
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [registrationEnabled, setRegistrationEnabled] = useState(true);

  useEffect(() => {
    const checkRegistration = async () => {
      try {
        const setting = await getSetting("ENABLE_REGISTRATION");
        setRegistrationEnabled(String(setting.value).toLowerCase() === "true");
      } catch {
        setRegistrationEnabled(true); // fallback in caso di errore
      }
    };
    checkRegistration();
  }, []);

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);
    try {
      await registerUser(username, password, email);
      navigate(loginUrl(loginDestination(location.search)), { replace: true });
    } catch {
      setError("Errore durante la registrazione");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="max-w-md mx-auto mt-10 p-6 border rounded-xl shadow-xl bg-white dark:bg-gray-900 dark:border-gray-700">
      <h2 className="text-2xl font-bold mb-4 text-center">Registrazione</h2>
      {!registrationEnabled && (
        <p className="text-gray-500 mb-4" role="status">
          La registrazione è attualmente disabilitata.
        </p>
      )}
      {error && <p className="text-red-500 mb-2 text-sm" role="alert">{error}</p>}
      <form onSubmit={handleRegister} className="space-y-4">
        <div>
          <label htmlFor="reg-username" className="block text-sm font-medium mb-1">
            Username <span className="text-red-500">*</span>
          </label>
          <input
            id="reg-username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full border p-2 rounded dark:bg-gray-800 dark:border-gray-700"
            required
            autoComplete="username"
            disabled={!registrationEnabled || isLoading}
          />
        </div>
        <div>
          <label htmlFor="reg-email" className="block text-sm font-medium mb-1">Email</label>
          <input
            id="reg-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full border p-2 rounded dark:bg-gray-800 dark:border-gray-700"
            autoComplete="email"
            disabled={!registrationEnabled || isLoading}
          />
        </div>
        <div>
          <label htmlFor="reg-password" className="block text-sm font-medium mb-1">
            Password <span className="text-red-500">*</span>
          </label>
          <input
            id="reg-password"
            type="password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              setPasswordMatch(
                e.target.value && confirmPassword
                  ? e.target.value === confirmPassword
                  : null
              );
            }}
            className="w-full border p-2 rounded dark:bg-gray-800 dark:border-gray-700"
            required
            autoComplete="new-password"
            disabled={!registrationEnabled || isLoading}
          />
        </div>
        <div>
          <label htmlFor="reg-confirm-password" className="block text-sm font-medium mb-1">
            Conferma Password <span className="text-red-500">*</span>
          </label>
          <input
            id="reg-confirm-password"
            type="password"
            value={confirmPassword}
            onChange={(e) => {
              setConfirmPassword(e.target.value);
              setPasswordMatch(
                password && e.target.value
                  ? password === e.target.value
                  : null
              );
            }}
            className="w-full border p-2 rounded dark:bg-gray-800 dark:border-gray-700"
            required
            autoComplete="new-password"
            disabled={!registrationEnabled || isLoading}
          />
        </div>
        {passwordMatch === false && (
          <p className="text-red-500 text-sm" role="status" aria-live="polite">Le password non coincidono.</p>
        )}
        {passwordMatch === true && (
          <p className="text-green-600 text-sm" role="status" aria-live="polite">Le password coincidono.</p>
        )}
        <button
          type="submit"
          className="flex w-full items-center justify-center gap-2 rounded bg-blue-600 py-2 font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
          disabled={
            !registrationEnabled ||
            isLoading ||
            !password ||
            !confirmPassword ||
            password !== confirmPassword
          }
          aria-busy={isLoading}
        >
          {isLoading ? (
            <>
              <FiLoader className="h-5 w-5 animate-spin" aria-hidden="true" />
              <span>Registrazione in corso...</span>
            </>
          ) : (
            "Registrati"
          )}
        </button>
        <p className="text-sm mt-4 text-center">
          Hai già un account? <Link to={loginUrl(loginDestination(location.search))} className="text-blue-600 hover:underline">Accedi</Link>
        </p>
      </form>
    </div>
  );
}
