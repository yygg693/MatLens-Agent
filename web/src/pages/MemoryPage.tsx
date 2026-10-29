import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Brain,
  ChevronLeft,
  ChevronRight,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { Input } from "@nous-research/ui/ui/components/input";
import { Label } from "@nous-research/ui/ui/components/label";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Toast } from "@nous-research/ui/ui/components/toast";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { useConfirmDelete } from "@nous-research/ui/hooks/use-confirm-delete";
import { useModalBehavior } from "@/hooks/useModalBehavior";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import { api } from "@/lib/api";
import type {
  MemoryContentStatus,
  MemoryItem,
  MemoryLastInjection,
} from "@/lib/api";
import { usePageHeader } from "@/contexts/usePageHeader";
import { cn, themedBody } from "@/lib/utils";

const PAGE_SIZE = 20;

/**
 * Category labels the extractor writes into the memory text. The API
 * parses the leading `[tag]` into `category`; anything untagged lands in
 * "其他".
 */
const CATEGORY_ORDER = ["用户", "实验", "材料", "结论", "其他"];

const CATEGORY_TONE: Record<string, "success" | "warning" | "secondary"> = {
  用户: "secondary",
  实验: "success",
  材料: "warning",
  结论: "success",
};

/** Provenance labels for `source_type` — where the fact came from. */
const SOURCE_LABELS: Record<string, string> = {
  user: "用户陈述",
  document: "文献",
  agent_inference: "Agent 推断",
  imported_web: "网络导入",
};

function formatTime(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString();
}

function truncateText(value: string, maxLength: number): string {
  return value.length > maxLength ? value.slice(0, maxLength) + "…" : value;
}

/** A short id for display — full uuids are unreadable in a dense list. */
function shortId(id: string): string {
  return id ? id.slice(0, 8) : "";
}

function MemoryDetail({
  item,
  onClose,
  onEdit,
}: {
  item: MemoryItem;
  onClose: () => void;
  onEdit: (item: MemoryItem) => void;
}) {
  const meta = item.metadata ?? {};
  const metaRows = Object.entries(meta).filter(
    ([, v]) => v !== null && v !== undefined && v !== "",
  );

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 py-4">
        <div className="flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-2">
              <Badge tone={CATEGORY_TONE[item.category] ?? "secondary"}>
                {item.category || "其他"}
              </Badge>
              {item.source_type && (
                <Badge tone="outline">
                  {SOURCE_LABELS[item.source_type] ?? item.source_type}
                </Badge>
              )}
              {typeof item.confidence === "number" && (
                <Badge tone="outline">
                  置信度 {Math.round(item.confidence * 100)}%
                </Badge>
              )}
            </div>
            <p className="text-sm leading-relaxed whitespace-pre-wrap break-words">
              {item.memory}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <Button
              outlined
              size="icon"
              onClick={() => onEdit(item)}
              aria-label="Edit memory"
              title="编辑"
            >
              <Pencil />
            </Button>
            <Button
              ghost
              size="icon"
              onClick={onClose}
              aria-label="Close detail"
              title="关闭"
            >
              <X />
            </Button>
          </div>
        </div>

        <dl className="grid gap-2 border-t border-border pt-3 text-xs text-muted-foreground">
          <div className="flex gap-2">
            <dt className="w-20 shrink-0">ID</dt>
            <dd className="font-mono break-all">{item.id}</dd>
          </div>
          {item.source_ref && (
            <div className="flex gap-2">
              <dt className="w-20 shrink-0">来源引用</dt>
              <dd className="break-all">{item.source_ref}</dd>
            </div>
          )}
          {item.created_at && (
            <div className="flex gap-2">
              <dt className="w-20 shrink-0">创建于</dt>
              <dd>{formatTime(item.created_at)}</dd>
            </div>
          )}
          {item.updated_at && (
            <div className="flex gap-2">
              <dt className="w-20 shrink-0">更新于</dt>
              <dd>{formatTime(item.updated_at)}</dd>
            </div>
          )}
          {metaRows.length > 0 && (
            <div className="flex gap-2">
              <dt className="w-20 shrink-0">元数据</dt>
              <dd className="flex flex-col gap-0.5 break-all">
                {metaRows.map(([k, v]) => (
                  <span key={k}>
                    <span className="text-foreground">{k}</span>
                    {": "}
                    {typeof v === "object" ? JSON.stringify(v) : String(v)}
                  </span>
                ))}
              </dd>
            </div>
          )}
        </dl>
      </CardContent>
    </Card>
  );
}

