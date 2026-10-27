// src/__tests__/change-password.test.tsx — change your own password (#117).

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChangePasswordForm } from "@/components/change-password";
import { clearSession, getSession } from "@/lib/session";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const session = {
  token: "tok-123",
  expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  username: "alice",
  tenant: "acme",
  role: "uploader",
};

async function fill(current: string, next: string, confirm = next) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Current password"), current);
  await user.type(screen.getByLabelText("New password"), next);
  await user.type(screen.getByLabelText("Confirm new password"), confirm);
  return user;
}
const submit = () => screen.getByRole("button", { name: /change password/i });

beforeEach(() => {
  clearSession();
  sessionStorage.setItem("te.session", JSON.stringify(session));
});
afterEach(() => vi.unstubAllGlobals());

describe("ChangePasswordForm", () => {
  it("keeps the button disabled while the new password is short or doesn't match", async () => {
    render(<ChangePasswordForm />);
    await fill("old password!", "short");
    expect(submit()).toBeDisabled();
    expect(screen.getByText(/at least 12 characters/i)).toBeInTheDocument();
  });

  it("flags a mismatched confirmation", async () => {
    render(<ChangePasswordForm />);
    await fill("old password!", "a brand new passphrase", "a different passphrase");
    expect(screen.getByText(/don't match/i)).toBeInTheDocument();
    expect(submit()).toBeDisabled();
  });

  it("posts current and new password with the bearer token, then confirms", async () => {
    const fetchMock = vi.fn(async () => json({ status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);
    const onDone = vi.fn();
    render(<ChangePasswordForm onDone={onDone} />);
    const user = await fill("old password!", "a brand new passphrase");
    await user.click(submit());
    expect(await screen.findByRole("status")).toHaveTextContent("Password changed");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/api\/auth\/password$/);
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok-123");
    expect(JSON.parse(init.body as string)).toEqual({
      currentPassword: "old password!",
      newPassword: "a brand new passphrase",
    });
    expect(onDone).toHaveBeenCalled();
    expect(getSession()?.token).toBe("tok-123");
  });

  it("shows the server's message for a wrong current password and keeps the session", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ detail: "Current password is incorrect" }, 400)),
    );
    render(<ChangePasswordForm />);
    const user = await fill("wrong", "a brand new passphrase");
    await user.click(submit());
    expect(await screen.findByRole("alert")).toHaveTextContent("Current password is incorrect");
    expect(screen.getByLabelText("Current password")).toHaveValue("");
    expect(getSession()).not.toBeNull();
  });
});
