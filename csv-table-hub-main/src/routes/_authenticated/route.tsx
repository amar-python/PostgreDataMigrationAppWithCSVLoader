import { createFileRoute, Outlet } from "@tanstack/react-router";
import { requireSession } from "@/lib/session";

// #96: every page under this layout needs a signed-in session.
export const Route = createFileRoute("/_authenticated")({
  ssr: false,
  beforeLoad: requireSession,
  component: () => <Outlet />,
});
