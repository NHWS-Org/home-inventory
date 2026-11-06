import { Link } from "react-router-dom";

export default function NotificationsPage() {
  return (
    <section aria-labelledby="notifications-heading" className="space-y-4 p-4">
      <h1 id="notifications-heading" className="text-2xl font-bold">Centro notifiche</h1>
      <p>Il centro notifiche sarà disponibile nella fase successiva.</p>
      <Link to="/profile" className="text-blue-700 underline dark:text-blue-300">
        Gestisci notifiche push
      </Link>
    </section>
  );
}
