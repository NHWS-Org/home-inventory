// src/components/ProtectedRoute.tsx
import { useAuth } from "../useAuth";
import { Navigate, useLocation } from "react-router-dom";
import { loginUrl } from "../utils/loginRedirect";
import Spinner from "../components/Spinner";

interface ProtectedRouteProps {
  children: React.ReactNode;
  requireAdmin?: boolean;
}

export default function ProtectedRoute({ children, requireAdmin = false }: ProtectedRouteProps) {
  const { user, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return <Spinner />;
  }

  if (user === null) {
    return <Navigate to={loginUrl(location.pathname + location.search + location.hash)} replace />;
  }

  if (requireAdmin && user.role?.name !== "admin") {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}