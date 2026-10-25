import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

// Cosmetic sign-in per gitreverse.com/designs/csv-joyride-sync-lovable-app.
// Backend has no user auth (X-API-Key only) — see docs/BUG_REPORT.md BUG-006/035.
// Submit does not authenticate; it just routes to /. Wire a real /api/auth/login
// before treating this as more than a mockup.
export const Route = createFileRoute("/auth")({
  head: () => ({
    meta: [
      { title: "Sign in — CSV Migrator" },
      { name: "description", content: "Sign in to CSV Migrator." },
    ],
  }),
  component: AuthPage,
});

function AuthPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  return (
    <div
      className="min-h-screen flex items-center justify-center bg-white px-4"
      style={{ fontFamily: '"CameraPlainVariable", ui-sans-serif, system-ui, sans-serif' }}
    >
      <div className="w-full max-w-sm space-y-8">
        <h1 className="text-2xl font-medium text-[#0F172B]">Sign in</h1>

        <form
          className="space-y-5"
          onSubmit={(e) => {
            e.preventDefault();
            // ponytail: cosmetic only, no auth backend. Replace with real login when it exists.
            navigate({ to: "/" });
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="email" className="text-[#0F172B]">
              Email
            </Label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="h-10 rounded-lg border-[#E2E8F0] shadow-sm focus-visible:ring-[#62748E]"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="password" className="text-[#0F172B]">
              Password
            </Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="h-10 rounded-lg border-[#E2E8F0] shadow-sm focus-visible:ring-[#62748E]"
            />
          </div>

          <Button
            type="submit"
            className="w-full h-10 rounded-lg shadow-sm bg-[#0F172B] text-[#F8FAFC] hover:bg-[#0F172B]/90"
          >
            Sign in
          </Button>
        </form>

        <p className="text-sm text-center text-[#62748E]">
          Need an account?{" "}
          <Link to="/auth" className="text-[#62748E] hover:text-[#0F172B] underline underline-offset-2">
            Sign up
          </Link>
        </p>
      </div>
    </div>
  );
}
