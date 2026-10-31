// src/components/ProtectedRoute.tsx
import { useAuth } from "../useAuth";
import { Navigate } from "react-router-dom";
import Spinner from "../components/Spinner";

interface ProtectedRouteProps {
  children: React.ReactNode;
  requireAdmin?: boolean;
}

export default function ProtectedRoute({ children, requireAdmin = false }: ProtectedRouteProps) {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return <Spinner />;
  }

  if (user === null) {
    return <Navigate to="/login" replace />;
  }

  if (requireAdmin && user.role?.name !== "admin") {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}