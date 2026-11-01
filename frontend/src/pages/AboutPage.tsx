import { useEffect, useState } from "react";
import { version as frontendVersion } from "../../package.json";
import { AboutStats, getAboutStats, getApiVersion } from "../api";

const REPO_URL = "https://github.com/NHWS-Org/home-inventory";

function countryName(code: string): string {
  try {
    return new Intl.DisplayNames(["it"], { type: "region" }).of(code) ?? code;
  } catch {
    return code;
  }
}

const AboutPage = () => {
  const [backendVersion, setBackendVersion] = useState<string>("…");
  const [stats, setStats] = useState<AboutStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getApiVersion()
      .then(({ version }) => setBackendVersion(version))
      .catch(() => setBackendVersion("n/d"));
    getAboutStats()
      .then(setStats)
      .catch(() => setStats(null))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      <h1 className="hidden text-3xl font-bold text-center md:block">About</h1>

      <section className="bg-white dark:bg-black shadow-md border border-gray-200 rounded p-4 space-y-1">
        <h2 className="text-lg font-semibold mb-2">Home Inventory</h2>
        <p>Versione backend: {backendVersion}</p>
        <p>Versione frontend: {frontendVersion}</p>
        <p>
          Codice sorgente:{" "}
          <a href={REPO_URL} target="_blank" rel="noopener noreferrer" className="text-blue-500 underline">
            github.com/napalmz/home-inventory
          </a>
        </p>
      </section>

      <section className="bg-white dark:bg-black shadow-md border border-gray-200 rounded p-4">
        <h2 className="text-lg font-semibold mb-2">Community</h2>
        {loading && <p className="text-sm text-gray-500">Caricamento…</p>}
        {!loading && !stats?.available && (
          <p className="text-sm text-gray-500">Le statistiche della community non sono disponibili.</p>
        )}
        {!loading && stats?.available && (
          <div className="space-y-4">
            <p>
              Installazioni attive negli ultimi {stats.active_window_days} giorni:{" "}
              <span className="font-bold">{stats.active_installations}</span>
            </p>

            {stats.countries.length > 0 && (
              <div>
                <h3 className="font-semibold mb-1">Nazioni ({stats.countries.length})</h3>
                <ul className="grid grid-cols-1 sm:grid-cols-2 gap-1 text-sm">
                  {stats.countries.map((c) => (
                    <li key={c.country}>
                      {countryName(c.country)}: {c.n}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {stats.channels.length > 0 && (
              <div>
                <h3 className="font-semibold mb-1">Canali</h3>
                <ul className="grid grid-cols-1 sm:grid-cols-2 gap-1 text-sm">
                  {stats.channels.map((c) => (
                    <li key={c.channel}>
                      {c.channel}: {c.n}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {stats.versions.length > 0 && (
              <div>
                <h3 className="font-semibold mb-1">Versioni in uso</h3>
                <ul className="grid grid-cols-1 sm:grid-cols-2 gap-1 text-sm">
                  {stats.versions.map((v) => (
                    <li key={v.version}>
                      {v.version}: {v.n}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
        <p className="text-xs text-gray-500 mt-4">
          Dati aggregati e anonimi inviati solo dalle installazioni che hanno attivato la telemetria (opt-in). Il
          conteggio è una stima.
        </p>
      </section>
    </div>
  );
};

export default AboutPage;
