import { createFileRoute } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";

export const Route = createFileRoute("/auth")({
  head: () => ({
    meta: [
      { title: "CSV Migrator — Upload without authentication" },
      { name: "description", content: "Authentication is disabled. Upload CSV files directly to your backend." },
    ],
  }),
  component: AuthPage,
});

function AuthPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-background via-background to-muted/30 px-6">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <CardTitle>Authentication disabled</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            This Lovable frontend has been configured to use a PostgreSQL-backed backend API directly, so user sign-in is not required.
          </p>
          <div className="space-y-2">
            <Label>Next step</Label>
            <p className="text-sm text-muted-foreground">
              Go back to the home screen and upload CSV files directly. Configure <code className="rounded bg-muted px-1">VITE_API_BASE</code> to point to your backend.
            </p>
          </div>
        </CardContent>
        <CardFooter>
          <Button asChild>
            <a href="/">Back to upload</a>
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
