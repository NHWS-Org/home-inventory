import { useState, lazy, Suspense } from "react";
import Spinner from "../components/Spinner";
import { useAuth } from "../useAuth";

const GeneralSettings = lazy(() => import("./settings/GeneralSettings"));
const UserManagementPage = lazy(() => import("./settings/UserManagementPage"));
const GroupManagementPage = lazy(() => import("./settings/GroupManagementPage"));
const MetadataDefinitionsPage = lazy(() => import("./settings/MetadataDefinitionsPage"));
const BackupManagementPage = lazy(() => import("./settings/BackupManagementPage"));
const BarcodeManagementPage = lazy(() => import("./settings/BarcodeManagementPage"));
const AuditLogPage = lazy(() => import("./settings/AuditLogPage"));

interface TabItem {
  name: string;
  Component: React.ComponentType;
  adminOnly?: boolean;
}

export default function SettingsPage() {
  const { user } = useAuth();
  const tabs: TabItem[] = [
    { name: "Generale", Component: GeneralSettings },
    { name: "Utenti", Component: UserManagementPage },
    { name: "Gruppi", Component: GroupManagementPage },
    { name: "Metadati", Component: MetadataDefinitionsPage },
    { name: "Backup", Component: BackupManagementPage },
    { name: "Barcode", Component: BarcodeManagementPage, adminOnly: true },
    { name: "Audit", Component: AuditLogPage },
  ].filter((tab) => !tab.adminOnly || user?.role?.name === 'admin');
  const [activeTab, setActiveTab] = useState("Generale");

  const currentTab = tabs.find((tab) => tab.name === activeTab);
  const CurrentComponent = currentTab?.Component;

  return (
    <div className="p-4 overflow-x-hidden w-full max-w-full">
      <div className="sticky top-0 z-10 bg-white dark:bg-gray-900 flex flex-wrap gap-2 border-b border-gray-200 dark:border-gray-700 mb-4">
        {tabs.map((tab) => (
          <button
            key={tab.name}
            className={`px-4 py-2 transition-colors ${
              tab.name === activeTab
                ? "border-b-2 border-blue-500 dark:border-blue-400 text-blue-600 dark:text-blue-400 font-semibold"
                : "text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
            }`}
            onClick={() => setActiveTab(tab.name)}
          >
            {tab.name}
          </button>
        ))}
      </div>
      <div>
        <Suspense fallback={<Spinner />}>
          {CurrentComponent && <CurrentComponent />}
        </Suspense>
      </div>
    </div>
  );
}
