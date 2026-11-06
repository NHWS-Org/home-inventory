import React, { useState, ReactNode, useEffect } from "react";
import { AuthContext } from "./auth-context-instance";
import { User } from "./types";
import { getUserInfo, logoutApi } from "./api";
import { disablePushForBrowser } from "./utils/pushNotifications";

type AuthProviderProps = {
  children: ReactNode;
};

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
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
      {children}
    </AuthContext.Provider>
  );
};

export { AuthContext };
