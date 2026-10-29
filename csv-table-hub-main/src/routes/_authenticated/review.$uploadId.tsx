// M4 (#108): review screen for one stored upload.
import { createFileRoute, Link } from "@tanstack/react-router";
import { Toaster } from "sonner";
import { ReviewTable } from "@/components/review-table";
import { SessionMenu } from "@/components/session-menu";

export const Route = createFileRoute("/_authenticated/review/$uploadId")({
  head: () => ({ meta: [{ title: "Review upload — CSV Migrator" }] }),
  component: ReviewScreen,
});

function ReviewScreen() {
  const { uploadId } = Route.useParams();
  return (
    <div className="min-h-screen bg-background">
      <Toaster richColors position="top-right" />
      <header className="border-b">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div>
            <Link to="/" className="text-xs text-muted-foreground hover:underline">
              ← Migrated files
            </Link>
            <h1 className="text-lg font-semibold tracking-tight">Review</h1>
          </div>
          <SessionMenu />
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-6">
        <ReviewTable uploadId={uploadId} />
      </main>
    </div>
  );
}