export default function MemoryPage() {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [status, setStatus] = useState<MemoryContentStatus | null>(null);
  const [injection, setInjection] = useState<MemoryLastInjection | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [category, setCategory] = useState<string>("all");
  const [loading, setLoading] = useState(true);
  const [hasMore, setHasMore] = useState(false);
  const [selected, setSelected] = useState<MemoryItem | null>(null);
  const [editing, setEditing] = useState<MemoryItem | null>(null);
  const [editText, setEditText] = useState("");
  const [creating, setCreating] = useState(false);
  const [newText, setNewText] = useState("");
  const { toast, showToast } = useToast();
  const { setEnd } = usePageHeader();

  const closeEditModal = useCallback(() => {
    setEditing(null);
    setEditText("");
  }, []);
  const editModalRef = useModalBehavior({
    open: editing !== null,
    onClose: closeEditModal,
  });

  const closeCreateModal = useCallback(() => {
    setCreating(false);
    setNewText("");
  }, []);
  const createModalRef = useModalBehavior({
    open: creating,
    onClose: closeCreateModal,
  });

  const load = useCallback(
    async (nextOffset: number) => {
      setLoading(true);
      try {
        const res = await api.listMemories({
          q: query || undefined,
          offset: nextOffset,
          limit: PAGE_SIZE,
        });
        setItems(res.memories ?? []);
        setTotal(typeof res.total === "number" ? res.total : null);
        setHasMore(Boolean(res.has_more));
        setOffset(nextOffset);
      } catch (e) {
        showToast(`加载失败：${e}`, "error");
        setItems([]);
        setTotal(null);
        setHasMore(false);
      } finally {
        setLoading(false);
      }
    },
    [query, showToast],
  );

  const loadStatus = useCallback(() => {
    api
      .getMemoryContentStatus()
      .then(setStatus)
      .catch(() => setStatus(null));
    api
      .getMemoryLastInjection()
      .then(setInjection)
      .catch(() => setInjection(null));
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  // Debounced search: typing should not fire a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(searchInput.trim());
    }, 350);
    return () => clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    load(0);
  }, [load]);

  // Category counts are derived from what is currently loaded — the API
  // has no category facet endpoint, and the page shows one page at a time.
  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const item of items) {
      const key = item.category || "其他";
      counts[key] = (counts[key] ?? 0) + 1;
    }
    return counts;
  }, [items]);

  const visible = useMemo(
    () =>
      category === "all"
        ? items
        : items.filter((item) => (item.category || "其他") === category),
    [items, category],
  );

  const page = Math.floor(offset / PAGE_SIZE);
  const pageCount = total !== null ? Math.ceil(total / PAGE_SIZE) : null;

  // The list endpoint's `total` and the status endpoint's `count` are both
  // meant to be the store-wide size, but the list can legitimately come
  // back empty (backend not ready, filters applied server-side) while the
  // status endpoint still knows the real number. Never report "0" when the
  // status endpoint has a real count.
  const storeCount =
    total !== null && total > 0
      ? total
      : (status?.count ?? total ?? 0);

  const handleCreate = useCallback(async () => {
    const text = newText.trim();
    if (!text) return;
    try {
      await api.addMemoryContent(text);
      showToast("已添加", "success");
      closeCreateModal();
      await load(0);
      loadStatus();
    } catch (e) {
      showToast(`添加失败：${e}`, "error");
    }
  }, [closeCreateModal, load, loadStatus, newText, showToast]);

  const handleSaveEdit = useCallback(async () => {
    if (!editing) return;
    const text = editText.trim();
    if (!text) {
      showToast("内容不能为空", "error");
      return;
    }
    try {
      await api.updateMemoryContent(editing.id, text);
      showToast("已更新", "success");
      closeEditModal();
      await load(offset);
    } catch (e) {
      showToast(`更新失败：${e}`, "error");
    }
  }, [closeEditModal, editText, editing, load, offset, showToast]);

  const memoryDelete = useConfirmDelete({
    onDelete: useCallback(
      async (memoryId: string) => {
        try {
          await api.deleteMemoryContent(memoryId);
          showToast("已删除", "success");
          if (selected?.id === memoryId) setSelected(null);
          await load(offset);
          loadStatus();
        } catch (e) {
          showToast(`删除失败：${e}`, "error");
          throw e;
        }
      },
      [load, loadStatus, offset, selected, showToast],
    ),
  });

  useEffect(() => {
    setEnd(
      <div className="flex items-center gap-2">
        <Button
          outlined
          size="icon"
          onClick={() => load(offset)}
          disabled={loading}
          aria-label="刷新"
          title="刷新"
        >
          <RefreshCw />
        </Button>
        <Button
          className="uppercase"
          size="sm"
          onClick={() => setCreating(true)}
          disabled={status?.enabled === false}
        >
          <Plus className="h-3.5 w-3.5" />
          添加记忆
        </Button>
      </div>,
    );
    return () => setEnd(null);
  }, [load, loading, offset, setEnd, status?.enabled]);

  const disabled = status?.enabled === false;

  return (
    <div className="flex flex-col gap-4">
      <Toast toast={toast} />

      <DeleteConfirmDialog
        open={memoryDelete.isOpen}
        onCancel={memoryDelete.cancel}
        onConfirm={memoryDelete.confirm}
        title="删除记忆"
        description={
          memoryDelete.pendingId
            ? `记忆 ${shortId(memoryDelete.pendingId)} 将被永久删除。`
            : "这条记忆将被永久删除。"
        }
        loading={memoryDelete.isDeleting}
      />

      {/* ── Status strip ─────────────────────────────────────────────── */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-2 py-3 text-sm">
          <span className="flex items-center gap-2 font-medium">
            <Brain className="h-4 w-4 text-muted-foreground" />
            记忆中心
          </span>
          <span className="text-muted-foreground">
            共{" "}
            <span className="text-foreground">{storeCount}</span> 条
          </span>
          <span className="text-muted-foreground">
            后端{" "}
            <Badge tone="outline">
              {status?.source ?? "未知"}
            </Badge>
          </span>
          <span className="text-muted-foreground">
            provider{" "}
            <Badge tone="outline">{status?.provider ?? "mem0"}</Badge>
          </span>
          {disabled && (
            <Badge tone="warning">记忆功能已关闭</Badge>
          )}
          {!disabled && status?.auto_write === false && (
            <Badge tone="outline">自动写入已关闭</Badge>
          )}
        </CardContent>
      </Card>

      {/* ── Last injection ───────────────────────────────────────────── */}
      {injection?.available && injection.memories.length > 0 && (
        <Card>
          <CardContent className="py-3">
            <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
              本轮注入（Agent 用到的记忆）
            </div>
            <div className="flex flex-wrap gap-2">
              {injection.memories.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setSelected(item)}
                  className="max-w-[22rem] truncate rounded border border-border px-2 py-1 text-left text-xs hover:bg-accent"
                  title={item.memory}
                >
                  {truncateText(item.memory, 60)}
                </button>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Search + categories ──────────────────────────────────────── */}
      <div className="flex flex-col gap-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="搜索记忆（语义 + 关键词混合召回）"
            className="pl-9"
            aria-label="搜索记忆"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setCategory("all")}
            className={cn(
              "rounded border px-2.5 py-1 text-xs transition-colors",
              category === "all"
                ? "border-primary bg-primary/10 text-foreground"
                : "border-border text-muted-foreground hover:text-foreground",
            )}
          >
            全部
            {items.length > 0 && (
              <span className="ml-1.5 opacity-60">{items.length}</span>
            )}
          </button>
          {CATEGORY_ORDER.filter((c) => categoryCounts[c]).map((cat) => (
            <button
              key={cat}
              type="button"
              onClick={() => setCategory(cat)}
              className={cn(
                "rounded border px-2.5 py-1 text-xs transition-colors",
                category === cat
                  ? "border-primary bg-primary/10 text-foreground"
                  : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {cat}
              <span className="ml-1.5 opacity-60">{categoryCounts[cat]}</span>
            </button>
          ))}
        </div>
      </div>

      {/* ── Detail ───────────────────────────────────────────────────── */}
      {selected && (
        <MemoryDetail
          item={selected}
          onClose={() => setSelected(null)}
          onEdit={(item) => {
            setEditing(item);
            setEditText(item.memory);
          }}
        />
      )}

      {/* ── List ─────────────────────────────────────────────────────── */}
      {loading && items.length === 0 ? (
        <div className="flex items-center justify-center py-16">
          <Spinner className="text-2xl text-primary" />
        </div>
      ) : visible.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-10 text-center text-sm text-muted-foreground">
            <span>
              {disabled
                ? "记忆功能已关闭 —— 在设置 → 记忆中开启后自动积累。"
                : query
                  ? `没有匹配「${query}」的记忆。`
                  : "还没有记忆。对话几轮后 Agent 会自动提取，也可以手动添加。"}
            </span>
            {!disabled && (
              <Button
                className="uppercase"
                size="sm"
                onClick={() => setCreating(true)}
              >
                <Plus className="h-3.5 w-3.5" />
                添加记忆
              </Button>
            )}
          </CardContent>
        </Card>
      ) : (
        <div className="flex flex-col gap-3">
          {visible.map((item) => (
            <Card key={item.id}>
              <CardContent className="flex items-start gap-4 py-3">
                <button
                  type="button"
                  onClick={() => setSelected(item)}
                  className="min-w-0 flex-1 text-left"
                >
                  <div className="mb-1 flex flex-wrap items-center gap-2">
                    <Badge tone={CATEGORY_TONE[item.category] ?? "secondary"}>
                      {item.category || "其他"}
                    </Badge>
                    {item.source_type && (
                      <Badge tone="outline">
                        {SOURCE_LABELS[item.source_type] ?? item.source_type}
                      </Badge>
                    )}
                    {typeof item.confidence === "number" && (
                      <Badge tone="outline">
                        置信度 {Math.round(item.confidence * 100)}%
                      </Badge>
                    )}
                    {item.rrf_score !== undefined && (
                      <Badge tone="outline" title="向量与关键词双路命中">
                        双路命中
                      </Badge>
                    )}
                    <span className="text-xs text-muted-foreground">
                      {formatTime(item.created_at ?? item.updated_at)}
                    </span>
                  </div>
                  <div className="text-sm leading-relaxed break-words">
                    {item.memory}
                  </div>
                </button>
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    outlined
                    size="icon"
                    onClick={() => {
                      setEditing(item);
                      setEditText(item.memory);
                    }}
                    aria-label="Edit memory"
                    title="编辑"
                  >
                    <Pencil />
                  </Button>
                  <Button
                    ghost
                    size="icon"
                    onClick={() => memoryDelete.request(item.id)}
                    aria-label="Delete memory"
                    title="删除"
                    className="text-muted-foreground hover:text-destructive"
                  >
                    <Trash2 />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}

          {/* ── Pagination ─────────────────────────────────────────── */}
          <div className="flex items-center justify-between pt-1">
            <span className="text-xs text-muted-foreground">
              {offset + 1}–{offset + visible.length}
              {storeCount > 0 && ` / ${storeCount}`}
            </span>
            <div className="flex items-center gap-1">
              <Button
                outlined
                size="icon"
                disabled={offset === 0 || loading}
                onClick={() => load(Math.max(0, offset - PAGE_SIZE))}
                aria-label="上一页"
              >
                <ChevronLeft />
              </Button>
              <span className="px-2 text-xs text-muted-foreground">
                第 {page + 1} 页
                {pageCount !== null && ` / ${pageCount}`}
              </span>
              <Button
                outlined
                size="icon"
                disabled={!hasMore || loading}
                onClick={() => load(offset + PAGE_SIZE)}
                aria-label="下一页"
              >
                <ChevronRight />
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ── Create modal ──────────────────────────────────────────────── */}
      {creating && (
        <div
          ref={createModalRef}
          className="fixed inset-0 z-[100] flex items-center justify-center bg-background/85 p-4"
          onClick={(e) => e.target === e.currentTarget && closeCreateModal()}
          role="dialog"
          aria-modal="true"
          aria-labelledby="mem-create-title"
        >
          <div
            className={cn(
              themedBody,
              "relative w-full max-w-lg border border-border bg-card shadow-2xl flex flex-col",
            )}
          >
            <Button
              ghost
              size="icon"
              onClick={closeCreateModal}
              className="absolute right-2 top-2 text-muted-foreground hover:text-foreground"
              aria-label="Close"
            >
              <X />
            </Button>
            <header className="border-b border-border p-5 pb-3">
              <h2
                id="mem-create-title"
                className="font-mondwest text-display text-base tracking-wider"
              >
                添加记忆
              </h2>
            </header>
            <div className="grid gap-4 p-5">
              <div className="grid gap-2">
                <Label htmlFor="mem-new-text">内容</Label>
                <textarea
                  id="mem-new-text"
                  autoFocus
                  rows={5}
                  value={newText}
                  onChange={(e) => setNewText(e.target.value)}
                  placeholder="[材料] 你的研究方向的材料体系与关键结论…"
                  className="w-full resize-y rounded border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary"
                />
              </div>
              <div className="flex justify-end gap-2">
                <Button outlined onClick={closeCreateModal}>
                  取消
                </Button>
                <Button onClick={handleCreate} disabled={!newText.trim()}>
                  保存
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Edit modal ────────────────────────────────────────────────── */}
      {editing && (
        <div
          ref={editModalRef}
          className="fixed inset-0 z-[100] flex items-center justify-center bg-background/85 p-4"
          onClick={(e) => e.target === e.currentTarget && closeEditModal()}
          role="dialog"
          aria-modal="true"
          aria-labelledby="mem-edit-title"
        >
          <div
            className={cn(
              themedBody,
              "relative w-full max-w-lg border border-border bg-card shadow-2xl flex flex-col",
            )}
          >
            <Button
              ghost
              size="icon"
              onClick={closeEditModal}
              className="absolute right-2 top-2 text-muted-foreground hover:text-foreground"
              aria-label="Close"
            >
              <X />
            </Button>
            <header className="border-b border-border p-5 pb-3">
              <h2
                id="mem-edit-title"
                className="font-mondwest text-display text-base tracking-wider"
              >
                编辑记忆
              </h2>
            </header>
            <div className="grid gap-4 p-5">
              <div className="grid gap-2">
                <Label htmlFor="mem-edit-text">内容</Label>
                <textarea
                  id="mem-edit-text"
                  autoFocus
                  rows={5}
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                  className="w-full resize-y rounded border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary"
                />
              </div>
              <div className="flex justify-end gap-2">
                <Button outlined onClick={closeEditModal}>
                  取消
                </Button>
                <Button onClick={handleSaveEdit} disabled={!editText.trim()}>
                  保存
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
