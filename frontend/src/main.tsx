import React from 'react'
import ReactDOM from "react-dom/client";
import './index.css'
import App from './App'
import { AuthProvider } from "./auth-context"
import { createApiInstance } from './api';

function mountApp() {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <AuthProvider>
        <App />
      </AuthProvider>
    </React.StrictMode>
  );
}

fetch("/config.json")
  .then((res) => {
    if (!res.ok) throw new Error("Config file not found");
    return res.json();
  })
  .then((config) => {
    window.APP_CONFIG = config;
    createApiInstance();
  })
  .catch((err) => {
    console.warn("Configurazione config.json non disponibile, uso default /api:", err);
  })
  .finally(() => {
    mountApp();
  });