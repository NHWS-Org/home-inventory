import { useEffect, useState } from "react";
import {
  getApiWelcomeInfo,
  getRecentInventoriesAndChecklists,
  InventoryOrChecklistRecent,
  getRecentItemsLimit
} from "../api";
import { useAuth } from "../useAuth";

const WelcomePage = () => {
  const [welcomeInfo, setWelcomeInfo] = useState<null | {
    title: string;
    message: string;
    stats: {
      total_inventories: number;
      total_inventories_items: number;
      total_checklists: number;
      total_checklists_items: number;
      total_users: number;
    };
  }>(null);

  const { user } = useAuth();
  const [welcomeError, setWelcomeError] = useState("");
  const [reloadRecent, setReloadRecent] = useState(0);
  const [recentResult, setRecentResult] = useState<{
    userId: number; username: string; reload: number; rows: InventoryOrChecklistRecent[]; error: string;
  } | null>(null);
  const currentResult = recentResult?.userId === user?.id && recentResult?.username === user?.username
    && recentResult?.reload === reloadRecent ? recentResult : null;
  const recenti = currentResult?.rows ?? [];
  const recentError = currentResult?.error ?? "";
  const recentLoading = !!user?.username && currentResult === null;
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    getApiWelcomeInfo().then(setWelcomeInfo).catch(() => {
      setWelcomeError("Impossibile caricare le informazioni della homepage.");
    });
    const handleResize = () => {
      setIsMobile(window.innerWidth < 768);
    };
    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  useEffect(() => {
    let active = true;
    if (!user?.username) return () => { active = false; };
    const userId = user.id;
    const username = user.username;
    getRecentItemsLimit()
      .then(getRecentInventoriesAndChecklists)
      .then(rows => { if (active) setRecentResult({ userId, username, reload: reloadRecent, rows, error: "" }); })
      .catch(() => {
        if (active) setRecentResult({ userId, username, reload: reloadRecent, rows: [], error: "Impossibile caricare gli ultimi inventari e liste. Riprova." });
      });
    return () => { active = false; };
  }, [user?.id, user?.username, reloadRecent]);

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      <h1 className="text-3xl font-bold text-center">{welcomeInfo?.title ?? "Benvenuto"}</h1>
      {welcomeError && <p role="alert">{welcomeError}</p>}
      {recentError && <div role="alert">{recentError} {user?.username && <button type="button" className="underline" onClick={() => setReloadRecent(value => value + 1)}>Riprova</button>}</div>}
      {recentLoading && <p role="status">Caricamento ultimi inventari e liste...</p>}

      {welcomeInfo && (
        <div className="text-gray-700 dark:text-gray-300">
          <p className="mb-2 font-bold">{welcomeInfo.message}</p>
          {user?.username && recenti.length > 0 && (
            <div className="bg-white dark:bg-black shadow-md border border-gray-200 rounded p-4 mb-6">
              <h2 className="text-lg font-semibold mb-2">Ultimi inventari e liste usati:</h2>
              <table className="w-full table-auto text-left text-sm border-collapse">
                <thead className="bg-gray-100 dark:bg-gray-800">
                  <tr>
                    <th className="p-3 border-b border-gray-300">#</th>
                    <th className="p-3 border-b border-gray-300">Nome</th>
                    <th className="p-3 border-b border-gray-300">Ultima modifica</th>
                    <th className="p-3 border-b border-gray-300">Utente modifica</th>
                  </tr>
                </thead>
                <tbody>
                  {recenti.map((rec, idx) => (
                    <tr
                      key={`${rec.type}-${rec.id}`}
                      className={`cursor-pointer ${idx % 2 === 0 ? 'bg-white dark:bg-black' : 'bg-gray-50 dark:bg-gray-900'} hover:bg-gray-100 dark:hover:bg-gray-700`}
                      onClick={() => window.location.href = `/${rec.type === "INVENTORY" ? "inventories" : "checklists"}/${rec.id}`}
                    >
                      <td className="p-3">{idx + 1} {isMobile ? (rec.type === "INVENTORY" ? "📦" : "📝") : (rec.type === "INVENTORY" ? "📦" : "📝")}</td>
                      <td className="p-3">{rec.name}</td>
                      <td className="p-3">{new Date(rec.data_mod).toLocaleString()}</td>
                      <td className="p-3">{rec.username_mod || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="mb-2 font-semibold">Statistiche</p>
          <ul className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm mt-2 text-gray-800 dark:text-gray-200">
            <li>Totale inventari: {welcomeInfo.stats.total_inventories}</li>
            <li>Totale oggetti negli inventari: {welcomeInfo.stats.total_inventories_items}</li>
            <li>Totale checklist: {welcomeInfo.stats.total_checklists}</li>
            <li>Totale oggetti nelle checklist: {welcomeInfo.stats.total_checklists_items}</li>
            <li>Totale utenti: {welcomeInfo.stats.total_users}</li>
          </ul>
        </div>
      )}
    </div>
  );
};

export default WelcomePage;