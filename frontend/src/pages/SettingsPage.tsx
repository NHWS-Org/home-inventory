import { useState } from "react";
import GeneralSettings from "./settings/GeneralSettings";
import UserManagementPage from "./settings/UserManagementPage";
//import RoleManagementPage from "./settings/RoleManagementPage";
import GroupManagementPage from "./settings/GroupManagementPage";
import MetadataDefinitionsPage from "./settings/MetadataDefinitionsPage";
//import InfoPage from "./settings/InfoPage";
import BackupManagementPage from "./settings/BackupManagementPage";
import AuditLogPage from "./settings/AuditLogPage";
import BarcodeManagementPage from "./settings/BarcodeManagementPage";
import { useAuth } from "../useAuth";

export default function SettingsPage() {
  const { user } = useAuth();
  const tabs = [
    { name: "Generale", component: <GeneralSettings /> },
    { name: "Utenti", component: <UserManagementPage /> },
    //{ name: "Ruoli", component: <RoleManagementPage /> },
    { name: "Gruppi", component: <GroupManagementPage /> },
    { name: "Metadati", component: <MetadataDefinitionsPage /> },
    { name: "Backup", component: <BackupManagementPage /> },
    { name: "Barcode", component: <BarcodeManagementPage />, adminOnly: true },
    { name: "Audit", component: <AuditLogPage /> },
    //{ name: "Info", component: <InfoPage /> },
  ].filter((tab) => !('adminOnly' in tab) || user?.role.name === 'admin');
  const [activeTab, setActiveTab] = useState("Generale");

  const currentTab = tabs.find((tab) => tab.name === activeTab);

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
      <div>{currentTab?.component}</div>
    </div>
  );
}
