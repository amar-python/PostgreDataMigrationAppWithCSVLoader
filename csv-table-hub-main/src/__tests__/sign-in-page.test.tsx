// src/__tests__/sign-in-page.test.tsx — the sign-in form (#96).

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { clearSession, getSession } from "@/lib/session";

const navigate = vi.fn();
vi.mock("@tanstack/react-router", async (orig) => ({
  ...(await orig<typeof import("@tanstack/react-router")>()),
  useNavigate: () => navigate,
}));

const { SignInPage } = await import("@/routes/auth");

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

async function fill(password = "pw") {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Tenant"), "acme");
  await user.type(screen.getByLabelText("Username"), "alice");
  await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: /sign in/i }));
}

beforeEach(() => {
  clearSession();
  navigate.mockReset();
});
afterEach(() => vi.unstubAllGlobals());

describe("SignInPage", () => {
  it("keeps the button disabled until every field is filled", () => {
    render(<SignInPage />);
    expect(screen.getByRole("button", { name: /sign in/i })).toBeDisabled();
  });

  it("signs in and goes to the upload page", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json({
          token: "t",
          expiresAt: new Date(Date.now() + 60_000).toISOString(),
          username: "alice",
          tenant: "acme",
          role: "uploader",
        }),
      ),
    );
    render(<SignInPage />);
    await fill();
    await vi.waitFor(() => expect(navigate).toHaveBeenCalledWith({ to: "/" }));
    expect(getSession()?.username).toBe("alice");
  });

  it("shows the error, clears the password and stays put on a failed sign-in", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ detail: "x" }, 401)),
    );
    render(<SignInPage />);
    await fill("wrong");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Invalid tenant, username or password",
    );
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(navigate).not.toHaveBeenCalled();
  });
});
