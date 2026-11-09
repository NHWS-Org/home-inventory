import { NavLink } from "react-router-dom";
import { FiBell } from "react-icons/fi";

export default function NotificationBell({ count, error, variant, navItemClass }: {
  count: number | null;
  error: boolean;
  variant: "desktop" | "mobile";
  navItemClass: (isActive: boolean) => string;
}) {
  const unread = count !== null && count > 0;
  const badge = error ? "!" : unread ? count > 99 ? "99+" : String(count) : null;
  return (
    <NavLink to="/notifications" aria-label={error ? "Notifiche: conteggio non disponibile" : count === null ? "Notifiche: caricamento" : `Notifiche: ${count} da leggere`}
      className={({ isActive }) => variant === "mobile" ? navItemClass(isActive)
        : `flex items-center gap-3 px-4 py-3 hover:text-blue-300 ${isActive ? "rounded-xl bg-gradient-to-r from-blue-500 to-blue-700 text-white" : ""}`}>
      <span className="relative shrink-0">
        <FiBell aria-hidden="true" className={`${variant === "mobile" ? "text-xl" : "text-lg"} ${unread ? `notification-bell-ringing ${variant === "mobile" ? "text-blue-500" : "text-blue-300"}` : ""}`} />
        {variant === "mobile" && badge && <span aria-hidden="true" className={`absolute -right-3 -top-2 flex h-4 min-w-4 items-center justify-center rounded-full px-0.5 text-[9px] font-bold leading-none text-white ${error ? "bg-amber-700" : "bg-blue-600"}`}>{badge}</span>}
      </span>
      <span className={variant === "mobile" ? "flex h-4 items-center text-[10px] leading-tight" : ""}>Notifiche</span>
      {variant === "desktop" && badge && <span aria-hidden="true" className={`ml-auto rounded-full px-2 py-0.5 text-xs font-bold text-white ${error ? "bg-amber-700" : "bg-blue-600"}`}>{badge}</span>}
    </NavLink>
  );
}
