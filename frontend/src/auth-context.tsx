import React, { useState, ReactNode, useEffect } from "react";
import { AuthContext } from "./auth-context-instance";
import { User } from "./types";
import { getUserInfo, logoutApi } from "./api";
import { disablePushForBrowser } from "./utils/pushNotifications";
import { renewSessionOnActivity } from "./utils/sessionRenewal";

type AuthProviderProps = {
  children: ReactNode;
};

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [renewalMessage, setRenewalMessage] = useState("");
  const [isLoading, setIsLoading] = useState<boolean>(() => {
    return Boolean(typeof window !== "undefined" && localStorage.getItem("access_token"));
  });

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (token) {
      const fetchUser = async () => {
        try {
          const userData = await getUserInfo();
          if (userData && (userData as User).username !== "") {
            setUser(userData as User);
          } else {
            setUser(null);
          }
        } catch {
          // Token non valido o scaduto
          localStorage.removeItem("access_token");
          setUser(null);
        } finally {
          setIsLoading(false);
        }
      };
      fetchUser();
    } else {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!user?.username) return;
    let active = true;
    let retryAfter = 0;
    const onActivity = (event: Event) => {
      if (!event.isTrusted || Date.now() < retryAfter) return;
      void renewSessionOnActivity(user.username).then((warning) => {
        if (active && warning) setRenewalMessage(warning);
      }).catch(() => {
        retryAfter = Date.now() + 30_000;
        if (active) setRenewalMessage("Impossibile rinnovare la sessione. Controlla la connessione e riprova.");
      });
    };
    document.addEventListener("pointerdown", onActivity, true);
    document.addEventListener("keydown", onActivity, true);
    document.addEventListener("input", onActivity, true);
    document.addEventListener("wheel", onActivity, { capture: true, passive: true });
    return () => {
      active = false;
      document.removeEventListener("pointerdown", onActivity, true);
      document.removeEventListener("keydown", onActivity, true);
      document.removeEventListener("input", onActivity, true);
      document.removeEventListener("wheel", onActivity, true);
    };
  }, [user?.username]);

  const logout = async () => {
    let cleanupError: unknown;
    let logoutError: unknown;
    if (user?.username) {
      try {
        await disablePushForBrowser(user.username);
      } catch (error) {
        cleanupError = error;
      }
    }
    try {
      await logoutApi();
    } catch (error) {
      logoutError = error;
    } finally {
      localStorage.removeItem("access_token");
      setUser(null);
      setRenewalMessage("");
    }
    if (cleanupError) {
      console.error("Browser push cleanup failed; session logout still completed.", cleanupError);
    }
    if (logoutError) {
      console.error("Server session revocation failed during logout.", logoutError);
    }
  };

  return (
    <AuthContext.Provider value={{ user, setUser, logout, isLoading }}>
      {renewalMessage && (
        <div role="alert" className="flex items-center justify-between gap-3 bg-amber-100 px-4 py-3 text-sm text-amber-950">
          <span>{renewalMessage}</span>
          <button type="button" onClick={() => setRenewalMessage("")} aria-label="Chiudi avviso rinnovo sessione">✕</button>
        </div>
      )}
      {children}
    </AuthContext.Provider>
  );
};

export { AuthContext };
