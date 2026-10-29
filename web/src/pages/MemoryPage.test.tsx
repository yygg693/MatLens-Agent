// @vitest-environment jsdom
// Tests for the memory center page: what it asks the backend for, and
// what it renders from the answer.
//
// The backend contract these lock down (matlens_kit/api/mem_api.py):
//   GET  /api/memories?q=&offset=&limit=  -> { memories, total, has_more, mode }
//   GET  /api/memories/status              -> { enabled, source, count, ... }
//   GET  /api/memories/last-injection      -> { memories, available }
//   POST /api/memories                     -> { ok }
//   PATCH/DELETE /api/memories/{id}

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";

import { I18nProvider } from "@/i18n";
import { PageHeaderProvider } from "@/contexts/PageHeaderProvider";
import { api } from "@/lib/api";
import type {
  MemoryContentStatus,
  MemoryItem,
  MemoryLastInjection,
  MemoryListResponse,
} from "@/lib/api";
import MemoryPage from "./MemoryPage";

let container: HTMLDivElement;
let root: Root;

/**
 * The page renders inside the dashboard chrome, which supplies the page
 * header (and through it the toolbar slot) plus the i18n context.
 */
function withProviders(ui: ReactNode) {
  return (
    <MemoryRouter initialEntries={["/memory"]}>
      <I18nProvider>
        <PageHeaderProvider pluginTabs={[]}>{ui}</PageHeaderProvider>
      </I18nProvider>
    </MemoryRouter>
  );
}

async function render(ui: ReactNode) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(withProviders(ui)));
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "listMemories").mockResolvedValue({
    ok: true,
    count: 0,
    total: 0,
    query: "",
    memories: [],
    offset: 0,
    limit: 20,
    has_more: false,
  } satisfies MemoryListResponse);
  vi.spyOn(api, "getMemoryContentStatus").mockResolvedValue({
    ok: true,
    enabled: true,
    provider: "mem0",
    source: "oss",
    count: 42,
    auto_write: true,
    graph_auto_build: true,
  } satisfies MemoryContentStatus);
  vi.spyOn(api, "getMemoryLastInjection").mockResolvedValue({
    ok: true,
    memories: [],
    count: 0,
    available: false,
  } satisfies MemoryLastInjection);
});

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
});

function item(over: Partial<MemoryItem> = {}): MemoryItem {
  return {
    id: "m-1",
    memory: "[材料] NCM811 的循环衰减分析",
    category: "材料",
    score: 0,
    created_at: "2026-10-20T10:00:00",
    updated_at: null,
    source_type: "user",
    source_ref: null,
    confidence: 0.9,
    metadata: {},
    ...over,
  };
}

function listWith(
  memories: MemoryItem[],
  over: Partial<MemoryListResponse> = {},
): MemoryListResponse {
  return {
    ok: true,
    count: memories.length,
    total: memories.length,
    query: "",
    memories,
    offset: 0,
    limit: 20,
    has_more: false,
    ...over,
  };
}

describe("MemoryPage", () => {
  it("asks the backend for the memory-content router, not the provider one", async () => {
    const spy = vi.spyOn(api, "listMemories");
    await render(<MemoryPage />);
    expect(spy).toHaveBeenCalled();
    const args = spy.mock.calls[0][0];
    // The dashboard server owns /api/memory for provider status; the
    // content router lives at /api/memories.
    expect(args?.offset).toBe(0);
    expect(args?.limit).toBe(20);
    expect(args?.q).toBeUndefined();
  });

  it("shows the exact store-wide count from the status endpoint", async () => {
    await render(<MemoryPage />);
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.textContent).toContain("42");
  });

  it("renders each memory with its category and provenance", async () => {
    vi.mocked(api.listMemories).mockResolvedValue(
      listWith([item()]),
    );
    await render(<MemoryPage />);
    await act(async () => {
      await Promise.resolve();
    });
    const text = container.textContent ?? "";
    expect(text).toContain("材料");
    expect(text).toContain("NCM811");
    expect(text).toContain("用户陈述");
    expect(text).toContain("置信度 90%");
  });

  it("flags a row that both recallers found", async () => {
    vi.mocked(api.listMemories).mockResolvedValue(
      listWith([item({ rrf_score: 0.032 })]),
    );
    await render(<MemoryPage />);
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.textContent).toContain("双路命中");
  });

  it("passes the search term to the backend", async () => {
    const spy = vi.spyOn(api, "listMemories");
    await render(<MemoryPage />);
    const input = container.querySelector(
      'input[aria-label="搜索记忆"]',
    ) as HTMLInputElement;
    expect(input).toBeTruthy();
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        "value",
      )?.set;
      setter?.call(input, "固态电解质");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    // The request is debounced, so advance past the timer.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 450));
    });
    const calls = spy.mock.calls;
    expect(calls.length).toBeGreaterThan(1);
    expect(calls[calls.length - 1][0]?.q).toBe("固态电解质");
  });

  it("explains an empty store instead of rendering a blank page", async () => {
    await render(<MemoryPage />);
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.textContent).toContain("还没有记忆");
  });

  it("says the subsystem is off when it is disabled", async () => {
    vi.mocked(api.getMemoryContentStatus).mockResolvedValue({
      ok: true,
      enabled: false,
      provider: "mem0",
      source: null,
      count: null,
      auto_write: false,
      graph_auto_build: false,
    } satisfies MemoryContentStatus);
    await render(<MemoryPage />);
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.textContent).toContain("记忆功能已关闭");
  });

  it("lists what the agent actually injected this turn", async () => {
    vi.mocked(api.getMemoryLastInjection).mockResolvedValue({
      ok: true,
      memories: [item({ id: "inj-1", memory: "用户偏好中文回复" })],
      count: 1,
      available: true,
    } satisfies MemoryLastInjection);
    await render(<MemoryPage />);
    await act(async () => {
      await Promise.resolve();
    });
    const text = container.textContent ?? "";
    expect(text).toContain("本轮注入");
    expect(text).toContain("用户偏好中文回复");
  });

  it("pages forward with the offset the backend expects", async () => {
    vi.mocked(api.listMemories).mockResolvedValue(
      listWith([item()], { total: 40, has_more: true }),
    );
    const spy = vi.spyOn(api, "listMemories");
    await render(<MemoryPage />);
    await act(async () => {
      await Promise.resolve();
    });
    const next = container.querySelector(
      'button[aria-label="下一页"]',
    ) as HTMLButtonElement;
    expect(next).toBeTruthy();
    expect(next.disabled).toBe(false);
    await act(async () => {
      next.click();
    });
    expect(spy.mock.calls[spy.mock.calls.length - 1][0]?.offset).toBe(20);
  });

  it("disables the next button on the last page", async () => {
    vi.mocked(api.listMemories).mockResolvedValue(
      listWith([item()], { total: 1, has_more: false }),
    );
    await render(<MemoryPage />);
    await act(async () => {
      await Promise.resolve();
    });
    const next = container.querySelector(
      'button[aria-label="下一页"]',
    ) as HTMLButtonElement;
    expect(next.disabled).toBe(true);
  });
});
