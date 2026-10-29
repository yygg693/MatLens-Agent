import { useCallback, useEffect, useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { useI18n } from '@/i18n'
import {
  addMemoryContent,
  deleteMemoryContent,
  getMemoryContentStatus,
  getMemoryLastInjection,
  listMemories,
  type MemoryContentStatus,
  type MemoryItem,
  type MemoryLastInjection,
  updateMemoryContent
} from '@/matlens'
import { notifyError } from '@/store/notifications'

import {
  Panel,
  PanelAction,
  PanelAddButton,
  PanelBlock,
  PanelBody,
  PanelDetail,
  PanelEmpty,
  PanelHeader,
  PanelList,
  PanelListRow,
  PanelMeta,
  PanelPill,
  type PanelPillTone,
  PanelSectionLabel
} from '../overlays/panel'

const PAGE_SIZE = 40

/** Category tones for the labels the extractor writes into the memory text. */
const CATEGORY_TONE: Record<string, PanelPillTone> = {
  用户: 'muted',
  实验: 'good',
  材料: 'warn',
  结论: 'good'
}

function formatTime(iso?: null | string): string {
  if (!iso) {
    return ''
  }

  const d = new Date(iso)

  if (Number.isNaN(d.getTime())) {
    return ''
  }

  return d.toLocaleString()
}

interface MemoryViewProps {
  onClose: () => void
}

export function MemoryView({ onClose }: MemoryViewProps) {
  const { t } = useI18n()
  const copy = t.memoryCenter
  const [items, setItems] = useState<MemoryItem[]>([])
  const [status, setStatus] = useState<MemoryContentStatus | null>(null)
  const [injection, setInjection] = useState<MemoryLastInjection | null>(null)
  const [total, setTotal] = useState<null | number>(null)
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [query, setQuery] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [selectedId, setSelectedId] = useState<null | string>(null)
  const [editing, setEditing] = useState<MemoryItem | null>(null)
  const [editText, setEditText] = useState('')
  const [creating, setCreating] = useState(false)
  const [newText, setNewText] = useState('')

  const load = useCallback(
    async (nextOffset: number, q: string) => {
      try {
        const res = await listMemories({ limit: PAGE_SIZE, offset: nextOffset, q: q || undefined })
        setItems(res.memories ?? [])
        setTotal(typeof res.total === 'number' ? res.total : null)
        setHasMore(Boolean(res.has_more))
        setOffset(nextOffset)
      } catch (error) {
        notifyError(error, 'Failed to load memories')
        setItems([])
        setTotal(null)
        setHasMore(false)
      }
    },
    []
  )

  const loadStatus = useCallback(() => {
    getMemoryContentStatus()
      .then(setStatus)
      .catch(() => setStatus(null))
    getMemoryLastInjection()
      .then(setInjection)
      .catch(() => setInjection(null))
  }, [])

  useEffect(() => {
    loadStatus()
  }, [loadStatus])

  // Debounced search: typing should not fire a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(searchInput.trim())
    }, 350)

    return () => clearTimeout(timer)
  }, [searchInput])

  useEffect(() => {
    void load(0, query)
  }, [load, query])

  const selected = useMemo(
    () => items.find(item => item.id === selectedId) ?? null,
    [items, selectedId]
  )

  // The list endpoint's `total` and the status endpoint's `count` are both
  // meant to be the store-wide size, but the list can come back empty while
  // the status endpoint still knows the real number. Never report "0" when
  // the status endpoint has a real count.
  const storeCount = total !== null && total > 0 ? total : (status?.count ?? total ?? 0)

  const handleCreate = useCallback(async () => {
    const text = newText.trim()

    if (!text) {
      return
    }

    try {
      await addMemoryContent(text)
      setNewText('')
      setCreating(false)
      await load(0, query)
      loadStatus()
    } catch (error) {
      notifyError(error, 'Failed to add the memory')
    }
  }, [load, loadStatus, newText, query])

  const handleSave = useCallback(async () => {
    if (!editing) {
      return
    }

    const text = editText.trim()

    if (!text) {
      notifyError(new Error('Empty memory'), 'Failed to update the memory')

      return
    }

    try {
      await updateMemoryContent(editing.id, text)
      setEditing(null)
      setEditText('')
      await load(offset, query)
    } catch (error) {
      notifyError(error, 'Failed to update the memory')
    }
  }, [editText, editing, load, offset, query])

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await deleteMemoryContent(id)

        if (selectedId === id) {
          setSelectedId(null)
        }

        await load(offset, query)
        loadStatus()
      } catch (error) {
        notifyError(error, 'Failed to delete the memory')
      }
    },
    [load, loadStatus, offset, query, selectedId]
  )

  const disabled = status?.enabled === false

  return (
    <Panel closeLabel={copy.close} onClose={onClose}>
      <PanelHeader
        actions={
          <PanelAction icon="refresh" onClick={() => void load(offset, query)}>
            {copy.refresh}
          </PanelAction>
        }
        subtitle={
          storeCount > 0
            ? `${copy.totalCount(storeCount)} · ${copy.backend(status?.source ?? '?')}`
            : copy.loading
        }
        title={copy.title}
      />

      <PanelBody>
        <PanelList
          onSearchChange={setSearchInput}
          searchLabel={copy.searchLabel}
          searchPlaceholder={copy.searchPlaceholder}
          searchValue={searchInput}
        >
          {disabled ? (
            <PanelEmpty description={copy.disabledDesc} icon="circle-slash" title={copy.disabledTitle} />
          ) : items.length === 0 ? (
            <PanelEmpty
              action={
                <Button className="mt-1" onClick={() => setCreating(true)} size="sm" variant="outline">
                  {copy.add}
                </Button>
              }
              description={query ? copy.noMatchDesc(query) : copy.emptyDesc}
              icon="database"
              title={query ? copy.noMatchTitle : copy.emptyTitle}
            />
          ) : (
            <>
              {items.map(item => (
                <PanelListRow
                  active={item.id === selectedId}
                  key={item.id}
                  menuItems={[
                    { icon: 'edit', label: copy.edit, onSelect: () => { setEditing(item); setEditText(item.memory) } },
                    { icon: 'trash', label: copy.delete, onSelect: () => void handleDelete(item.id), tone: 'danger' }
                  ]}
                  meta={item.category || '?'}
                  onSelect={() => setSelectedId(item.id)}
                  title={item.memory}
                />
              ))}
              {hasMore ? (
                <PanelAddButton
                  icon="chevron-down"
                  label={copy.loadMore}
                  onClick={() => void load(offset + PAGE_SIZE, query)}
                />
              ) : null}
            </>
          )}
        </PanelList>

        <PanelDetail>
          {injection?.available && injection.memories.length > 0 ? (
            <div className="space-y-1.5">
              <PanelSectionLabel>{copy.lastInjection}</PanelSectionLabel>
              <div className="flex flex-wrap gap-1.5">
                {injection.memories.map(item => (
                  <PanelPill key={item.id}>{item.memory.slice(0, 48)}</PanelPill>
                ))}
              </div>
            </div>
          ) : null}

          {selected ? (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-1.5">
                <PanelPill tone={CATEGORY_TONE[selected.category] ?? 'muted'}>
                  {selected.category || '?'}
                </PanelPill>
                {selected.source_type ? (
                  <PanelPill tone="muted">
                    {copy.sourceLabels[selected.source_type as keyof typeof copy.sourceLabels] ??
                      selected.source_type}
                  </PanelPill>
                ) : null}
                {typeof selected.confidence === 'number' ? (
                  <PanelPill tone="muted">
                    {copy.confidence(Math.round(selected.confidence * 100))}
                  </PanelPill>
                ) : null}
                {selected.rrf_score !== undefined ? (
                  <PanelPill tone="good">{copy.bothRecallers}</PanelPill>
                ) : null}
              </div>

              <PanelBlock>{selected.memory}</PanelBlock>

              <PanelAction
                icon="edit"
                onClick={() => { setEditing(selected); setEditText(selected.memory) }}
              >
                {copy.edit}
              </PanelAction>

              <PanelMeta
                rows={[
                  { label: 'ID', value: <span className="font-mono">{selected.id}</span> },
                  ...(selected.source_ref ? [{ label: 'Source', value: selected.source_ref }] : []),
                  ...(selected.created_at ? [{ label: 'Created', value: formatTime(selected.created_at) }] : []),
                  ...(selected.updated_at ? [{ label: 'Updated', value: formatTime(selected.updated_at) }] : [])
                ]}
              />
            </div>
          ) : (
            <PanelEmpty description={copy.selectDesc} icon="database" title={copy.selectTitle} />
          )}
        </PanelDetail>
      </PanelBody>

      {creating ? (
        <Dialog
          onOpenChange={open => { if (!open) { setCreating(false); setNewText('') } }}
          open
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{copy.createTitle}</DialogTitle>
            </DialogHeader>
            <Textarea
              autoFocus
              onChange={event => setNewText(event.target.value)}
              placeholder={copy.createPlaceholder}
              rows={5}
              value={newText}
            />
            <DialogFooter>
              <Button onClick={() => setCreating(false)} variant="outline">
                {copy.cancel}
              </Button>
              <Button disabled={!newText.trim()} onClick={() => void handleCreate()}>
                {copy.save}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      ) : null}

      {editing ? (
        <Dialog
          onOpenChange={open => { if (!open) { setEditing(null); setEditText('') } }}
          open
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{copy.editTitle}</DialogTitle>
            </DialogHeader>
            <Textarea
              autoFocus
              onChange={event => setEditText(event.target.value)}
              rows={5}
              value={editText}
            />
            <DialogFooter>
              <Button onClick={() => setEditing(null)} variant="outline">
                {copy.cancel}
              </Button>
              <Button disabled={!editText.trim()} onClick={() => void handleSave()}>
                {copy.save}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      ) : null}
    </Panel>
  )
}
