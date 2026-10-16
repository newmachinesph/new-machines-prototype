import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { hasUnsavedWork, useConfirmLeave, useLeaveGuard } from "./use-leave-guard";

const followed = vi.fn();
const PROMPT = "You have unsaved changes. Leave this page without saving them?";

function Page({ dirty }: { dirty: boolean }) {
  useLeaveGuard(dirty);
  // The app's links are React anchors: the guard must stop them before their own click handler runs.
  const stop = (e: React.MouseEvent) => {
    e.preventDefault();
    followed();
  };
  return (
    <nav>
      <a href="/elsewhere" onClick={stop}>
        Packs
      </a>
      <a href="/elsewhere" target="_blank" onClick={stop}>
        New tab
      </a>
      <a href="/files/pack.yaml" download onClick={stop}>
        Download
      </a>
      <a href="#steps" onClick={stop}>
        Steps
      </a>
      <a href="https://example.com/docs" onClick={stop}>
        Docs
      </a>
    </nav>
  );
}

const unload = () => {
  const e = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(e);
  return e.defaultPrevented;
};

describe("useLeaveGuard", () => {
  let confirm: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    followed.mockReset();
    confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  });
  afterEach(() => confirm.mockRestore());

  it("does nothing while there is nothing to lose", async () => {
    renderWithIntl(<Page dirty={false} />);
    expect(unload()).toBe(false);
    await userEvent.click(screen.getByRole("link", { name: "Packs" }));
    expect(confirm).not.toHaveBeenCalled();
    expect(followed).toHaveBeenCalledTimes(1);
  });

  it("asks before a reload and before an in-app link, and stops the link on no", async () => {
    renderWithIntl(<Page dirty />);
    expect(unload()).toBe(true);
    await userEvent.click(screen.getByRole("link", { name: "Packs" }));
    expect(confirm).toHaveBeenCalledWith(PROMPT);
    expect(followed).not.toHaveBeenCalled();
  });

  it("lets the link through on yes", async () => {
    confirm.mockReturnValue(true);
    renderWithIntl(<Page dirty />);
    await userEvent.click(screen.getByRole("link", { name: "Packs" }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(followed).toHaveBeenCalledTimes(1);
  });

  it("leaves new-tab, download, same-page and external links and modified clicks alone", async () => {
    renderWithIntl(<Page dirty />);
    for (const name of ["New tab", "Download", "Steps", "Docs"])
      await userEvent.click(screen.getByRole("link", { name }));
    fireEvent.click(screen.getByRole("link", { name: "Packs" }), { ctrlKey: true });
    fireEvent.click(screen.getByRole("link", { name: "Packs" }), { button: 1 });
    expect(confirm).not.toHaveBeenCalled();
    expect(followed).toHaveBeenCalledTimes(6);
  });

  it("stops guarding once the changes are saved", async () => {
    const { rerender } = renderWithIntl(<Page dirty />);
    rerender(<Page dirty={false} />);
    expect(unload()).toBe(false);
    await userEvent.click(screen.getByRole("link", { name: "Packs" }));
    expect(confirm).not.toHaveBeenCalled();
  });

  it("lets navigation in code ask too, only while some page holds unsaved work", () => {
    let mayLeave: () => boolean = () => true;
    function Away() {
      const check = useConfirmLeave();
      useEffect(() => {
        mayLeave = check;
      });
      return null;
    }
    const { rerender } = renderWithIntl(
      <>
        <Page dirty />
        <Away />
      </>,
    );
    expect(hasUnsavedWork()).toBe(true);
    expect(mayLeave()).toBe(false);
    expect(confirm).toHaveBeenCalledWith(PROMPT);
    confirm.mockReturnValue(true);
    expect(mayLeave()).toBe(true);

    confirm.mockClear();
    rerender(
      <>
        <Page dirty={false} />
        <Away />
      </>,
    );
    expect(hasUnsavedWork()).toBe(false);
    expect(mayLeave()).toBe(true);
    expect(confirm).not.toHaveBeenCalled();
  });

  it("asks in Japanese", async () => {
    renderWithIntl(<Page dirty />, { locale: "ja" });
    await userEvent.click(screen.getByRole("link", { name: "Packs" }));
    expect(confirm).toHaveBeenCalledWith("未保存の変更があります。保存せずにこのページを離れますか？");
  });
});
