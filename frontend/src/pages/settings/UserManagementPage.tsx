import { useEffect, useState, useRef } from "react";
import { getUsers, getRoles, updateUser, createUser, deleteUser } from "../../api"; // Assicurati che esista o crealo
import { Dialog } from "@headlessui/react";
import { User, Role } from "../../types";
import { useBottomSheetDrag } from "../../components/useBottomSheetDrag";

export default function UserManagementPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [newUserData, setNewUserData] = useState<{ username: string; email: string; roleId: number; isBlocked: boolean; password: string; confirmPassword: string }>({ username: "", email: "", roleId: 0, isBlocked: false, password: "", confirmPassword: "" });
  const [roleFilter, setRoleFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [newEmail, setNewEmail] = useState<string>("");
  const [newRole, setNewRole] = useState<string>("");
  const [newIsBlocked, setNewIsBlocked] = useState<boolean>(false);
  const [password, setPassword] = useState<string>("");
  const [confirmPassword, setConfirmPassword] = useState<string>("");
  const [message, setMessage] = useState<string>("");
  const [messageType, setMessageType] = useState<"success" | "error" | "">("");

  const createUsernameRef = useRef<HTMLInputElement>(null);
  const createEmailRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getUsers().then((data) => setUsers(data as User[]));
    getRoles().then((data) => {
      if (Array.isArray(data)) {
        setRoles(data as Role[]);
      } else {
        console.error("Dati ruolo non validi:", data);
        setRoles([]);
      }
    });
  }, []);

  useEffect(() => {
    if (isCreateModalOpen) {
      setTimeout(() => {
        if (createUsernameRef.current) {
          createUsernameRef.current.focus();
        }
      }, 0);
    }
  }, [isCreateModalOpen]);

  const openModal = (user: User) => {
    setSelectedUser(user);
    setNewEmail(user.email);
    setNewRole(user.role.name);
    setNewIsBlocked(user.is_blocked);
    setIsModalOpen(true);
  };

  const closeModal = () => {
    setSelectedUser(null);
    setPassword("");
    setConfirmPassword("");
    setIsModalOpen(false);
  };

  const deleteUserHandler = (userId: number) => {
    deleteUser(userId).then(() => {
      setUsers(users.filter(user => user.id !== userId));
      showMessage("Utente eliminato con successo", "success");
    });
  };

  const showMessage = (text: string, type: "success" | "error") => {
    setMessage(text);
    setMessageType(type);
    const timeout = setTimeout(() => {
      setMessage("");
      setMessageType("");
    }, type === "success" ? 5000 : 10000);
    return () => clearTimeout(timeout);
  };

  const editSheetDrag = useBottomSheetDrag(closeModal);
  const createSheetDrag = useBottomSheetDrag(() => setIsCreateModalOpen(false));

  const saveChanges = () => {
    if (password && password !== confirmPassword) {
      showMessage("Le password non coincidono", "error");
      return;
    }

    const updatedUserData = {
      username: selectedUser?.username || "", // non modificabile
      email: newEmail,
      role_id: roles.find(role => role.name === newRole)?.id as number,
      is_blocked: newIsBlocked,
      password: password || undefined
    };

    updateUser(selectedUser?.id as number, updatedUserData).then(() => {
      showMessage("Utente aggiornato con successo", "success");
  
      // aggiorna lo stato localmente
      setUsers(prev =>
        prev.map(u =>
          u.id === selectedUser?.id
            ? {
                ...u,
                email: newEmail,
                role: roles.find(r => r.name === newRole)!,
                is_blocked: newIsBlocked,
                data_mod: new Date().toISOString(),
              }
            : u
        )
      );
  
      closeModal();
    });
  };

  const createUserHandler = async () => {
    try {
      await createUser(newUserData);
      showMessage("Utente creato con successo", "success");
      const updatedUsers = await getUsers();
      setUsers(updatedUsers as User[]);
      setIsCreateModalOpen(false);
      setNewUserData({ username: "", email: "", roleId: 0, isBlocked: false, password: "", confirmPassword: "" });
    } catch {
      showMessage("Errore durante la creazione dell'utente", "error");
    }
  };

  const filteredUsers = users.filter(user =>
    (roleFilter === "all" || user.role?.name === roleFilter) &&
    (statusFilter === "all" || (statusFilter === "active" ? !user.is_blocked : user.is_blocked))
  );

  return (
    <div className="space-y-4 overflow-x-auto px-2 sm:px-4">
      <h2 className="text-lg font-semibold">Gestione utenti</h2>
  
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between space-y-2 sm:space-y-0">
        <div className="flex flex-wrap gap-2">
          <select
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value)}
            className="w-full border rounded p-1"
          >
            <option value="all">Tutti i ruoli</option>
            {[...new Set(users.map(u => u.role?.name).filter(Boolean))].map(role => (
              <option key={role} value={role}>{role}</option>
            ))}
          </select>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="w-full border rounded p-1"
          >
            <option value="all">Tutti gli status</option>
            <option value="active">Attivi</option>
            <option value="blocked">Bloccati</option>
          </select>
        </div>
        <button onClick={() => setIsCreateModalOpen(true)} className="px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700">+ Nuovo utente</button>
      </div>
  
      <div className="overflow-x-auto">
        <table className="min-w-full table-auto border border-gray-300">
          <thead className="bg-gray-100 dark:bg-gray-800">
            <tr>
              <th className="p-2 border">Username</th>
              <th className="p-2 border">Email</th>
              <th className="p-2 border">Ruolo</th>
              <th className="p-2 border">Status</th>
              <th className="p-2 border">Creato il</th>
              <th className="p-2 border">Ultima modifica</th>
              <th className="p-2 border">Azioni</th>
            </tr>
          </thead>
          <tbody>
            {filteredUsers.map((user) => (
              <tr key={user.id}>
                <td className="p-2 border">{user.username}</td>
                <td className="p-2 border">{user.email}</td>
                <td className="p-2 border">{user.role?.name ?? "-"}</td>
                <td className="p-2 border text-center">{user.is_blocked ? "🔴 Bloccato" : "🟢 Attivo"}</td>
                <td className="p-2 border">{new Date(user.data_ins).toLocaleString()}</td>
                <td className="p-2 border">{new Date(user.data_mod).toLocaleString()}</td>
                <td className="p-2 border whitespace-nowrap text-right">
                  <button
                    className="px-2 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700"
                    onClick={() => openModal(user)}
                  >
                    Modifica
                  </button>
                  <button
                    className="ml-2 px-2 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700"
                    onClick={() => {
                      if (window.confirm(`Sei sicuro di voler eliminare ${user.username}?`)) {
                        deleteUserHandler(user.id);
                      }
                    }}
                  >
                    Elimina
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
  
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between space-y-2 sm:space-y-0">
        <button onClick={() => setIsCreateModalOpen(true)} className="px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700">+ Nuovo utente</button>
      </div>
  
      {message && (
        <div
          className={`fixed z-50 p-3 rounded shadow-lg text-white transition-opacity duration-1000 ${messageType === "success" ? "bg-green-500" : "bg-red-500"} ${window.innerWidth < 768 ? "bottom-4 left-1/2 transform -translate-x-1/2" : "top-4 right-4"}`}
        >
          {message}
        </div>
      )}

      <Dialog open={isModalOpen} onClose={closeModal} className="relative z-50">
        <div className="fixed inset-0 bg-black/30" aria-hidden="true" />
        <div className="fixed inset-0 flex items-end justify-center sm:items-center sm:p-4">
          <Dialog.Panel style={{ transform: `translateY(${editSheetDrag.offset}px)`, transition: editSheetDrag.isDragging ? 'none' : 'transform 220ms ease-out' }} className="max-h-[90dvh] w-full space-y-4 overflow-y-auto rounded-t-3xl bg-white p-5 pb-[calc(env(safe-area-inset-bottom)+1rem)] text-gray-900 shadow-2xl dark:bg-gray-900 dark:text-white sm:max-w-md sm:rounded-xl sm:p-6 sm:pb-6">
            <button type="button" aria-label="Chiudi o trascina verso il basso" {...editSheetDrag.gripProps} className="mx-auto mb-3 flex h-8 w-16 touch-none items-center justify-center sm:hidden"><span className="h-1 w-10 rounded-full bg-gray-300 dark:bg-gray-600" aria-hidden="true" /></button>
            <Dialog.Title className="text-lg font-semibold mb-4">
              Modifica utente
            </Dialog.Title>
            {selectedUser && (
              <table className="w-full text-sm border border-gray-300">
                <tbody>
                  <tr><td className="p-2 font-medium">Username</td><td className="p-2">{selectedUser.username}</td></tr>
                  <tr><td className="p-2 font-medium">Email</td><td className="p-2"><input type="email" className="w-full border rounded p-1 text-sm" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} /></td></tr>
                  <tr><td className="p-2 font-medium">Ruolo</td><td className="p-2">
                    <select value={newRole} onChange={(e) => setNewRole(e.target.value)} className="w-full border rounded p-1">
                      {roles.map(role => (
                        <option key={role.id} value={role.name}>{role.name}</option>
                      ))}
                    </select>
                  </td></tr>
                  <tr><td className="p-2 font-medium">Bloccato</td><td className="p-2"><input type="checkbox" checked={newIsBlocked} onChange={(e) => setNewIsBlocked(e.target.checked)} /></td></tr>
                  <tr>
                    <td className="p-2 font-medium">Nuova password</td>
                    <td className="p-2 flex items-center gap-2">
                      <input
                        type="password"
                        className="w-full border rounded p-1 text-sm"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                      />
                    </td>
                  </tr>
                  <tr>
                    <td className="p-2 font-medium">Ripeti password</td>
                    <td className="p-2 flex items-center gap-2">
                      <input
                        type="password"
                        className="w-full border rounded p-1 text-sm"
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                      />
                    </td>
                  </tr>
                  {(password || confirmPassword) && (
                    <tr>
                      <td colSpan={2} className="p-2 text-sm">
                        {password === confirmPassword ? (
                          <span className="text-green-600">✔️ Le password coincidono</span>
                        ) : (
                          <span className="text-red-600">❌ Le password non coincidono</span>
                        )}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            )}
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={closeModal}
                className="px-3 py-1 text-sm bg-gray-400 rounded hover:bg-gray-600"
              >
                Chiudi
              </button>
              <button
                onClick={saveChanges}
                disabled={!!((password || confirmPassword) && password !== confirmPassword)}
                className={`px-3 py-1 text-sm text-white rounded w-full ${
                  (password || confirmPassword) && password !== confirmPassword
                    ? 'bg-gray-400 cursor-not-allowed'
                    : 'bg-green-600 hover:bg-green-700'
                }`}
              >
                Salva
              </button>
            </div>
          </Dialog.Panel>
        </div>
      </Dialog>

      <Dialog open={isCreateModalOpen} onClose={() => setIsCreateModalOpen(false)} className="relative z-50">
        <div className="fixed inset-0 bg-black/30" aria-hidden="true" />
        <div className="fixed inset-0 flex items-end justify-center sm:items-center sm:p-4">
          <Dialog.Panel style={{ transform: `translateY(${createSheetDrag.offset}px)`, transition: createSheetDrag.isDragging ? 'none' : 'transform 220ms ease-out' }} className="max-h-[90dvh] w-full space-y-4 overflow-y-auto rounded-t-3xl bg-white p-5 pb-[calc(env(safe-area-inset-bottom)+1rem)] text-gray-900 shadow-2xl dark:bg-gray-900 dark:text-white sm:max-w-md sm:rounded-xl sm:p-6 sm:pb-6">
            <button type="button" aria-label="Chiudi o trascina verso il basso" {...createSheetDrag.gripProps} className="mx-auto mb-3 flex h-8 w-16 touch-none items-center justify-center sm:hidden"><span className="h-1 w-10 rounded-full bg-gray-300 dark:bg-gray-600" aria-hidden="true" /></button>
            <Dialog.Title className="text-lg font-semibold mb-4">
              Crea utente
            </Dialog.Title>
            <table className="w-full text-sm border border-gray-300">
              <tbody>
                <tr><td className="p-2 font-medium">Username</td><td className="p-2"><input
                  type="text"
                  ref={createUsernameRef}
                  className="w-full border rounded p-1 text-sm"
                  value={newUserData.username}
                  onChange={(e) => setNewUserData({ ...newUserData, username: e.target.value })}
                /></td></tr>
                <tr><td className="p-2 font-medium">Email</td><td className="p-2"><input type="email" ref={createEmailRef} className="w-full border rounded p-1 text-sm" value={newUserData.email} onChange={(e) => setNewUserData({ ...newUserData, email: e.target.value })} /></td></tr>
                <tr><td className="p-2 font-medium">Ruolo</td><td className="p-2">
                  <select value={newUserData.roleId} onChange={(e) => setNewUserData({ ...newUserData, roleId: Number(e.target.value) })} className="w-full border rounded p-1">
                    <option value={0}>Seleziona un ruolo</option>
                    {roles.map(role => (
                      <option key={role.id} value={role.id}>{role.name}</option>
                    ))}
                  </select>
                </td></tr>
                <tr><td className="p-2 font-medium">Password</td><td className="p-2"><input type="password" className="w-full border rounded p-1 text-sm" value={newUserData.password} onChange={(e) => setNewUserData({ ...newUserData, password: e.target.value })} /></td></tr>
                <tr><td className="p-2 font-medium">Ripeti password</td><td className="p-2"><input type="password" className="w-full border rounded p-1 text-sm" value={newUserData.confirmPassword} onChange={(e) => setNewUserData({ ...newUserData, confirmPassword: e.target.value })} /></td></tr>
              </tbody>
            </table>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setIsCreateModalOpen(false)}
                className="px-3 py-1 text-sm bg-gray-400 rounded hover:bg-gray-600"
              >
                Chiudi
              </button>
              <button
                onClick={createUserHandler}
                className="px-3 py-1 text-sm bg-green-600 text-white rounded hover:bg-green-700 w-full"
              >
                Crea
              </button>
            </div>
          </Dialog.Panel>
        </div>
      </Dialog>
    </div>
  );
}
