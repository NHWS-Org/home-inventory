import React, { useState, ReactNode, useEffect } from "react";
import { AuthContext } from "./auth-context-instance";
import { User } from "./types";
import { getUserInfo } from "./api";

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
    localStorage.removeItem("access_token");
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, setUser, logout, isLoading }}>
      {children}
    </AuthContext.Provider>
  );
};

export { AuthContext };
