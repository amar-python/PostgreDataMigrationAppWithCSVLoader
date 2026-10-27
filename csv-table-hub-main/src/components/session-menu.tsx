// Signed-in user, tenant and role, with change password (#117) and sign-out (#96).
import { useNavigate } from "@tanstack/react-router";
import { LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getSession, signOut } from "@/lib/session";
import { ChangePasswordDialog } from "@/components/change-password";

export function SessionMenu() {
  const navigate = useNavigate();
  const s = getSession();
  if (!s) return null;
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <span title={`Role: ${s.role}`}>
        {s.username} · {s.tenant}
      </span>
      <ChangePasswordDialog />
      <Button
        variant="ghost"
        size="sm"
        aria-label="Sign out"
        onClick={async () => {
          await signOut();
          navigate({ to: "/auth" });
        }}
      >
        <LogOut className="h-4 w-4" />
      </Button>
    </div>
  );
}
